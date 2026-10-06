"""Candidate-only observation for the WP10 stateful harness.

Runs in-process against the candidate, after the model has consumed each
replayed event, and compares private state with the model's expectation. It
never feeds back into the public trace, and it is never run against C0 or b1,
whose private state differs by design. See "Public replay and candidate-only
observation" in plans/design/v2.0.0b2-wp10-qualification.md.

Checked after every event:

- Lifecycle against ``_is_closed`` and ``_file``: UNOPENED has nothing
  published, OPEN has a published resource, CLOSED is latched.
- Reservations idle: ``_opening``, ``_read_call_active`` and
  ``_write_call_active`` on the binary file and, for text, on the wrapper.
  Every event lands only after its calls settle.
- Readers: ``_read_health`` equals the model's health, and an unhealthy
  reader has ``eof`` set. The decoder is live exactly while the reader is
  OPEN and HEALTHY, so a poisoned or closed reader holds no inflate state.
- Writers: ``_write_broken`` equals the model's broken latch.
- Text: binary observers are attached while OPEN and detached once CLOSED,
  and the wrapper's poison hint is set whenever the binary reader is
  unhealthy (the hint is one-way; only a text rewind clears it).
"""

from __future__ import annotations

from typing import Any

from model import (
    CLOSED,
    OPEN,
    OPENING,
    Checker,
    Health,
    Lifecycle,
    LifecycleRow,
    U,
    WriteChecker,
    lifecycle_after,
)


def observed_lifecycle(handle: Any) -> Lifecycle:
    """The lifecycle a binary or text handle's private state shows."""
    if handle._is_closed:
        return CLOSED
    if handle._opening:
        return OPENING
    binary = handle._binary_file if hasattr(handle, "_binary_file") else handle
    if binary is not None and binary._file is not None:
        return OPEN
    return U


def assert_lifecycle(handle: Any, source: Lifecycle, event: str) -> LifecycleRow:
    """Assert ``handle`` is where the lifecycle table sends ``source`` on ``event``.

    Focused tests use this for every end state they check, so the table and
    those tests cannot drift apart. Returns the row for further assertions.
    """
    row = lifecycle_after(source, event)
    actual = observed_lifecycle(handle)
    assert actual is row.target, (
        f"{source.value} --{event}--> {actual.value}, table says {row.target.value}"
    )
    return row


class Observer:
    """A replay hook; call it after the model checker for the same event."""

    def __init__(self, checker: Checker | WriteChecker) -> None:
        self.checker = checker
        self.violations: list[str] = []
        self.coverage: set[str] = set()

    def fail(self, index: int, message: str) -> None:
        self.violations.append(f"op {index} (observer): {message}")

    def __call__(self, handle: Any, event: Any, context: Any) -> None:
        if handle is None or event.op["op"] in ("timeout",):
            return
        index = event.index
        text = hasattr(handle, "_binary_file")
        binary = handle._binary_file if text else handle
        lifecycle = self.checker.lifecycle
        self.check_lifecycle(index, handle, binary, lifecycle)
        self.check_idle(index, handle, binary, text)
        if binary is None or lifecycle is U:
            return
        if isinstance(self.checker, Checker):
            self.check_reader(index, binary, lifecycle)
            if text:
                self.check_text_reader(index, handle, binary)
        else:
            self.check_writer(index, binary)
        if text:
            self.check_text_binding(index, binary, lifecycle)

    def check_lifecycle(self, index, handle, binary, lifecycle) -> None:
        closed = handle._is_closed
        published = binary is not None and binary._file is not None
        if lifecycle is CLOSED:
            ok = closed
        elif lifecycle is OPEN:
            ok = not closed and published
        else:
            ok = not closed and not published
        self.coverage.add(f"lifecycle {lifecycle.value}")
        if not ok:
            self.fail(
                index,
                f"model {lifecycle.value} but _is_closed={closed}, published={published}",
            )

    def check_idle(self, index, handle, binary, text) -> None:
        layers = [("binary", binary)] + ([("text", handle)] if text else [])
        for layer, obj in layers:
            if obj is None:
                continue
            for flag in ("_opening", "_read_call_active", "_write_call_active"):
                if getattr(obj, flag, False):
                    self.fail(
                        index, f"{layer} {flag} still set after the event settled"
                    )
        self.coverage.add("reservations idle")

    def check_reader(self, index, binary, lifecycle) -> None:
        expected = self.checker.health
        actual = binary._read_health
        if actual.name != expected.name:
            self.fail(index, f"read health {actual.name}, model {expected.name}")
        if actual.name != Health.HEALTHY.name and not binary._eof:
            self.fail(index, f"{actual.name} reader without eof")
        decoder = binary._decoder
        live = decoder is not None and not decoder._discarded
        should_live = lifecycle is OPEN and actual.name == Health.HEALTHY.name
        if live is not should_live:
            self.fail(
                index,
                f"decoder live={live} for a {lifecycle.value} {actual.name} reader",
            )
        self.coverage.add(f"read health {actual.name} ({lifecycle.value})")

    def check_text_reader(self, index, handle, binary) -> None:
        if (
            binary._read_health.name != Health.HEALTHY.name
            and not handle._read_poison_seen
        ):
            self.fail(index, "text missed a poison notification")
        self.coverage.add("text poison hint")

    def check_writer(self, index, binary) -> None:
        if binary._write_broken is not self.checker.broken:
            self.fail(
                index,
                f"_write_broken={binary._write_broken}, model broken={self.checker.broken}",
            )
        self.coverage.add(f"writer broken={self.checker.broken}")

    def check_text_binding(self, index, binary, lifecycle) -> None:
        attached = (
            binary._closed_observer is not None,
            binary._read_poison_observer is not None,
        )
        if lifecycle is OPEN and attached != (True, True):
            self.fail(index, f"text observers attached={attached} while OPEN")
        if lifecycle is CLOSED and attached != (False, False):
            self.fail(index, f"text observers attached={attached} after close")
        self.coverage.add(f"text observers ({lifecycle.value})")
