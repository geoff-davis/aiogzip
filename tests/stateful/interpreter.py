#!/usr/bin/env python3
"""Replay stateful scenarios through aiogzip's public API only.

The same interpreter runs unchanged against b1, C0 and the candidate. As a
script it imports aiogzip from ``--source-root`` (verified), replays a JSONL
file of scenarios and writes one symbolic trace per scenario. In-process, the
candidate's tests call :func:`run` with hooks that see every raw outcome.

Ordering uses events and gates, never sleeps: a custom source parks a read
on an ``asyncio.Event``; native work parks inside a gated default executor.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import concurrent.futures
import dataclasses
import hashlib
import json
import os
import sys
import tempfile
import threading
import zlib
from pathlib import Path
from typing import Any, Callable

from generator import write_payload

SCENARIO_TIMEOUT = 30.0
INLINE_LIMIT = 64


class InjectedAbort(Exception):
    """Raised from an ``async with`` body to force exceptional context exit."""


class Gate:
    """A one-shot park point shared by the custom source and the executor.

    Each arming creates fresh events, so a worker still waking from an earlier
    release can never observe a later arming's cleared state.
    """

    def __init__(self) -> None:
        self.armed = False
        # What the call that parked was sending: set at park, taken by the
        # next landed event.
        self.parked: dict[str, Any] | None = None
        self.entered = asyncio.Event()
        self.release_async = asyncio.Event()
        self.release_thread = threading.Event()

    def arm(self) -> None:
        self.armed = True
        self.parked = None
        self.entered = asyncio.Event()
        self.release_async = asyncio.Event()
        self.release_thread = threading.Event()

    def release(self) -> None:
        self.armed = False
        self.release_async.set()
        self.release_thread.set()


# Loop turns allowed for a cancellation or abort to settle on-loop before the
# parked worker is released. Turns, not time: no thread can make progress
# while parked, so the outcome is deterministic.
SETTLE_TURNS = 50


async def settle_then_release(gate: Gate, task: asyncio.Task | None) -> None:
    for _ in range(SETTLE_TURNS):
        if task is not None and task.done():
            break
        await asyncio.sleep(0)
    gate.release()


class GatedExecutor(concurrent.futures.ThreadPoolExecutor):
    """Default executor whose next submission parks while the gate is armed."""

    def __init__(self, gate: Gate, loop: asyncio.AbstractEventLoop) -> None:
        super().__init__(max_workers=4)
        self.gate = gate
        self.loop = loop

    def submit(self, fn, /, *args, **kwargs):  # type: ignore[override]
        gate = self.gate
        if not gate.armed:
            return super().submit(fn, *args, **kwargs)
        gate.armed = False
        entered, release = gate.entered, gate.release_thread
        gate.parked = _native_parked(fn)

        def parked():
            self.loop.call_soon_threadsafe(entered.set)
            if not release.wait(SCENARIO_TIMEOUT):
                raise TimeoutError("gated executor was never released")
            return fn(*args, **kwargs)

        return super().submit(parked)


class Source:
    """Async custom source with frames, failures, a gate and close counters."""

    def __init__(self, wire: bytes, config: dict[str, Any], gate: Gate) -> None:
        self.wire = wire
        self.offset = 0
        self.frames = list(config.get("frames") or [])
        self.frame_index = 0
        self.frame_left = self.frames[0] if self.frames else None
        self._seekable = config["seekable"]
        self.gate = gate
        self.fail: str | None = None
        self.closes = 0
        self.calls_after_close = 0
        # Work counters (never part of the public trace).
        self.reads = 0
        self.empty_reads = 0
        self.bytes = 0
        self.seeks = 0
        if config["checkpoint"]:
            self.tell = self._tell

    def _tell(self) -> int:
        return self.offset

    def counters(self) -> dict[str, int]:
        return {
            "reads": self.reads,
            "empty_reads": self.empty_reads,
            "bytes": self.bytes,
            "seeks": self.seeks,
        }

    async def seekable(self) -> bool:
        # Read-mode open awaits this, so an armed gate parks the opener here.
        if self.closes:
            self.calls_after_close += 1
        await _park(self.gate)
        return self._seekable

    async def seek(self, offset: int, whence: int = 0) -> int:
        if self.closes:
            self.calls_after_close += 1
        if self._seekable:
            await _park(self.gate)  # a physical rewind can park, like a read
        self.seeks += 1
        if not self._seekable:
            raise OSError("not seekable")
        if whence != 0:
            raise OSError("test source supports absolute seeks only")
        self.offset = offset
        self.frame_index = 0
        self.frame_left = self.frames[0] if self.frames else None
        return offset

    def _take(self, size: int) -> bytes:
        limit = len(self.wire) - self.offset if size < 0 else size
        if self.frame_left is not None:
            if self.frame_left == 0 and self.frame_index + 1 < len(self.frames):
                self.frame_index += 1
                self.frame_left = self.frames[self.frame_index]
            if self.frame_index < len(self.frames) and self.frame_left:
                limit = min(limit, self.frame_left)
        data = self.wire[self.offset : self.offset + limit]
        self.offset += len(data)
        if self.frame_left is not None and self.frame_left:
            self.frame_left -= len(data)
        return data

    async def read(self, size: int = -1) -> bytes:
        if self.closes:
            self.calls_after_close += 1
        await _park(self.gate)
        self.reads += 1
        fail, self.fail = self.fail, None
        if fail == "no_effect":
            raise OSError("injected source failure without effect")
        if fail == "consumed":
            taken = self._take(size)
            self.bytes += len(taken)
            if not taken:
                # At the end of the source there is nothing to consume, so the
                # failure has no effect; only a checkpoint can show that.
                raise OSError("injected source failure at end of input")
            raise OSError("injected source failure after consuming input")
        data = self._take(size)
        self.bytes += len(data)
        if not data and size != 0:
            self.empty_reads += 1
        return data

    async def close(self) -> None:
        self.closes += 1


def _native_parked(fn) -> dict[str, Any]:
    """Describe a parked executor call: aiofiles passes a ``partial``, the
    candidate a ``_NativeSourceCall``; both expose ``args``."""
    method = getattr(fn, "method", None) or getattr(
        getattr(fn, "func", None), "__name__", None
    )
    args = getattr(fn, "args", ())
    data = args[0] if args and isinstance(args[0], (bytes, bytearray)) else None
    return {
        "via": "native",
        "method": method,
        "bytes": None if data is None else bytes(data),
    }


class Sink:
    """Async custom sink with short writes, failures, a gate and counters."""

    def __init__(self, config: dict[str, Any], gate: Gate) -> None:
        self.data = bytearray()
        self.short: int | None = config["short"]
        self.gate = gate
        self.fail: str | None = None
        self.closes = 0
        self.calls_after_close = 0

    async def write(self, data: bytes) -> int:
        if self.closes:
            self.calls_after_close += 1
        parked = None
        if self.gate.armed:
            # "resumed" and "accepted" stay unset unless the parked call
            # resumes (rather than being cancelled) and stores bytes.
            parked = {
                "via": "custom",
                "method": "write",
                "bytes": bytes(data),
                "resumed": False,
                "accepted": b"",
            }
            self.gate.parked = parked
        await _park(self.gate)
        if parked is not None:
            parked["resumed"] = True
        fail, self.fail = self.fail, None
        if fail == "no_effect":
            raise OSError("injected sink failure without effect")
        count = len(data) if self.short is None else min(len(data), self.short)
        if fail == "partial":
            count = len(data) // 2
        self.data += data[:count]
        if parked is not None:
            parked["accepted"] = bytes(data[:count])
        if fail == "partial":
            raise OSError("injected sink failure after a partial write")
        return count

    async def flush(self) -> None:
        if self.closes:
            self.calls_after_close += 1

    async def close(self) -> None:
        self.closes += 1


async def _park(gate: Gate) -> None:
    """Park the calling coroutine if the gate is armed."""
    if gate.armed:
        gate.armed = False
        release = gate.release_async
        gate.entered.set()
        await release.wait()


def _open_fds() -> int | None:
    """Open descriptors of this process, where the platform exposes them."""
    try:
        return len(os.listdir("/proc/self/fd"))
    except OSError:
        return None


def decode_output(data: bytes) -> dict[str, Any]:
    """Decode a writer's output: payload, whether a member completed, error."""
    decompressor = zlib.decompressobj(31)
    try:
        decoded = decompressor.decompress(data)
    except zlib.error as error:
        return {"decoded": b"", "complete": False, "error": str(error)}
    complete = decompressor.eof and not decompressor.unused_data
    return {"decoded": decoded, "complete": complete, "error": None}


