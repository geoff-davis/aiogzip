"""Reference model for the WP10 stateful harness.

Two importable tables are written from the documented contracts (the
open-ownership, read-health and bridge designs), not from the implementation:
``LIFECYCLE`` (one row per handle event) and ``READ_HEALTH``. ``Checker``
consumes the interpreter's raw events for one scenario and reports every
violation of those tables and of the expected-bytes oracle.

Expected bytes come from the generator's clean payloads, never from decoding
the produced file. See plans/design/v2.0.0b2-wp10-qualification.md.
"""

from __future__ import annotations

import base64
import codecs
import dataclasses
import gzip
import io
import os
import types
from enum import Enum
from typing import Any

from oracle import engine_modules, raw_reference, wire_reference


class Lifecycle(Enum):
    UNOPENED = "UNOPENED"
    OPENING = "OPENING"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class Health(Enum):
    HEALTHY = "HEALTHY"
    VALIDATION_SALVAGE = "VALIDATION_SALVAGE"
    BROKEN = "BROKEN"


U, OPENING, OPEN, CLOSED = (
    Lifecycle.UNOPENED,
    Lifecycle.OPENING,
    Lifecycle.OPEN,
    Lifecycle.CLOSED,
)
HEALTHY, SALVAGE, BROKEN = Health.HEALTHY, Health.VALIDATION_SALVAGE, Health.BROKEN


@dataclasses.dataclass(frozen=True)
class LifecycleRow:
    source: Lifecycle
    event: str
    target: Lifecycle
    outcome: str


# The lifecycle and ownership table (design, "Lifecycle and ownership table").
LIFECYCLE: tuple[LifecycleRow, ...] = (
    LifecycleRow(U, "open_starts", OPENING, "open/close reservation active"),
    LifecycleRow(
        OPENING, "open_succeeds", OPEN, "resource published; reservation idle"
    ),
    LifecycleRow(
        OPENING,
        "acquisition_fails",
        U,
        "natively acquired resource closed exactly once; nothing published",
    ),
    LifecycleRow(
        OPENING,
        "initialization_fails",
        U,
        "owned resource closed once; borrowed resource never closed",
    ),
    LifecycleRow(
        OPENING,
        "cleanup_raises_exception",
        U,
        "opening exception propagates; cleanup error added as a note",
    ),
    LifecycleRow(
        OPENING,
        "cleanup_raises_base_exception",
        U,
        "BaseException propagates with the opening failure as __context__",
    ),
    LifecycleRow(
        OPENING, "overlapping_open_or_close", OPENING, "ConcurrentOperationError"
    ),
    LifecycleRow(OPENING, "exceptional_context_exit", OPENING, "no closure claimed"),
    LifecycleRow(OPEN, "open", OPEN, "ValueError"),
    LifecycleRow(OPEN, "call_starts", OPEN, "call reservation active"),
    LifecycleRow(OPEN, "overlapping_call", OPEN, "ConcurrentOperationError"),
    LifecycleRow(OPEN, "close_during_call", OPEN, "ConcurrentOperationError"),
    LifecycleRow(
        OPEN,
        "context_exit_abort",
        CLOSED,
        "health BROKEN; owned resource closed; text notified",
    ),
    LifecycleRow(
        OPEN,
        "context_exit_abort_cleanup_fails",
        OPEN,
        "health BROKEN; text notified; close() retries the underlying close",
    ),
    LifecycleRow(
        OPEN,
        "close",
        CLOSED,
        "health and eof retained; owned resource closed once; observers detached",
    ),
    # Before any successful open: calls are refused and close latches.
    LifecycleRow(U, "call_starts", U, "ValueError: file not opened"),
    LifecycleRow(U, "close", CLOSED, "nothing acquired, nothing closed"),
    LifecycleRow(
        CLOSED,
        "close",
        CLOSED,
        "no state change; text over a directly closed binary surfaces unwritten "
        "encoder bytes as ValueError",
    ),
    LifecycleRow(CLOSED, "open", CLOSED, "ValueError"),
    LifecycleRow(CLOSED, "call_starts", CLOSED, "ValueError"),
)


def lifecycle_after(state: Lifecycle, event: str) -> LifecycleRow:
    for row in LIFECYCLE:
        if row.source is state and row.event == event:
            return row
    raise KeyError((state, event))


# The read-health table (design, "Read-health table"): (health, event) ->
# health. ``eof`` is True whenever health is not HEALTHY.
READ_HEALTH: dict[tuple[Health, str], Health] = {}
for _health in Health:
    READ_HEALTH[(_health, "rewind_ok")] = HEALTHY
    READ_HEALTH[(_health, "rewind_failed")] = _health
    READ_HEALTH[(_health, "abort")] = BROKEN
    READ_HEALTH[(_health, "close")] = _health
    READ_HEALTH[(_health, "overlap_rejected")] = _health
READ_HEALTH.update(
    {
        (HEALTHY, "no_effect_failure"): HEALTHY,
        (HEALTHY, "uncertain_failure"): BROKEN,
        (HEALTHY, "consumed_failure"): BROKEN,
        (HEALTHY, "cancel_no_effect"): HEALTHY,
        (HEALTHY, "cancel_uncertain"): BROKEN,
        (HEALTHY, "validation_failure"): SALVAGE,
        (HEALTHY, "limit_failure"): BROKEN,
        # A cancelled rewind from an unhealthy reader: a proven no-effect
        # cancellation leaves health as it was; an uncertain one breaks the
        # reader like any uncertain source outcome.
        (SALVAGE, "cancel_no_effect"): SALVAGE,
        (SALVAGE, "cancel_uncertain"): BROKEN,
        (BROKEN, "cancel_no_effect"): BROKEN,
        (BROKEN, "cancel_uncertain"): BROKEN,
        (SALVAGE, "salvage_exhausted"): SALVAGE,
        (BROKEN, "terminal_refusal"): BROKEN,
        (SALVAGE, "terminal_refusal"): SALVAGE,
    }
)
# Every reachable (lifecycle, health, eof) combination.
REACHABLE = frozenset(
    {(OPEN, HEALTHY, False), (OPEN, HEALTHY, True)}
    | {(OPEN, h, True) for h in (SALVAGE, BROKEN)}
    | {(CLOSED, HEALTHY, False), (CLOSED, HEALTHY, True)}
    | {(CLOSED, h, True) for h in (SALVAGE, BROKEN)}
)


