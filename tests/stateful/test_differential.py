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
    _losses,
    _wire_scenario,
    bc2_claim,
    bc2_request,
    bc2_trigger_only,
    compare,
    encoded,
    lossy_scenario,
    parse,
    raw_bytes,
    replay_scenario,
    shadow_scenario,
)
from generator import generate, member_spans, unb64
from interpreter import Event, Outcome, final_output, recorded_run
from model import (
    INJECTED_AT_END,
    INJECTED_CONSUMED,
    INJECTED_NO_EFFECT,
    Checker,
    LossyChecker,
    later_loss_kind,
    wire_view,
)
from oracle import engine_modules, wire_reference

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
    ref_info: dict[str, Any] | None = None,
) -> Pair:
    """A pair over the live candidate; ``scenario`` overrides only what the
    predicates see, ``run_scenario`` what the candidate also runs."""
    live_scenario, run = live(seed, run_scenario)
    rows = parse(run["trace"]) if cand is None else cand
    refs = parse(C0[str(seed)]) if ref is None else ref
    return Pair(
        scenario or live_scenario, reference, rows, refs, run, ENGINE, ref_info or {}
    )


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


def fails(pair: Pair, *unclaimed: str, lossy=None, shadow=None) -> None:
    result = compare(pair, lossy, shadow)
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


