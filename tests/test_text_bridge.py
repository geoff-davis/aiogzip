"""WP8: the text/binary bridge, observer ownership and one health authority.

Binary health is the only health state. Text keeps a one-way latch,
``_read_poison_seen``, that gates its hot read paths; every decision it gates
queries binary. The invariant checked after every event: while the text handle
is open, binary health that is not HEALTHY implies the latch is set.
"""

import ast
import asyncio
import gc
import gzip
import io
from pathlib import Path

import pytest
from conftest import FramedAsyncReader

import aiogzip._text as text_module
from aiogzip import AsyncGzipBinaryFile, AsyncGzipTextFile, ConcurrentOperationError
from aiogzip._binary import _ReadHealth

TEXT_SOURCE = Path(__file__).resolve().parents[1] / "src" / "aiogzip" / "_text.py"
LINES = [f"line {i:03d}\n" for i in range(200)]
PAYLOAD = "".join(LINES)
WIRE = gzip.compress(PAYLOAD.encode(), mtime=0)

# Private binary names text may use; anything else must be reviewed first.
ALLOWLIST = {
    # observer attachment
    "_attach_text_observers",
    # health, usability and salvage (authoritative predicates)
    "_read_is_healthy",
    "_has_validation_failure",
    "_can_restore_failed_read",
    "_check_read_usable",
    "_validation_salvage_exhausted",
    # positions and buffers; _eof and _position are measured hot-path reads
    "_read_buffer_exhausted",
    "_eof",
    "_position",
    # lifecycle
    "_close_on_context_exit",
    "_check_write_call_available",
}


def _corrupt_crc(data=WIRE):
    corrupt = bytearray(data)
    corrupt[-8] ^= 1
    return bytes(corrupt)


def _assert_bridge(stream):
    binary = stream._binary_file
    if binary is not None and not stream.closed and not binary._read_is_healthy():
        assert stream._read_poison_seen is True


def _text(data=WIRE, **options):
    options.setdefault("closefd", False)
    return AsyncGzipTextFile(
        None, "rt", fileobj=FramedAsyncReader(data), chunk_size=64, **options
    )


# Structure


def _binary_aliases(function):
    """Names bound to the binary object inside one function."""
    names = set()
    arguments = function.args.args + function.args.kwonlyargs
    for arg in arguments:
        annotation = arg.annotation
        if isinstance(annotation, ast.Name) and annotation.id == "AsyncGzipBinaryFile":
            names.add(arg.arg)
    for node in ast.walk(function):
        if isinstance(node, ast.Assign):
            value = node.value
            is_binary = (
                isinstance(value, ast.Attribute) and value.attr == "_binary_file"
            ) or (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id == "AsyncGzipBinaryFile"
            )
            if is_binary:
                names.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return names


def _binary_private_accesses():
    tree = ast.parse(TEXT_SOURCE.read_text(encoding="utf-8"))
    accesses = []
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        aliases = _binary_aliases(function)
        for node in ast.walk(function):
            if not isinstance(node, ast.Attribute) or not node.attr.startswith("_"):
                continue
            if node.attr.startswith("__"):
                continue
            base = node.value
            on_binary = (isinstance(base, ast.Name) and base.id in aliases) or (
                isinstance(base, ast.Attribute)
                and base.attr in ("_binary_file", "buffer")
            )
            if on_binary:
                accesses.append((node.attr, type(node.ctx).__name__, node.lineno))
    return accesses


def test_text_private_binary_access_matches_the_allowlist():
    accesses = _binary_private_accesses()
    assert {name for name, _, _ in accesses} == ALLOWLIST
    stores = [a for a in accesses if a[1] != "Load"]
    assert stores == [], "text must not store binary attributes"


def test_alias_detection_sees_every_binary_binding():
    # Guards the allowlist test itself: the known aliases are recognized.
    tree = ast.parse(TEXT_SOURCE.read_text(encoding="utf-8"))
    seen = set()
    for function in ast.walk(tree):
        if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            seen |= _binary_aliases(function)
    assert {"bf", "binary_file"} <= seen


