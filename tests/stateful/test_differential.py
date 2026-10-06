"""Predicate, near-miss and composition tests for the C0 and b1 differentials.

Every candidate trace here is live: the seed's scenario replayed in-process
against the candidate with the model and observer attached, exactly as the
runner's ``--observe`` side records it. C0-shaped references are traces
recorded from C0 (``tests/data/wp10_c0_traces.json``); near misses mutate
them. Most b1-shaped references are written from the design's b1 inventory,
because no b1 comparison could run before these tests passed; the ones found
by the first b1 comparison are recorded from b1 itself
(``tests/data/wp10_b1_runs.json``). See "Rules" in
plans/design/v2.0.0b2-wp10-qualification.md.
"""

from __future__ import annotations

import base64
import copy
import dataclasses
import gzip
import json
from functools import cache
from pathlib import Path
from typing import Any

import interpreter
import pytest
from differential import (
    CLOSED,
    READ_BROKEN,
    Bc2Request,
    Pair,
    Row,
    _converged,
    bc2_request,
    compare,
    encoded,
    lossy_scenario,
    parse,
    raw_bytes,
)
from generator import generate, member_spans, unb64
from interpreter import Event, Outcome, final_output, recorded_run
from model import Checker, LossyChecker

import aiogzip

ENGINE = aiogzip.engine_info().decompression
DATA = Path(__file__).resolve().parent.parent / "data" / "wp10_c0_traces.json"
C0 = json.loads(DATA.read_text(encoding="utf-8"))["traces"]
B1 = json.loads((DATA.parent / "wp10_b1_runs.json").read_text(encoding="utf-8"))["runs"]


@cache
def _live(seed: int, scenario_json: str | None = None) -> tuple[str, str]:
    scenario = json.loads(scenario_json) if scenario_json else generate(seed)
    run = recorded_run(aiogzip, scenario, ENGINE, "observe")
    # The runner exchanges runs as JSON; compare like it does.
    return json.dumps(scenario), json.dumps(run)


def live(seed: int, scenario: dict[str, Any] | None = None):
    """The scenario and the candidate's run record (fresh copies)."""
    scenario_json, run_json = _live(
        seed, json.dumps(scenario, sort_keys=True) if scenario else None
    )
    return json.loads(scenario_json), json.loads(run_json)


def make_pair(
    seed: int,
    ref: list[Row] | None = None,
    *,
    reference: str = "c0",
    scenario: dict[str, Any] | None = None,
    cand: list[Row] | None = None,
    run_scenario: dict[str, Any] | None = None,
) -> Pair:
    """A pair over the live candidate; ``scenario`` overrides only what the
    predicates see, ``run_scenario`` what the candidate also runs."""
    live_scenario, run = live(seed, run_scenario)
    rows = parse(run["trace"]) if cand is None else cand
    refs = parse(C0[str(seed)]) if ref is None else ref
    return Pair(scenario or live_scenario, reference, rows, refs, run, ENGINE)


def c0_rows(seed: int) -> list[Row]:
    return parse(copy.deepcopy(C0[str(seed)]))


def cand_rows(seed: int) -> list[Row]:
    return parse(live(seed)[1]["trace"])


def edit(rows: list[Row], key, **fields) -> list[Row]:
    assert any(row.key == key for row in rows), key
    return [
        dataclasses.replace(row, **fields) if row.key == key else row for row in rows
    ]


def edit_final(rows: list[Row], **fields) -> list[Row]:
    final = rows[-1]
    assert final.name == "final"
    outcome = copy.deepcopy(final.outcome)
    outcome["ok"].update(fields)
    return edit(rows, final.key, outcome=outcome)


def row(rows: list[Row], index: int, name: str) -> Row:
    return next(r for r in rows if r.key[:2] == (index, name))


def b64(data: bytes) -> dict[str, str]:
    return {"base64": base64.b64encode(data).decode("ascii")}


def raw(item: dict[str, str]) -> bytes:
    return base64.b64decode(item["base64"])


def claims(result, name: str) -> list[str]:
    return result.claims.get(name, [])


def passes(pair: Pair, predicate: str, lossy=None) -> None:
    result = compare(pair, lossy)
    assert result.ok, result.failures
    assert claims(result, predicate), result.claims


def fails(pair: Pair, *unclaimed: str, lossy=None) -> None:
    result = compare(pair, lossy)
    assert not result.ok, result.claims
    for item in unclaimed:
        assert any(item in failure for failure in result.failures), result.failures


# Recorded C0 references: every fixture seed is claimed, by its predicate only.

C0_SEEDS = {
    "BC7-TEXT-SALVAGE": (4819, 921, 2512, 2500, 3134, 2575, 3152, 3608),
    "BC8-WRITER-ABORT": (316, 499, 4036, 2678, 5587, 146, 1, 164),
    "BC9-REWIND-ABORT": (124, 431, 584),
}


@pytest.mark.parametrize(
    ("predicate", "seed"),
    [(name, seed) for name, seeds in C0_SEEDS.items() for seed in seeds],
)
def test_recorded_c0_difference_is_claimed(predicate, seed):
    result = compare(make_pair(seed))
    assert result.ok, result.failures
    assert {name for name, items in result.claims.items() if items} == {predicate}


def test_fixture_covers_exactly_the_listed_seeds():
    assert sorted(map(int, C0)) == sorted(
        s for seeds in C0_SEEDS.values() for s in seeds
    )


# member_spans: the replayable member boundaries BC2 relies on.


@pytest.mark.parametrize("seed", range(0, 400))
def test_member_spans_locate_every_recorded_member(seed):
    scenario = generate(seed)
    if scenario["mode"] not in ("rb", "rt"):
        return
    wire = base64.b64decode(scenario["wire"])
    payloads = [base64.b64decode(p) for p in scenario["payloads"]]
    spans = scenario["member_spans"]
    corruption = scenario["corruption"]
    damaged = corruption.get("member")
    previous = 0
    for index, (start, end) in enumerate(spans):
        assert previous <= start <= end <= len(wire)
        previous = end
        assert wire[start:end].startswith(b"\x1f\x8b"[: end - start])
        if index != damaged:
            assert gzip.decompress(wire[start:end]) == payloads[index]
    assert not wire[previous:].strip(b"\0"), "bytes past the last span"


def test_member_spans_body_damage_shrinks_and_shifts_later_members():
    members = [b"A" * 30, b"B" * 30, b"C" * 30]
    offsets = [0, 30, 60]
    corruption = {"kind": "body", "member": 1, "at": 40, "span": 4}
    assert member_spans(members, offsets, corruption, 88) == [
        [0, 30],
        [30, 58],
        [58, 88],
    ]


def test_member_spans_body_damage_crossing_a_trailer_runs_to_the_wire_end():
    members = [b"A" * 30, b"B" * 30, b"C" * 30]
    offsets = [0, 30, 60]
    corruption = {"kind": "body", "member": 1, "at": 58, "span": 16}
    assert member_spans(members, offsets, corruption, 76) == [[0, 30], [30, 76]]