def test_bc2_judges_a_range_with_an_endpoint_inside_a_member_by_the_oracle():
    request = bc2_request_for(2486)
    a, b = request.lossy["lossy_range"]
    pair, _lossy = b1_emulated(2486)
    scenario = copy.deepcopy(pair.scenario)
    # Move the last member's end past the range's end: the same wire, now
    # with an endpoint inside a member, so the wire oracle judges the view.
    assert scenario["member_spans"][-1][1] == b
    scenario["member_spans"][-1][1] = b + 1
    moved = bc2_request(make_pair(2486, pair.ref, reference="b1", scenario=scenario))
    assert moved is not None
    assert moved.lossy["corruption"] == {"kind": "wire"}
    assert moved.lossy["lossy_range"] == [a, b]
    wire = unb64(scenario["wire"])
    assert unb64(moved.lossy["wire"]) == wire[:a] + wire[b:]
    # Over the same spliced wire, the oracle's view and the structural
    # view expect exactly the same bytes, guarantee and failure.
    oracle = Checker(moved.lossy, ENGINE).expect
    structural = Checker(request.lossy, ENGINE).expect
    assert (oracle.upper, oracle.lower, oracle.clean, oracle.failure) == (
        structural.upper,
        structural.lower,
        structural.clean,
        structural.failure,
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
    monkeypatch.setattr(
        interpreter.Gate, "seeked", lambda self, target, origin=None: None
    )
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


def b1_evidence(seed: int) -> dict[str, Any]:
    run = copy.deepcopy(B1[str(seed)])
    return {"seeks": run["seeks"], "origins": run["origins"]}


def b1_recorded(seed: int) -> tuple[Pair, dict[str, Any]]:
    run = copy.deepcopy(B1[str(seed)])
    pair = make_pair(
        seed, parse(run["trace"]), reference="b1", ref_info=b1_evidence(seed)
    )
    return pair, run["lossy"]


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


def test_bc2_l2_judges_a_range_with_an_endpoint_inside_a_member_by_the_oracle():
    pair, _lossy = b1_recorded(584)
    ref = edit(pair.ref, row(pair.ref, 4, "cancel").key, taken=[0, 100])
    request = bc2_request(make_pair(584, ref, reference="b1"))
    assert request is not None and request.clause == "L2"
    assert request.lossy["corruption"] == {"kind": "wire"}
    assert request.lossy["lossy_range"] == request.taken == [0, 100]
    wire = unb64(pair.scenario["wire"])
    assert unb64(request.lossy["wire"]) == wire[100:]


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


# E: an L2 trigger whose one-sided witness is the seed's only difference.


@pytest.mark.parametrize("seed", [169, 232])
def test_bc2_e_mid_member_trigger_goes_to_the_oracle_lossy_run(seed):
    # The oracle makes the mid-member range eligible: b1's recorded lossy
    # run over the spliced wire accepts it, and BC2 claims the trigger.
    pair, lossy = b1_recorded(seed)
    request = bc2_request(pair)
    assert request is not None and request.clause == "L2"
    assert request.lossy["corruption"] == {"kind": "wire"}
    assert lossy is not None and lossy["violations"] == []
    (key,) = pair.diffs
    assert key[1] == "cancel" and pair.ref_by_key[key].taken is not None
    result = compare(pair, lossy)
    assert result.ok, result.failures
    assert claims(result, "BC2-LOST-INPUT") == [repr(("event", key))]
    assert bc2_trigger_only(pair).events == set()


@pytest.mark.parametrize("seed", [169, 232])
def test_bc2_e_trigger_only_is_claimed_without_a_lossy_view(seed):
    # With no view at all (no member spans), the trigger-only clause still
    # claims the one-sided witness without a lossy run.
    pair, _lossy = b1_recorded(seed)
    scenario = copy.deepcopy(pair.scenario)
    del scenario["member_spans"]
    pair = make_pair(seed, pair.ref, reference="b1", scenario=scenario)
    assert bc2_request(pair) is None
    (key,) = pair.diffs
    result = compare(pair)
    assert result.ok, result.failures
    assert claims(result, "BC2-LOST-INPUT") == [repr(("event", key))]


def _e_pair(**edits) -> Pair:
    pair, _lossy = b1_recorded(169)
    ref, cand = pair.ref, pair.cand
    if "later" in edits:
        target = row(ref, 7, "read1")
        ref = edit(ref, target.key, outcome={"ok": {"bytes": "00"}})
    if "final" in edits:
        ref = edit_final(ref, fd_delta=1)
    if "cand_taken" in edits:
        cand = edit(cand, row(cand, 4, "cancel").key, taken=[147, 150])
    if "second" in edits:
        ref = edit(ref, row(ref, 4, "cancel").key, second={"ok": {"str": "x"}})
    if "eligible" in edits:
        ref = edit(ref, row(ref, 4, "cancel").key, taken=[0, 0])
    if "one_sided" in edits:
        ref = ref[:-1] + [Row((14, "cleanup_close", 0), {"ok": None}), ref[-1]]
    # Without member spans no lossy view exists, so E is the clause judging.
    scenario = copy.deepcopy(generate(169))
    if "eligible" not in edits:
        del scenario["member_spans"]
    if "custom" in edits:
        scenario["source"] = {
            "kind": "custom",
            "seekable": True,
            "checkpoint": False,
            "frames": [],
            "closefd": False,
        }
    return make_pair(169, ref, reference="b1", scenario=scenario, cand=cand)


@pytest.mark.parametrize(
    "change", ["later", "final", "cand_taken", "second", "one_sided", "custom"]
)
def test_bc2_e_rejects_anything_beyond_the_trigger_witness(change):
    fails(_e_pair(**{change: True}), "(4, 'cancel', 0)")


def test_bc2_e_defers_an_eligible_range_to_the_lossy_run():
    pair = _e_pair(eligible=True)
    assert bc2_request(pair) is not None
    fails(pair, "(4, 'cancel', 0)")


# F1: context exit aborts a native read parked in the executor.


@pytest.mark.parametrize("seed", [290, 1426])
def test_bc2_f1_aborted_native_read_is_claimed(seed):
    pair, lossy = b1_recorded(seed)
    (key,) = [k for k in pair.diffs if k[1] == "abort"]
    result = compare(pair, lossy)
    assert result.ok, result.failures
    assert repr(("event", key)) in claims(result, "BC2-LOST-INPUT")


def _f1_pair(**edits) -> Pair:
    pair, _lossy = b1_recorded(290)
    ref, cand = pair.ref, pair.cand
    key = row(ref, 1, "abort").key
    c, r = pair.cand_by_key[key], pair.ref_by_key[key]
    if "period" in edits:
        message = r.second["message"] + "."
        ref = edit(ref, key, second={"error": "OSError", "message": message})
    if "cand_untaken" in edits:
        cand = edit(cand, key, taken=None)
    if "ref_taken" in edits:
        ref = edit(ref, key, taken=c.taken)
    if "method" in edits:
        parked = dict(r.parked, method="seek")
        ref, cand = edit(ref, key, parked=parked), edit(cand, key, parked=parked)
    if "injected" in edits:
        ref = edit(ref, key, outcome={"error": "ValueError", "message": "x"})
    if "closed" in edits:
        ref = edit_final(ref, closed=False)
    if "cand_second" in edits:
        cand = edit(cand, key, second={"error": "OSError", "message": "x"})
    scenario = None
    if "custom" in edits:
        scenario = copy.deepcopy(generate(290))
        scenario["source"] = {
            "kind": "custom",
            "seekable": True,
            "checkpoint": False,
            "frames": [],
            "closefd": False,
        }
    return make_pair(290, ref, reference="b1", scenario=scenario, cand=cand)


@pytest.mark.parametrize(
    "change",
    [
        "period",
        "cand_untaken",
        "ref_taken",
        "method",
        "injected",
        "closed",
        "cand_second",
        "custom",
    ],
)
def test_bc2_f1_rejects_a_near_miss(change):
    fails(_f1_pair(**{change: True}), "(1, 'abort', 0)")


def _wire_len(seed: int) -> int:
    return len(unb64(generate(seed)["wire"]))


MALFORMED = [
    [],
    "0,21",
    [0],
    [0, 21, 30],
    [-1, 5],
    [21, 0],
    [True, 5],
    [0.0, 21],
    None,
]


@pytest.mark.parametrize("taken", MALFORMED + ["past-end"])
def test_bc2_f1_rejects_a_malformed_candidate_witness(taken):
    if taken == "past-end":
        taken = [0, _wire_len(290) + 1]
    pair, _lossy = b1_recorded(290)
    key = row(pair.ref, 1, "abort").key
    cand = edit(pair.cand, key, taken=taken)
    fails(make_pair(290, pair.ref, reference="b1", cand=cand), "(1, 'abort', 0)")


def test_bc2_f1_accepts_an_empty_witness_at_the_end_of_input():
    pair, _lossy = b1_recorded(290)
    key = row(pair.ref, 1, "abort").key
    end = _wire_len(290)
    cand = edit(pair.cand, key, taken=[end, end])
    passes(make_pair(290, pair.ref, reference="b1", cand=cand), "BC2-LOST-INPUT")


@pytest.mark.parametrize(
    "primary",
    [
        {"error": "ValueError", "message": "abort at 1"},
        {"error": "InjectedAbort", "message": "abort at 2"},
        {"error": "InjectedAbort", "message": "exit at 1"},
        {"ok": None},
    ],
)
def test_bc2_f1_requires_the_injected_abort_on_both_sides(primary):
    pair, _lossy = b1_recorded(290)
    key = row(pair.ref, 1, "abort").key
    ref = edit(pair.ref, key, outcome=primary)
    cand = edit(pair.cand, key, outcome=primary)
    fails(make_pair(290, ref, reference="b1", cand=cand), "(1, 'abort', 0)")


@pytest.mark.parametrize("taken", MALFORMED[:-1] + ["past-end"])
def test_bc2_l2_rejects_a_malformed_reference_witness(taken):
    if taken == "past-end":
        taken = [147, _wire_len(169) + 1]
    pair, _lossy = b1_recorded(169)
    ref = edit(pair.ref, row(pair.ref, 4, "cancel").key, taken=taken)
    pair = make_pair(169, ref, reference="b1")
    assert bc2_request(pair) is None
    fails(pair, "(4, 'cancel', 0)")


@pytest.mark.parametrize("taken", MALFORMED[:-1] + ["past-end"])
def test_bc2_l1_rejects_a_malformed_shared_witness(taken):
    if taken == "past-end":
        taken = [0, _wire_len(2060) + 1]
    pair, lossy = b1_emulated(2060)
    trigger = bc2_request(pair).trigger
    ref = edit(pair.ref, trigger, taken=taken)
    cand = edit(pair.cand, trigger, taken=taken)
    pair = make_pair(2060, ref, reference="b1", cand=cand)
    assert bc2_request(pair) is None
    assert not compare(pair, lossy).claims["BC2-LOST-INPUT"]


# F2: context exit aborts a custom-source read; b1 lets the call finish, and
# a shadow run of the call without the abort must reproduce b1's outcome.


@cache
def _shadow_run(seed: int) -> str:
    pair, _lossy = b1_recorded(seed)
    shadow = shadow_scenario(pair)
    assert shadow is not None
    return json.dumps(recorded_run(aiogzip, shadow, ENGINE, "observe"))


def b1_f2(seed: int) -> tuple[Pair, dict[str, Any]]:
    pair, _lossy = b1_recorded(seed)
    return pair, json.loads(_shadow_run(seed))


F2_SEEDS = {
    4: "the injected failure, with its taken witness",
    99: "a gzip validation error",
    621: "the decompressed-size limit",
}


@pytest.mark.parametrize("seed", sorted(F2_SEEDS))
def test_bc2_f2_shadow_reproduces_b1s_call_outcome(seed):
    pair, shadow = b1_f2(seed)
    (key,) = [k for k in pair.diffs if k[1] == "abort"]
    assert shadow["violations"] == []
    result = compare(pair, None, shadow)
    assert result.ok, result.failures
    assert claims(result, "BC2-LOST-INPUT") == [repr(("event", key))]


def test_bc2_f2_witness_case_carries_a_taken_range():
    pair, _shadow = b1_f2(4)
    assert row(pair.ref, 7, "abort").taken == [20, 23]


def test_bc2_f2_rejects_b1s_broken_refusal():
    # b1's close marks the stream broken under the parked call, which the
    # shadow (the call without the abort) cannot reproduce: unclaimed.
    pair, _lossy = b1_recorded(44)
    shadow = recorded_run(aiogzip, shadow_scenario(pair), ENGINE, "observe")
    fails(pair, "(2, 'abort', 0)", shadow=shadow)


def _f2_mutated(change: str) -> tuple[Pair, dict[str, Any] | None]:
    pair, shadow = b1_f2(4)
    key = row(pair.ref, 7, "abort").key
    ref, cand = pair.ref, pair.cand
    if change == "no-shadow":
        shadow = None
    elif change == "violation":
        shadow["violations"] = [[3, "injected"]]
    elif change == "prefix":
        trace = shadow["trace"]
        n = max(i for i, raw_row in enumerate(trace) if raw_row[0] < 7)
        trace[n][2] = {"error": "OSError", "message": "x"}
    elif change == "extra-row":
        trace = shadow["trace"]
        n = next(i for i, raw_row in enumerate(trace) if raw_row[0] == 7)
        trace.insert(n + 1, copy.deepcopy(trace[n]))
    elif change == "ref-taken":
        ref = edit(ref, key, taken=[20, 22])
    elif change == "ref-untaken":
        ref = edit(ref, key, taken=None)
    elif change == "ref-second":
        message = {"error": "OSError", "message": "injected source failure"}
        ref = edit(ref, key, second=message)
    elif change == "cand-second":
        cand = edit(cand, key, second={"error": "OSError", "message": "x"})
    elif change == "cand-taken":
        cand = edit(cand, key, taken=[20, 23])
    elif change == "parked":
        parked = {"via": "native", "method": "read", "bytes": None}
        ref, cand = edit(ref, key, parked=parked), edit(cand, key, parked=parked)
    elif change == "primary":
        primary = {"error": "InjectedAbort", "message": "exit at 7"}
        ref, cand = edit(ref, key, outcome=primary), edit(cand, key, outcome=primary)
    scenario = None
    if change == "native":
        scenario = copy.deepcopy(generate(4))
        scenario["source"] = {"kind": "native"}
    return make_pair(4, ref, reference="b1", scenario=scenario, cand=cand), shadow


@pytest.mark.parametrize(
    "change",
    [
        "no-shadow",
        "violation",
        "prefix",
        "extra-row",
        "ref-taken",
        "ref-untaken",
        "ref-second",
        "cand-second",
        "cand-taken",
        "parked",
        "primary",
        "native",
    ],
)
def test_bc2_f2_rejects_a_near_miss(change):
    pair, shadow = _f2_mutated(change)
    fails(pair, "(7, 'abort', 0)", shadow=shadow)


def test_bc2_f2_shadow_runs_the_call_without_the_abort():
    pair, _shadow = b1_f2(4)
    shadow = shadow_scenario(pair)
    ops = pair.scenario["ops"]
    assert shadow["ops"] == ops[:7] + [ops[7]["call"]]
    assert {k: v for k, v in shadow.items() if k != "ops"} == {
        k: v for k, v in pair.scenario.items() if k != "ops"
    }


# G custom: a cancelled custom seek0 is an L1 trigger with an empty range.


@pytest.mark.parametrize("seed", [1956, 2350])
def test_bc2_g_cancelled_custom_rewind_is_claimed(seed):
    pair, lossy = b1_recorded(seed)
    request = bc2_request(pair)
    assert request is not None and request.clause == "L1"
    assert pair.op(request.trigger)["call"]["op"] == "seek0"
    assert request.taken == [0, 0] and request.lossy is pair.scenario
    assert lossy["violations"] == []
    passes(pair, "BC2-LOST-INPUT", lossy)


def test_bc2_g_rejects_a_checkpoint_source():
    pair, lossy = b1_recorded(1956)
    scenario = copy.deepcopy(pair.scenario)
    scenario["source"]["checkpoint"] = True
    pair = make_pair(1956, pair.ref, reference="b1", scenario=scenario)
    assert bc2_request(pair) is None
    fails(pair, "(2, 'read', 0)", lossy=lossy)


def test_bc2_g_rejects_a_lossy_violation_after_the_rewind_cancel():
    pair, lossy = b1_recorded(1956)
    lossy["violations"] = [[2, "injected"]]
    fails(pair, "lossy model: op 2: injected", lossy=lossy)


# G native: a cancelled native seek0 moved the file without resetting b1's
# decoder, which replays the consumed prefix and then reads from offset 0.


@pytest.mark.parametrize("seed, origin", [(1620, 49), (242, 15015)])
def test_bc2_g_native_cancelled_rewind_is_claimed(seed, origin):
    pair, lossy = b1_recorded(seed)
    request = bc2_request(pair)
    assert request is not None and request.clause == "G"
    assert pair.op(request.trigger)["call"]["op"] == "seek0"
    assert request.taken == [origin, origin]
    wire = unb64(pair.scenario["wire"])
    assert request.lossy == replay_scenario(pair.scenario, origin, ENGINE)
    assert unb64(request.lossy["wire"]) == wire[:origin] + wire
    assert request.lossy["replayed_prefix"] == origin
    assert request.lossy["corruption"] == {"kind": "wire"}
    assert lossy["violations"] == []
    result = compare(pair, lossy)
    assert result.ok, result.failures
    assert set(pair.diffs) <= {eval(i)[1] for i in claims(result, "BC2-LOST-INPUT")}


def test_bc2_g_native_1620_replays_the_prefix_into_mid_member_state():
    # A fresh decode of the true wire inflates the whole member and fails
    # only its CRC; the replayed state fails inside the body, as b1 does
    # with "invalid distance too far back".
    pair, _lossy = b1_recorded(1620)
    wire = unb64(pair.scenario["wire"])
    module = engine_modules()[ENGINE]
    fresh = wire_reference(module, wire)
    assert (fresh["failure"], len(fresh["output"])) == ("trailer crc", 283)
    replayed = wire_reference(module, wire[:49] + wire)
    assert replayed["failure"] == "body invalid"
    assert replayed["validated"] == 0 and len(replayed["output"]) < 283
    (key,) = [k for k in pair.diffs if k[1] == "next"]
    assert "invalid distance too far back" in pair.ref_by_key[key].outcome["message"]


KEEP = object()


def _g_native(seeks=KEEP, origins=KEEP) -> Pair:
    pair, _lossy = b1_recorded(1620)
    info = b1_evidence(1620)
    assert info == {"seeks": [[2, [0]]], "origins": [[2, [[49, 0]]]]}
    if seeks is not KEEP:
        info["seeks"] = seeks
    if origins is not KEEP:
        info["origins"] = origins
    return make_pair(1620, pair.ref, reference="b1", ref_info=info)


def test_bc2_g_native_control_is_a_trigger():
    request = bc2_request(_g_native())
    assert request is not None and request.clause == "G"


@pytest.mark.parametrize(
    "seeks, origins",
    [
        (KEEP, []),  # no origin witnessed (the probe found the file closed)
        (KEEP, [[2, [[49, 0]]], [2, [[49, 0]]]]),  # two records at the event
        (KEEP, [[2, [[49, 0], [49, 0]]]]),  # two origins in one record
        (KEEP, [[3, [[49, 0]]]]),  # at another event
        (KEEP, [[2.0, [[49, 0]]]]),  # a float event index
        (KEEP, [[True, [[49, 0]]]]),
        (KEEP, [[2, [[49, 1]]]]),  # a seek not to 0
        (KEEP, [[2, [[49, True]]]]),
        (KEEP, [[2, [[49, False]]]]),
        (KEEP, [[2, [[49, 0.0]]]]),
        (KEEP, [[2, [[True, 0]]]]),
        (KEEP, [[2, [[49.0, 0]]]]),
        (KEEP, [[2, [["49", 0]]]]),
        (KEEP, [[2, [[49]]]]),
        (KEEP, [[2, [[49, 0, 0]]]]),
        (KEEP, [[2, [-1, 0]]]),
        (KEEP, [[2, [[-1, 0]]]]),
        (KEEP, [[2, [None]]]),
        (KEEP, [[2, ["49,0"]]]),
        (KEEP, [[2, None]]),  # a null payload
        (KEEP, [[2, "[[49, 0]]"]]),  # a string payload
        (KEEP, [[2]]),  # a short record
        (KEEP, [[2, [[49, 0]], 1]]),  # a long record
        (KEEP, [2, [[49, 0]]]),  # not a list of records
        (KEEP, [[2, [[49, 0]]], [5]]),  # a malformed record elsewhere
        (KEEP, None),
        (KEEP, "origins"),
        (KEEP, [[2, [[172, 0]]]]),  # the whole wire: b1 may have seen EOF
        (KEEP, [[2, [[173, 0]]]]),  # past the wire
        ([], KEEP),  # no completed seek
        ([[2, [0, 0]]], KEEP),
        ([[2, [5]]], KEEP),
        ([[2, [False]]], KEEP),  # a Boolean target
        ([[2, [0.0]]], KEEP),  # a float target
        ([[2.0, [0]]], KEEP),  # a float event index
        ([[2, None]], KEEP),
        ([[2, "0"]], KEEP),
        ([[2]], KEEP),
        ([[2, [0]], [7, None]], KEEP),
        ([2, [0]], KEEP),
        (None, KEEP),
    ],
)
def test_bc2_g_native_rejects_malformed_or_missing_evidence(seeks, origins):
    pair = _g_native(seeks, origins)
    request = bc2_request(pair)
    assert request is None or request.clause != "G"
    fails(pair, "unclaimed")


@pytest.mark.parametrize(
    "parked",
    [
        {"method": "seek", "bytes": None},  # no via
        {"via": "custom", "method": "seek", "bytes": None},
        {"via": "native", "method": "seek", "bytes": b64(b"x")},
        {"via": "native", "method": "seek"},
        {"via": "native", "method": "seek", "bytes": None, "extra": 1},
        {"via": "native", "method": "read", "bytes": None},
    ],
)
def test_bc2_g_native_requires_the_exact_parked_seek_witness(parked):
    pair, _lossy = b1_recorded(1620)
    key = row(pair.ref, 2, "cancel").key
    ref = edit(pair.ref, key, parked=parked)
    cand = edit(pair.cand, key, parked=parked)  # rows stay identical
    pair = make_pair(1620, ref, reference="b1", cand=cand, ref_info=b1_evidence(1620))
    assert pair.cand_by_key[key] == pair.ref_by_key[key]
    request = bc2_request(pair)
    assert request is None or request.clause != "G"


def test_bc2_g_native_rejects_a_cancel_whose_rows_differ():
    pair, lossy = b1_recorded(1620)
    key = row(pair.ref, 2, "cancel").key
    ref = edit(pair.ref, key, second={"ok": {"str": "x"}})
    pair = make_pair(1620, ref, reference="b1", ref_info=b1_evidence(1620))
    assert bc2_request(pair) is None


def test_bc2_g_native_rejects_a_lossy_violation():
    pair, lossy = b1_recorded(1620)
    lossy["violations"] = [[3, "injected"]]
    fails(pair, "lossy model: op 3: injected", lossy=lossy)


def test_bc2_g_native_view_differs_from_the_true_view():
    # The true view guarantees the whole member before its CRC failure; the
    # replayed view guarantees nothing.
    pair, _lossy = b1_recorded(1620)
    assert len(unb64(pair.scenario["wire"])) == 172
    request = bc2_request(pair)
    true_view = Checker(pair.scenario, ENGINE).expect
    replayed = Checker(request.lossy, ENGINE).expect
    assert true_view.lower == 283 and replayed.lower == 0
    assert len(replayed.upper) < len(true_view.upper)


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


@pytest.mark.parametrize(
    "shift, upper, clean",
    [
        # m1, then 0x1f, then m3: the next header's magic is wrong.
        ((1, 0), "ab", False),
        # m1, then the trailer's last ISIZE byte (zero padding), then m3.
        ((0, -1), "abef", True),
    ],
)
def test_lossy_scenario_judges_an_endpoint_inside_a_member_by_the_oracle(
    shift, upper, clean
):
    scenario = synthetic([b"ab", b"cd", b"ef"])
    a, b = middle(scenario)
    a, b = a + shift[0], b + shift[1]
    wire = unb64(scenario["wire"])
    lossy = lossy_scenario(scenario, a, b, ENGINE)
    assert lossy is not None
    assert lossy["corruption"] == {"kind": "wire"}
    assert lossy["lossy_range"] == [a, b]
    assert unb64(lossy["wire"]) == wire[:a] + wire[b:]
    assert lossy["payloads"] == [] and lossy["member_spans"] is None
    checker = Checker(lossy, ENGINE)
    reference = wire_reference(engine_modules()[ENGINE], wire[:a] + wire[b:])
    assert checker.expect.reference == reference
    assert checker.upper == upper and checker.expect.clean is clean
    assert lossy_scenario(scenario, *middle(scenario), ENGINE)["corruption"] == {
        "kind": "none"
    }


def test_wire_view_matches_the_structural_view_over_the_same_splice():
    for payloads in ([b"ab", b"cd", b"ef"], [b"ab\n" * 40, b"cd", b"ef\r\n" * 9]):
        scenario = synthetic(payloads)
        a, b = middle(scenario)
        wire = unb64(scenario["wire"])
        structural = Checker(lossy_scenario(scenario, a, b, ENGINE), ENGINE)
        view = _wire_scenario(scenario, wire[:a] + wire[b:], ENGINE, lossy_range=[a, b])
        oracle = Checker(view, ENGINE)
        assert (oracle.upper, oracle.lower, oracle.expect.clean) == (
            structural.upper,
            structural.lower,
            structural.expect.clean,
        )


def _limited(scenario, limit):
    scenario = copy.deepcopy(scenario)
    scenario["corruption"] = {"kind": "limit", "limit": limit}
    return scenario


def test_wire_view_composes_the_decompression_limit():
    scenario = synthetic([b"ab" * 10, b"cd" * 10, b"ef" * 10])
    a, b = middle(scenario)
    lossy = lossy_scenario(_limited(scenario, 25), a, b - 1, ENGINE)
    assert lossy["corruption"] == {"kind": "wire", "limit": 25}
    expect = Checker(lossy, ENGINE).expect
    assert (expect.upper, expect.lower, expect.failure) == (
        (b"ab" * 10 + b"ef" * 10)[:25],
        0,
        "limit",
    )
    lossy = lossy_scenario(_limited(scenario, 40), a, b - 1, ENGINE)
    expect = Checker(lossy, ENGINE).expect
    assert expect.clean and expect.upper == b"ab" * 10 + b"ef" * 10


@pytest.mark.parametrize(
    "limit, outcome",
    [
        (3, "limit"),  # the validated member alone passes the limit
        (4, None),  # between validated and inflated: not determined
        (6, None),
        (7, "validation"),  # the damaged member never reaches the limit
    ],
)
def test_wire_view_refuses_a_limit_inside_an_invalid_body(limit, outcome):
    # "abcd" validates; the damaged member inflates "xyz" then fails.
    scenario = synthetic([b"abcd", b"xyz"], damaged=b"xyz")
    wire = unb64(scenario["wire"])
    view = _wire_scenario(_limited(scenario, limit), wire, ENGINE, lossy_range=[0, 0])
    if outcome is None:
        assert view is None
    else:
        assert Checker(view, ENGINE).expect.failure == outcome


def test_wire_view_holds_text_before_the_first_undecodable_byte():
    scenario = synthetic([b"abcd", b"\xff"], damaged=b"\xffz")
    wire = unb64(scenario["wire"])
    view = _wire_scenario(scenario, wire, ENGINE, lossy_range=[0, 0])
    checker = Checker(view, ENGINE)
    assert checker.expect.upper == b"abcd" and checker.upper == "abcd"
    assert checker.expect.failure == "validation" and not checker.expect.clean
    # A clean wire view whose bytes are not text is refused outright.
    clean = synthetic([b"abcd", b"\xff"])
    wire = unb64(clean["wire"])
    assert _wire_scenario(clean, wire, ENGINE, lossy_range=[0, 0]) is None


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


# H: later losses per physical-source epoch. Seed 129 is a three-member
# binary read of a custom source without checkpoints (wire 108 bytes).


def _h_checker(trigger: int = 2, source=None, **lossy_fields) -> LossyChecker:
    scenario = generate(129)
    if source is not None:
        scenario = scenario | {"source": source}
    lossy = dict(scenario) | lossy_fields
    checker = LossyChecker(lossy, scenario, ENGINE, trigger, True, 0)
    # Past the trigger: on the trigger's lossy view, or (without one) as
    # after a rebase, on the true view with no epoch open.
    checker.lost = True
    checker.state = "lossy" if lossy_fields else "true"
    return checker


H_EVENTS = {
    "no_effect": ({"op": "read"}, Outcome("error", error=OSError(INJECTED_NO_EFFECT))),
    "at_end": ({"op": "read"}, Outcome("error", error=OSError(INJECTED_AT_END))),
    "consumed": ({"op": "read"}, Outcome("error", error=OSError(INJECTED_CONSUMED))),
    "cancel": ({"op": "cancel", "call": {"op": "read"}}, Outcome("cancelled")),
    "ok": ({"op": "seek0"}, Outcome("ok", 0)),
    # Effective calls: the primary call of an overlap or close_during, a
    # cancel that lost the race, and a seek's replay.
    "overlap": (
        {"op": "overlap", "call": {"op": "read"}, "second": {"op": "read"}},
        Outcome("error", error=OSError(INJECTED_CONSUMED)),
    ),
    "close_during": (
        {"op": "close_during", "call": {"op": "readline"}},
        Outcome("error", error=OSError(INJECTED_CONSUMED)),
    ),
    "cancel_lost": (
        {"op": "cancel", "call": {"op": "read"}},
        Outcome("error", error=OSError(INJECTED_CONSUMED)),
    ),
    "seek": (
        {"op": "seek_abs", "target": 3},
        Outcome("error", error=OSError(INJECTED_CONSUMED)),
    ),
    # The concurrent second call's failure is never the loss.
    "overlap_second": (
        {"op": "overlap", "call": {"op": "read"}, "second": {"op": "read"}},
        Outcome("ok", b""),
    ),
}
SECOND = Outcome("error", error=OSError(INJECTED_CONSUMED))


def _at(checker: LossyChecker, index: int, taken=None, seeks=None, kind="no_effect"):
    op, outcome = H_EVENTS[kind]
    second = SECOND if kind == "overlap_second" else None
    checker.index = index
    checker.event = Event(index, op, outcome, second, taken=taken, seeks=seeks)
    return checker


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("overlap", (True, [38, 66])),
        ("close_during", (True, [38, 66])),
        ("cancel_lost", (True, [38, 66])),
        ("seek", (True, [38, 66])),
        ("overlap_second", (False, None)),
    ],
)
def test_h_later_loss_classifies_the_effective_call(kind, expected):
    checker = _at(_h_checker(), 5, [38, 66], kind=kind)
    assert checker.later_loss("consumed_failure") == expected