@dataclasses.dataclass
class Outcome:
    kind: str  # "ok", "error", "cancelled", "stop", "skipped"
    value: Any = None
    error: BaseException | None = None


@dataclasses.dataclass
class Event:
    index: int
    op: dict[str, Any]
    outcome: Outcome
    second: Outcome | None = None  # overlap/close_during/abort partner
    work: dict[str, int] | None = None  # source counters spent (raw only)
    # "unparked": an abort whose call finished before parking, so the exit
    # had no active call (raw only; the trace shows it as the call outcome).
    note: str | None = None
    parked: dict[str, Any] | None = None  # the parked call (raw only)


Hook = Callable[[Any, Event, "Context"], None]


@dataclasses.dataclass
class Context:
    scenario: dict[str, Any]
    source: Source | None
    path: Path | None
    sink: Sink | None = None
    handle: Any = None
    phase: str = "body"  # "acquire", "body", "after"


async def _call(coroutine) -> Outcome:
    try:
        value = await coroutine
    except StopAsyncIteration:
        return Outcome("stop")
    except asyncio.CancelledError:
        raise
    except Exception as error:  # noqa: BLE001 - recorded, never swallowed silently
        return Outcome("error", error=error)
    return Outcome("ok", value)


def _surface(handle, op: dict[str, Any], text: dict[str, Any] | None):
    """Return a coroutine for one ordinary public call."""
    name = op["op"]
    if name == "write":
        return handle.write(write_payload(op, text))
    if name == "writelines":
        return handle.writelines([write_payload(part, text) for part in op["parts"]])
    if name == "flush":
        return handle.flush()
    if name == "write_flush":

        async def write_flush():
            await handle.write(write_payload(op, text))
            return await handle.flush()

        return write_flush()
    if name == "read":
        return handle.read(op.get("n", -1))
    if name == "read1":
        return handle.read1(op.get("n", -1))
    if name == "peek":
        return handle.peek(op.get("n", -1))
    if name == "readinto":

        async def readinto():
            buffer = bytearray(op["n"])
            count = await handle.readinto(buffer)
            return bytes(buffer[:count])

        return readinto()
    if name == "readline":
        return handle.readline(op.get("limit", -1))
    if name == "readlines":
        return handle.readlines(op.get("hint", -1))
    if name == "next":
        return handle.__anext__()
    if name in ("tell", "tell_mark"):
        return handle.tell()
    if name == "seek_abs":
        return handle.seek(op["target"])
    if name == "seek_rel":
        return handle.seek(op["delta"], os.SEEK_CUR)
    if name == "seek_back":

        async def seek_back():
            return await handle.seek(max(0, await handle.tell() - op["back"]))

        return seek_back()
    if name == "seek0":
        return handle.seek(0)
    if name == "buffer_read":
        return handle.buffer.read(op.get("n", -1))
    if name == "close":
        return handle.close()
    if name == "open":
        return handle.open()
    raise ValueError(f"unknown operation {name!r}")