def health_after(health: Health, event: str) -> Health:
    return READ_HEALTH[(health, event)]


BROKEN_MESSAGE = "read stream is broken"
ABORTED_MESSAGE = "read aborted because the gzip file was closed"
CLOSED_MESSAGE = "I/O operation on closed file"
INJECTED_NO_EFFECT = "injected source failure without effect"
INJECTED_CONSUMED = "injected source failure after consuming input"
INJECTED_AT_END = "injected source failure at end of input"
NOT_SEEKABLE = "not seekable"
LIMIT_MESSAGE = "max_decompressed_size"
READ_OPS = {
    "read",
    "read1",
    "readinto",
    "peek",
    "readline",
    "readlines",
    "next",
    "buffer_read",
}
SEEK_OPS = {"seek_abs", "seek_rel", "seek_back", "seek0", "seek_mark"}


def text_model(
    data: bytes, encoding: str, newline: str | None, final: bool, boundary: bool = False
) -> str:
    """Decode exactly as the text reader's stages do, incrementally.

    ``boundary`` models a failure boundary: an incomplete trailing character
    stays held (no continuation can complete it), while a pending CR resolves
    as a line end, since every continuation of the bytes decodes to text that
    begins with that resolution.
    """
    decoder = codecs.getincrementaldecoder(encoding)()
    decoded = decoder.decode(data, final=final)
    if newline is None or newline == "":
        stage = io.IncrementalNewlineDecoder(None, translate=newline is None)
        decoded = stage.decode(decoded, final=final or boundary)
    return decoded


def line_terminators(newline: str | None, text: bool) -> tuple[Any, ...]:
    if not text:
        return (b"\n",)
    if newline is None:
        return ("\n",)
    if newline == "":
        return ("\r\n", "\n", "\r")
    return (newline,)


@dataclasses.dataclass
class Expectation:
    """Bytes a reader may deliver, and the delivered-length bounds at failure."""

    upper: bytes  # every allowed byte, in order
    lower: int  # delivered bytes guaranteed before a failure is terminal
    clean: bool  # whether the stream must reach validated EOF
    failure: str | None  # "validation", "limit" or None
    reference: dict[str, Any] | None = None


def expectation(scenario: dict[str, Any], engine: str) -> Expectation:
    payloads = [base64.b64decode(p) for p in scenario["payloads"]]
    whole = b"".join(payloads)
    corruption = scenario["corruption"]
    kind = corruption["kind"]
    if kind == "wire":
        # A lossy view whose splice lies inside a member: the bytes come from
        # the engine-matched member-loop oracle over the spliced wire itself.
        module = engine_modules()[engine]
        reference = wire_reference(module, base64.b64decode(scenario["wire"]))
        output = reference["output"]
        limit = corruption.get("limit")
        if limit is not None and len(output) > limit:
            # Every byte past the limit precedes the wire's own failure, so
            # the limit fails first, exactly as for a clean limit scenario.
            return Expectation(output[:limit], 0, False, "limit", reference)
        clean = reference["failure"] is None
        failure = None if clean else "validation"
        lower = reference["validated"]
        if scenario["mode"] == "rt":
            decoder = codecs.getincrementaldecoder(scenario["text"]["encoding"])()
            try:
                decoder.decode(output, final=clean)
            except UnicodeDecodeError as error:
                if clean:
                    raise AssertionError(
                        "a clean wire view does not decode as text"
                    ) from error
                # Text holds only the bytes before the first undecodable
                # sequence; the reader may raise the gzip failure first, but a
                # decode error is not modeled and stays a violation.
                output, lower = output[: error.start], min(lower, error.start)
        return Expectation(output, lower, clean, failure, reference)
    if kind == "none" or (kind == "limit" and corruption["limit"] >= len(whole)):
        return Expectation(whole, len(whole), True, None)
    if kind == "limit":
        return Expectation(whole[: corruption["limit"]], 0, False, "limit")
    index = corruption["member"]
    start = sum(len(p) for p in payloads[:index])
    end = start + len(payloads[index])
    if kind in ("crc", "isize"):
        return Expectation(whole[:end], end, False, "validation")
    if kind == "truncate":
        return Expectation(whole[:end], start, False, "validation")
    wire = base64.b64decode(scenario["wire"])
    body = wire[corruption["body_start"] : corruption["body_end"]]
    reference = raw_reference(engine_modules()[engine], body)
    if reference["error"] is None:
        raise AssertionError("body corruption scenario has no engine error")
    upper = whole[:start] + reference["output"]
    return Expectation(upper, start, False, "validation", reference)


OPEN_FAULT_ERRORS: dict[str, tuple[type[BaseException], ...]] = {
    "missing": (FileNotFoundError,),
    # Windows reports opening a directory as PermissionError.
    "directory": (IsADirectoryError, PermissionError),
}
INJECTED_SINK = "injected sink failure"
WRITE_BROKEN_MESSAGE = "write stream is broken"
WRITE_ABORTED = "aborted because the gzip file was closed"