def _expect_without(*ranges: list[int]):
    scenario = generate(129)
    wire, spliced, at = unb64(scenario["wire"]), b"", 0
    for a, b in ranges:
        spliced, at = spliced + wire[at:a], b
    view = wire_view(scenario, spliced + wire[at:], ENGINE, lossy_ranges=list(ranges))
    return Checker(view, ENGINE).expect


@pytest.mark.parametrize(
    ("transition", "taken", "expected"),
    [
        ("uncertain_failure", [38, 66], (True, [38, 66])),
        ("consumed_failure", [0, 0], (True, [0, 0])),
        ("cancel_uncertain", [108, 108], (True, [108, 108])),
        ("cancel_uncertain", None, (True, None)),
        # Without a witness the candidate's semantics stand.
        ("uncertain_failure", None, (False, None)),
        ("consumed_failure", None, (False, None)),
        ("no_effect_failure", [0, 38], (False, None)),
        # Malformed or impossible ranges are no witness.
        ("uncertain_failure", [38, 109], (False, None)),
        ("uncertain_failure", [66, 38], (False, None)),
        ("uncertain_failure", [-1, 38], (False, None)),
        ("uncertain_failure", [True, 38], (False, None)),
        ("uncertain_failure", [0.0, 38], (False, None)),
        ("uncertain_failure", [0, 38, 66], (False, None)),
        ("uncertain_failure", (0, 38), (False, None)),
    ],
)
def test_h_later_loss_needs_its_own_witness(transition, taken, expected):
    kind = {
        "uncertain_failure": "no_effect",
        "no_effect_failure": "no_effect",
        "consumed_failure": "consumed",
        "cancel_uncertain": "cancel",
    }[transition]
    assert _at(_h_checker(), 5, taken, kind=kind).later_loss(transition) == expected


