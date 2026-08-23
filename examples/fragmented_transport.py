#!/usr/bin/env python3
"""Run aiogzip's public codec over an explicitly framed loopback transport."""

from __future__ import annotations

import argparse
import asyncio
import gzip
import hashlib
import json
import random
import struct
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, cast

import aiogzip

_FRAME_LENGTH = struct.Struct(">H")
_FRAGMENT_PATTERN = (1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 97)
Status = Literal["receiving-provisional", "verified", "invalid", "aborted"]
Record = dict[str, object]


@dataclass(frozen=True)
class ReceiveReport:
    records: tuple[Record, ...]
    status: Status
    decoded_sha256: str
    member_count: int
    error: str | None = None


@dataclass(frozen=True)
class LoopbackReport:
    receive: ReceiveReport
    wire: bytes
    source_sha256: str
    provisional_before_finish: bool


class _Writer(Protocol):
    def write(self, data: bytes) -> None: ...

    async def drain(self) -> None: ...


class _Reader(Protocol):
    async def readexactly(self, size: int) -> bytes: ...


def demo_records(count: int = 12) -> list[Record]:
    """Return deterministic records generated entirely by this example."""
    return [
        {
            "id": index,
            "kind": "demo",
            "message": f"event-{index:03d}",
        }
        for index in range(count)
    ]