def test_temporary_seam_is_gone():
    for name in ("_read_broken", "_read_validation_failed", "_read_poisoned"):
        assert not hasattr(AsyncGzipBinaryFile, name)
        assert name not in AsyncGzipTextFile.__slots__
    assert "_read_poison_seen" in AsyncGzipTextFile.__slots__


# Attachment and detachment


def _binary():
    return AsyncGzipBinaryFile(
        None, "rb", fileobj=FramedAsyncReader(WIRE), closefd=False
    )


def test_attach_refuses_to_replace_existing_observers():
    binary = _binary()

    def closed():
        pass

    def poisoned(validation_failed):
        pass

    binary._attach_text_observers(closed=closed, poisoned=poisoned)
    with pytest.raises(RuntimeError, match="already has text observers"):
        binary._attach_text_observers(closed=lambda: None, poisoned=lambda v: None)
    assert binary._closed_observer is closed
    assert binary._read_poison_observer is poisoned


def test_detach_is_idempotent_and_closes_nothing():
    source = FramedAsyncReader(WIRE)
    binary = AsyncGzipBinaryFile(None, "rb", fileobj=source, closefd=True)
    binary._attach_text_observers(closed=lambda: None, poisoned=lambda v: None)
    binary._detach_text_observers()
    binary._detach_text_observers()
    assert binary._closed_observer is None
    assert binary._read_poison_observer is None
    assert not binary.closed
    # Reattaching after a detach is allowed.
    binary._attach_text_observers(closed=lambda: None, poisoned=lambda v: None)


async def test_open_attaches_the_text_handle_observers():
    stream = _text()
    await stream.open()
    binary = stream.buffer
    assert binary._closed_observer == stream._mark_binary_closed
    assert binary._read_poison_observer == stream._mark_binary_read_poisoned
    assert stream._read_poison_seen is False
    await stream.close()


@pytest.mark.parametrize("failure", [OSError("open failed"), asyncio.CancelledError()])
async def test_failed_or_cancelled_open_never_attaches(monkeypatch, failure):
    created = []

    class Failing(AsyncGzipBinaryFile):
        __slots__ = ()

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            created.append(self)

        async def open(self):
            raise failure

    monkeypatch.setattr(text_module, "AsyncGzipBinaryFile", Failing)
    stream = _text()
    with pytest.raises(type(failure)):
        await stream.open()
    (binary,) = created
    assert binary._closed_observer is None
    assert binary._read_poison_observer is None
    assert stream._binary_file is None


@pytest.mark.parametrize("via", ["text", "buffer"])
async def test_close_detaches_and_repeated_close_is_a_no_op(via):
    stream = _text()
    await stream.open()
    binary = stream.buffer
    await (stream.close() if via == "text" else binary.close())
    assert stream.closed and binary.closed
    assert binary._closed_observer is None
    assert binary._read_poison_observer is None
    await stream.close()
    await binary.close()
    assert stream.closed


def _reaches(root, target, depth=3):
    """Whether ``target`` is reachable from ``root`` within ``depth`` hops."""
    frontier, seen = [root], {id(root)}
    for _ in range(depth):
        following = []
        for item in frontier:
            for referent in gc.get_referents(item):
                if referent is target:
                    return True
                if id(referent) not in seen and not isinstance(referent, type):
                    seen.add(id(referent))
                    following.append(referent)
        frontier = following
    return False


async def test_binary_holds_no_reference_to_a_closed_text_handle():
    # Text uses __slots__ without __weakref__, so the lifetime check walks
    # the binary's referents instead of using a weak reference.
    stream = _text()
    await stream.open()
    binary = stream.buffer
    assert _reaches(binary, stream)  # the bound observers, while attached
    await stream.close()
    assert not _reaches(binary, stream)


# Health authority and the latch invariant