NATIVE = {"kind": "native"}
CHECKPOINT = generate(129)["source"] | {"checkpoint": True}


@pytest.mark.parametrize(
    ("source", "taken", "expected"),
    [
        (NATIVE, [0, 38], (True, [0, 38])),
        # A native cancel settled without effect loses input only with a
        # nonempty range.
        (NATIVE, [5, 5], (False, None)),
        (NATIVE, None, (False, None)),
        (NATIVE, [0, 109], (False, None)),
        # A checkpoint source restores the cancelled read: no loss.
        (CHECKPOINT, [0, 38], (False, None)),
        (CHECKPOINT, None, (False, None)),
    ],
)
def test_h_a_settled_cancel_is_a_loss_only_on_a_native_source(source, taken, expected):
    checker = _at(_h_checker(source=source), 5, taken, kind="cancel")
    assert checker.later_loss("cancel_no_effect") == expected


def test_h_later_loss_is_only_after_the_trigger():
    checker = _h_checker()
    assert _at(checker, 2, [0, 38]).later_loss("uncertain_failure") == (False, None)
    fresh = LossyChecker(generate(129), generate(129), ENGINE, 2, True, 0)
    assert _at(fresh, 1, [0, 38]).later_loss("uncertain_failure") == (False, None)


def test_h_an_empty_cancel_loss_needs_a_custom_source_without_checkpoints():
    scenario = generate(129)
    for source in ({"kind": "native"}, scenario["source"] | {"checkpoint": True}):
        true = scenario | {"source": source}
        checker = LossyChecker(true, true, ENGINE, 2, True, 0)
        checker.lost = True
        assert _at(checker, 5, kind="cancel").later_loss("cancel_uncertain") == (
            False,
            None,
        )