def test_member_spans_truncation_ends_at_the_cut():
    members = [b"A" * 30, b"B" * 30, b"C" * 30]
    corruption = {"kind": "truncate", "member": 1, "cut": 45}
    assert member_spans(members, [0, 30, 60], corruption, 45) == [[0, 30], [30, 45]]


# Witnesses recorded by the interpreter.


def test_buffer_read_records_the_pulled_uncompressed_range():
    pulled = [r for r in cand_rows(3134) if r.name == "buffer_read"]
    assert [r.pulled for r in pulled][1][1] - pulled[1].pulled[0] == 7
    assert pulled[0].pulled[0] == pulled[0].pulled[1] == pulled[1].pulled[0]


def test_consumed_source_failure_records_the_taken_wire_range():
    rows = cand_rows(3152)
    failed = row(rows, 12, "readline")
    assert failed.taken == [0, 64]


def test_fd_counts_follow_a_collection(monkeypatch):
    # A file an earlier scenario leaked closes when its garbage is collected;
    # collecting right before each count keeps that out of fd_delta. The
    # interpreter's CLI (every differential side) turns this on.
    calls = []
    real_count = interpreter._open_fds
    monkeypatch.setattr(interpreter, "COLLECT_FOR_FD_COUNTS", True)
    monkeypatch.setattr(interpreter.gc, "collect", lambda: calls.append("collect"))
    monkeypatch.setattr(
        interpreter, "_open_fds", lambda: calls.append("count") or real_count()
    )
    recorded_run(aiogzip, generate(558), ENGINE)
    assert calls == ["collect", "count", "collect", "count"]


# The model's EOF narrowing (seed 4946): an empty result that could only
# come from the end narrows an uncertain position to it.


def test_empty_read_after_uncertain_seek_narrows_to_the_end(monkeypatch):
    scenario, run = live(4946)
    assert not run["violations"]
    assert any(p and p[0] != p[1] for p in run["positions"]), "never uncertain"
    # Without narrowing, the model flags the candidate's correct empty reads.
    monkeypatch.setattr(Checker, "narrow_to_end", lambda self: None)
    stale = recorded_run(aiogzip, scenario, ENGINE, "observe")
    assert any("validated EOF" in message for _i, message in stale["violations"])


# BC7: text salvage drain.


def _set_op(scenario, index, **fields):
    scenario = copy.deepcopy(scenario)
    op = scenario["ops"][index]
    target = op["call"] if "call" in op and "n" not in op else op
    target.update(fields)
    return scenario


@pytest.mark.parametrize("size", [None, -5])
def test_bc7_f1a_normalizes_unbounded_sizes(size):
    scenario = _set_op(generate(4819), 1, n=size)
    passes(make_pair(4819, run_scenario=scenario), "BC7-TEXT-SALVAGE")


def test_bc7_f2_on_a_sized_read():
    scenario = _set_op(generate(2512), 1, n=7)
    pair = make_pair(2512, run_scenario=scenario)
    c = row(pair.cand, 1, "overlap")
    assert READ_BROKEN in c.outcome["message"]
    passes(pair, "BC7-TEXT-SALVAGE")


def test_bc7_rejects_a_healthy_reader():
    pair = make_pair(2512)
    n = pair.cand_order[row(pair.cand, 1, "overlap").key]
    pair.cand_info["health"][n] = ["HEALTHY", "HEALTHY"]
    fails(pair, "(1, 'overlap', 0)")


def test_bc7_rejects_a_binary_reader():
    scenario = generate(2512)
    scenario["mode"] = "rb"
    fails(make_pair(2512, scenario=scenario), "(1, 'overlap', 0)")


def test_bc7_rejects_a_non_read_call():
    scenario = _set_op(generate(2512), 1, op="readline", limit=-1)
    scenario["ops"][1]["call"].pop("n")
    fails(make_pair(2512, scenario=scenario), "(1, 'overlap', 0)")


def test_bc7_rejects_an_invalid_byte_decode_error():
    ref = c0_rows(4819)
    f = row(ref, 1, "read")
    message = f.outcome["message"].replace(
        "unexpected end of data", "invalid start byte"
    )
    ref = edit(ref, f.key, outcome={**f.outcome, "message": message})
    fails(make_pair(4819, ref), "(1, 'read', 0)")


def test_bc7_rejects_f1a_on_a_sized_read():
    scenario = _set_op(generate(4819), 1, n=64)
    fails(make_pair(4819, scenario=scenario), "(1, 'read', 0)")


def test_bc7_rejects_f1a_text_off_by_one_character():
    cand = cand_rows(4819)
    f = row(cand, 1, "read")
    text = f.outcome["ok"]["str"]
    cand = edit(cand, f.key, outcome={"ok": {"str": text[:-1]}})
    fails(make_pair(4819, cand=cand), "(1, 'read', 0)")


def test_bc7_rejects_later_reference_text_that_is_not_a_prefix():
    ref = c0_rows(2500)
    later = row(ref, 4, "next")
    text = later.outcome["ok"]["str"]
    ref = edit(ref, later.key, outcome={"ok": {"str": "x" + text[1:]}})
    result = compare(make_pair(2500, ref))
    # The broken prefix stops the claim: this event and every later text one.
    assert result.failures[0] == "unclaimed difference ('event', (4, 'next', 0))"
    assert "(6, 'overlap', 0)" in "".join(result.failures)
    assert "('event', (4, 'next', 0))" not in claims(result, "BC7-TEXT-SALVAGE")


def test_bc7_replay_fails_closed_without_the_pulled_witness():
    cand = cand_rows(3134)
    pulled = row(cand, 3, "buffer_read")
    cand = edit(cand, pulled.key, pulled=None)
    ref = edit(c0_rows(3134), pulled.key, pulled=None)
    fails(make_pair(3134, ref, cand=cand), "(4, 'abort', 0)")


def test_bc7_replay_rejects_a_shifted_pulled_range():
    cand = cand_rows(3134)
    pulled = row(cand, 3, "buffer_read")
    shifted = [pulled.pulled[0] + 1, pulled.pulled[1] + 1]
    cand = edit(cand, pulled.key, pulled=shifted)
    ref = edit(c0_rows(3134), pulled.key, pulled=shifted)
    fails(make_pair(3134, ref, cand=cand), "(4, 'abort', 0)")


# BC8: writer abort.


def test_bc8_w1a_cases_cover_short_partial_and_no_effect_sinks():
    sources = {seed: generate(seed)["source"] for seed in (316, 499, 4036, 2678)}
    assert sources[2678]["short"] and sources[2678]["closefd"]
    assert c0_rows(2678)[-1].outcome["ok"]["source_calls_after_close"] == 2
    assert any(op["op"] == "fail_sink_partial" for op in generate(499)["ops"])
    no_effect = c0_rows(4036)
    assert raw(no_effect[-1].outcome["ok"]["output_raw"]) == raw(
        cand_rows(4036)[-1].outcome["ok"]["output_raw"]
    )


