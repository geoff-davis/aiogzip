"""The WP10 PR seed set: generated public-API sequences against the model.

Each seed generates one scenario, replays it through the public interpreter
on the candidate, and checks every event against the model (public replay)
and the candidate's private state against the model's tables (observer).
The C0 and b1 differentials run locally and in the release run, not here;
see "Seeds, minimization and CI" in plans/design/v2.0.0b2-wp10-qualification.md.
"""

from __future__ import annotations

import asyncio
import gc
import os
import re
from functools import cache
from pathlib import Path

import interpreter
import pytest
from generator import CHUNK_SIZES, SEEK_CANCEL_BASE, SEEK_END_BASE, generate
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
# (BC11), and 2000322 and 2001408, whose cookie taken on a reader a cancelled
# cookie seek left BROKEN named a position the model had kept as certain.
REGRESSION_SEEDS = (
    1062, 1071, 1149, 1494, 1506, 1530, 1671, 1726,
    1737, 1754, 1787, 1818, 2105, 2254, 2344, 5767,
    2000322, 2001408,
)  # fmt: skip
assert not set(REGRESSION_SEEDS) & set(range(1000))
# End-relative seeks (BC12) live in their own block so lower seeds keep
# their operations.
SEEK_END_SEEDS = tuple(range(SEEK_END_BASE, SEEK_END_BASE + 200))
# Cancellations partway through a text cookie seek's replay (R02).
SEEK_CANCEL_SEEDS = tuple(range(SEEK_CANCEL_BASE, SEEK_CANCEL_BASE + 200))
PR_SEEDS = tuple(range(1000)) + REGRESSION_SEEDS + SEEK_END_SEEDS + SEEK_CANCEL_SEEDS

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


# fd_delta counts every descriptor in the process. An automatic collection
# mid-scenario once closed a file an earlier test left in unreachable
# garbage, and the run reported "-1 file descriptors leaked" (CI flake F-A).

needs_fd_counts = pytest.mark.skipif(
    interpreter._open_fds() is None, reason="platform does not expose open fds"
)


def test_no_automatic_collection_runs_during_a_scenario():
    collections = []
    allocations = []
    enabled = []

    def record(phase, info):
        # Count from the first event on: before replay() pauses collection,
        # the caller (or coverage's tracer) can still trigger one.
        if phase == "start" and allocations:
            collections.append(info["generation"])

    def allocate(handle, event, context):
        enabled.append(gc.isenabled())
        # Far past any threshold below: automatic collection would run here.
        allocations.append([[] for _ in range(1000)])
        if event.op["op"] == "final":  # after the last count
            allocations.append(list(collections))

    scenario, hooks = generate(0), (allocate,)
    thresholds = gc.get_threshold()
    gc.callbacks.append(record)
    gc.set_threshold(1, 1, 1)
    try:
        replay(aiogzip, scenario, hooks)
    finally:
        gc.set_threshold(*thresholds)
        gc.callbacks.remove(record)
    assert len(allocations) > 3
    assert allocations[-1] == []
    assert not any(enabled)
    assert gc.isenabled()


def test_collection_is_restored_when_a_scenario_raises():
    def explode(handle, event, context):
        raise RuntimeError("hook failed")

    with pytest.raises(RuntimeError, match="hook failed"):
        replay(aiogzip, generate(0), (explode,))
    assert gc.isenabled()


@needs_fd_counts
def test_a_file_the_scenario_leaves_open_still_counts():
    # Positive control: with collection paused, a descriptor opened during
    # the scenario and still open at the final count is reported.
    kept = []

    def leak(handle, event, context):
        if not kept:
            kept.append(open(os.devnull, "rb"))  # noqa: SIM115

    try:
        events, _trace = replay(aiogzip, generate(0), (leak,))
    finally:
        for file in kept:
            file.close()
    assert events[-1].outcome.value["fd_delta"] == 1


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