class _Source:
    """Async source with optional gating, failures and a failing close."""

    def __init__(self, data, *, seekable=False, fail=None, close_error=None):
        self.buffer = io.BytesIO(data)
        self._seekable = seekable
        self.fail = fail
        self.close_error = close_error
        self.gate = None
        self.absorb_cancel = False
        self.consume_on_cancel = False
        self.entered = asyncio.Event()
        self.closed = False
        self.tell = self.buffer.tell

    def seekable(self):
        return self._seekable

    async def seek(self, offset, whence=0):
        if not self._seekable:
            raise OSError("not seekable")
        return self.buffer.seek(offset, whence)

    async def read(self, size=-1):
        if self.gate is not None:
            self.entered.set()
            try:
                await self.gate.wait()
            except asyncio.CancelledError:
                if self.consume_on_cancel:
                    # Consume input before propagating, so the active call
                    # sees a moved position and poisons the reader itself.
                    self.buffer.read(size)
                    raise
                if not self.absorb_cancel:
                    raise
        fail, self.fail = self.fail, None
        if fail == "consumed":
            self.buffer.read(size)
            raise OSError("source failed after consuming input")
        return self.buffer.read(size)

    def close(self):
        self.closed = True
        if self.close_error is not None:
            raise self.close_error


async def test_open_and_healthy_reads_leave_the_latch_clear():
    async with _text() as stream:
        _assert_bridge(stream)
        assert await stream.readline() == LINES[0]
        assert stream._read_poison_seen is False
        _assert_bridge(stream)