def test_bc8_rejects_a_read_scenario():
    scenario = generate(316)
    scenario["mode"] = "rb"
    fails(make_pair(316, scenario=scenario), "(1, 'abort', 0)")


def test_bc8_rejects_a_complete_member():
    ref = c0_rows(316)
    output = copy.deepcopy(ref[-1].outcome["ok"]["output"])
    output["complete"] = True
    fails(make_pair(316, edit_final(ref, output=output)), "'output'")


def test_bc8_rejects_a_second_differing_event():
    ref = c0_rows(316)
    ref = edit(ref, (0, "write", 0), outcome={"ok": 999})
    result = compare(make_pair(316, ref))
    assert result.failures == ["unclaimed difference ('event', (0, 'write', 0))"]


def test_bc8_w1a_rejects_e_not_a_prefix_of_p():
    ref = c0_rows(316)
    data = bytearray(raw(ref[-1].outcome["ok"]["output_raw"]))
    data[-1] ^= 1
    fails(
        make_pair(316, edit_final(ref, output_raw=b64(bytes(data)))), "(1, 'abort', 0)"
    )


def test_bc8_w1a_rejects_empty_e_without_the_no_effect_failure():
    ref = edit_final(c0_rows(316), **{
        k: cand_rows(316)[-1].outcome["ok"][k] for k in ("output", "output_raw")
    })  # fmt: skip
    fails(make_pair(316, ref), "(1, 'abort', 0)")


def test_bc8_w1a_rejects_non_empty_e_with_the_no_effect_failure():
    ref = c0_rows(4036)
    abort = row(ref, 3, "abort")
    data = raw(ref[-1].outcome["ok"]["output_raw"]) + raw(abort.parked["bytes"])[:1]
    fails(make_pair(4036, edit_final(ref, output_raw=b64(data))), "output_raw")


@pytest.mark.parametrize(("side", "resumed"), [("cand", True), ("ref", False)])
def test_bc8_w1a_rejects_wrong_resumption(side, resumed):
    rows = cand_rows(316) if side == "cand" else c0_rows(316)
    abort = row(rows, 1, "abort")
    rows = edit(rows, abort.key, parked={**abort.parked, "resumed": resumed})
    pair = make_pair(316, cand=rows) if side == "cand" else make_pair(316, rows)
    fails(pair, "(1, 'abort', 0)")


@pytest.mark.parametrize(("seed", "index"), [(316, 1), (146, 2), (1, 4)])
def test_bc8_rejects_an_exact_p_difference_in_the_wrong_direction(seed, index):
    cand, ref = cand_rows(seed), c0_rows(seed)
    # Swap the outputs: whichever side wrote P now writes less.
    fields = ("output", "output_raw")
    c_out = {f: cand[-1].outcome["ok"][f] for f in fields}
    r_out = {f: ref[-1].outcome["ok"][f] for f in fields}
    pair = make_pair(seed, edit_final(ref, **c_out), cand=edit_final(cand, **r_out))
    fails(pair, "output_raw")


def test_bc8_w1b_rejects_a_reference_that_already_aborts():
    ref = c0_rows(146)
    abort = row(ref, 2, "abort")
    cand_second = row(cand_rows(146), 2, "abort").second
    ref = edit(
        ref, abort.key, second={**cand_second, "message": cand_second["message"] + "!"}
    )
    fails(make_pair(146, ref), "(2, 'abort', 0)")


def test_bc8_rejects_a_cancelled_custom_sink_write():
    cand, ref = cand_rows(1), c0_rows(1)
    key = row(cand, 4, "cancel").key
    custom = {"via": "custom"}
    cand = edit(cand, key, parked={**row(cand, 4, "cancel").parked, **custom})
    ref = edit(ref, key, parked={**row(ref, 4, "cancel").parked, **custom})
    fails(make_pair(1, ref, cand=cand), "output_raw")


def test_bc8_w2_rejects_a_binary_writelines():
    scenario = generate(164)
    scenario["mode"] = "wb"
    fails(make_pair(164, scenario=scenario), "(9, 'writelines', 0)")


# BC9: abort of a native rewind.


def _b1_bc9(seed: int, index: int) -> list[Row]:
    ref = c0_rows(seed)
    abort = row(ref, index, "abort")
    return edit(
        ref, abort.key, second={"error": "ValueError", "message": "seek of closed file"}
    )


def test_bc9_b1_shaped_mismatch_is_claimed():
    passes(make_pair(124, _b1_bc9(124, 1), reference="b1"), "BC9-REWIND-ABORT")


def test_bc9_rejects_a_custom_source():
    scenario = generate(124)
    scenario["source"] = {"kind": "custom", "seekable": True, "checkpoint": False}
    fails(make_pair(124, scenario=scenario), "(1, 'abort', 0)")


def test_bc9_rejects_a_parked_native_read():
    cand, ref = cand_rows(124), c0_rows(124)
    key = row(cand, 1, "abort").key
    read = {"via": "native", "method": "read", "bytes": None}
    fails(
        make_pair(124, edit(ref, key, parked=read), cand=edit(cand, key, parked=read))
    )


def test_bc9_rejects_a_cancel():
    cand, ref = cand_rows(124), c0_rows(124)
    scenario = generate(124)
    scenario["ops"][1]["op"] = "cancel"

    def rename(rows):
        return [
            dataclasses.replace(r, key=(1, "cancel", 0))
            if r.key[:2] == (1, "abort")
            else r
            for r in rows
        ]

    fails(make_pair(124, rename(ref), cand=rename(cand), scenario=scenario))


def test_bc9_rejects_another_reference_error():
    ref = c0_rows(124)
    key = row(ref, 1, "abort").key
    fails(
        make_pair(124, edit(ref, key, second={"error": "OSError", "message": "boom"}))
    )


def test_bc9_rejects_the_candidate_returning_zero():
    cand = cand_rows(124)
    cand = edit(cand, row(cand, 1, "abort").key, second={"ok": 0})
    fails(make_pair(124, _b1_bc9(124, 1), reference="b1", cand=cand))


def test_bc9_rejects_a_second_differing_event():
    ref = c0_rows(124)
    ref = edit(ref, (0, "readlines", 0), outcome={"ok": []})
    result = compare(make_pair(124, ref))
    assert result.failures == ["unclaimed difference ('event', (0, 'readlines', 0))"]
    assert claims(result, "BC9-REWIND-ABORT")


# Composition.


