"""The WP10 PR seed set: generated public-API sequences against the model.

Each seed generates one scenario, replays it through the public interpreter
on the candidate, and checks every event against the model (public replay)
and the candidate's private state against the model's tables (observer).
The C0 and b1 differentials run locally and in the release run, not here;
see "Seeds, minimization and CI" in plans/design/v2.0.0b2-wp10-qualification.md.
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path

import interpreter
import pytest
from generator import SEEK_END_BASE, generate
from interpreter import Outcome, replay
from model import (
    BROKEN_MESSAGE,
    LIFECYCLE,
    READ_HEALTH,
    Health,
    Lifecycle,
    make_checker,
)
from observer import Observer

import aiogzip

# Seeds outside the base range that once exposed a defect or a model gap,
# plus 5767, the only seed below 6000 that aborts a BROKEN reader (943, also
# such a seed, is inside the base range), and 1671 and 2344, the first seeds
# whose failed text seek moves the cursor of a BROKEN and a HEALTHY reader
# (BC11).
REGRESSION_SEEDS = (
    1062, 1071, 1149, 1494, 1506, 1530, 1671, 1726,
    1737, 1754, 1787, 1818, 2105, 2254, 2344, 5767,
)  # fmt: skip
assert not set(REGRESSION_SEEDS) & set(range(1000))
# End-relative seeks (BC12) live in their own block so lower seeds keep
# their operations.
SEEK_END_SEEDS = tuple(range(SEEK_END_BASE, SEEK_END_BASE + 200))
PR_SEEDS = tuple(range(1000)) + REGRESSION_SEEDS + SEEK_END_SEEDS

# Table rows the generator cannot reach, each with the focused test that
# covers it instead (path, test function).
TESTS = Path(__file__).resolve().parent.parent
COVERED_ELSEWHERE = {
    ("lifecycle", "OPENING->cleanup_raises_exception"): (
        "test_open_settlement.py",
        "test_failed_header_preserves_primary_error_when_cleanup_fails",
    ),
    ("lifecycle", "OPENING->cleanup_raises_base_exception"): (
        "test_open_qualification.py",
        "test_native_cleanup_stays_reserved_through_repeated_cancel",
    ),
    ("lifecycle", "OPENING->exceptional_context_exit"): (
        "test_open_qualification.py",
        "test_context_exit_during_open_does_not_abandon_opener",
    ),
    ("lifecycle", "OPEN->context_exit_abort_cleanup_fails"): (
        "test_file_lifecycle.py",
        "test_failed_abort_close_preserves_body_error_and_open_state",
    ),
}


@cache
def _run(seed: int) -> tuple[list[str], frozenset[tuple[str, str]]]:
    scenario = generate(seed)
    checker = make_checker(scenario, aiogzip.engine_info().decompression)
    observer = Observer(checker)

    def hook(handle, event, context):
        checker.observe(event)
        observer(handle, event, context)

    replay(aiogzip, scenario, (hook,))
    return checker.violations + observer.violations, frozenset(checker.coverage)


@pytest.mark.parametrize("seed", PR_SEEDS)
def test_seed_matches_the_model(seed):
    violations, _coverage = _run(seed)
    assert not violations, f"seed {seed}:\n" + "\n".join(violations)


def test_seed_set_covers_every_table_row():
    covered = frozenset().union(*(_run(seed)[1] for seed in PR_SEEDS))
    rows = {("lifecycle", f"{row.source.value}->{row.event}") for row in LIFECYCLE}
    rows |= {("health", f"{health.value}->{event}") for health, event in READ_HEALTH}
    assert covered <= rows, sorted(covered - rows)
    assert rows - covered == set(COVERED_ELSEWHERE)
    for (_table, row), (path, name) in COVERED_ELSEWHERE.items():
        source = (TESTS / path).read_text(encoding="utf-8")
        start = re.search(rf"^\s*(async )?def {name}\(", source, re.M)
        assert start, (path, name)
        end = re.compile(r"^\s*(async )?def test|^class ", re.M).search(
            source, start.end()
        )
        body = source[start.end() : end.start() if end else None]
        # The focused test asserts that row through the shared table.
        source_state, event = row.split("->")
        assert re.search(
            rf"assert_lifecycle\(\s*\w+(\.\w+)*,\s*{source_state},\s*\"{event}\"",
            body,
        ), (path, name, row)


def test_timed_out_scenario_closes_its_handle(monkeypatch):
    # A run that hits the hard timeout must still close its handle, or
    # Windows cannot remove the scenario's file and the timeout surfaces as
    # an unrelated cleanup error. Seed 734 reads a native file by path.
    monkeypatch.setattr(interpreter, "SCENARIO_TIMEOUT", 0.05)
    events, _trace = replay(aiogzip, generate(734))
    (timeout,) = [event for event in events if event.op["op"] == "timeout"]
    # The cleanup outcome is recorded beside the timeout, which still fails.
    assert timeout.second == interpreter.Outcome("ok", "closed")
    final = events[-1]
    assert final.op["op"] == "final"
    assert final.outcome.value["closed"] is True
    if "fd_delta" in final.outcome.value:
        assert final.outcome.value["fd_delta"] == 0


def test_timeout_with_a_parked_native_call_opens_the_gate(monkeypatch):
    # Seed 36's overlap (op 2) parks a native read in a background task.
    # Holding that read until the deadline makes the timeout land while it is
    # parked and unprevented: the context exit then waits for the read to run
    # and settle (BC1), so the deadline itself must open the gate. Before,
    # the gate opened only after the exit, so the run deadlocked until the
    # parked worker gave up without running the call, which no exit or close
    # could then settle.
    settle = interpreter.settle_then_release
    calls = 0

    async def hold_overlap_until_deadline(gate, task):
        nonlocal calls
        calls += 1
        if calls == 2:  # the overlap's releaser; the cancel (op 1) settles
            await gate.release_async.wait()
        await settle(gate, task)

    monkeypatch.setattr(interpreter, "SCENARIO_TIMEOUT", 0.5)
    monkeypatch.setattr(interpreter, "settle_then_release", hold_overlap_until_deadline)
    events, _trace = replay(aiogzip, generate(36))
    assert calls >= 2
    (timeout,) = [event for event in events if event.op["op"] == "timeout"]
    assert timeout.second == interpreter.Outcome("ok", "closed")
    final = events[-1].outcome.value
    assert final["closed"] is True
    if "fd_delta" in final:
        assert final["fd_delta"] == 0


def test_expired_gate_releases_every_later_arming():
    # Past the deadline an op may still park a call (a body op that records
    # the timeout's cancellation as its outcome, say); the release it would
    # wait for has already been spent, so the arming itself must release.
    gate = interpreter.Gate()
    gate.arm()
    assert not gate.release_thread.is_set()
    gate.expire()
    assert gate.release_thread.is_set() and gate.release_async.is_set()
    gate.arm()
    assert gate.release_thread.is_set() and gate.release_async.is_set()


def test_deadline_landing_on_a_parked_call_await_is_recorded(monkeypatch):
    # Seed 36 parks a native read1 (op 1). With the partner's cancel and the
    # release both withheld, the scenario waits at _parked()'s final await
    # until the deadline, whose cancellation lands there. It must surface as
    # the scenario's timeout, never as the parked call's "cancelled" outcome.
    settle = interpreter.settle_then_release
    calls = 0

    async def withhold_first_release(gate, task):
        nonlocal calls
        calls += 1
        if calls > 1:
            await settle(gate, task)

    async def no_cancel(task):
        return interpreter.Outcome("ok", "cancel withheld")

    monkeypatch.setattr(interpreter, "SCENARIO_TIMEOUT", 0.3)
    monkeypatch.setattr(interpreter, "settle_then_release", withhold_first_release)
    monkeypatch.setattr(interpreter, "_cancel_partner", no_cancel)
    events, _trace = replay(aiogzip, generate(36))
    assert calls >= 1
    (timeout,) = [event for event in events if event.op["op"] == "timeout"]
    assert timeout.second == interpreter.Outcome("ok", "closed")
    assert events[-1].outcome.value["closed"] is True
    # The parked call (op 1) never lands with the deadline as its outcome.
    assert not [event for event in events if event.index == 1]


def _seek_end_ops(scenario):
    ops = scenario.get("ops", [])
    return [op.get("call", op) for op in ops if op.get("call", op)["op"] == "seek_end"]


def test_only_the_seek_end_block_issues_end_relative_seeks():
    assert not any(_seek_end_ops(generate(seed)) for seed in range(1000))
    block = [generate(seed) for seed in SEEK_END_SEEDS]
    binary = [s for s in block if s["mode"] == "rb"]
    text = [s for s in block if s["mode"] == "rt"]
    assert any(op["offset"] < 0 for s in binary for op in _seek_end_ops(s))
    assert all(op["offset"] == 0 for s in text for op in _seek_end_ops(s))
    # The R04 shape: a peek() that reaches EOF directly before the seek.
    assert any(
        first == {"op": "peek", "n": s["payload_size"] + 1}
        and second["op"] == "seek_end"
        for s in binary
        for first, second in zip(s["ops"], s["ops"][1:], strict=False)
    )
    parked = {"cancel", "overlap", "close_during", "abort"}
    assert any(
        op["op"] in parked and op["call"]["op"] == "seek_end"
        for s in block
        for op in s.get("ops", [])
    )


def _text_checker_at(health):
    # Seed 39: text with a CRC failure, so salvage is reachable.
    scenario = generate(39)
    assert scenario["mode"] == "rt"
    assert scenario["corruption"]["kind"] == "crc"
    checker = make_checker(scenario, aiogzip.engine_info().decompression)
    checker.lifecycle = Lifecycle.OPEN
    checker.health = health
    return checker


def test_text_seek_end_from_broken_is_a_violation():
    checker = _text_checker_at(Health.BROKEN)
    checker.handle_call(0, {"op": "seek_end", "offset": 0}, Outcome("ok", 7))
    assert any("BROKEN" in v for v in checker.violations), checker.violations


def test_text_seek_end_from_salvage_keeps_checking_content():
    checker = _text_checker_at(Health.VALIDATION_SALVAGE)
    checker.lower = 10  # guaranteed salvage short of the end
    checker.handle_call(0, {"op": "seek_end", "offset": 0}, Outcome("ok", 7))
    assert not checker.violations, checker.violations
    assert checker.modeled
    end = len(checker.upper)
    assert checker.candidates == list(range(10, end + 1))
    # Data that matches no allowed offset is still caught.
    checker.accept_data(1, "\0" * 3)
    assert checker.violations


def _drained_salvage_checker():
    checker = _text_checker_at(Health.VALIDATION_SALVAGE)
    checker.lower = 10
    checker.handle_call(0, {"op": "seek_end", "offset": 0}, Outcome("ok", 7))
    assert not checker.violations, checker.violations
    return checker


def test_read_after_a_salvage_draining_seek_end_must_refuse():
    checker = _drained_salvage_checker()
    # A matching suffix is still wrong: the seek drained all salvage.
    suffix = checker.upper[-3:]
    checker.handle_call(1, {"op": "read", "n": 3}, Outcome("ok", suffix))
    assert any("drained the salvage" in v for v in checker.violations)


def test_refusal_after_a_salvage_draining_seek_end_is_accepted():
    checker = _drained_salvage_checker()
    refusal = OSError(f"{BROKEN_MESSAGE} after failed or cancelled decompression")
    checker.handle_call(1, {"op": "read", "n": 3}, Outcome("error", error=refusal))
    assert not checker.violations, checker.violations


def test_rewind_after_a_salvage_draining_seek_end_restores_reads():
    checker = _drained_salvage_checker()
    checker.handle_call(1, {"op": "seek0"}, Outcome("ok", 0))
    checker.handle_call(2, {"op": "read", "n": 3}, Outcome("ok", checker.upper[:3]))
    assert not checker.violations, checker.violations