async def _parked(handle, op, gate: Gate, partner, text: dict[str, Any] | None):
    """Park ``op['call']`` inside a source read, then run ``partner``."""
    gate.arm()
    task = asyncio.create_task(_call(_surface(handle, op["call"], text)))
    waiter = asyncio.create_task(gate.entered.wait())
    done, _ = await asyncio.wait({task, waiter}, return_when=asyncio.FIRST_COMPLETED)
    if task in done:
        # The call finished from buffered data without reaching the source.
        waiter.cancel()
        gate.armed = False
        return await task, Outcome("skipped", "call did not reach the source")
    second = await partner(task)
    await settle_then_release(gate, task)
    try:
        first = await task
    except asyncio.CancelledError:
        first = Outcome("cancelled")
    return first, second


async def _cancel_partner(task):
    task.cancel()
    return Outcome("ok", "cancel requested")


PARKED_OPEN_FAULTS = ("cancel_open", "overlap_open", "overlap_close")


async def run(
    package,
    scenario: dict[str, Any],
    workdir: Path,
    hooks: tuple[Hook, ...] = (),
) -> list[Event]:
    """Replay ``scenario``; return raw events (hooks see each as it lands)."""
    loop = asyncio.get_running_loop()
    fds_before = _open_fds()
    gate = Gate()
    loop.set_default_executor(GatedExecutor(gate, loop))
    mode = scenario["mode"]
    writing = mode in ("wb", "wt")
    text_options = scenario["text"]
    text = text_options is not None
    config = scenario["source"]
    acquisition = scenario["acquisition"]
    fault = acquisition.get("fault", "none")
    options: dict[str, Any] = {"chunk_size": scenario["chunk_size"]}
    if scenario.get("max_decompressed_size") is not None:
        options["max_decompressed_size"] = scenario["max_decompressed_size"]
    if "max_rewind_cache_size" in scenario:
        options["max_rewind_cache_size"] = scenario["max_rewind_cache_size"]
    if writing:
        options["mtime"] = 0  # a fixed header, so raw output is comparable
    if text:
        options["encoding"] = text_options["encoding"]
        options["newline"] = text_options["newline"]
    source = sink = path = None
    target: str | None = None
    if config["kind"] == "custom":
        if writing:
            sink = Sink(config, gate)
            options.update(fileobj=sink, closefd=config["closefd"])
        else:
            source = Source(base64.b64decode(scenario["wire"]), config, gate)
            options.update(fileobj=source, closefd=config["closefd"])
    else:
        path = workdir / f"scenario-{scenario['seed']}.gz"
        if not writing:
            path.write_bytes(base64.b64decode(scenario["wire"]))
        target = str(path)
        if fault == "missing":
            target = str(workdir / "missing" / "scenario.gz")
        elif fault == "directory":
            target = str(workdir)
    context = Context(scenario, source, path, sink)
    events: list[Event] = []
    # Scenarios that can abort or cancel a parked write keep raw bytes, for
    # the writer-abort predicate's exact-prefix checks.
    retain = writing and any(op["op"] in ("abort", "cancel") for op in scenario["ops"])
    spent = source.counters() if source is not None else None

    def land(event: Event) -> None:
        nonlocal spent
        if source is not None:
            now = source.counters()
            event.work = {key: now[key] - spent[key] for key in now}
            spent = now
        if gate.parked is not None and event.op["op"] != "final":
            event.parked, gate.parked = gate.parked, None
            if retain:
                event.parked = {
                    key: {"base64": base64.b64encode(item).decode("ascii")}
                    if isinstance(item, bytes)
                    else item
                    for key, item in event.parked.items()
                }
        events.append(event)
        for hook in hooks:
            hook(context.handle, event, context)

    construct = acquisition["construct"]
    if construct == "factory":
        handle = package.open(target, mode, **options)
    elif text:
        handle = package.AsyncGzipTextFile(target, mode, **options)
    else:
        handle = package.AsyncGzipBinaryFile(target, mode, **options)
    context.handle = handle
    ops = scenario["ops"]
    terminal = {"close", "abort", "raise_exit"}
    split = next((i + 1 for i, op in enumerate(ops) if op["op"] in terminal), len(ops))
    body_ops, after_ops = ops[:split], ops[split:]
    cookies: dict[str, Any] = {}
    releasers: list[asyncio.Task] = []

    async def step(index: int, op: dict[str, Any]) -> None:
        name = op["op"]
        if name in ("fail_no_effect", "fail_consumed"):
            source.fail = name[len("fail_") :]
            land(Event(index, op, Outcome("ok", "armed")))
            return
        if name in ("fail_sink_no_effect", "fail_sink_partial"):
            sink.fail = name[len("fail_sink_") :]
            land(Event(index, op, Outcome("ok", "armed")))
            return
        if name == "seek_mark":
            if op["label"] not in cookies:
                land(Event(index, op, Outcome("skipped", "no cookie")))
                return
            outcome = await _call(handle.seek(cookies[op["label"]]))
            land(Event(index, op, outcome))
            return
        if name == "overlap":
            second_op = op["second"]

            async def partner(task):
                return await _call(_surface(handle, second_op, text_options))

            first, second = await _parked(handle, op, gate, partner, text_options)
            land(Event(index, op, first, second))
            return
        if name == "close_during":

            async def partner(task):
                return await _call(handle.close())

            first, second = await _parked(handle, op, gate, partner, text_options)
            land(Event(index, op, first, second))
            return
        if name == "cancel":
            first, second = await _parked(
                handle, op, gate, _cancel_partner, text_options
            )
            land(Event(index, op, first, second))
            return
        if name == "abort":
            gate.arm()
            task = asyncio.create_task(
                _call(_surface(handle, op["call"], text_options))
            )
            waiter = asyncio.create_task(gate.entered.wait())
            done, _ = await asyncio.wait(
                {task, waiter}, return_when=asyncio.FIRST_COMPLETED
            )
            if task in done:
                waiter.cancel()
                gate.armed = False
                pending = None
                first = await task
            else:
                pending = task
                first = None
            # Release only after exit has had its turns to cancel or settle,
            # and concurrently with it, so native settlement can finish.
            releaser = asyncio.create_task(settle_then_release(gate, pending))
            releasers.append(releaser)
            abort = InjectedAbort(f"abort at {index}")
            abort.pending = pending  # type: ignore[attr-defined]
            abort.first = first  # type: ignore[attr-defined]
            abort.index = index  # type: ignore[attr-defined]
            raise abort
        if name == "raise_exit":
            abort = InjectedAbort(f"exit at {index}")
            abort.pending = None  # type: ignore[attr-defined]
            abort.first = None  # type: ignore[attr-defined]
            abort.index = index  # type: ignore[attr-defined]
            raise abort
        outcome = await _call(_surface(handle, op, text_options))
        if name == "tell_mark" and outcome.kind == "ok":
            cookies[op["label"]] = outcome.value
        land(Event(index, op, outcome))

    async def body() -> None:
        for index, op in enumerate(body_ops):
            await step(index, op)

    async def acquire() -> Outcome:
        """Explicit open(), with the scenario's opening fault applied."""
        op = {"op": "acquire", "fault": fault}
        if fault == "init_fail":
            sink.fail = "no_effect"
        if fault not in PARKED_OPEN_FAULTS:
            outcome = await _call(handle.open())
            land(Event(-1, op, outcome))
            if fault == "init_fail" and outcome.kind == "error":
                outcome = await _call(handle.open())
                land(Event(-1, {"op": "acquire", "fault": "retry"}, outcome))
            return outcome
        gate.arm()
        task = asyncio.create_task(_call(handle.open()))
        waiter = asyncio.create_task(gate.entered.wait())
        done, _ = await asyncio.wait(
            {task, waiter}, return_when=asyncio.FIRST_COMPLETED
        )
        if task in done:
            waiter.cancel()
            gate.armed = False
            first = await task
            second = Outcome("skipped", "open did not park")
        else:
            if fault == "cancel_open":
                second = await _cancel_partner(task)
            elif fault == "overlap_open":
                second = await _call(handle.open())
            else:
                second = await _call(handle.close())
            await settle_then_release(gate, task)
            try:
                first = await task
            except asyncio.CancelledError:
                first = Outcome("cancelled")
        land(Event(-1, op, first, second))
        if first.kind == "cancelled":
            first = await _call(handle.open())
            land(Event(-1, {"op": "acquire", "fault": "retry"}, first))
        return first

    async def land_abort(abort: InjectedAbort, outcome: Outcome) -> None:
        second = None
        note = None
        pending = abort.pending  # type: ignore[attr-defined]
        if pending is not None:
            try:
                second = await pending
            except asyncio.CancelledError:
                second = Outcome("cancelled")
        elif abort.first is not None:  # type: ignore[attr-defined]
            second = abort.first  # type: ignore[attr-defined]
            note = "unparked"
        index = abort.index  # type: ignore[attr-defined]
        land(Event(index, body_ops[index], outcome, second, note=note))

    async def drive() -> None:
        context.phase = "acquire"
        if acquisition["enter"] == "async_with":
            try:
                async with handle:
                    land(Event(-1, {"op": "acquire", "fault": fault}, Outcome("ok")))
                    context.phase = "body"
                    await body()
                    context.phase = "exit"
                if context.phase == "exit":
                    land(Event(split, {"op": "exit"}, Outcome("ok")))
            except InjectedAbort as abort:
                await land_abort(abort, Outcome("error", error=abort))
            except Exception as error:  # noqa: BLE001 - acquisition failure
                if isinstance(error.__context__, InjectedAbort):
                    # Exit's close raised, replacing the body's exception.
                    await land_abort(error.__context__, Outcome("error", error=error))
                elif context.phase == "acquire":
                    land(
                        Event(
                            -1,
                            {"op": "acquire", "fault": fault},
                            Outcome("error", error=error),
                        )
                    )
                elif context.phase == "exit":
                    land(Event(split, {"op": "exit"}, Outcome("error", error=error)))
                else:
                    raise
        else:
            outcome = await acquire()
            # A failed open leaves an unopened handle; its scenarios probe it.
            if outcome.kind == "ok" or fault in ("missing", "directory"):
                context.phase = "body"
                await body()
        for releaser in releasers:
            await releaser
        context.phase = "after"
        for offset, op in enumerate(after_ops):
            await step(split + offset, op)
        if not handle.closed:
            land(Event(len(ops), {"op": "cleanup_close"}, await _call(handle.close())))

    try:
        async with asyncio.timeout(SCENARIO_TIMEOUT):
            await drive()
    except TimeoutError:
        gate.release()
        land(Event(len(ops) + 1, {"op": "timeout"}, Outcome("error")))
    finally:
        gate.release()
    final: dict[str, Any] = {"closed": handle.closed}
    if source is not None:
        final.update(
            source_closes=source.closes,
            source_calls_after_close=source.calls_after_close,
        )
    if sink is not None:
        final.update(
            source_closes=sink.closes,
            source_calls_after_close=sink.calls_after_close,
        )
    if writing:
        if sink is not None:
            output = bytes(sink.data)
        elif path is not None and path.is_file():
            output = path.read_bytes()
        else:
            output = b""
        final["output"] = decode_output(output)
        # W1-eligible scenarios keep the raw bytes for the exact-prefix
        # predicate; the rest compare a digest.
        if retain:
            final["output_raw"] = {"base64": base64.b64encode(output).decode("ascii")}
        else:
            final["output_raw"] = {"bytes_len": len(output), "sha256": _digest(output)}
    fds_after = _open_fds()
    if fds_before is not None and fds_after is not None:
        final["fd_delta"] = fds_after - fds_before
    land(Event(len(ops) + 2, {"op": "final"}, Outcome("ok", final)))
    return events