def test_composition_rejects_one_event_claimed_by_two_predicates(monkeypatch):
    import differential

    def bc8_too(pair):
        return differential.bc9(pair)

    specific = tuple(
        (name, bc8_too if name == "BC8-WRITER-ABORT" else fn)
        for name, fn in differential.SPECIFIC
    )
    monkeypatch.setattr(differential, "SPECIFIC", specific)
    fails(make_pair(124), "claimed by BC8-WRITER-ABORT and BC9-REWIND-ABORT")


def test_composition_rejects_an_unclaimed_one_sided_event():
    ref = c0_rows(124)
    extra = Row((1, "readline", 0), CLOSED)
    fails(make_pair(124, ref[:2] + [extra] + ref[2:]), "one-sided")


def test_composition_rejects_shared_keys_out_of_order():
    ref = c0_rows(124)
    ref[1], ref[2] = ref[2], ref[1]
    fails(make_pair(124, ref), "out of order")


def test_composition_rejects_candidate_model_violations():
    pair = make_pair(124)
    pair.cand_info["violations"] = [[0, "injected"]]
    fails(pair, "candidate model: op 0: injected")


# BC2: lost input (b1 only). A custom-source b1 is emulated in-process: the
# candidate over a source on which injected failures and cancelled reads
# lose what they took, as b1's reader does. Its ``tell()`` hides that loss,
# so the candidate's checkpoint proof agrees with b1's view. The emulated
# run carries the lossy model, exactly as the runner's b1 side records it.


class LyingSource(interpreter.Source):
    """The fake source as b1's reader sees it after losing input."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.hidden = 0
        self.tell = self._lying_tell

    def _lying_tell(self) -> int:
        return self.offset - self.hidden

    async def read(self, size=-1):
        try:
            return await super().read(size)
        except OSError:
            if self.taken is not None:
                self.hidden += self.taken[1] - self.taken[0]
            raise

    async def seek(self, offset, whence=0):
        result = await super().seek(offset, whence)
        self.hidden = 0
        return result


def bc2_request_for(seed: int, scenario: dict[str, Any] | None = None) -> Bc2Request:
    _scenario, run = live(seed)
    rows = parse(run["trace"])
    pair = Pair(scenario or _scenario, "b1", rows, rows, run, ENGINE)
    request = bc2_request(pair)
    assert request is not None, seed
    return request


@cache
def _b1_emulated(seed: int) -> str:
    request = bc2_request_for(seed)
    real = interpreter.Source
    interpreter.Source = LyingSource
    try:
        lossy = recorded_run(
            aiogzip,
            generate(seed),
            ENGINE,
            "lossy",
            request.line(generate(seed)),
        )
    finally:
        interpreter.Source = real
    return json.dumps(lossy)


def b1_emulated(seed: int) -> tuple[Pair, dict[str, Any]]:
    """The candidate against the emulated b1, and b1's lossy run record."""
    lossy = json.loads(_b1_emulated(seed))
    return make_pair(seed, parse(lossy["trace"]), reference="b1"), lossy


BC2_SEEDS = {
    # (mode, trigger, lossy range, checkpoint)
    923: "rt fail_no_effect, empty",
    3879: "rb fail_no_effect, empty",
    20: "rb fail_consumed at EOF, empty",
    1499: "rt fail_consumed at EOF, empty",
    3479: "rb cancel, empty",
    1231: "rt cancel, empty",
    2060: "rb fail_consumed, member range to EOF",
    662: "rt fail_consumed, member range to EOF",
    2486: "rb fail_consumed with a checkpoint, member range",
    3958: "rt fail_consumed with a checkpoint, member range",
    1065: "rt seekable: a rewind with no source call keeps the lossy view",
    277: "rb seekable: a rewind with no source call keeps the lossy view",
    430: "rt seekable: a physical rewind, but the models never converge",
    2969: "rb seekable: the span ends where the models converge",
    2361: "rt seekable: the span ends where the models converge",
    3210: "rb seekable: convergence at a seek_back",
}
CONVERGING = (2969, 2361, 3210)


def span_end(pair: Pair, lossy: dict[str, Any]) -> int | None:
    """The candidate-order position where BC2's span ends, if it does."""
    request = bc2_request(pair)
    assert request is not None
    return _converged(pair, lossy, pair.cand_order[request.trigger])


@pytest.mark.parametrize("seed", sorted(BC2_SEEDS))
def test_bc2_l1_emulated_b1_is_claimed(seed):
    pair, lossy = b1_emulated(seed)
    assert pair.diffs, "the emulated b1 must differ from the candidate"
    assert lossy["violations"] == []
    passes(pair, "BC2-LOST-INPUT", lossy)


def test_bc2_cases_cover_each_trigger_kind():
    seen = set()
    for seed in BC2_SEEDS:
        request = bc2_request_for(seed)
        scenario = generate(seed)
        lost = scenario["wire"] != request.lossy["wire"]
        index, name, _ = request.trigger
        if name != "cancel":
            # A read trigger fails as the latest arming op before it says.
            armed = [op["op"] for op in scenario["ops"][:index] if "fail" in op["op"]]
            name = armed[-1]
        seen.add((scenario["mode"], name, lost))
        pair, lossy = b1_emulated(seed)
        if seed in (1065, 277):
            assert request.rebase and lossy["rebased_at"] is None
        if seed == 430:
            assert lossy["rebased_at"] is not None
            assert span_end(pair, lossy) is None
        if seed in CONVERGING:
            assert lossy["rebased_at"] is not None
            assert span_end(pair, lossy) is not None
    for mode in ("rb", "rt"):
        assert {(mode, "fail_no_effect", False), (mode, "cancel", False)} <= seen
        assert {(mode, "fail_consumed", False), (mode, "fail_consumed", True)} <= seen


def test_bc2_requests_nothing_from_c0():
    pair, lossy = b1_emulated(923)
    pair.reference = "c0"
    assert bc2_request(pair) is None


def test_bc2_rejects_a_checkpoint_trigger_proven_no_effect():
    pair, lossy = b1_emulated(923)
    scenario = copy.deepcopy(pair.scenario)
    scenario["source"]["checkpoint"] = True
    fails(
        make_pair(923, pair.ref, reference="b1", scenario=scenario),
        "unclaimed",
        lossy=lossy,
    )


def test_bc2_rejects_a_scenario_without_member_spans():
    pair, lossy = b1_emulated(2060)
    scenario = copy.deepcopy(pair.scenario)
    del scenario["member_spans"]
    fails(
        make_pair(2060, pair.ref, reference="b1", scenario=scenario),
        "unclaimed",
        lossy=lossy,
    )


def test_bc2_rejects_a_range_with_an_endpoint_inside_a_member():
    request = bc2_request_for(2486)
    a, b = request.lossy["lossy_range"]
    pair, lossy = b1_emulated(2486)
    scenario = copy.deepcopy(pair.scenario)
    # Move the last member's end past the range's end.
    assert scenario["member_spans"][-1][1] == b
    scenario["member_spans"][-1][1] = b + 1
    fails(
        make_pair(2486, pair.ref, reference="b1", scenario=scenario),
        "unclaimed",
        lossy=lossy,
    )