async def test_ordinary_breakage_latches_and_discards_text():
    stream = _text(max_decompressed_size=len(PAYLOAD) // 2)
    async with stream:
        with pytest.raises(OSError, match="max_decompressed_size"):
            await stream.read()
        assert stream.buffer._read_health is _ReadHealth.BROKEN
        assert stream._read_poison_seen is True
        assert stream._buffered_text_len() == 0
        _assert_bridge(stream)
        with pytest.raises(OSError, match="broken"):
            await stream.readline()


async def test_validation_salvage_latches_and_retains_text():
    async with _text(_corrupt_crc()) as stream:
        with pytest.raises(gzip.BadGzipFile, match="CRC check failed"):
            await stream.readlines()
        assert stream.buffer._read_health is _ReadHealth.VALIDATION_SALVAGE
        assert stream._read_poison_seen is True
        _assert_bridge(stream)
        # Salvage is still served, then the reader is terminal.
        assert await stream.readlines() == LINES
        with pytest.raises(OSError, match="broken"):
            await stream.readlines()


@pytest.mark.parametrize("first_size", [-1, 1, 100])
async def test_salvage_ending_inside_a_character_keeps_complete_text(first_size):
    # b1 and C0 finalized the decoder on the salvage drain, so the incomplete
    # final byte raised UnicodeDecodeError and discarded 'ab' (WP10 F1a).
    payload = "abé".encode()[:-1]
    async with _text(_corrupt_crc(gzip.compress(payload, mtime=0))) as stream:
        with pytest.raises(gzip.BadGzipFile):
            await stream.read(first_size)
        delivered = ""
        while True:
            try:
                delivered += await stream.read(first_size)
            except OSError as error:
                assert "broken" in str(error)
                break
        assert delivered == "ab"


@pytest.mark.parametrize(("newline", "expected"), [(None, "ab\n"), ("", "ab\r")])
async def test_salvage_ending_in_a_cr_resolves_it_as_a_line_end(newline, expected):
    # Every continuation of a trailing CR begins with this resolution, so
    # emitting it is safe; pins b1/C0 behaviour. The newline kind stays
    # unrecorded: the continuation could have made the CR part of a CRLF.
    async with _text(
        _corrupt_crc(gzip.compress(b"ab\r", mtime=0)), newline=newline
    ) as (stream):
        with pytest.raises(gzip.BadGzipFile):
            await stream.read(100)
        assert await stream.read() == expected
        assert stream.newlines is None
        with pytest.raises(OSError, match="broken"):
            await stream.read()


@pytest.mark.parametrize(
    ("payload", "encoding"), [(b"", "utf-8"), ("".encode("utf-16"), "utf-16")]
)
@pytest.mark.parametrize("size", [-1, 1])
async def test_salvage_completing_no_character_is_never_clean_eof(
    payload, encoding, size
):
    # b1 and C0 returned '' here, which reads as clean EOF (WP10 F2).
    async with _text(
        _corrupt_crc(gzip.compress(payload, mtime=0)), encoding=encoding
    ) as stream:
        with pytest.raises(gzip.BadGzipFile):
            await stream.read(size)
        for _ in range(2):
            with pytest.raises(OSError, match="broken"):
                await stream.read(size)


async def _drain_lines(stream, surface):
    if surface == "readline":
        return await stream.readline()
    if surface == "readlines":
        return await stream.readlines()
    if surface == "anext":
        return await anext(stream)
    return await anext(stream.iter_batches())


@pytest.mark.parametrize(
    ("payload", "encoding"), [(b"", "utf-8"), ("".encode("utf-16"), "utf-16")]
)
@pytest.mark.parametrize("surface", ["readline", "readlines", "anext", "iter_batches"])
@pytest.mark.parametrize("newline", [None, ""])
async def test_line_surfaces_never_report_empty_salvage_as_eof(
    payload, encoding, surface, newline
):
    # These surfaces needed no BC7 change: an empty salvage forces another
    # binary access, which raises. Pins that they never signal EOF, on both
    # the fast (newline=None) and generic (newline="") line paths.
    async with _text(
        _corrupt_crc(gzip.compress(payload, mtime=0)),
        encoding=encoding,
        newline=newline,
    ) as stream:
        with pytest.raises(gzip.BadGzipFile):
            await _drain_lines(stream, surface)
        for _ in range(2):
            with pytest.raises(OSError, match="broken"):
                await _drain_lines(stream, surface)


async def test_transport_uncertainty_latches():
    source = _Source(WIRE, fail="consumed")
    stream = AsyncGzipTextFile(None, "rt", fileobj=source, closefd=False)
    async with stream:
        with pytest.raises(OSError, match="consuming input"):
            await stream.read()
        assert stream.buffer._read_health is _ReadHealth.BROKEN
        assert stream._read_poison_seen is True
        _assert_bridge(stream)


async def test_successful_text_rewind_clears_the_latch():
    source = _Source(WIRE, seekable=True, fail="consumed")
    stream = AsyncGzipTextFile(None, "rt", fileobj=source, closefd=False)
    async with stream:
        with pytest.raises(OSError):
            await stream.read()
        assert stream._read_poison_seen is True
        assert await stream.seek(0) == 0
        assert stream.buffer._read_is_healthy()
        assert stream._read_poison_seen is False
        _assert_bridge(stream)
        assert await stream.read() == PAYLOAD


async def test_failed_text_rewind_keeps_the_latch():
    stream = _text(max_decompressed_size=len(PAYLOAD) // 2, max_rewind_cache_size=16)
    stream._external_file = _Source(WIRE)
    async with stream:
        with pytest.raises(OSError, match="max_decompressed_size"):
            await stream.read()
        with pytest.raises(OSError):
            await stream.seek(0)
        assert not stream.buffer._read_is_healthy()
        assert stream._read_poison_seen is True
        _assert_bridge(stream)


async def test_close_during_active_work_is_rejected_without_health_change():
    source = _Source(WIRE)
    source.gate = asyncio.Event()
    stream = AsyncGzipTextFile(None, "rt", fileobj=source, closefd=False)
    await stream.open()
    reader = asyncio.create_task(stream.read())
    await asyncio.wait_for(source.entered.wait(), 5)
    with pytest.raises(ConcurrentOperationError):
        await stream.close()
    assert stream.buffer._read_is_healthy()
    assert stream._read_poison_seen is False
    _assert_bridge(stream)
    source.gate.set()
    assert await reader == PAYLOAD
    await stream.close()


async def _abort_with_active_read(source, deliveries=None):
    stream = AsyncGzipTextFile(None, "rt", fileobj=source, closefd=True, chunk_size=16)
    reader = None
    with pytest.raises(RuntimeError, match="body"):
        async with stream:
            assert await stream.readline() == LINES[0]
            if deliveries is not None:
                # Count poison deliveries while keeping text's own handlers.
                binary = stream.buffer
                binary._detach_text_observers()

                def poisoned(validation_failed):
                    deliveries.append(validation_failed)
                    stream._mark_binary_read_poisoned(validation_failed)

                binary._attach_text_observers(
                    closed=stream._mark_binary_closed, poisoned=poisoned
                )
            source.gate = asyncio.Event()
            reader = asyncio.create_task(stream.read())
            await asyncio.wait_for(source.entered.wait(), 5)
            raise RuntimeError("body")
    with pytest.raises(OSError, match="read aborted"):
        await reader
    return stream


@pytest.mark.parametrize("active_call_poisons", [True, False])
async def test_failed_abort_close_leaves_text_refusing_reads(active_call_poisons):
    # The accepted WP8 correction: an abort notifies text when it breaks the
    # reader, so text no longer serves text decoded before a failed abort.
    # With active-call poison, the cancelled read consumes input first, so
    # the active call poisons the reader again after the abort notification:
    # delivery is at-least-once and text's handler must be idempotent.
    source = _Source(WIRE, close_error=OSError("underlying close failed"))
    source.consume_on_cancel = active_call_poisons
    source.absorb_cancel = not active_call_poisons
    deliveries = []
    stream = await _abort_with_active_read(source, deliveries)
    assert deliveries == ([False, False] if active_call_poisons else [False])
    assert source.closed is True  # the close was attempted
    assert stream.closed is False  # and failed, so the handle stays open
    assert stream.buffer._read_health is _ReadHealth.BROKEN
    assert stream._read_poison_seen is True
    assert stream._buffered_text_len() == 0
    _assert_bridge(stream)
    with pytest.raises(OSError, match="broken"):
        await stream.readline()
    # An explicit close retries the underlying close.
    source.close_error = None
    await stream.close()
    assert stream.closed


async def test_successful_abort_closes_the_handle():
    source = _Source(WIRE)
    source.absorb_cancel = True
    stream = await _abort_with_active_read(source)
    assert stream.closed is True
    assert source.closed is True
    assert stream.buffer._read_health is _ReadHealth.BROKEN


# Observer failures


class _Sink:
    """Async write target that can fail writes and close on request."""

    def __init__(self):
        self.data = bytearray()
        self.fail_writes = None
        self.close_error = None
        self.closed = False

    async def write(self, data):
        if self.fail_writes is not None:
            raise self.fail_writes
        self.data += data
        return len(data)

    def close(self):
        self.closed = True
        if self.close_error is not None:
            raise self.close_error


def _attach_failing_closed(binary, error):
    def closed():
        raise error

    binary._attach_text_observers(closed=closed, poisoned=lambda v: None)


async def test_raising_closed_observer_still_finishes_a_reader(monkeypatch):
    source = _Source(WIRE)
    binary = AsyncGzipBinaryFile(None, "rb", fileobj=source, closefd=True)
    await binary.open()
    assert await binary.read(10) == PAYLOAD[:10].encode()
    decoder = binary._decoder
    observer_error = RuntimeError("closed observer failed")
    _attach_failing_closed(binary, observer_error)
    with pytest.raises(RuntimeError) as raised:
        await binary.close()
    assert raised.value is observer_error
    assert binary.closed
    assert decoder._discarded
    assert source.closed is True
    assert binary._closed_observer is None


async def test_raising_closed_observer_still_writes_the_trailer():
    sink = _Sink()
    binary = AsyncGzipBinaryFile(None, "wb", fileobj=sink, closefd=True)
    await binary.open()
    await binary.write(PAYLOAD.encode())
    observer_error = RuntimeError("closed observer failed")
    _attach_failing_closed(binary, observer_error)
    with pytest.raises(RuntimeError) as raised:
        await binary.close()
    assert raised.value is observer_error
    assert sink.closed is True
    assert gzip.decompress(bytes(sink.data)) == PAYLOAD.encode()


async def _writer_failing_at_close(observer_error, close_error=None):
    sink = _Sink()
    binary = AsyncGzipBinaryFile(None, "wb", fileobj=sink, closefd=True)
    await binary.open()
    await binary.write(b"x" * 1000)
    _attach_failing_closed(binary, observer_error)
    sink.fail_writes = OSError("final write failed")
    sink.close_error = close_error
    return binary, sink


async def test_observer_and_failed_finalization_raise_the_finalization_error():
    binary, sink = await _writer_failing_at_close(RuntimeError("observer"))
    with pytest.raises(OSError, match="final write failed") as raised:
        await binary.close()
    assert any("observer" in note for note in raised.value.__notes__)
    assert sink.closed is True
    assert binary._encoder._discarded


async def test_observer_finalization_and_close_failures_keep_close_suppressed():
    binary, sink = await _writer_failing_at_close(
        RuntimeError("observer"), OSError("underlying close failed")
    )
    with pytest.raises(OSError, match="final write failed") as raised:
        await binary.close()
    assert any("observer" in note for note in raised.value.__notes__)
    assert "underlying close failed" not in str(raised.value)
    assert sink.closed is True


async def test_cancelled_close_after_failed_finalization_outranks_it():
    cancelled = asyncio.CancelledError()
    binary, sink = await _writer_failing_at_close(RuntimeError("observer"), cancelled)
    with pytest.raises(asyncio.CancelledError) as raised:
        await binary.close()
    assert raised.value is cancelled
    assert isinstance(raised.value.__context__, OSError)
    assert "final write failed" in str(raised.value.__context__)
    assert any("observer" in note for note in raised.value.__notes__)


async def test_observer_and_failed_underlying_close_raise_the_close_error():
    source = _Source(WIRE, close_error=OSError("underlying close failed"))
    binary = AsyncGzipBinaryFile(None, "rb", fileobj=source, closefd=True)
    await binary.open()
    _attach_failing_closed(binary, RuntimeError("observer"))
    with pytest.raises(OSError, match="underlying close failed") as raised:
        await binary.close()
    assert any("observer" in note for note in raised.value.__notes__)


async def test_observer_interrupt_outranks_an_ordinary_finalization_error():
    interrupt = KeyboardInterrupt()
    binary, sink = await _writer_failing_at_close(interrupt)
    with pytest.raises(KeyboardInterrupt) as raised:
        await binary.close()
    assert raised.value is interrupt
    assert isinstance(raised.value.__context__, OSError)
    assert sink.closed is True


async def test_raising_abort_observer_still_closes_the_underlying_file():
    source = _Source(WIRE)
    source.absorb_cancel = True
    binary = AsyncGzipBinaryFile(None, "rb", fileobj=source, closefd=True)
    events = []

    def poisoned(validation_failed):
        events.append(validation_failed)
        raise RuntimeError("abort observer failed")

    reader = None
    with pytest.raises(RuntimeError, match="body"):
        async with binary:
            binary._attach_text_observers(closed=lambda: None, poisoned=poisoned)
            source.gate = asyncio.Event()
            reader = asyncio.create_task(binary.read())
            await asyncio.wait_for(source.entered.wait(), 5)
            raise RuntimeError("body")
    with pytest.raises(OSError, match="read aborted"):
        await reader
    assert events[0] is False
    assert source.closed is True
    assert binary.closed
    assert binary._read_health is _ReadHealth.BROKEN


# Direct buffer use (characterized; mixing with text reads is unsupported)


async def test_direct_buffer_seek_does_not_resynchronize_text():
    async with _text() as stream:
        assert await stream.readline() == LINES[0]
        buffered = stream._buffered_text_len()
        assert buffered > 0
        assert await stream.buffer.seek(0) == 0
        # Text keeps its decoded buffer: the next line continues from it.
        assert await stream.readline() == LINES[1]
        assert stream._read_poison_seen is False


async def test_direct_buffer_read_takes_bytes_text_has_not_decoded():
    async with _text() as stream:
        assert await stream.readline() == LINES[0]
        decoded = stream._buffered_text_len()
        rest = await stream.buffer.read()
        assert PAYLOAD.encode().endswith(rest)
        assert len(rest) == len(PAYLOAD) - len(LINES[0]) - decoded


async def test_direct_buffer_close_closes_text():
    stream = _text()
    await stream.open()
    await stream.buffer.close()
    assert stream.closed
    with pytest.raises(ValueError, match="closed"):
        await stream.readline()
    await stream.close()