def test_only_the_seek_cancel_block_cancels_a_cookie_seek():
    def cancelled_cookie_seeks(scenario):
        return [
            op
            for op in scenario.get("ops", [])
            if op["op"] == "cancel" and op["call"]["op"] == "seek_mark"
        ]

    lower = range(0, SEEK_END_BASE + 200, 997)
    assert not any(cancelled_cookie_seeks(generate(seed)) for seed in lower)
    block = [generate(seed) for seed in SEEK_CANCEL_SEEDS]
    assert all(s["mode"] == "rt" for s in block)
    # Payloads span many source chunks, and some cancels land after the
    # gate has let source accesses through, partway into the replay.
    assert max(s["payload_size"] for s in block) > 2 * max(CHUNK_SIZES)
    ops = [op for s in block for op in cancelled_cookie_seeks(s)]
    assert any(op["after"] > 0 for op in ops)


async def test_armed_gate_lets_its_skip_count_through_first():
    gate = interpreter.Gate()
    config = {"seekable": True, "checkpoint": False, "frames": []}
    source = interpreter.Source(bytes(range(20)), config, gate)
    gate.arm(2)
    # Bounded: a gate that parked these would otherwise hang the test.
    assert await asyncio.wait_for(source.read(3), 5) == bytes(range(3))
    assert await asyncio.wait_for(source.seek(1), 5) == 1  # an access too
    task = asyncio.create_task(source.read(2))
    await asyncio.wait_for(gate.entered.wait(), 5)
    assert not task.done()
    gate.release()
    assert await task == bytes([1, 2])
    assert not gate.armed and gate.skip == 0


async def test_gated_executor_lets_its_skip_count_through_first():
    loop = asyncio.get_running_loop()
    gate = interpreter.Gate()
    executor = interpreter.GatedExecutor(gate, loop)
    try:
        gate.arm(1)
        passed = loop.run_in_executor(executor, int, "7")
        assert await asyncio.wait_for(passed, 5) == 7
        parked = loop.run_in_executor(executor, int, "8")
        await asyncio.wait_for(gate.entered.wait(), 5)
        assert not parked.done()
        gate.release()
        assert await parked == 8
    finally:
        executor.shutdown()


@pytest.mark.parametrize("seed", [2000137, 2000160])
def test_cancel_partway_through_a_cookie_seek_replay_refuses_reads(seed):
    # R02: the cancel lets source accesses through (a custom source for
    # 2000137, a native file for 2000160), so it lands after the replay
    # has moved the cursor. The next read must refuse, never return the
    # old text over the moved position (R01, BC11).
    events, _trace = replay(aiogzip, generate(seed))
    index = next(
        i
        for i, event in enumerate(events)
        if event.op["op"] == "cancel" and event.op["call"]["op"] == "seek_mark"
    )
    cancel = events[index]
    assert cancel.op["after"] > 0
    assert cancel.outcome.kind == "cancelled"
    assert cancel.cursor_moved is True
    following = events[index + 1]
    assert following.outcome.kind == "error"
    assert BROKEN_MESSAGE in str(following.outcome.error)


def _text_checker_at(health):
    # Seed 39: text with a CRC failure, so salvage is reachable.
    scenario = generate(39)
    assert scenario["mode"] == "rt"
    assert scenario["corruption"]["kind"] == "crc"
    checker = make_checker(scenario, aiogzip.engine_info().decompression)
    checker.lifecycle = Lifecycle.OPEN
    checker.health = health
    return checker


def _recovered_by_an_uncertain_cookie():
    # A cancelled cookie seek moves the cursor (BC11); a cookie taken on the
    # BROKEN reader then names an unknown offset, and seeking to it recovers.
    checker = _text_checker_at(Health.HEALTHY)
    cancel = interpreter.Event(
        0,
        {"op": "cancel", "call": {"op": "seek_mark", "label": "m0"}},
        Outcome("cancelled"),
        Outcome("ok", "cancel requested"),
    )
    cancel.cursor_moved = True
    checker.observe(cancel)
    assert checker.health is Health.BROKEN
    checker.observe(
        interpreter.Event(1, {"op": "tell_mark", "label": "m1"}, Outcome("ok", -5))
    )
    checker.observe(
        interpreter.Event(2, {"op": "seek_mark", "label": "m1"}, Outcome("ok", -5))
    )
    assert not checker.violations, checker.violations
    assert checker.health is Health.HEALTHY
    assert checker.modeled and not checker.certain
    return checker


def test_cookie_recovery_from_an_uncertain_position_keeps_checking_content():
    checker = _recovered_by_an_uncertain_cookie()
    read = {"op": "read", "n": 3}
    checker.observe(interpreter.Event(3, read, Outcome("ok", "\0" * 3)))
    assert any("matches no allowed offset" in v for v in checker.violations)