def test_bc2_rejects_reference_data_the_lossy_model_does_not_accept():
    pair, lossy = b1_emulated(2060)
    claimed = compare(pair, lossy).claims["BC2-LOST-INPUT"]
    index = min(eval(item)[1][0] for item in claimed)
    lossy["violations"] = [[index, "injected"]]
    fails(pair, f"({index}, ", lossy=lossy)


def test_bc2_fails_a_lossy_violation_at_a_matching_event():
    pair, lossy = b1_emulated(2060)
    matching = [r for r in pair.cand if r.key not in pair.diffs and r.index >= 0]
    index = matching[-1].index
    assert all(r.key not in pair.diffs for r in pair.cand if r.index == index)
    lossy["violations"] = [[index, "injected"]]
    fails(pair, f"lossy model: op {index}: injected", lossy=lossy)


def test_bc2_fails_a_lossy_violation_with_no_differences():
    scenario, run = live(2060)
    rows = parse(run["trace"])
    pair = make_pair(2060, rows, reference="b1")
    assert not pair.diffs and bc2_request(pair) is not None
    lossy = {
        "trace": run["trace"],
        "violations": [],
        "rebased_at": None,
        "normalized": [],
    }
    assert compare(pair, lossy).ok
    lossy["violations"] = [[0, "injected"]]
    fails(pair, "lossy model: op 0: injected", lossy=lossy)


def test_bc2_claims_nothing_when_the_lossy_trace_is_not_b1s():
    pair, lossy = b1_emulated(2060)
    lossy["trace"] = lossy["trace"][:-1]
    result = compare(pair, lossy)
    assert not result.ok
    assert claims(result, "BC2-LOST-INPUT") == []


@pytest.mark.parametrize("seed", CONVERGING)
def test_bc2_rejects_a_difference_after_the_span(seed):
    pair, lossy = b1_emulated(seed)
    end = pair.cand[span_end(pair, lossy)].index
    later = [r for r in pair.ref if r.index > end and r.name != "final"]
    assert later
    target = later[-1]
    ref = edit(pair.ref, target.key, outcome={"error": "OSError", "message": "x"})
    fails(make_pair(seed, ref, reference="b1"), repr(target.key), lossy=lossy)


def test_bc2_rejects_a_candidate_refusal_after_its_rewind():
    seed = 2361
    pair, lossy = b1_emulated(seed)
    end = pair.cand[span_end(pair, lossy)].index
    later = [r for r in pair.cand if r.index > end and r.name != "final"]
    target = later[-1]
    cand = edit(
        pair.cand, target.key, outcome={"error": "OSError", "message": READ_BROKEN}
    )
    fails(
        make_pair(seed, pair.ref, reference="b1", cand=cand),
        repr(target.key),
        lossy=lossy,
    )


def unparse(rows: list[Row]) -> list[list[Any]]:
    """The trace rows ``parse`` reads back as ``rows``."""
    trace = []
    for r in rows:
        raw_row = [r.index, r.name, r.outcome]
        if r.second is not None:
            raw_row.append(r.second)
        if r.parked is not None:
            raw_row.append(
                {
                    "parked": {
                        k: {"str": v} if isinstance(v, str) else v
                        for k, v in r.parked.items()
                    }
                }
            )
        if r.taken is not None:
            raw_row.append({"taken": r.taken})
        if r.pulled is not None:
            raw_row.append({"pulled": r.pulled})
        trace.append(raw_row)
    assert parse(trace) == rows
    return trace


@pytest.mark.parametrize("field", ["view", "position", "eof", "health"])
def test_bc2_span_ends_only_when_every_converged_field_agrees(field):
    pair, lossy = b1_emulated(2969)
    end = span_end(pair, lossy)
    m = next(n for n, r in enumerate(pair.ref) if r.key == pair.cand[end].key)
    position, eof, view = lossy["states"][m]
    if field == "view":
        lossy["states"][m] = [position, eof, "lossy"]
    elif field == "position":
        lossy["states"][m] = [[position[0] + 1] * 2, eof, view]
    elif field == "eof":
        lossy["states"][m] = [position, not eof, view]
    else:
        lossy["health"][m] = [lossy["health"][m][0], "BROKEN"]
    later = span_end(pair, lossy)
    assert later is None or later > end


def test_bc2_span_ends_only_at_a_certain_position():
    pair, lossy = b1_emulated(2969)
    end = span_end(pair, lossy)
    m = next(n for n, r in enumerate(pair.ref) if r.key == pair.cand[end].key)
    position, eof, view = lossy["states"][m]
    lossy["states"][m] = [[position[0], position[0] + 1], eof, view]
    pair.cand_info["states"][end][0] = [position[0], position[0] + 1]
    later = span_end(pair, lossy)
    assert later is None or later > end


# The lossy model's view switch: a model rewind with an attested physical
# source seek over the lost range, never a cancelled call.


def _lossy_checker(lost_start: int = 10) -> LossyChecker:
    scenario = generate(2969)
    return LossyChecker(scenario, scenario, ENGINE, 0, True, lost_start)


@pytest.mark.parametrize(
    ("seeks", "kind", "expected"),
    [
        ([0], "ok", True),
        ([10], "ok", True),
        ([11], "ok", False),
        ([20, 0], "error", True),
        (None, "ok", False),
        ([0], "cancelled", False),
    ],
)
def test_lossy_checker_physical_rewind_needs_a_seek_over_the_range(
    seeks, kind, expected
):
    event = Event(3, {"op": "seek0"}, Outcome(kind), seeks=seeks)
    assert _lossy_checker().physical_rewind(event) is expected


def test_lossy_checker_stays_lossy_without_a_recorded_seek(monkeypatch):
    assert _lossy_run(2969)["rebased_at"] is not None
    monkeypatch.setattr(interpreter.Gate, "seeked", lambda self, target: None)
    run = _lossy_run(2969)
    assert run["seeks"] == [] and run["rebased_at"] is None


def test_lossy_checker_stays_lossy_after_a_seek_past_the_range():
    request = bc2_request_for(2969)
    assert _lossy_run(2969, taken=[-1, -1])["rebased_at"] is None
    assert request.taken == [0, 0]


def test_custom_source_seeks_are_recorded_outside_the_trace():
    scenario, run = live(2969)
    assert run["seeks"] and all(targets for _, targets in run["seeks"])
    assert all(
        not (isinstance(x, dict) and "seeks" in x) for r in run["trace"] for x in r
    )


def test_native_source_seeks_are_recorded():
    seeds = [
        s
        for s in range(200)
        if generate(s)["source"]["kind"] == "native"
        and generate(s)["mode"] in ("rb", "rt")
        and any(op["op"] == "seek0" for op in generate(s)["ops"])
    ]
    assert any(live(seed)[1]["seeks"] for seed in seeds[:10])