def test_h_a_loss_opens_an_epoch_on_the_oracle_view():
    checker = _at(_h_checker(), 5, [38, 66])
    checker.transition("uncertain_failure")
    assert checker.view == "lossy" and checker.losses == [[5, [38, 66]]]
    assert checker.deleted == [[38, 66]] and checker.epoch_start == 38
    assert checker.expect == _expect_without([38, 66])
    assert checker.violations == []


def test_h_losses_accumulate_in_wire_order():
    checker = _at(_h_checker(), 5, [0, 10])
    checker.transition("uncertain_failure")
    _at(checker, 7, [38, 66], kind="consumed").transition("consumed_failure")
    assert checker.deleted == [[0, 10], [38, 66]] and checker.epoch_start == 0
    assert checker.expect == _expect_without([0, 10], [38, 66])
    assert checker.violations == []


def test_h_a_loss_before_the_epochs_last_is_a_violation():
    checker = _at(_h_checker(), 5, [38, 66])
    checker.transition("uncertain_failure")
    _at(checker, 7, [60, 70]).transition("uncertain_failure")
    assert checker.violations and checker.violations[0].startswith("op 7:")


def test_h_extends_the_trigger_range():
    checker = _h_checker(lossy_range=[0, 10])
    assert checker.view == "lossy" and checker.deleted == [[0, 10]]
    _at(checker, 5, [38, 66]).transition("uncertain_failure")
    assert checker.deleted == [[0, 10], [38, 66]]
    assert checker.expect == _expect_without([0, 10], [38, 66])