def serialize_records(records: Sequence[Record]) -> bytes:
    """Serialize records as deterministic UTF-8 JSON Lines."""
    return b"".join(
        (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
        for record in records
    )


def _consume_operation(operation: aiogzip.CodecOperation) -> bytes:
    exhausted = False
    output = bytearray()
    try:
        for chunk in operation:
            output.extend(chunk)
        exhausted = True
        return bytes(output)
    finally:
        if not exhausted:
            operation.close()


def encode_records(records: Sequence[Record]) -> tuple[bytes, bytes]:
    """Encode one deterministic member through the public codec."""
    encoder = aiogzip.GzipEncoder(mtime=0, original_filename="events.jsonl")
    payload = serialize_records(records)
    wire = bytearray()
    try:
        wire.extend(_consume_operation(encoder.start()))
        for line in payload.splitlines(keepends=True):
            wire.extend(_consume_operation(encoder.feed(line)))
            wire.extend(_consume_operation(encoder.flush()))
        wire.extend(_consume_operation(encoder.finish()))
        return bytes(wire), payload
    except BaseException:
        encoder.discard()
        raise


class _Fragmenter:
    def __init__(self, pattern: Sequence[int]) -> None:
        if not pattern or any(size <= 0 or size > 0xFFFF for size in pattern):
            raise ValueError("frame sizes must be integers from 1 through 65535")
        self._pattern = tuple(pattern)
        self._index = 0

    def split(self, data: bytes) -> Iterator[bytes]:
        offset = 0
        while offset < len(data):
            size = self._pattern[self._index % len(self._pattern)]
            self._index += 1
            frame = data[offset : offset + size]
            offset += len(frame)
            yield frame


def fragment_bytes(data: bytes, pattern: Sequence[int]) -> list[bytes]:
    """Split bytes into explicit application frames using a fixed pattern."""
    return list(_Fragmenter(pattern).split(data))


def deterministic_random_pattern(seed: int = 2004) -> tuple[int, ...]:
    """Return a reproducible pseudo-random 1-97-byte frame pattern."""
    generator = random.Random(seed)
    return tuple(generator.randint(1, 97) for _ in range(31))


def _encoded_frame(frame: bytes) -> bytes:
    if not frame or len(frame) > 0xFFFF:
        raise ValueError("data frames must contain 1 through 65535 bytes")
    return _FRAME_LENGTH.pack(len(frame)) + frame


async def send_operation(
    writer: _Writer,
    operation: aiogzip.CodecOperation,
    fragmenter: _Fragmenter,
    captured_wire: bytearray,
) -> None:
    """Exhaust one operation with backpressure and deterministic framing."""
    exhausted = False
    try:
        for chunk in operation:
            captured_wire.extend(chunk)
            for frame in fragmenter.split(chunk):
                writer.write(_encoded_frame(frame))
                await writer.drain()
        exhausted = True
    finally:
        if not exhausted:
            operation.close()


class _ReceiverState:
    def __init__(self, first_record: asyncio.Event | None = None) -> None:
        self.decoder = aiogzip.GzipDecoder(collect_member_info=True)
        self.records: list[Record] = []
        self.pending = bytearray()
        self.digest = hashlib.sha256()
        self.status: Status = "receiving-provisional"
        self.error: str | None = None
        self.first_record = first_record

    def _accept_output(self, output: bytes) -> None:
        self.digest.update(output)
        self.pending.extend(output)
        while True:
            newline = self.pending.find(b"\n")
            if newline < 0:
                return
            line = bytes(self.pending[:newline])
            del self.pending[: newline + 1]
            record = cast(Record, json.loads(line.decode("utf-8")))
            self.records.append(record)
            if self.first_record is not None:
                self.first_record.set()

    def _drive(self, operation: aiogzip.CodecOperation) -> None:
        exhausted = False
        try:
            for output in operation:
                self._accept_output(output)
            exhausted = True
        finally:
            if not exhausted:
                operation.close()

    def feed(self, frame: bytes) -> None:
        if not frame:
            raise ValueError("zero-length frames terminate the transport")
        self._drive(self.decoder.feed(frame))

    def finish(self) -> ReceiveReport:
        try:
            self._drive(self.decoder.finish())
            if self.pending:
                raise ValueError("decoded stream ended with an incomplete JSON line")
            self.status = "verified"
            return self.report()
        except BaseException as error:
            return self.invalidate(error)

    def invalidate(self, error: BaseException) -> ReceiveReport:
        self.decoder.discard()
        self.status = "invalid"
        self.error = f"{type(error).__name__}: {error}"
        return self.report()

    def abort(self, reason: str) -> ReceiveReport:
        self.decoder.discard()
        self.status = "aborted"
        self.error = reason
        return self.report()

    def report(self) -> ReceiveReport:
        return ReceiveReport(
            records=tuple(self.records),
            status=self.status,
            decoded_sha256=self.digest.hexdigest(),
            member_count=self.decoder.member_count,
            error=self.error,
        )


def decode_frames(frames: Iterable[bytes]) -> ReceiveReport:
    """Decode frame payloads; one empty frame marks clean transport end."""
    state = _ReceiverState()
    try:
        for frame in frames:
            if not frame:
                return state.finish()
            state.feed(frame)
    except BaseException as error:
        return state.invalidate(error)
    return state.abort("transport EOF arrived before the zero-length end frame")


async def _receive_stream(
    reader: _Reader,
    writer: _MemoryEndpoint,
    first_record: asyncio.Event,
) -> ReceiveReport:
    state = _ReceiverState(first_record)
    try:
        while True:
            header = await reader.readexactly(_FRAME_LENGTH.size)
            (length,) = _FRAME_LENGTH.unpack(header)
            if length == 0:
                return state.finish()
            state.feed(await reader.readexactly(length))
    except asyncio.IncompleteReadError:
        return state.abort("transport EOF arrived before the zero-length end frame")
    except asyncio.CancelledError:
        state.abort("receiver task was cancelled")
        raise
    except BaseException as error:
        return state.invalidate(error)
    finally:
        writer.close()
        await writer.wait_closed()


async def _send_records(
    writer: _Writer,
    records: Sequence[Record],
    first_record: asyncio.Event,
) -> tuple[bytes, str, bool]:
    fragmenter = _Fragmenter(_FRAGMENT_PATTERN)
    encoder = aiogzip.GzipEncoder(mtime=0, original_filename="events.jsonl")
    payload = serialize_records(records)
    captured_wire = bytearray()
    visible_before_finish = False
    try:
        await send_operation(writer, encoder.start(), fragmenter, captured_wire)
        for index, line in enumerate(payload.splitlines(keepends=True)):
            await send_operation(writer, encoder.feed(line), fragmenter, captured_wire)
            await send_operation(writer, encoder.flush(), fragmenter, captured_wire)
            if index == 0:
                await asyncio.wait_for(first_record.wait(), timeout=2)
                visible_before_finish = True
        await send_operation(writer, encoder.finish(), fragmenter, captured_wire)
        writer.write(_FRAME_LENGTH.pack(0))
        await writer.drain()
        return (
            bytes(captured_wire),
            hashlib.sha256(payload).hexdigest(),
            visible_before_finish,
        )
    except BaseException:
        encoder.discard()
        raise


class _MemoryEndpoint:
    """One side of a bounded in-memory byte transport."""

    def __init__(
        self,
        incoming: asyncio.Queue[bytes | None],
        outgoing: asyncio.Queue[bytes | None],
    ) -> None:
        self._incoming = incoming
        self._outgoing = outgoing
        self._read_buffer = bytearray()
        self._pending_writes: list[bytes] = []
        self._closing = False
        self._eof_sent = False

    def write(self, data: bytes) -> None:
        if self._closing:
            raise RuntimeError("transport endpoint is closing")
        self._pending_writes.append(bytes(data))

    async def drain(self) -> None:
        pending, self._pending_writes = self._pending_writes, []
        for data in pending:
            await self._outgoing.put(data)

    async def readexactly(self, size: int) -> bytes:
        while len(self._read_buffer) < size:
            data = await self._incoming.get()
            if data is None:
                partial = bytes(self._read_buffer)
                self._read_buffer.clear()
                raise asyncio.IncompleteReadError(partial, size)
            self._read_buffer.extend(data)
        output = bytes(self._read_buffer[:size])
        del self._read_buffer[:size]
        return output

    def close(self) -> None:
        self._closing = True

    async def wait_closed(self) -> None:
        if self._eof_sent:
            return
        await self.drain()
        await self._outgoing.put(None)
        self._eof_sent = True


def _memory_transport_pair() -> tuple[_MemoryEndpoint, _MemoryEndpoint]:
    client_incoming: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=1)
    server_incoming: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=1)
    return (
        _MemoryEndpoint(client_incoming, server_incoming),
        _MemoryEndpoint(server_incoming, client_incoming),
    )