# Recorded b1 references (tests/data/wp10_b1_runs.json).


def b1_recorded(seed: int) -> tuple[Pair, dict[str, Any]]:
    run = copy.deepcopy(B1[str(seed)])
    return make_pair(seed, parse(run["trace"]), reference="b1"), run["lossy"]


def test_bc2_l2_584_stays_lossy_to_the_end():
    # b1's cancelled native read took the whole wire. Its later seek_mark and
    # seek0 stand at decompressed position 0 and make no source call, so b1
    # never returns to the true wire, and its abort of a rewind it skipped
    # is a BC2 residual, not BC9.
    pair, lossy = b1_recorded(584)
    request = bc2_request(pair)
    assert request is not None and request.clause == "L2"
    assert request.lossy["wire"] == "" and request.taken == [0, 242]
    assert lossy["rebased_at"] is None and lossy["seeks"] == [[3, [0]]]
    result = compare(pair, lossy)
    assert result.ok, result.failures
    bc2 = {eval(item)[1][0] for item in claims(result, "BC2-LOST-INPUT")}
    assert bc2 == {4, 6, 7, 8, 10, 12, 13}
    assert claims(result, "BC9-REWIND-ABORT") == []


def test_bc2_l2_584_fails_if_b1_had_rewound():
    # Had b1 rewound physically at its seek_mark (9) and converged there or
    # at its readline (10), the span would end, leaving b1's later lossy
    # reads and its abort unclaimed.
    pair, lossy = b1_recorded(584)
    for m, r in enumerate(pair.ref):
        if r.index >= 9:
            position, eof, _ = lossy["states"][m]
            lossy["states"][m] = [position, eof, "true"]
    cand_states = pair.cand_info["states"]
    m = next(n for n, r in enumerate(pair.ref) if r.index == 9)
    n = next(n for n, r in enumerate(pair.cand) if r.index == 9)
    lossy["states"][m] = copy.deepcopy(cand_states[n])
    lossy["health"][m] = copy.deepcopy(pair.cand_info["health"][n])
    fails(pair, "(12, 'readlines', 0)", "(13, 'abort', 0)", lossy=lossy)


def test_bc2_l2_rejects_a_trigger_that_differs_beyond_the_witness():
    pair, lossy = b1_recorded(584)
    cancel = row(pair.ref, 4, "cancel")
    ref = edit(pair.ref, cancel.key, second={"ok": {"str": "other"}})
    lossy["trace"] = unparse(ref)
    pair = make_pair(584, ref, reference="b1")
    assert bc2_request(pair) is None
    fails(pair, "(4, 'cancel', 0)", "(6, 'buffer_read', 0)", lossy=lossy)


def test_bc2_l2_rejects_a_range_with_an_endpoint_inside_a_member():
    pair, lossy = b1_recorded(584)
    ref = edit(pair.ref, row(pair.ref, 4, "cancel").key, taken=[0, 100])
    lossy["trace"] = unparse(ref)
    pair = make_pair(584, ref, reference="b1")
    assert bc2_request(pair) is None
    fails(pair, "unclaimed", lossy=lossy)


def test_bc2_168_span_runs_past_the_rebase_until_convergence():
    # b1 rewinds physically at op 5, but its seek_back started from a
    # position ahead of the candidate's, so the models never converge.
    pair, lossy = b1_recorded(168)
    assert lossy["rebased_at"] == 5
    assert span_end(pair, lossy) is None
    result = compare(pair, lossy)
    assert result.ok, result.failures
    bc2 = {eval(item)[1][0] for item in claims(result, "BC2-LOST-INPUT")}
    assert {6, 7} <= bc2


@pytest.mark.parametrize("seed", [20, 271, 2716])
def test_bc2_o1_acquisition_is_normalized_for_the_lossy_model(seed):
    pair, lossy = b1_recorded(seed)
    request = bc2_request(pair)
    assert request is not None and request.acquire == "O1"
    assert lossy["normalized"] == [-1] and lossy["violations"] == []
    result = compare(pair, lossy)
    assert result.ok, result.failures
    assert claims(result, "BC3-OPENING") == ["('event', (-1, 'acquire', 0))"]


def test_bc2_o1_normalization_needs_bc3_to_own_the_acquisition():
    pair, lossy = b1_recorded(20)
    key = (-1, "acquire", 0)
    ref = edit(
        pair.ref,
        key,
        second={"error": "ValueError", "message": "File is already closed"},
    )
    pair = make_pair(20, ref, reference="b1")
    request = bc2_request(pair)
    assert request is not None and request.acquire is None
    lossy["trace"] = unparse(ref)
    fails(pair, "lossy model normalized [-1], expected []", lossy=lossy)


@pytest.mark.parametrize("normalized", [None, [], [-1, -1], [0], ["-1"]])
def test_bc2_o1_requires_exactly_one_normalized_acquisition(normalized):
    pair, lossy = b1_recorded(20)
    assert bc2_request(pair).acquire == "O1"
    if normalized is None:
        del lossy["normalized"]
    else:
        lossy["normalized"] = normalized
    fails(pair, f"lossy model normalized {normalized!r}, expected [-1]", lossy=lossy)


def test_bc2_without_a_clause_rejects_any_normalized_event():
    pair, lossy = b1_recorded(168)
    assert bc2_request(pair).acquire is None
    assert compare(pair, lossy).ok
    lossy["normalized"] = [-1]
    fails(pair, "lossy model normalized [-1], expected []", lossy=lossy)


@pytest.mark.parametrize(
    ("acquire", "index", "violates"),
    [("O1", -1, False), (None, -1, True), ("O1", 4, True)],
)
def test_lossy_checker_normalizes_only_the_o1_acquisition(acquire, index, violates):
    scenario = generate(20)
    checker = LossyChecker(scenario, scenario, ENGINE, 0, True, 0, acquire)
    error = ValueError("File is already open")
    checker.expect_concurrent(index, Outcome("error", error=error))
    assert bool(checker.violations) is violates
    assert checker.normalized == ([] if violates else [-1])


def test_lossy_checker_normalizes_only_o1():
    scenario = generate(20)
    with pytest.raises(ValueError):
        LossyChecker(scenario, scenario, ENGINE, 0, True, 0, "O2")


# lossy_scenario over synthetic text scenarios: whole members removed from
# the middle, joins across a character, and failure-boundary prefixes.

GZIP_HEADER = gzip.compress(b"", mtime=0)[:10]


def stored_then_invalid(data: bytes) -> bytes:
    """A raw DEFLATE body that outputs ``data`` and then raises."""
    n = len(data)
    return bytes([0, n & 0xFF, n >> 8, ~n & 0xFF, (~n >> 8) & 0xFF]) + data + b"\x07"