class _HandleChecker:
    """Lifecycle, acquisition, close and resource checks shared by both modes."""

    def __init__(self, scenario: dict[str, Any]) -> None:
        self.scenario = scenario
        source = scenario["source"]
        self.native = source["kind"] == "native"
        self.closefd = self.native or source["closefd"]
        self.fault = scenario["acquisition"].get("fault", "none")
        self.lifecycle = U
        self.published = False
        self.violations: list[str] = []
        self.coverage: set[tuple[str, str]] = set()

    def fail(self, index: int, message: str) -> None:
        self.violations.append(f"op {index}: {message}")

    def lifecycle_event(self, event: str) -> None:
        try:
            row = lifecycle_after(self.lifecycle, event)
        except KeyError:
            self.violations.append(
                f"op ?: no lifecycle row for {self.lifecycle.value} + {event}"
            )
            return
        self.coverage.add(("lifecycle", f"{row.source.value}->{event}"))
        self.lifecycle = row.target

    def expect_ok(self, index: int, name: str, outcome) -> None:
        if outcome.kind != "ok":
            self.fail(index, f"{name} did not succeed: {describe(outcome)}")

    def expect_concurrent(self, index: int, outcome) -> None:
        if (
            outcome is None
            or outcome.kind != "error"
            or (type(outcome.error).__name__ != "ConcurrentOperationError")
        ):
            self.fail(
                index, f"expected ConcurrentOperationError, got {describe(outcome)}"
            )

    def handle_acquire(self, index: int, op: dict[str, Any], first, second) -> None:
        """One open attempt; ``second`` is the overlapping partner, if any."""
        fault = op.get("fault", "none")
        self.lifecycle_event("open_starts")
        if second is not None and second.kind != "skipped":
            if fault in ("overlap_open", "overlap_close"):
                self.lifecycle_event("overlapping_open_or_close")
                self.expect_concurrent(index, second)
        if first.kind == "ok":
            self.lifecycle_event("open_succeeds")
            self.published = True
            return
        if first.kind == "cancelled":
            if fault != "cancel_open":
                self.fail(index, "open was cancelled without a cancellation")
        elif first.kind == "error":
            self.check_open_error(index, fault, first.error)
        else:
            self.fail(index, f"open outcome {describe(first)}")
        self.lifecycle_event(
            "acquisition_fails" if self.native else "initialization_fails"
        )

    def check_open_error(self, index: int, fault: str, error: BaseException) -> None:
        expected = OPEN_FAULT_ERRORS.get(fault)
        if expected is not None:
            if not isinstance(error, expected):
                self.fail(index, f"{fault} open raised {type(error).__name__}: {error}")
            return
        if fault == "init_fail" and INJECTED_SINK in str(error):
            return
        self.fail(index, f"open raised unexpected {type(error).__name__}: {error}")

    def handle_unopened_call(self, index: int, op: dict[str, Any], outcome) -> None:
        if op["op"] == "open":
            # A retried open meets the same fault.
            self.handle_acquire(
                index, {"op": "open", "fault": self.fault}, outcome, None
            )
            return
        self.lifecycle_event("call_starts")
        if not (outcome.kind == "error" and isinstance(outcome.error, ValueError)):
            self.fail(index, f"{op['op']} on an unopened handle: {describe(outcome)}")

    def handle_closed_call(self, index: int, name: str, outcome) -> None:
        if name == "open":
            self.lifecycle_event("open")
        else:
            self.lifecycle_event("call_starts")
        error = outcome.error
        if not (outcome.kind == "error" and isinstance(error, ValueError)):
            self.fail(index, f"{name} on a closed handle: {describe(outcome)}")

    def handle_double_open(self, index: int, outcome) -> None:
        self.lifecycle_event("open")
        if not (outcome.kind == "error" and isinstance(outcome.error, ValueError)):
            self.fail(index, f"open on an open handle: {describe(outcome)}")

    def check_final(self, final: dict[str, Any]) -> None:
        if final.get("closed") is not (self.lifecycle is CLOSED):
            self.fail(-1, f"closed={final.get('closed')} but model is {self.lifecycle}")
        if "source_closes" in final:
            closed = self.published and self.lifecycle is CLOSED
            expected = 1 if (self.closefd and closed) else 0
            if final["source_closes"] != expected:
                self.fail(
                    -1,
                    f"source closed {final['source_closes']} times, expected {expected}",
                )
            if final["source_calls_after_close"]:
                self.fail(-1, "source was touched after it was closed")
        if final.get("fd_delta"):
            self.fail(-1, f"{final['fd_delta']} file descriptors leaked")