def test_h_a_loss_over_a_replayed_prefix_is_not_modeled():
    checker = _h_checker(replayed_prefix=38)
    assert checker.view == "lossy" and checker.deleted is None
    _at(checker, 5, [40, 50]).transition("uncertain_failure")
    assert checker.violations


def test_h_the_trigger_epoch_ends_only_over_its_lost_start():
    checker = _h_checker(lossy_range=[0, 10])
    _at(checker, 5, [38, 66]).transition("uncertain_failure")
    _at(checker, 6, seeks=[38], kind="ok").transition("rewind_ok")
    assert checker.view == "lossy" and checker.rebases == []
    _at(checker, 7, seeks=[0], kind="ok").transition("rewind_ok")
    assert checker.view == "true" and checker.rebases == [7]


def test_h_an_empty_loss_leaves_the_view():
    checker = _at(_h_checker(), 5, [38, 38])
    expect, health = checker.expect, checker.health
    checker.transition("uncertain_failure")
    assert checker.losses == [[5, [38, 38]]] and checker.view == "true"
    assert checker.expect is expect and checker.health == health


@pytest.mark.parametrize(("target", "rebased"), [(38, True), (0, True), (39, False)])
def test_h_a_physical_rewind_over_the_epoch_ends_it(target, rebased):
    checker = _at(_h_checker(), 5, [38, 66])
    checker.transition("uncertain_failure")
    _at(checker, 6, seeks=[target], kind="ok").transition("rewind_ok")
    assert (checker.view == "true") is rebased
    assert checker.rebases == ([6] if rebased else [])
    if rebased:
        assert checker.deleted == [] and checker.expect == checker.true.expect
        # The next loss opens a new epoch.
        _at(checker, 8, [66, 108]).transition("uncertain_failure")
        assert checker.deleted == [[66, 108]] and checker.epoch_start == 66
        assert checker.rebased_at == 6


@pytest.mark.parametrize(
    "losses",
    [
        "x",
        [[5]],
        [(5, None)],
        [[True, None]],
        [[5, [1]]],
        [[5, [2, 1]]],
        [[5, [-1, 1]]],
        [[5, [0, 1.0]]],
        [[5, None], [5, None]],
        [[7, None], [5, None]],
    ],
)
def test_h_malformed_losses_claim_nothing(losses):
    pair, lossy = b1_recorded(169)
    request = bc2_request(pair)
    assert bc2_claim(pair, request, lossy, set()).events
    lossy["losses"] = losses
    assert bc2_claim(pair, request, lossy, set()).events == set()