def synthetic(payloads: list[bytes], corruption=None, damaged: bytes | None = None):
    """A text scenario over ``payloads``; the last member's body is replaced
    by one that outputs ``damaged`` and fails, or truncated by ``cut``."""
    scenario = copy.deepcopy(generate(62))
    members = [gzip.compress(p, mtime=0) for p in payloads]
    corruption = corruption or {"kind": "none"}
    if damaged is not None:
        body = stored_then_invalid(damaged)
        members[-1] = GZIP_HEADER + body + members[-1][-8:]
    offsets = [sum(len(m) for m in members[:i]) for i in range(len(members))]
    wire = b"".join(members)
    if damaged is not None:
        start = offsets[-1]
        corruption = {
            "kind": "body",
            "member": len(members) - 1,
            "at": start + 10,
            "span": 1,
            "body_start": start + 10,
            "body_end": len(wire) - 8,
        }
    if corruption["kind"] == "truncate":
        corruption = dict(corruption, member=len(members) - 1)
        wire = wire[: corruption["cut"]]
    scenario.update(
        text={"encoding": "utf-8", "newline": ""},
        payloads=[base64.b64encode(p).decode("ascii") for p in payloads],
        payload_size=sum(map(len, payloads)),
        member_offsets=offsets,
        member_spans=member_spans(members, offsets, corruption, len(wire)),
        corruption=corruption,
        wire=base64.b64encode(wire).decode("ascii"),
    )
    return scenario


def middle(scenario):
    return scenario["member_spans"][1]


def test_lossy_scenario_removes_a_middle_member_on_a_character_boundary():
    scenario = synthetic([b"ab", "\u20ac".encode(), b"cd"])
    lossy = lossy_scenario(scenario, *middle(scenario), ENGINE)
    assert lossy is not None
    a, b = middle(scenario)
    assert (
        unb64(lossy["wire"])
        == unb64(scenario["wire"])[:a] + unb64(scenario["wire"])[b:]
    )
    assert lossy["member_spans"][1] == [
        s - (b - a) for s in scenario["member_spans"][2]
    ]
    assert Checker(lossy, ENGINE).upper == "abcd"


def test_lossy_scenario_rejects_a_join_across_a_character():
    scenario = synthetic([b"ab\xe2", b"\x82\xacc", b"d"])
    assert lossy_scenario(scenario, *middle(scenario), ENGINE) is None


def test_lossy_scenario_rejects_an_endpoint_inside_a_member():
    scenario = synthetic([b"ab", b"cd", b"ef"])
    a, b = middle(scenario)
    assert lossy_scenario(scenario, a + 1, b, ENGINE) is None
    assert lossy_scenario(scenario, a, b - 1, ENGINE) is None
    assert lossy_scenario(scenario, a, b, ENGINE) is not None


def test_lossy_scenario_keeps_a_truncation_as_validation():
    payloads = [b"ab", b"cd", b"ef" * 40]
    whole = synthetic(payloads)
    cut = whole["member_spans"][2][0] + 20
    scenario = synthetic(payloads, {"kind": "truncate", "cut": cut})
    a, b = middle(scenario)
    lossy = lossy_scenario(scenario, a, b, ENGINE)
    assert lossy is not None
    assert lossy["corruption"]["member"] == 1
    assert lossy["corruption"]["cut"] == cut - (b - a) == len(unb64(lossy["wire"]))
    expect = Checker(lossy, ENGINE).expect
    assert expect.failure == "validation" and not expect.clean
    assert expect.lower == 2


def test_lossy_scenario_requires_the_failure_boundary_prefix_to_decode():
    # The whole lossy payload decodes ("ab\u20acd"), and the damaged member's
    # output completes no character: its held tail keeps the prefix eligible.
    payloads = [b"ab\xe2", b"\x82\xacc\xe2", b"\x82\xacd"]
    held = synthetic(payloads, damaged=b"\x82")
    lossy = lossy_scenario(held, *middle(held), ENGINE)
    assert lossy is not None
    assert Checker(lossy, ENGINE).expect.failure == "validation"
    # Output that cannot continue the character fails the prefix.
    invalid = synthetic(payloads, damaged=b"A")
    assert lossy_scenario(invalid, *middle(invalid), ENGINE) is None


# The lossy model itself, over emulated b1 runs.


def _lossy_run(seed: int, **override) -> dict[str, Any]:
    request = bc2_request_for(seed)
    fields = request.line(generate(seed)) | override
    real = interpreter.Source
    interpreter.Source = LyingSource
    try:
        return recorded_run(aiogzip, generate(seed), ENGINE, "lossy", fields)
    finally:
        interpreter.Source = real


def test_lossy_checker_treats_the_trigger_as_no_effect():
    assert _lossy_run(2060)["violations"] == []


def test_lossy_checker_rejects_a_misplaced_trigger():
    request = bc2_request_for(2060)
    assert _lossy_run(2060, trigger=request.trigger[0] + 1)["violations"]


def test_lossy_checker_rejects_the_true_scenario_after_lost_input():
    assert _lossy_run(2060, lossy=generate(2060))["violations"]


def _584_lossy_run(**override) -> dict[str, Any]:
    # Seed 584 reads the whole wire (op 0), rewinds (op 3), and then its
    # cancelled native read (op 4) is where b1 lost [0, 242).
    scenario = generate(584)
    lossy = lossy_scenario(scenario, 0, 242, ENGINE)
    assert lossy is not None and lossy["wire"] == ""
    request = {"lossy": lossy, "trigger": 4, "rebase": False, "taken": [0, 242]}
    request |= override
    return recorded_run(aiogzip, scenario, ENGINE, "lossy", request)


def test_lossy_checker_reads_the_true_wire_before_the_trigger():
    violations = _584_lossy_run()["violations"]
    # Before the trigger the true wire is in force, so op 0's whole-wire
    # readlines is accepted. From the trigger on the lossy (empty) view is:
    # the first data the model checks again, op 12's readlines after the
    # seek0 at op 11 (text buffer reads at 6 and 8 suspend data checks), is
    # true-wire data the lossy wire does not hold.
    assert violations and min(i for i, _ in violations) == 12


def test_lossy_checker_keeps_its_state_across_the_switch():
    # A trigger after every event leaves the true view in force throughout:
    # the run is the candidate's own, so nothing is rejected.
    assert _584_lossy_run(trigger=1000)["violations"] == []


def test_lossy_checker_rebases_only_when_asked():
    assert _lossy_run(2969)["rebased_at"] is not None
    assert _lossy_run(2969, rebase=False)["rebased_at"] is None


# BC3: opening under overlap (b1 only). References are written from the
# design's b1 inventory: per-surface closed outcomes, one-sided events and
# final fields, independently of the predicate's own tables.

B1_CLOSED = {"error": "ValueError", "message": "I/O operation on closed file."}
B1_SURFACE = {
    "next": {"stop": True},
    "close": {"ok": None},
    "open": {"error": "ValueError", "message": "Cannot reopen a closed file"},
    "seek_mark": {"skipped": True},
}
NOT_REACHED = {"skipped": True}
ARMED = ("fail_no_effect", "fail_consumed", "fail_sink_no_effect", "fail_sink_partial")