class Checker(_HandleChecker):
    """Check one read scenario's raw events against the tables and the oracle."""

    def __init__(self, scenario: dict[str, Any], engine: str) -> None:
        super().__init__(scenario)
        self.text = scenario["mode"] == "rt"
        self.expect = expectation(scenario, engine)
        source = scenario["source"]
        self.seekable = self.native or source["seekable"]
        self.checkpoint = not self.native and source["checkpoint"]
        self.wire_size = len(base64.b64decode(scenario["wire"]))
        self.source_bytes = 0
        self.source_seeks = 0
        if self.text:
            options = scenario["text"]
            encoding, newline = options["encoding"], options["newline"]
            self.newline = newline
            final = self.expect.clean
            self.upper: Any = text_model(
                self.expect.upper, encoding, newline, final, boundary=not final
            )
            self.lower = len(
                text_model(
                    self.expect.upper[: self.expect.lower], encoding, newline, False
                )
            )
            if not self.expect.clean:
                # Characters decodable from the allowed bytes, held tail kept.
                self.lower = min(self.lower, len(self.upper))
        else:
            self.newline = None
            self.upper = self.expect.upper
            self.lower = self.expect.lower
        self.health = HEALTHY
        self.eof = False
        # Contract-permitted uncertainty: a failed forward seek may have
        # skipped some of the bytes it was asked to skip, and a BROKEN
        # reader's position is unspecified until rewind. ``candidates`` holds
        # every offset the reader may stand at; later data, ``tell`` and
        # relative seeks narrow it, and data must match at some candidate.
        self.candidates: list[int] = [0]
        self.modeled = True  # False after a direct buffer read in text mode
        self.marks: dict[str, int] = {}

    @property
    def position(self) -> int:
        return self.candidates[0]

    @position.setter
    def position(self, value: int) -> None:
        self.candidates = [value]

    @property
    def certain(self) -> bool:
        return len(self.candidates) == 1

    # Recording helpers

    def transition(self, event: str) -> None:
        before = self.health
        if (before, event) not in READ_HEALTH:
            self.violations.append(
                f"op ?: no read-health row for {before.value} + {event}"
            )
            return
        self.health = health_after(before, event)
        self.coverage.add(("health", f"{before.value}->{event}"))
        if self.health is not HEALTHY:
            self.eof = True

    # Data checks

    def accept_data(self, index: int, data: Any) -> None:
        if not self.modeled:
            return
        size = len(data)
        upper = self.upper
        ends = [
            start + size
            for start in self.candidates
            if start + size <= len(upper) and upper[start : start + size] == data
        ]
        if ends:
            self.candidates = ends
            return
        self.fail(
            index,
            f"data of length {size} matches no allowed offset in "
            f"{self.describe_position()} (allowed length {len(upper)})",
        )
        self.position = self.candidates[-1] + size

    def describe_position(self) -> str:
        if self.certain:
            return str(self.position)
        return f"[{self.candidates[0]}..{self.candidates[-1]}]"

    def widen(self, limit: int) -> None:
        """Let the position drift forward to at most ``limit``."""
        limit = min(limit, len(self.upper))
        if limit > self.candidates[-1]:
            self.candidates = list(range(self.candidates[0], limit + 1))

    def at_validated_eof(self) -> bool:
        return self.expect.clean and self.position == len(self.upper)

    def narrow_to_end(self) -> None:
        """An empty result that could have returned data narrows to the end.

        Of the offsets an uncertain position allows, only the end of a clean
        stream yields nothing; any other would have delivered data.
        """
        end = len(self.upper)
        if self.modeled and self.expect.clean and end in self.candidates:
            self.position = end

    def check_line(self, index: int, line: Any, limit: int) -> None:
        if not self.modeled or not line:
            return
        terminators = line_terminators(self.newline, self.text)
        body = line
        for terminator in terminators:
            if line.endswith(terminator):
                body = line[: -len(terminator)]
                break
        else:
            ends_data = self.position + len(line) >= len(self.upper)
            if (limit < 0 or len(line) < limit) and not (
                ends_data or not self.expect.clean
            ):
                self.fail(index, "unterminated line before end of data")
        for terminator in terminators:
            if terminator in body:
                self.fail(index, f"line contains an inner terminator {terminator!r}")
                break

    # Event handling

    def check_work(self, index: int, work: dict[str, int] | None) -> None:
        """Bounded work: no spinning on empty reads, no unrewound re-reads."""
        if work is None:
            return
        self.source_bytes += work["bytes"]
        self.source_seeks += work["seeks"]
        if work["empty_reads"] > 2 + work["seeks"]:
            self.fail(index, f"{work['empty_reads']} empty source reads in one call")
        if self.source_bytes > self.wire_size * (1 + self.source_seeks):
            self.fail(
                index,
                f"read {self.source_bytes} source bytes of {self.wire_size} "
                f"with {self.source_seeks} rewinds",
            )

    def observe(self, event) -> None:
        op = event.op
        name = op["op"]
        outcome = event.outcome
        index = event.index
        self.check_work(index, event.work)
        if name == "acquire":
            self.handle_acquire(index, op, outcome, event.second)
            return
        if name == "final":
            self.check_final(outcome.value)
            return
        if name == "timeout":
            self.fail(index, "scenario exceeded its hard timeout")
            return
        if name in ("fail_no_effect", "fail_consumed"):
            return
        if name in ("abort", "raise_exit"):
            self.handle_exit(event)
            return
        if name in ("close", "cleanup_close", "exit"):
            self.expect_ok(index, name, outcome)
            if self.lifecycle is OPEN:
                self.transition("close")
            self.lifecycle_event("close")
            return
        if self.lifecycle is U:
            self.handle_unopened_call(index, op, outcome)
            return
        if self.lifecycle is CLOSED:
            self.handle_closed_call(index, name, outcome)
            return
        if name == "open":
            self.handle_double_open(index, outcome)
            return
        if name in ("overlap", "close_during", "cancel"):
            self.handle_parked(event)
            return
        self.handle_call(index, op, outcome)

    def handle_exit(self, event) -> None:
        index = event.index
        second = event.second
        active = (
            event.op["op"] == "abort"
            and second is not None
            and event.note != "unparked"
        )
        if not active:
            # No call was active at exit (``raise_exit``, or an abort whose
            # call finished before parking): exit is an ordinary close, and
            # health and eof are retained. The finished call happened while
            # the handle was still open.
            if event.note == "unparked":
                self.handle_call(index, event.op["call"], second)
            if self.lifecycle is OPEN:
                self.transition("close")
            self.lifecycle_event("close")
            return
        self.lifecycle_event("context_exit_abort")
        self.transition("abort")
        if second.kind == "error" and ABORTED_MESSAGE in str(second.error):
            return
        # The call completed while exit settled it: an ordinary call outcome.
        if second.kind not in ("ok", "error", "stop"):
            self.fail(index, f"aborted call outcome {describe(second)}")

    def handle_parked(self, event) -> None:
        index, op = event.index, event.op
        name = op["op"]
        first, second = event.outcome, event.second
        if second is not None and second.kind == "skipped":
            # The call completed without reaching the gate: ordinary outcome.
            self.handle_call(index, op["call"], first)
            return
        if name == "overlap":
            self.lifecycle_event("overlapping_call")
            self.expect_concurrent(index, second)
            self.transition("overlap_rejected")
            self.handle_call(index, op["call"], first)
        elif name == "close_during":
            self.lifecycle_event("close_during_call")
            self.expect_concurrent(index, second)
            self.transition("overlap_rejected")
            self.handle_call(index, op["call"], first)
        else:
            if first.kind != "cancelled":
                # Cancellation lost the race with completion of the call.
                self.handle_call(index, op["call"], first)
                return
            if self.native or self.checkpoint:
                self.transition("cancel_no_effect")
            else:
                self.transition("cancel_uncertain")

    def handle_call(self, index: int, op: dict[str, Any], outcome) -> None:
        name = op["op"]
        self.lifecycle_event("call_starts")
        if name == "buffer_read":
            self.modeled = False
        if outcome.kind == "error":
            self.handle_error(index, op, outcome.error)
            return
        if outcome.kind == "stop":
            self.narrow_to_end()
            if self.modeled and not (
                self.at_validated_eof() and self.health is HEALTHY
            ):
                self.fail(index, "iteration stopped before validated EOF")
            return
        if outcome.kind != "ok":
            self.fail(index, f"unexpected outcome {describe(outcome)}")
            return
        value = outcome.value
        if name in ("tell", "tell_mark"):
            if name == "tell" and self.modeled:
                if value not in self.candidates:
                    self.fail(index, f"tell {value} outside {self.describe_position()}")
                self.position = value
            if name == "tell_mark":
                known = self.modeled and self.certain
                self.marks[op["label"]] = self.position if known else -1
            return
        if name in SEEK_OPS:
            self.handle_seek(index, op, value)
            return
        if name == "peek":
            if self.modeled and not any(
                self.upper[start : start + len(value)] == value
                for start in self.candidates
            ):
                self.fail(index, "peek is not a prefix of the unread data")
            return
        if name == "readlines":
            hint = op.get("hint", -1)
            if not value:
                self.narrow_to_end()
            if not value and self.modeled and not self.at_validated_eof():
                self.fail(index, "readlines returned [] before validated EOF")
            for line in value:
                self.check_line(index, line, -1)
                self.accept_data(index, line)
            if (hint is None or hint <= 0) and self.health is HEALTHY:
                self.require_eof(index, name)
            return
        if name in ("readline", "next"):
            limit = op.get("limit", -1)
            if limit is not None and limit >= 0 and len(value) > limit:
                self.fail(index, f"line longer than limit {limit}")
            if name == "next" and not value:
                self.fail(index, "iteration yielded an empty line")
            if not value and limit != 0:
                self.narrow_to_end()
            if (
                name == "readline"
                and limit != 0
                and not value
                and self.modeled
                and not self.at_validated_eof()
            ):
                self.fail(index, "readline returned empty before validated EOF")
            self.check_line(index, value, -1 if limit is None else limit)
            self.accept_data(index, value)
            return
        # read, read1, readinto, buffer_read
        size = op.get("n", -1)
        if size is not None and size >= 0 and len(value) > size:
            self.fail(index, f"{name} returned {len(value)} > {size}")
        before_health = self.health
        if size and not value:
            self.narrow_to_end()
        self.accept_data(index, value)
        if not self.modeled:
            return
        if size and not value and not self.at_validated_eof():
            self.fail(index, f"{name} returned empty before validated EOF")
        if (size is None or size < 0) and name == "read":
            if before_health is HEALTHY:
                self.require_eof(index, name)
            elif before_health is SALVAGE and self.position < self.lower:
                self.fail(
                    index,
                    f"read() drained salvage to {self.position}, "
                    f"short of the guaranteed {self.lower}",
                )

    def require_eof(self, index: int, name: str) -> None:
        if self.modeled and not self.at_validated_eof():
            self.fail(index, f"{name} ended at {self.position} without validated EOF")

    def handle_seek(self, index: int, op: dict[str, Any], value: Any) -> None:
        name = op["op"]
        if name == "seek0":
            if value != 0:
                self.fail(index, f"seek(0) returned {value}")
            self.transition("rewind_ok")
            self.position = 0
            self.modeled = True
            return
        if name == "seek_mark":
            # A text cookie seek is a rewind plus a forward replay.
            self.transition("rewind_ok")
            target = self.marks.get(op["label"], -1)
            if target < 0:
                self.modeled = False
                return
            self.position = target
            return
        if not self.modeled:
            return
        if name == "seek_abs":
            targets = [op["target"]] * len(self.candidates)
        elif name == "seek_rel":
            targets = [start + op["delta"] for start in self.candidates]
        else:
            targets = [max(0, start - op["back"]) for start in self.candidates]
        if any(
            t < start for t, start in zip(targets, self.candidates, strict=True)
        ) or (self.health is not HEALTHY):
            self.transition("rewind_ok")
        if self.expect.clean:
            allowed = {min(t, len(self.upper)) for t in targets}
        else:
            allowed = set(targets)
        if value not in allowed:
            self.fail(index, f"{name} returned {value}, allowed {sorted(allowed)[:4]}")
        if value > len(self.upper):
            self.fail(index, f"{name} moved past the allowed data to {value}")
        self.position = value

    def seek_target(self, op: dict[str, Any]) -> int | None:
        name = op["op"]
        if name == "seek0":
            return 0
        if name == "seek_abs":
            return op["target"]
        if name == "seek_rel":
            return self.position + op["delta"]
        if name == "seek_back":
            return max(0, self.position - op["back"])
        if name == "seek_mark":
            target = self.marks.get(op["label"], -1)
            return target if target >= 0 else None
        return None

    def handle_error(
        self, index: int, op: dict[str, Any], error: BaseException
    ) -> None:
        before = self.health
        message = str(error)
        refused = BROKEN_MESSAGE in message or NOT_SEEKABLE in message
        if op["op"] in SEEK_OPS and not refused:
            target = self.seek_target(op) if self.modeled else None
            # A text cookie seek always replays from a rewind.
            if (
                self.text
                or before is not HEALTHY
                or target is None
                or target < self.candidates[0]
            ):
                # The physical rewind succeeded; the forward replay failed
                # like any healthy read, somewhere before the target.
                self.transition("rewind_ok")
                self.position = 0
            self.classify_error(index, op, error)
            self.widen(len(self.upper) if target is None else target)
            return
        self.classify_error(index, op, error)
        if self.health is BROKEN and before is not BROKEN:
            self.widen(len(self.upper))

    def classify_error(
        self, index: int, op: dict[str, Any], error: BaseException
    ) -> None:
        name = op["op"]
        message = str(error)
        if type(error).__name__ == "ConcurrentOperationError":
            self.fail(index, f"{name} rejected as concurrent outside an overlap")
            return
        if INJECTED_NO_EFFECT in message or INJECTED_AT_END in message:
            self.transition(
                "no_effect_failure" if self.checkpoint else "uncertain_failure"
            )
            return
        if INJECTED_CONSUMED in message:
            self.transition("consumed_failure")
            return
        if NOT_SEEKABLE in message:
            if self.seekable:
                self.fail(index, f"{name} reported not seekable on a seekable source")
            self.transition("rewind_failed")
            return
        if BROKEN_MESSAGE in message:
            if self.health is HEALTHY:
                self.fail(index, f"{name} reported a broken stream while healthy")
                return
            if self.health is SALVAGE and self.modeled:
                self.check_salvage_refusal(index, op)
                if self.certain and self.position >= self.lower:
                    # Refused with the guaranteed salvage all served.
                    self.transition("salvage_exhausted")
            self.transition("terminal_refusal")
            return
        if isinstance(error, gzip.BadGzipFile) or (
            isinstance(error, EOFError) and self.expect.failure == "validation"
        ):
            if self.expect.failure != "validation":
                self.fail(
                    index, f"{name} raised a gzip error on a clean stream: {message}"
                )
            if self.health is HEALTHY:
                self.transition("validation_failure")
            return
        if LIMIT_MESSAGE in message:
            if self.expect.failure != "limit":
                self.fail(index, f"{name} hit the size limit unexpectedly: {message}")
            if self.health is HEALTHY:
                self.transition("limit_failure")
            return
        if isinstance(error, UnicodeDecodeError):
            # Valid by construction unless a direct buffer read split a
            # character, which ends text modeling.
            if self.modeled:
                self.fail(index, f"{name} raised UnicodeDecodeError on valid text")
            return
        if isinstance(error, (ValueError, OSError)) and name in SEEK_OPS:
            # Documented refusals such as seeking a text handle to an
            # unknown cookie leave the state unchanged.
            return
        self.fail(index, f"{name} raised unexpected {type(error).__name__}: {message}")

    def check_salvage_refusal(self, index: int, op: dict[str, Any]) -> None:
        """Salvage is served when retained data can satisfy the request.

        A refusal is wrong only if the guaranteed salvage (up to ``lower``)
        could have satisfied it: an unbounded read before ``lower``, a bounded
        read that fits, or a line whose terminator lies before ``lower``.
        """
        name = op["op"]
        guaranteed = self.upper[self.position : self.lower]
        if not guaranteed or not self.certain:
            return
        if name in ("read", "read1", "readinto", "peek", "buffer_read"):
            size = op.get("n", -1)
            if size is None or size < 0 or size <= len(guaranteed):
                self.fail(index, f"{name}({size}) refused with salvage remaining")
        elif name == "readlines":
            hint = op.get("hint", -1)
            # Unbounded readlines needs EOF, which salvage never provides.
            if hint is not None and hint > 0:
                lines = self.complete_lines(guaranteed)
                if sum(map(len, lines)) >= hint:
                    self.fail(
                        index, f"readlines({hint}) refused with salvage remaining"
                    )
        elif name in ("readline", "next"):
            limit = op.get("limit", -1) if name == "readline" else -1
            if limit is not None and 0 <= limit <= len(guaranteed):
                self.fail(index, f"{name}({limit}) refused with salvage remaining")
                return
            terminators = line_terminators(self.newline, self.text)
            if any(t in guaranteed for t in terminators):
                self.fail(index, f"{name} refused a complete salvaged line")

    def complete_lines(self, data: Any) -> list[Any]:
        terminators = line_terminators(self.newline, self.text)
        lines, start = [], 0
        for offset in range(len(data)):
            for terminator in terminators:
                if data.startswith(terminator, offset) and offset >= start:
                    end = offset + len(terminator)
                    lines.append(data[start:end])
                    start = end
                    break
        return lines