def test_cookie_recovery_from_an_uncertain_position_accepts_payload_text():
    checker = _recovered_by_an_uncertain_cookie()
    text = checker.upper[5:8]
    checker.observe(interpreter.Event(3, {"op": "read", "n": 3}, Outcome("ok", text)))
    assert not checker.violations, checker.violations


def test_a_reused_mark_label_drops_its_old_uncertainty():
    checker = _recovered_by_an_uncertain_cookie()
    checker.handle_call(3, {"op": "seek0"}, Outcome("ok", 0))
    checker.handle_call(4, {"op": "tell_mark", "label": "m1"}, Outcome("ok", 0))
    checker.handle_call(5, {"op": "seek_mark", "label": "m1"}, Outcome("ok", 0))
    assert checker.certain and checker.position == 0, checker.candidates


def _after_a_cancelled_read_breaks_the_reader():
    # Seed 2000012 on a zlib-ng wire (Windows 3.14): a cancel lands inside
    # read(-1) on a custom source without a checkpoint. The read consumed an
    # unknown amount, so a cookie taken on the BROKEN reader names wherever
    # the reader stopped, not where the read began.
    scenario = generate(2000012)
    source = scenario["source"]
    assert source["kind"] == "custom" and not source["checkpoint"]
    checker = make_checker(scenario, aiogzip.engine_info().decompression)
    checker.lifecycle = Lifecycle.OPEN
    upper = checker.upper
    events = [
        interpreter.Event(0, {"op": "read", "n": 2}, Outcome("ok", upper[:2])),
        interpreter.Event(
            1,
            {"op": "cancel", "call": {"op": "read", "n": -1}, "after": 1},
            Outcome("cancelled"),
            Outcome("ok", "cancel requested"),
        ),
        interpreter.Event(2, {"op": "tell_mark", "label": "m0"}, Outcome("ok", 7)),
        interpreter.Event(3, {"op": "seek0"}, Outcome("ok", 0)),
        interpreter.Event(4, {"op": "seek_mark", "label": "m0"}, Outcome("ok", 7)),
    ]
    for event in events:
        checker.observe(event)
    assert not checker.violations, checker.violations
    assert checker.health is Health.HEALTHY
    return checker


def test_a_cookie_after_a_cancelled_read_may_name_a_later_offset():
    checker = _after_a_cancelled_read_breaks_the_reader()
    text = checker.upper[4:7]
    readline = {"op": "readline", "limit": 3}
    checker.observe(interpreter.Event(5, readline, Outcome("ok", text)))
    assert not checker.violations, checker.violations


def test_a_cookie_after_a_cancelled_read_keeps_checking_content():
    checker = _after_a_cancelled_read_breaks_the_reader()
    # The read began at 2, so the cookie names no earlier offset.
    assert checker.candidates[0] == 2, checker.candidates[:4]
    readline = {"op": "readline", "limit": 3}
    checker.observe(interpreter.Event(5, readline, Outcome("ok", "\0" * 3)))
    assert any("matches no allowed offset" in v for v in checker.violations)


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


def test_repeated_seek_end_after_a_salvage_drain_must_refuse():
    checker = _drained_salvage_checker()
    checker.handle_call(1, {"op": "seek_end", "offset": 0}, Outcome("ok", 7))
    assert any("drained the salvage" in v for v in checker.violations)


def test_repeated_seek_end_refusal_after_a_salvage_drain_is_accepted():
    checker = _drained_salvage_checker()
    refusal = OSError(f"{BROKEN_MESSAGE} after failed or cancelled decompression")
    checker.handle_call(
        1, {"op": "seek_end", "offset": 0}, Outcome("error", error=refusal)
    )
    assert not checker.violations, checker.violations


def test_rewind_lets_seek_end_drain_again():
    checker = _drained_salvage_checker()
    checker.handle_call(1, {"op": "seek0"}, Outcome("ok", 0))
    assert not checker.salvage_drained
    checker.health = Health.VALIDATION_SALVAGE  # a new failure after the rewind
    checker.handle_call(2, {"op": "seek_end", "offset": 0}, Outcome("ok", 7))
    assert not checker.violations, checker.violations