def symbolic(events: list[Event], workdir: str | None = None) -> list[Any]:
    """Serialize raw events to a JSON trace; text cookies become symbols.

    The per-run temporary ``workdir`` in error messages becomes ``$WORKDIR``.
    """
    symbols: dict[Any, str] = {}

    def value(item: Any, op: str) -> Any:
        if op in ("tell_mark", "seek_mark") and isinstance(item, int):
            return symbols.setdefault(item, f"C{len(symbols) + 1}")
        if isinstance(item, (bytes, bytearray)):
            if len(item) <= INLINE_LIMIT:
                return {"bytes": bytes(item).hex()}
            return {"bytes_len": len(item), "sha256": _digest(bytes(item))}
        if isinstance(item, str):
            if len(item) <= INLINE_LIMIT:
                return {"str": item}
            return {
                "str_len": len(item),
                "sha256": _digest(item.encode("utf-8", "surrogatepass")),
            }
        if isinstance(item, list):
            return [value(x, op) for x in item]
        if isinstance(item, dict):
            if item.keys() == {"base64"}:  # retained raw bytes
                return item
            return {k: value(v, op) for k, v in item.items()}
        if item is None or isinstance(item, (bool, int, float)):
            return item
        # open() returns the handle itself; record only that it did.
        return {"object": type(item).__name__}

    def outcome(item: Outcome | None, op: str) -> Any:
        if item is None:
            return None
        if item.kind == "error":
            error = item.error
            if error is None:
                return {"error": "timeout"}
            message = str(error)
            if workdir:
                message = message.replace(workdir, "$WORKDIR")
            return {"error": type(error).__name__, "message": message}
        if item.kind == "ok":
            return {"ok": value(item.value, op)}
        return {item.kind: True}

    trace = []
    for event in events:
        name = event.op["op"]
        row = [event.index, name, outcome(event.outcome, name)]
        if event.second is not None:
            row.append(outcome(event.second, event.op.get("call", {}).get("op", name)))
        if event.parked is not None:
            row.append({"parked": value(event.parked, name)})
        trace.append(row)
    return trace


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def replay(package, scenario: dict[str, Any], hooks: tuple[Hook, ...] = ()):
    """Run one scenario on a fresh event loop; return (raw events, trace)."""
    with tempfile.TemporaryDirectory(prefix="aiogzip-stateful-") as directory:
        events = asyncio.run(run(package, scenario, Path(directory), hooks))
    return events, symbolic(events, directory)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--engine", choices=("stdlib", "zlib-ng"), required=True)
    parser.add_argument("--scenarios", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.source_root.resolve()
    os.environ["AIOGZIP_ENGINE"] = args.engine
    sys.path.insert(0, str(root / "src"))
    import aiogzip

    origin = Path(aiogzip.__file__).resolve()
    if not origin.is_relative_to(root / "src"):
        raise RuntimeError(f"wrong import origin: {origin}")
    engines = dataclasses.asdict(aiogzip.engine_info())
    if args.engine == "stdlib":
        assert set(engines.values()) == {"stdlib-zlib"}, engines
    else:
        assert engines["decompression"] == "zlib-ng", engines
    traces = {}
    with args.scenarios.open(encoding="utf-8") as lines:
        for line in lines:
            scenario = json.loads(line)
            _events, trace = replay(aiogzip, scenario)
            traces[str(scenario["seed"])] = trace
    record = {
        "schema": 1,
        "source_import": str(origin),
        "engines": engines,
        "python": sys.version,
        "traces": traces,
    }
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(record, output, ensure_ascii=False)
        output.write("\n")


if __name__ == "__main__":
    main()