def test_h_a_loss_the_oracle_refuses_is_a_violation(monkeypatch):
    import model

    monkeypatch.setattr(model, "wire_view", lambda *args, **kwargs: None)
    checker = _at(_h_checker(), 5, [38, 66])
    checker.transition("uncertain_failure")
    assert checker.violations == ["op 5: no model for the losses [[38, 66]]"]


# H on recorded b1 runs: each later loss row, and the rows after it until
# the models agree again, are BC2's.

H_SEEDS = {
    # Pre-rebase: the loss extends the trigger's epoch.
    58: [[4, [0, 21]]],
    3626: [[3, [0, 1]], [5, [1, 8]]],
    5782: [[9, [236677, 236684]]],
    # Post-rebase: a cancelled native read opens a new epoch (L2-shaped).
    53: [[10, [0, 64]]],
    2473: [[9, [0, 64]]],
    # Empty cancelled custom reads: no view change.
    2228: [[1, None], [9, None]],
    # An overlap's primary read consumed.
    1124: [[5, [0, 22]]],
    1893: [[3, [0, 4096]]],
    # A seek's replay consumed: relative, nonseekable forward, and a
    # seek_mark that rebases first and opens a new epoch at the same event.
    363: [[8, [0, 512]]],
    4358: [[7, [10000, 10010]]],
    4533: [[6, [0, 3]]],
}


@pytest.mark.parametrize("seed", sorted(H_SEEDS))
def test_h_recorded_later_losses_are_claimed(seed):
    pair, lossy = b1_recorded(seed)
    assert lossy["losses"] == H_SEEDS[seed] and lossy["violations"] == []
    result = compare(pair, lossy)
    assert result.ok, result.failures
    assert claims(result, "BC2-LOST-INPUT")


@pytest.mark.parametrize(
    ("seed", "row"),
    [
        (53, "(10, 'cancel', 0)"),
        (2473, "(9, 'cancel', 0)"),
    ],
)
def test_h_recorded_loss_rows_need_the_loss_record(seed, row):
    # Post-rebase losses only: a pre-rebase loss (58) lies in the trigger's
    # span, which never converges; there H is the model's view (unit tests).
    pair, lossy = b1_recorded(seed)
    bc2 = claims(compare(pair, lossy), "BC2-LOST-INPUT")
    assert any(row in item for item in bc2)
    lossy["losses"] = []
    fails(pair, row, lossy=lossy)


def test_h_4533_rebases_and_reopens_at_the_seek():
    _pair, lossy = b1_recorded(4533)
    assert lossy["rebases"] == [6] and lossy["losses"] == [[6, [0, 3]]]


def test_h_53_rebases_before_its_second_epoch():
    _pair, lossy = b1_recorded(53)
    assert lossy["rebases"] == [9] and lossy["rebased_at"] == 9
    m = next(n for n, r in enumerate(parse(lossy["trace"])) if r.index == 10)
    assert lossy["states"][m - 1][2] == "true" and lossy["states"][m][2] == "lossy"


def _h_claim(seed: int, mutate) -> set:
    pair, lossy = b1_recorded(seed)
    request = bc2_request(pair)
    assert bc2_claim(pair, request, lossy, set()).events
    mutate(pair, request, lossy)
    return bc2_claim(pair, request, lossy, set()).events


def _set_losses(value):
    def mutate(pair, request, lossy):
        lossy["losses"] = value(pair, request) if callable(value) else value

    return mutate


@pytest.mark.parametrize(
    "mutate",
    [
        # The record must exist.
        lambda pair, request, lossy: lossy.pop("losses"),
        # Indices must be single b1 rows after the trigger.
        _set_losses([[-1, [0, 64]]]),
        _set_losses(lambda pair, request: [[request.trigger[0], [0, 64]]]),
        _set_losses(lambda pair, request: [[request.trigger[0] - 1, [0, 64]]]),
        _set_losses([[999, [0, 64]]]),
        # A range must be that row's taken, within the true wire.
        _set_losses([[10, [0, 63]]]),
        _set_losses([[10, [1, 64]]]),
        _set_losses(
            lambda pair, request: [[10, [0, len(unb64(pair.scenario["wire"])) + 1]]]
        ),
        # An empty loss must be a custom cancelled read without checkpoints.
        _set_losses([[10, None]]),
        # A loss at a row without a taken witness.
        _set_losses([[11, [0, 0]]]),
    ],
)
def test_h_losses_must_be_bound_to_b1s_native_rows(mutate):
    assert _h_claim(53, mutate) == set()


def test_h_53_losses_record_is_its_witness():
    pair, _lossy = b1_recorded(53)
    assert row(pair.ref, 10, "cancel").taken == [0, 64]


def _non_cancel_after(pair, request):
    return next(
        r.index
        for r in pair.ref
        if r.index > request.trigger[0] and r.name != "cancel" and r.index >= 0
    )


@pytest.mark.parametrize(
    "mutate",
    [
        # None on a row that is not a cancelled read.
        _set_losses(lambda pair, request: [[_non_cancel_after(pair, request), None]]),
        # A range on a cancelled read that has no taken witness.
        _set_losses([[1, [0, 0]], [9, None]]),
        # The empty-loss shape needs a custom source without checkpoints.
        lambda pair, request, lossy: pair.scenario["source"].update(checkpoint=True),
    ],
)
def test_h_empty_losses_must_be_custom_cancelled_reads(mutate):
    assert _h_claim(2228, mutate) == set()


# The loss classification shared by the lossy model and the claim's check.

CUSTOM = generate(129)["source"]


READ = {"op": "read", "n": -1}
SEEK = {"op": "seek_abs", "target": 3}