def wire_view(
    scenario: dict[str, Any], spliced: bytes, engine: str, **witness: Any
) -> dict[str, Any] | None:
    """A view no payload model describes, judged by the engine-matched wire
    oracle: a splice inside a member, or a replayed prefix.

    The view carries only its decoder input and the ``wire`` corruption kind:
    its expected bytes, guarantee and failure come from ``wire_reference``
    over that input. A decompression limit the oracle cannot order, or a
    view the model refuses, stays ineligible (fail closed).
    """
    corruption: dict[str, Any] = {"kind": "wire"}
    if scenario["corruption"]["kind"] == "limit":
        limit = scenario["corruption"]["limit"]
        module = engine_modules()[engine]
        reference = wire_reference(module, spliced)
        if reference["failure"] == "body invalid" and reference[
            "validated"
        ] <= limit < len(reference["output"]):
            # A batched inflate may raise before it emits the bytes that pass
            # the limit, so which failure comes first is not determined.
            return None
        corruption["limit"] = limit
    lossy = dict(scenario)
    lossy.update(
        wire=base64.b64encode(spliced).decode("ascii"),
        payloads=[],
        payload_size=0,
        member_offsets=None,
        member_spans=None,
        corruption=corruption,
        **witness,
    )
    try:
        Checker(lossy, engine)
    except (UnicodeDecodeError, ValueError, AssertionError):
        return None
    return lossy