async def run_loopback(records: Sequence[Record]) -> LoopbackReport:
    """Send records through a bounded local bidirectional byte transport."""
    first_record = asyncio.Event()
    client, server = _memory_transport_pair()
    receive_task = asyncio.create_task(_receive_stream(server, server, first_record))
    try:
        wire, source_digest, provisional = await _send_records(
            client, records, first_record
        )
        client.close()
        await client.wait_closed()
        receive = await asyncio.wait_for(receive_task, timeout=2)
    finally:
        if not receive_task.done():
            receive_task.cancel()
            try:
                await receive_task
            except asyncio.CancelledError:
                pass

    if gzip.decompress(wire) != serialize_records(records):
        raise AssertionError("stdlib gzip rejected the captured wire stream")
    return LoopbackReport(receive, wire, source_digest, provisional)


def demonstrate_abandonment(wire: bytes) -> None:
    """Exercise explicit operation close and retained-operation invalidation."""
    decoder = aiogzip.GzipDecoder(output_chunk_size=1)
    operation = decoder.feed(wire)
    next(operation)
    operation.close()
    try:
        decoder.finish()
    except OSError:
        pass
    else:  # pragma: no cover - protects the example's assertion
        raise AssertionError("an abandoned operation did not poison its decoder")
    decoder.discard()
    decoder.discard()

    retained_decoder = aiogzip.GzipDecoder()
    retained = retained_decoder.feed(wire)
    retained_decoder.discard()
    try:
        next(retained)
    except RuntimeError:
        pass
    else:  # pragma: no cover - protects the example's assertion
        raise AssertionError("discard did not invalidate the retained operation")


async def self_test() -> None:
    """Run deterministic success, fragmentation, corruption, and cleanup checks."""
    records = demo_records()
    loopback = await run_loopback(records)
    expected_payload = serialize_records(records)
    assert loopback.receive.status == "verified"
    assert loopback.receive.records == tuple(records)
    assert loopback.receive.decoded_sha256 == loopback.source_sha256
    assert loopback.provisional_before_finish
    assert gzip.decompress(loopback.wire) == expected_payload

    patterns = [
        (len(loopback.wire),),
        (1,),
        _FRAGMENT_PATTERN,
        deterministic_random_pattern(),
    ]
    for pattern in patterns:
        report = decode_frames([*fragment_bytes(loopback.wire, pattern), b""])
        assert report.status == "verified"
        assert report.records == tuple(records)
        assert report.member_count == 1

    trailer_split = [loopback.wire[:-8], loopback.wire[-8:], b""]
    assert decode_frames(trailer_split).status == "verified"
    trailer_edges = [loopback.wire[:-9], loopback.wire[-9:-8], loopback.wire[-8:], b""]
    assert decode_frames(trailer_edges).status == "verified"

    first_wire, _ = encode_records(records[:6])
    second_wire, _ = encode_records(records[6:])
    concatenated = first_wire + second_wire
    concatenated_report = decode_frames(
        [*fragment_bytes(concatenated, _FRAGMENT_PATTERN), b""]
    )
    assert concatenated_report.status == "verified"
    assert concatenated_report.member_count == 2
    assert concatenated_report.records == tuple(records)

    truncated = decode_frames(
        [*fragment_bytes(loopback.wire[:-3], _FRAGMENT_PATTERN), b""]
    )
    assert truncated.status == "invalid"
    assert truncated.records

    for trailer_index in (-8, -4):
        corrupt = bytearray(loopback.wire)
        corrupt[trailer_index] ^= 1
        report = decode_frames([*fragment_bytes(bytes(corrupt), (1, 97)), b""])
        assert report.status == "invalid"

    aborted = decode_frames(fragment_bytes(loopback.wire, _FRAGMENT_PATTERN))
    assert aborted.status == "aborted"
    demonstrate_abandonment(loopback.wire)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Demonstrate aiogzip's public codec over framed loopback I/O."
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="run deterministic success and failure scenarios",
    )
    return parser


async def _main(self_test_requested: bool) -> None:
    if self_test_requested:
        await self_test()
        print("fragmented transport self-test: passed")
        return
    report = await run_loopback(demo_records())
    print(
        f"status={report.receive.status} records={len(report.receive.records)} "
        f"sha256={report.receive.decoded_sha256} "
        f"provisional_before_finish={report.provisional_before_finish}"
    )


def main() -> int:
    args = _parser().parse_args()
    asyncio.run(_main(args.self_test))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