@pytest.mark.parametrize(
    ("op", "kind", "message", "source", "expected"),
    [
        # A cancelled cancel: cancel semantics.
        ({"op": "cancel", "call": READ}, "cancelled", None, NATIVE, "cancel_no_effect"),
        ({"op": "cancel", "call": READ}, "cancelled", None, CUSTOM, "cancel_uncertain"),
        ({"op": "cancel", "call": READ}, "cancelled", None, CHECKPOINT, None),
        # Cancellation lost the race: the call's own outcome.
        (
            {"op": "cancel", "call": READ},
            "error",
            INJECTED_CONSUMED,
            CUSTOM,
            "consumed_failure",
        ),
        ({"op": "cancel", "call": READ}, "error", INJECTED_CONSUMED, NATIVE, None),
        ({"op": "cancel", "call": READ}, "ok", None, NATIVE, None),
        ({"op": "cancel"}, "error", INJECTED_CONSUMED, CUSTOM, None),
        # Direct read calls.
        (READ, "error", INJECTED_NO_EFFECT, CUSTOM, "uncertain_failure"),
        ({"op": "next"}, "error", INJECTED_AT_END, CUSTOM, "uncertain_failure"),
        ({"op": "readinto"}, "error", INJECTED_CONSUMED, CUSTOM, "consumed_failure"),
        (
            {"op": "readinto"},
            "error",
            INJECTED_CONSUMED,
            CHECKPOINT,
            "consumed_failure",
        ),
        # A checkpoint restores a no-effect or at-end failure.
        ({"op": "readinto"}, "error", INJECTED_NO_EFFECT, CHECKPOINT, None),
        ({"op": "readinto"}, "error", INJECTED_AT_END, CHECKPOINT, None),
        # Direct seeks (a forward replay or rewind that reads).
        (SEEK, "error", INJECTED_CONSUMED, CUSTOM, "consumed_failure"),
        ({"op": "seek0"}, "error", INJECTED_CONSUMED, CHECKPOINT, "consumed_failure"),
        ({"op": "seek_mark"}, "error", INJECTED_NO_EFFECT, CUSTOM, "uncertain_failure"),
        ({"op": "seek_back"}, "error", INJECTED_NO_EFFECT, CHECKPOINT, None),
        (SEEK, "error", INJECTED_CONSUMED, NATIVE, None),
        # Overlap and close_during: the primary call's outcome only.
        (
            {"op": "overlap", "call": READ, "second": READ},
            "error",
            INJECTED_CONSUMED,
            CUSTOM,
            "consumed_failure",
        ),
        (
            {"op": "close_during", "call": {"op": "readline"}},
            "error",
            INJECTED_NO_EFFECT,
            CUSTOM,
            "uncertain_failure",
        ),
        ({"op": "overlap", "call": READ}, "ok", None, CUSTOM, None),
        (
            {"op": "overlap", "call": {"op": "tell"}},
            "error",
            INJECTED_CONSUMED,
            CUSTOM,
            None,
        ),
        ({"op": "overlap"}, "error", INJECTED_CONSUMED, CUSTOM, None),
        (
            {"op": "close_during", "call": READ},
            "error",
            INJECTED_CONSUMED,
            NATIVE,
            None,
        ),
        # Native failures, other calls, other outcomes, other messages.
        (READ, "error", INJECTED_CONSUMED, NATIVE, None),
        ({"op": "tell"}, "error", INJECTED_CONSUMED, CUSTOM, None),
        ({"op": "close"}, "error", INJECTED_CONSUMED, CUSTOM, None),
        (READ, "cancelled", None, CUSTOM, None),
        (READ, "ok", None, CUSTOM, None),
        (READ, "error", "boom", CUSTOM, None),
        (READ, "error", None, CUSTOM, None),
    ],
)
def test_h_later_loss_kind(op, kind, message, source, expected):
    assert later_loss_kind(op, kind, message, source) == expected


def test_h_a_checkpointed_no_effect_failure_is_no_loss():
    # Seed 1598 (checkpoint source): after the trigger (op 1's consumed
    # close_during), op 4's readinto fails without effect, with an empty
    # taken witness. The model records no loss, and a record naming one
    # claims nothing.
    pair, lossy = b1_recorded(1598)
    readinto = row(pair.ref, 4, "readinto")
    assert readinto.taken == [4096, 4096] and lossy["losses"] == []
    _set_losses([[4, [4096, 4096]]])(pair, None, lossy)
    request = bc2_request(pair)
    assert request.trigger[0] == 1
    assert _losses(pair, request, lossy) is None
    assert bc2_claim(pair, request, lossy, set()).events == set()


def _with_row(pair, index: int, **changes):
    pair.ref = [
        dataclasses.replace(r, **changes) if r.index == index else r for r in pair.ref
    ]


def _with_source(pair, **changes):
    pair.scenario = pair.scenario | {"source": pair.scenario["source"] | changes}


@pytest.mark.parametrize(
    ("seed", "mutate", "bound"),
    [
        # 58: op 4's next consumed [0, 21] on a custom source without
        # checkpoints.
        (58, lambda pair: None, [4]),
        (58, lambda pair: _with_source(pair, checkpoint=True), [4]),
        # A seek failing the same way is a loss too.
        (58, lambda pair: _with_row(pair, 4, key=(4, "seek0", 0)), [4]),
        (58, lambda pair: _with_row(pair, 4, key=(4, "tell", 0)), None),
        (58, lambda pair: _with_row(pair, 4, key=(4, "overlap", 0)), None),
        (58, lambda pair: _with_row(pair, 4, outcome={"cancelled": True}), None),
        (58, lambda pair: _with_row(pair, 4, outcome={"ok": None}), None),
        (
            58,
            lambda pair: _with_row(
                pair, 4, outcome={"error": "OSError", "message": "boom"}
            ),
            None,
        ),
        (
            58,
            lambda pair: _with_row(
                pair, 4, outcome={"error": "OSError", "message": INJECTED_NO_EFFECT}
            ),
            [4],
        ),
        (
            58,
            lambda pair: (
                _with_row(
                    pair,
                    4,
                    outcome={"error": "OSError", "message": INJECTED_NO_EFFECT},
                ),
                _with_source(pair, checkpoint=True),
            ),
            None,
        ),
        (58, lambda pair: _with_source(pair, kind="native"), None),
        # 53: op 10's native cancel took [0, 64].
        (53, lambda pair: None, [10]),
        (53, lambda pair: _with_row(pair, 10, key=(10, "read", 0)), None),
        (
            53,
            lambda pair: _with_row(
                pair, 10, outcome={"error": "OSError", "message": INJECTED_CONSUMED}
            ),
            None,
        ),
        (
            53,
            lambda pair: _with_source(
                pair, kind="custom", seekable=True, checkpoint=True, frames=[]
            ),
            None,
        ),
        # 1124: op 5's overlap; its primary read consumed [0, 22].
        (1124, lambda pair: None, [5]),
        (
            1124,
            lambda pair: _with_row(
                pair,
                5,
                outcome={"ok": {"str": ""}},
                second={"error": "OSError", "message": INJECTED_CONSUMED},
            ),
            None,
        ),
        (1124, lambda pair: _with_source(pair, kind="native"), None),
        # 4358: op 7's seek_abs on a nonseekable source consumed [10000, 10010].
        (4358, lambda pair: None, [7]),
        (4358, lambda pair: _with_row(pair, 7, key=(7, "tell", 0)), None),
        # 2228: empty cancelled reads at 1 and 9, custom without checkpoints.
        (2228, lambda pair: None, [1, 9]),
        (2228, lambda pair: _with_row(pair, 9, outcome={"ok": None}), None),
    ],
)
def test_h_losses_are_bound_to_rows_that_can_lose(seed, mutate, bound):
    pair, lossy = b1_recorded(seed)
    request = bc2_request(pair)
    mutate(pair)
    assert _losses(pair, request, lossy) == bound