def _b1_closed_row(scenario, r: Row) -> Row:
    op = scenario["ops"][r.index]
    if r.name in ARMED:
        return r
    if r.name in ("overlap", "close_during", "cancel"):
        call = op["call"]["op"]
        return Row(r.key, B1_SURFACE.get(call, B1_CLOSED), NOT_REACHED)
    return Row(r.key, B1_SURFACE.get(r.name, B1_CLOSED))


def b1_o2(seed: int) -> list[Row]:
    """b1's trace for an ``overlap_close`` opening, from the design."""
    scenario = generate(seed)
    assert scenario["acquisition"]["fault"] == "overlap_close"
    cand = cand_rows(seed)
    source = scenario["source"]
    writer = scenario["mode"] in ("wb", "wt")
    custom_writer = writer and source["kind"] == "custom"
    acquire = cand[0]
    assert acquire.key == (-1, "acquire", 0)
    if custom_writer:
        acquire = dataclasses.replace(
            acquire,
            outcome={
                "error": "RuntimeError",
                "message": "gzip codec operation was invalidated by discard()",
            },
            second={
                "error": "RuntimeError",
                "message": "gzip encoder has an active operation",
            },
        )
    else:
        acquire = dataclasses.replace(acquire, second={"ok": None})
    split = next(
        (i + 1 for i, op in enumerate(scenario["ops"]) if op["op"] == "close"),
        len(scenario["ops"]),
    )
    rows = [acquire]
    for r in cand[1:-1]:
        if r.name == "cleanup_close":
            continue  # b1's handle is closed: no cleanup lands
        if custom_writer:
            if r.index >= split:
                rows.append(r)  # after-close probes: closed on both sides
            continue  # body never runs on b1
        rows.append(_b1_closed_row(scenario, r))
    final = copy.deepcopy(cand[-1].outcome)
    fields = final["ok"]
    if source["kind"] == "native":
        fields["fd_delta"] += 1
        if writer:
            fields.update(encoded(final_output(b"", False), "final"))
    elif custom_writer:
        header = raw_bytes(cand[0].parked["bytes"])
        fields.update(encoded(final_output(header, False), "final"))
        short = source.get("short")
        if source["closefd"] and short and short < len(header):
            fields["source_calls_after_close"] = -(-len(header) // short) - 1
    rows.append(dataclasses.replace(cand[-1], outcome=final))
    return rows


O2_SEEDS = {
    "native reader": 1755,
    "native writer": 1845,
    "custom reader": 2002,
    "text custom reader": 2988,
    "custom writer, closefd": 1196,
    "custom writer, short writes": 3838,
    "custom writer, closefd and short writes": 4458,
}


@pytest.mark.parametrize("seed", O2_SEEDS.values(), ids=O2_SEEDS.keys())
def test_bc3_o2_b1_shape_is_claimed(seed):
    passes(make_pair(seed, b1_o2(seed), reference="b1"), "BC3-OPENING")


def test_bc3_o2_cases_exercise_one_sided_events_and_short_writes():
    one_sided = compare(make_pair(1196, b1_o2(1196), reference="b1"))
    assert "('one-sided', (1, 'cleanup_close', 0))" in claims(one_sided, "BC3-OPENING")
    body = compare(make_pair(4458, b1_o2(4458), reference="b1"))
    claimed = claims(body, "BC3-OPENING")
    assert "('one-sided', (0, 'writelines', 0))" in claimed
    assert "('final', 'source_calls_after_close')" in claimed


O1_SEEDS = {"text custom": 4137, "custom binary": 2371, "native binary": 1996}


def b1_o1(seed: int) -> list[Row]:
    scenario = generate(seed)
    assert scenario["acquisition"]["fault"] == "overlap_open"
    rows = cand_rows(seed)
    native_binary = scenario["source"]["kind"] == "native" and scenario["mode"] == "rb"
    second = (
        {"ok": {"object": "AsyncGzipBinaryFile"}}
        if native_binary
        else {"error": "ValueError", "message": "File is already open"}
    )
    return edit(rows, (-1, "acquire", 0), second=second)


@pytest.mark.parametrize("seed", O1_SEEDS.values(), ids=O1_SEEDS.keys())
def test_bc3_o1_b1_shape_is_claimed(seed):
    passes(make_pair(seed, b1_o1(seed), reference="b1"), "BC3-OPENING")


def test_bc3_o1_rejects_another_b1_error():
    ref = edit(b1_o1(4137), (-1, "acquire", 0), second=B1_CLOSED)
    fails(make_pair(4137, ref, reference="b1"), "(-1, 'acquire', 0)")


def test_bc3_o1_rejects_an_fd_delta_difference():
    ref = b1_o1(1996)
    ref = edit_final(ref, fd_delta=ref[-1].outcome["ok"]["fd_delta"] + 1)
    fails(make_pair(1996, ref, reference="b1"), "'fd_delta'")


def test_bc3_o2_rejects_a_body_event_with_another_outcome():
    ref = b1_o2(2002)
    ref = edit(ref, (1, "peek", 0), outcome={"error": "ValueError", "message": "x"})
    fails(make_pair(2002, ref, reference="b1"), "(1, 'peek', 0)")


def test_bc3_o2_rejects_custom_writer_output_off_by_a_byte():
    cand = cand_rows(1196)
    header = raw_bytes(cand[0].parked["bytes"])
    ref = edit_final(b1_o2(1196), **encoded(final_output(header[:-1], False), "final"))
    fails(make_pair(1196, ref, reference="b1"), "'output_raw'")


@pytest.mark.parametrize("delta", [-1, 1])
def test_bc3_o2_rejects_an_off_by_one_short_write_count(delta):
    ref = b1_o2(4458)
    calls = ref[-1].outcome["ok"]["source_calls_after_close"] + delta
    ref = edit_final(ref, source_calls_after_close=calls)
    fails(make_pair(4458, ref, reference="b1"), "'source_calls_after_close'")


def test_bc3_o2_rejects_an_unlisted_one_sided_event():
    ref = b1_o2(2002)
    ref = ref[:-1] + [Row((5, "readline", 0), B1_CLOSED)] + ref[-1:]
    fails(make_pair(2002, ref, reference="b1"), "one-sided")


def test_bc3_o3_claims_no_fd_delta():
    rows = cand_rows(2598)
    ref = edit_final(rows, fd_delta=rows[-1].outcome["ok"]["fd_delta"] + 1)
    fails(make_pair(2598, ref, reference="b1"), "'fd_delta'")


def test_bc3_rejects_an_opening_under_async_with():
    scenario = generate(1755)
    scenario["acquisition"]["enter"] = "async_with"
    fails(make_pair(1755, b1_o2(1755), reference="b1", scenario=scenario))