class LossyChecker(Checker):
    """b1's reader over the input it actually saw after losing some (BC2).

    Built on the lossy scenario: the true wire with the lost range removed.
    Before the trigger b1 reads the true wire, so the model checks against
    the true scenario until the trigger event, then switches to the lossy
    one, keeping the position, health and marks it has accumulated (the lost
    range starts where the reader's source stood, so the data before the
    position is the same in both). At the trigger event an injected failure
    or a cancellation has no effect,
    because b1 retries. After the trigger, b1 returns to the true wire only at
    a successful model rewind whose event also completed a physical source
    seek to or before the lost range's start, when ``rebase`` is set (a
    seekable source). A rewind b1 answers without a source call (``seek0`` at
    decompressed position 0) keeps the lossy view, and so does a cancelled
    call. On a non-seekable custom source b1 replays its cache, which lacks
    the lost range, so it never returns. Every violation is recorded with its
    event index.

    H: b1 can lose input again after the trigger. A later uncertain or
    consumed failure, or an uncertain cancel, is b1's no-effect retry only
    with its own witness: the event's valid ``taken`` range, or (a cancelled
    read on a custom source without a checkpoint) an empty loss, as at the
    trigger. A native cancel, which the candidate settles without effect,
    is a loss when b1 took a nonempty range (L2). Without a witness the event
    gets the candidate's semantics and fails closed.
    Losses accumulate per physical-source epoch in true-wire coordinates,
    in order; the view is then the wire oracle over the true wire with every
    lost range of the epoch removed. A physical rewind over the epoch's
    first lost start restores the true view and ends the epoch; the next
    loss starts a new one. A later loss over a replayed prefix (G native) is
    not modeled.

    ``acquire`` names the BC3 clause that owns the acquisition event exactly
    (only "O1"); its contender outcome then takes b1's lifecycle transition
    (OPENING stays OPENING) instead of the candidate's error check, and the
    event index is recorded in ``normalized``.
    """

    NO_EFFECT = {
        "uncertain_failure": "no_effect_failure",
        "consumed_failure": "no_effect_failure",
        "cancel_uncertain": "cancel_no_effect",
    }

    def __init__(
        self,
        lossy: dict[str, Any],
        true: dict[str, Any],
        engine: str,
        trigger: int,
        rebase: bool,
        lost_start: int,
        acquire: str | None = None,
    ) -> None:
        super().__init__(lossy, engine)
        self.true = Checker(true, engine)
        self.true_scenario = true
        # The physical source still holds and delivers the lost range; only
        # the reader's view lacks it, so source work is bounded by the true
        # wire.
        self.wire_size = self.true.wire_size
        self.trigger = trigger
        self.rebase = rebase
        self.lost_start = lost_start
        if acquire not in (None, "O1"):
            raise ValueError(f"no lossy normalization for {acquire}")
        self.acquire = acquire
        self.engine = engine
        self.normalized: list[int] = []
        self.rebased_at: int | None = None
        self.rebases: list[int] = []
        # H: later losses as [event index, true-wire range or None (empty)].
        self.losses: list[list[Any]] = []
        self.index: int | None = None
        self.event: Any = None
        self.lossy = types.SimpleNamespace(**{n: getattr(self, n) for n in self.VIEW})
        self._use(self.true)
        self.lost = False  # whether the trigger has been reached
        self.state = "true"  # the view in force: "true" or "lossy"
        # The current epoch's lost true-wire ranges, or None over a replayed
        # prefix, and the offset a physical rewind must reach to end it.
        if "replayed_prefix" in lossy:
            self.deleted: list[list[int]] | None = None
        elif (
            "lossy_range" in lossy and lossy["lossy_range"][0] < lossy["lossy_range"][1]
        ):
            self.deleted = [list(lossy["lossy_range"])]
        else:
            self.deleted = []
        self.epoch_start = lost_start
        self._lost_index: int | None = None

    VIEW = ("expect", "upper", "lower")

    def _use(self, view: Any) -> None:
        for name in self.VIEW:
            setattr(self, name, getattr(view, name))

    @property
    def view(self) -> str:
        return self.state

    def expect_concurrent(self, index: int, outcome) -> None:
        if self.acquire == "O1" and index == -1:
            self.normalized.append(index)
            return
        super().expect_concurrent(index, outcome)

    def physical_rewind(self, event) -> bool:
        """Whether ``event`` completed a source seek back over the lost range.

        A cancelled call never counts, even if its native seek ran.
        """
        if event is None or event.outcome.kind == "cancelled":
            return False
        return any(target <= self.epoch_start for target in event.seeks or ())

    def observe(self, event) -> None:
        self.index = event.index
        self.event = event
        if not self.lost and event.index >= self.trigger:
            self._use(self.lossy)
            self.lost = True
            self.state = "lossy"
        super().observe(event)

    def later_loss(self, transition: str) -> tuple[bool, list[int] | None]:
        """Whether this event is a witnessed later loss, and its range
        (None for an empty loss at an unwitnessed source position)."""
        if (
            not self.lost
            or self.index is None
            or self.index <= self.trigger
            or self._lost_index == self.index
            or transition not in (*self.NO_EFFECT, "cancel_no_effect")
        ):
            return False, None
        source = self.true_scenario["source"]
        if transition == "cancel_no_effect" and source["kind"] != "native":
            # Only a native cancel loses input the candidate settles without
            # effect (L2); a checkpoint source restores it.
            return False, None
        taken = getattr(self.event, "taken", None)
        if taken is not None:
            if (
                isinstance(taken, list)
                and len(taken) == 2
                and all(type(x) is int for x in taken)
                and 0 <= taken[0] <= taken[1] <= self.wire_size
                # A cancel the model already settles without effect loses
                # input only when b1 took some (L2).
                and (transition != "cancel_no_effect" or taken[0] < taken[1])
            ):
                return True, list(taken)
            return False, None
        if transition == "cancel_no_effect":
            return False, None
        if (
            transition == "cancel_uncertain"
            and source["kind"] == "custom"
            and not source["checkpoint"]
        ):
            return True, None
        return False, None

    def lose(self, taken: list[int] | None) -> None:
        """Apply a later loss: extend the epoch, or start a new one."""
        index = self.index
        assert index is not None
        self._lost_index = index
        self.losses.append([index, taken])
        if taken is None or taken[0] == taken[1]:
            return  # nothing lost: the view in force stands
        if self.state == "true":
            self.state = "lossy"
            self.deleted = [taken]
            self.epoch_start = taken[0]
            self._view()
            return
        if self.deleted is None:
            self.fail(index, "a later loss over a replayed prefix is not modeled")
            return
        if self.deleted and taken[0] < self.deleted[-1][1]:
            self.fail(
                index, f"loss {taken} precedes the epoch's loss {self.deleted[-1]}"
            )
            return
        self.deleted.append(taken)
        self._view()

    def _view(self) -> None:
        """Use the oracle view of the true wire without the epoch's losses."""
        if not self.deleted:
            self._use(self.true)
            return
        wire = base64.b64decode(self.true_scenario["wire"])
        spliced, at = b"", 0
        for a, b in self.deleted:
            spliced += wire[at:a]
            at = b
        spliced += wire[at:]
        scenario = wire_view(
            self.true_scenario,
            spliced,
            self.engine,
            lossy_ranges=[list(r) for r in self.deleted],
        )
        if scenario is None:
            assert self.index is not None
            self.fail(self.index, f"no model for the losses {self.deleted}")
            return
        self._use(Checker(scenario, self.engine))

    def transition(self, event: str) -> None:
        if self.index == self.trigger:
            event = self.NO_EFFECT.get(event, event)
        else:
            witnessed, taken = self.later_loss(event)
            if witnessed:
                self.lose(taken)
                event = self.NO_EFFECT.get(event, event)
        super().transition(event)
        if (
            event == "rewind_ok"
            and self.rebase
            and self.state == "lossy"
            and self.index is not None
            and self.index > self.trigger
            and self.physical_rewind(self.event)
        ):
            # The position is then set in the shared decompressed
            # coordinates, which the rewind makes valid on the true wire.
            if self.rebased_at is None:
                self.rebased_at = self.index
            self.rebases.append(self.index)
            self.state = "true"
            self.deleted = []
            self._use(self.true)


class WriteChecker(_HandleChecker):
    """Check one write scenario: writer health, lifecycle and decoded output.

    The writer is checked by decompression. A clean close must produce one
    complete member holding exactly the accepted payloads. After any failure
    (sink error, cancellation, abort) the writer is broken: later writes and
    flushes are refused, close writes no trailer, and the output is an
    incomplete member whose payload is a prefix of everything attempted.
    """

    def __init__(self, scenario: dict[str, Any]) -> None:
        super().__init__(scenario)
        self.text = scenario["text"]
        self.accepted: list[Any] = []
        self.attempted: list[Any] = []
        self.broken = False
        self.armed = False
        self.completed = False

    def payload(self, op: dict[str, Any]) -> list[Any]:
        from generator import write_payload

        name = op["op"]
        if name in ("write", "write_flush"):
            return [write_payload(op, self.text)]
        if name == "writelines":
            return [write_payload(part, self.text) for part in op["parts"]]
        return []

    def encode(self, pieces: list[Any]) -> bytes:
        if self.text is None:
            return b"".join(pieces)
        newline = self.text["newline"]
        encoder = codecs.getincrementalencoder(self.text["encoding"])()
        out = []
        for piece in pieces:
            if newline is None:
                piece = piece.replace("\n", os.linesep)
            elif newline in ("\r", "\r\n"):
                piece = piece.replace("\n", newline)
            out.append(encoder.encode(piece))
        if pieces:
            out.append(encoder.encode("", final=True))
        return b"".join(out)

    def observe(self, event) -> None:
        op = event.op
        name = op["op"]
        outcome = event.outcome
        index = event.index
        if name == "acquire":
            self.handle_acquire(index, op, outcome, event.second)
            if self.fault == "init_fail" and op.get("fault") == "init_fail":
                self.armed = False  # the injected failure was spent on the header
            return
        if name == "final":
            self.check_final(outcome.value)
            self.check_output(outcome.value.get("output"))
            return
        if name == "timeout":
            self.fail(index, "scenario exceeded its hard timeout")
            return
        if name in ("fail_sink_no_effect", "fail_sink_partial"):
            self.armed = True
            return
        if name == "abort" and event.note == "unparked":
            # The call finished first; the exit had no active call.
            self.handle_call(index, op["call"], event.second)
            self.handle_close(index, "raise_exit", outcome)
            return
        if name == "abort":
            self.lifecycle_event("context_exit_abort")
            second = event.second
            if second is not None:
                # The aborted call's own outcome happened before the abort
                # latched the writer broken.
                call = op["call"]
                if second.kind == "cancelled" or (
                    second.kind == "error" and WRITE_ABORTED in str(second.error)
                ):
                    self.attempted += self.payload(call)
                else:
                    self.handle_call(index, call, second, lifecycle=False)
            self.break_writer()
            return
        if name in ("raise_exit", "close", "cleanup_close", "exit"):
            self.handle_close(index, name, outcome)
            return
        if self.lifecycle is U:
            self.handle_unopened_call(index, op, outcome)
            return
        if self.lifecycle is CLOSED:
            self.handle_closed_call(index, name, outcome)
            return
        if name == "open":
            self.handle_double_open(index, outcome)
            return
        if name in ("overlap", "close_during", "cancel"):
            self.handle_parked(event)
            return
        self.handle_call(index, op, outcome)

    def break_writer(self) -> None:
        self.broken = True

    def handle_close(self, index: int, name: str, outcome) -> None:
        was_open = self.lifecycle is OPEN
        error = outcome.error if outcome.kind == "error" else None
        if (
            name in ("raise_exit", "abort")
            and isinstance(error, Exception)
            and (type(error).__name__ == "InjectedAbort")
        ):
            error = None  # the body's own exception; the close succeeded
        elif outcome.kind not in ("ok", "error"):
            self.fail(index, f"{name} outcome {describe(outcome)}")
        self.lifecycle_event("close")
        if not was_open:
            if error is not None:
                self.fail(index, f"{name} raised {type(error).__name__}: {error}")
            return
        if error is None:
            if not self.broken:
                if self.armed:
                    self.fail(
                        index, f"{name} wrote a trailer past an armed sink failure"
                    )
                self.completed = True
            return
        if INJECTED_SINK in str(error) and self.armed and not self.broken:
            self.armed = False
            self.break_writer()
            return
        self.fail(index, f"{name} raised {type(error).__name__}: {error}")

    def handle_parked(self, event) -> None:
        index, op = event.index, event.op
        name = op["op"]
        first, second = event.outcome, event.second
        if second is not None and second.kind == "skipped":
            self.handle_call(index, op["call"], first)
            return
        if name == "overlap":
            self.lifecycle_event("overlapping_call")
            self.expect_concurrent(index, second)
        elif name == "close_during":
            self.lifecycle_event("close_during_call")
            self.expect_concurrent(index, second)
        self.handle_call(index, op["call"], first)

    def handle_call(
        self, index: int, op: dict[str, Any], outcome, lifecycle=True
    ) -> None:
        if lifecycle:
            self.lifecycle_event("call_starts")
        pieces = self.payload(op)
        if outcome.kind == "ok":
            if self.broken:
                self.fail(index, f"{op['op']} succeeded on a broken writer")
            self.accepted += pieces
            return
        if outcome.kind == "cancelled":
            self.attempted += pieces
            self.break_writer()
            return
        if outcome.kind != "error":
            self.fail(index, f"{op['op']} outcome {describe(outcome)}")
            return
        message = str(outcome.error)
        if INJECTED_SINK in message:
            if not self.armed or self.broken:
                self.fail(index, f"{op['op']} hit a sink failure that was not armed")
            self.armed = False
            self.attempted += pieces
            self.break_writer()
            return
        if WRITE_BROKEN_MESSAGE in message:
            if not self.broken:
                self.fail(index, f"{op['op']} refused a healthy writer: {message}")
            return
        self.fail(index, f"{op['op']} raised {type(outcome.error).__name__}: {message}")

    def check_output(self, output: dict[str, Any] | None) -> None:
        if output is None:
            return
        if output["error"] is not None:
            self.fail(-1, f"writer output is not a gzip prefix: {output['error']}")
            return
        decoded = output["decoded"]
        if self.completed:
            if not output["complete"]:
                self.fail(-1, "a cleanly closed writer left an incomplete member")
            expected = self.encode(self.accepted)
            if decoded != expected:
                self.fail(
                    -1,
                    f"writer output of {len(decoded)} bytes differs from the "
                    f"{len(expected)} accepted",
                )
            return
        if output["complete"]:
            self.fail(-1, "a broken or unclosed writer produced a complete member")
        allowed = self.encode(self.accepted + self.attempted)
        if not allowed.startswith(decoded):
            self.fail(-1, "broken writer output is not a prefix of the attempted data")


def make_checker(scenario: dict[str, Any], engine: str) -> _HandleChecker:
    if scenario["mode"] in ("wb", "wt"):
        return WriteChecker(scenario)
    return Checker(scenario, engine)


def describe(outcome) -> str:
    if outcome is None:
        return "nothing"
    if outcome.kind == "error":
        return f"{type(outcome.error).__name__}: {outcome.error}"
    return f"{outcome.kind} {outcome.value!r}"[:200]
