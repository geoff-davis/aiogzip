#!/usr/bin/env python3
"""C0 and b1 differential comparison for the WP10 stateful harness.

The candidate, C0 and b1 each replay the same scenario JSON in their own
subprocess (``interpreter.py``), importing aiogzip from a clean source root.
This module compares the symbolic traces event by event. Every difference
must be claimed by exactly one predicate named for a ledger exception;
everything unclaimed must match. See "Differential comparison" in
plans/design/v2.0.0b2-wp10-qualification.md, which this implements:

- events align by key (scenario index, op name, occurrence); the keys both
  traces share must appear in the same order, and a key on one side only is
  a one-sided event that only ``BC3-OPENING`` clause O2 may claim;
- event-specific predicates claim first (``BC3-OPENING``,
  ``BC7-TEXT-SALVAGE``, ``BC8-WRITER-ABORT``, ``BC9-REWIND-ABORT``), and an
  item two of them claim fails the seed;
- ``BC2-LOST-INPUT`` then claims the remaining differing events in its span,
  subject to the lossy model run over b1's replay (a second subprocess).

``C0-WP8-FAILED-ABORT`` has no predicate: it needs an abort whose underlying
close fails, which the generator never produces, so any such difference
stays unclaimed and fails the seed.
"""

from __future__ import annotations

import argparse
import base64
import codecs
import concurrent.futures
import copy
import dataclasses
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from generator import generate, unb64  # noqa: E402
from interpreter import Event, Outcome, final_output, symbolic  # noqa: E402
from model import (  # noqa: E402
    Checker,
    later_loss_kind,
    loss_witness,
    text_model,
    wire_view,
)
from oracle import engine_modules, raw_reference, wire_reference  # noqa: E402

READ_ABORTED = "read aborted because the gzip file was closed while the call was active"
READ_BROKEN = "read stream is broken"
B1_READ_CLOSED = {
    "error": "OSError",
    "message": "Error reading from file: I/O operation on closed file",
}
B1_READ_BROKEN_SEEK0 = {
    "error": "OSError",
    "message": "read stream is broken after failed or cancelled decompression; "
    "seek to 0 to recover, or close and reopen the gzip file",
}
WRITE_BROKEN = "write stream is broken"
CLOSED = {"error": "ValueError", "message": "I/O operation on closed file."}
REOPEN = {"error": "ValueError", "message": "Cannot reopen a closed file"}
ALREADY_OPEN = {"error": "ValueError", "message": "File is already open"}
ENCODER_ACTIVE = {
    "error": "RuntimeError",
    "message": "gzip encoder has an active operation",
}
INVALIDATED = {
    "error": "RuntimeError",
    "message": "gzip codec operation was invalidated by discard()",
}
OPEN_IN_PROGRESS = {
    "error": "ConcurrentOperationError",
    "message": "open() is already in progress",
}
CLOSE_DURING_OPEN = {
    "error": "ConcurrentOperationError",
    "message": "close() called while open() is in progress",
}
READ_CALLS = {"read", "read1", "readinto", "peek", "readline", "readlines", "next"}
READ_CALLS |= {"buffer_read"}

PREDICATES = (
    "BC2-LOST-INPUT",
    "BC3-OPENING",
    "BC7-TEXT-SALVAGE",
    "BC8-WRITER-ABORT",
    "BC9-REWIND-ABORT",
)
APPLIES = {
    "c0": ("BC7-TEXT-SALVAGE", "BC8-WRITER-ABORT", "BC9-REWIND-ABORT"),
    "b1": PREDICATES,
}


# Traces


@dataclasses.dataclass(frozen=True)
class Row:
    key: tuple[int, str, int]
    outcome: Any
    second: Any = None
    parked: dict[str, Any] | None = None
    taken: list[int] | None = None
    pulled: list[int] | None = None

    @property
    def index(self) -> int:
        return self.key[0]

    @property
    def name(self) -> str:
        return self.key[1]

    def without_taken(self) -> Row:
        return dataclasses.replace(self, taken=None)


def parse(trace: list[list[Any]]) -> list[Row]:
    rows, seen = [], {}
    for raw in trace:
        index, name, outcome, *extras = raw
        second = parked = taken = pulled = None
        for extra in extras:
            if isinstance(extra, dict) and extra.keys() == {"parked"}:
                # Strings in the parked record are symbolically encoded.
                parked = {
                    field: item["str"]
                    if isinstance(item, dict) and item.keys() == {"str"}
                    else item
                    for field, item in extra["parked"].items()
                }
            elif isinstance(extra, dict) and extra.keys() == {"taken"}:
                taken = extra["taken"]
            elif isinstance(extra, dict) and extra.keys() == {"pulled"}:
                pulled = extra["pulled"]
            else:
                second = extra
        count = seen.get((index, name), 0)
        seen[(index, name)] = count + 1
        rows.append(Row((index, name, count), outcome, second, parked, taken, pulled))
    return rows


def raw_bytes(item: Any) -> bytes | None:
    """Bytes from a symbolic value, or None when only a digest was kept."""
    if isinstance(item, dict) and "base64" in item:
        return base64.b64decode(item["base64"])
    if isinstance(item, dict) and "bytes" in item:
        return bytes.fromhex(item["bytes"])
    return None


def encoded(value: Any, op: str = "read") -> Any:
    """The symbolic encoding the interpreter gives ``value`` in an ok outcome."""
    row = symbolic([Event(0, {"op": op}, Outcome("ok", value))])[0]
    return row[2]["ok"]


def is_error(outcome: Any, kind: str | None = None, contains: str = "") -> bool:
    return (
        isinstance(outcome, dict)
        and "error" in outcome
        and (kind is None or outcome["error"] == kind)
        and contains in outcome.get("message", "")
    )


# Claims and comparison


@dataclasses.dataclass
class Claim:
    events: set[tuple[int, str, int]] = dataclasses.field(default_factory=set)
    fields: set[str] = dataclasses.field(default_factory=set)
    one_sided: set[tuple[int, str, int]] = dataclasses.field(default_factory=set)

    def items(self) -> set[tuple[str, Any]]:
        return (
            {("event", k) for k in self.events}
            | {("final", f) for f in self.fields}
            | {("one-sided", k) for k in self.one_sided}
        )


@dataclasses.dataclass
class Pair:
    """One seed's candidate and reference traces, and the candidate's model."""

    scenario: dict[str, Any]
    reference: str  # "c0" or "b1"
    cand: list[Row]
    ref: list[Row]
    cand_info: dict[str, Any]
    engine: str
    # The reference run record's evidence (``seeks``, ``origins``), if any.
    ref_info: dict[str, Any] = dataclasses.field(default_factory=dict)

    def __post_init__(self) -> None:
        self.cand_by_key = {row.key: row for row in self.cand}
        self.ref_by_key = {row.key: row for row in self.ref}
        self.cand_order = {row.key: n for n, row in enumerate(self.cand)}
        common = self.cand_by_key.keys() & self.ref_by_key.keys()
        self.cand_only = self.cand_by_key.keys() - common
        self.ref_only = self.ref_by_key.keys() - common
        self.order_ok = [r.key for r in self.cand if r.key in common] == [
            r.key for r in self.ref if r.key in common
        ]
        final = (len(self.ops) + 2, "final", 0)
        self.cand_final = self._final(self.cand_by_key.get(final))
        self.ref_final = self._final(self.ref_by_key.get(final))
        self.diffs = {
            k
            for k in common
            if k != final and self.cand_by_key[k] != self.ref_by_key[k]
        }
        fields = self.cand_final.keys() | self.ref_final.keys()
        self.final_diffs = {
            f for f in fields if self.cand_final.get(f) != self.ref_final.get(f)
        }

    @staticmethod
    def _final(row: Row | None) -> dict[str, Any]:
        if row is None or not isinstance(row.outcome, dict):
            return {}
        return row.outcome.get("ok") or {}

    @property
    def ops(self) -> list[dict[str, Any]]:
        return self.scenario["ops"]

    @property
    def mode(self) -> str:
        return self.scenario["mode"]

    def op(self, key: tuple[int, str, int]) -> dict[str, Any]:
        index = key[0]
        if 0 <= index < len(self.ops) and self.ops[index]["op"] == key[1]:
            return self.ops[index]
        return {"op": key[1]}

    def health_before(self, key: tuple[int, str, int]) -> str | None:
        n = self.cand_order.get(key)
        health = self.cand_info.get("health") or []
        return health[n][0] if n is not None and n < len(health) else None

    def health_after(self, key: tuple[int, str, int]) -> str | None:
        n = self.cand_order.get(key)
        health = self.cand_info.get("health") or []
        return health[n][1] if n is not None and n < len(health) else None


@dataclasses.dataclass
class Result:
    seed: int
    reference: str
    claims: dict[str, list[str]]  # predicate -> claimed items
    failures: list[str]

    @property
    def ok(self) -> bool:
        return not self.failures

    @property
    def claimed(self) -> bool:
        return any(self.claims.values())


def compare(
    pair: Pair,
    lossy: dict[str, Any] | None = None,
    shadow: dict[str, Any] | None = None,
) -> Result:
    """Compare one seed; ``lossy`` is the BC2 lossy run for it and ``shadow``
    its F2 shadow run, each if requested."""
    seed = pair.scenario["seed"]
    failures = [
        f"candidate model: op {i}: {m}" for i, m in pair.cand_info["violations"]
    ]
    if not pair.order_ok:
        failures.append("the shared event keys are out of order")
    applies = APPLIES[pair.reference]
    owner: dict[tuple[str, Any], str] = {}
    for name, predicate in SPECIFIC:
        if name not in applies:
            continue
        claim = predicate(pair)
        for item in claim.items():
            if item in owner:
                failures.append(f"{item} claimed by {owner[item]} and {name}")
            owner.setdefault(item, name)
    if "BC2-LOST-INPUT" in applies:
        clauses = (
            bc2_aborted_native_read(pair),
            bc2_trigger_only(pair),
            bc2_shadow_claim(pair, shadow),
            bc2_broken_refusal(pair, shadow),
        )
        for clause in clauses:
            for item in clause.items():
                if item in owner:
                    failures.append(f"{item} claimed by {owner[item]} and BC2")
                owner.setdefault(item, "BC2-LOST-INPUT")
        request = bc2_request(pair)
        if request is not None and lossy is not None:
            # The lossy model must accept b1's whole run, matching events
            # included; any violation fails the seed.
            failures += [f"lossy model: op {i}: {m}" for i, m in lossy["violations"]]
            # The normalization evidence must match the request exactly:
            # O1 normalizes the acquisition once, nothing else normalizes.
            expected = [-1] if request.acquire == "O1" else []
            if lossy.get("normalized") != expected:
                failures.append(
                    f"lossy model normalized {lossy.get('normalized')!r}, "
                    f"expected {expected!r}"
                )
            claim = bc2_claim(pair, request, lossy, set(owner))
            for item in claim.items():
                owner.setdefault(item, "BC2-LOST-INPUT")
    differences = (
        {("event", k) for k in pair.diffs}
        | {("final", f) for f in pair.final_diffs}
        | {("one-sided", k) for k in pair.cand_only | pair.ref_only}
    )
    for item in sorted(differences - owner.keys(), key=repr):
        failures.append(f"unclaimed difference {item}")
    claims: dict[str, list[str]] = {name: [] for name in applies}
    for item in sorted(differences & owner.keys(), key=repr):
        claims[owner[item]].append(repr(item))
    return Result(seed, pair.reference, claims, failures)


# BC9


def bc9(pair: Pair) -> Claim:
    claim = Claim()
    if pair.mode not in ("rb", "rt") or pair.scenario["source"]["kind"] != "native":
        return claim
    expected = (
        {"ok": 0}
        if pair.reference == "c0"
        else {"error": "ValueError", "message": "seek of closed file"}
    )
    for key in pair.diffs:
        c, r = pair.cand_by_key[key], pair.ref_by_key[key]
        if key[1] != "abort" or pair.op(key).get("call", {}).get("op") != "seek0":
            continue
        parked = c.parked or {}
        if parked.get("via") != "native" or parked.get("method") != "seek":
            continue
        if (c.outcome, c.parked, c.taken) != (r.outcome, r.parked, r.taken):
            continue
        if c.second == {"error": "OSError", "message": READ_ABORTED} and (
            r.second == expected
        ):
            claim.events.add(key)
    return claim


# BC8


def _parked_write(row: Row) -> bool:
    return bool(row.parked) and row.parked.get("method") == "write"


def bc8(pair: Pair) -> Claim:
    claim = Claim()
    if pair.mode not in ("wb", "wt"):
        return claim
    if pair.mode == "wt":
        for key in pair.diffs:
            c, r = pair.cand_by_key[key], pair.ref_by_key[key]
            if (
                key[1] == "writelines"
                and r.outcome == {"ok": None}
                and is_error(c.outcome, contains=WRITE_BROKEN)
                and (c.second, c.parked, c.taken) == (r.second, r.parked, r.taken)
            ):
                claim.events.add(key)
    events = [
        k
        for k in pair.cand_by_key.keys() & pair.ref_by_key.keys()
        if k[1] in ("abort", "cancel")
        and (_parked_write(pair.cand_by_key[k]) or _parked_write(pair.ref_by_key[k]))
    ]
    if len(events) == 1:
        w1 = _w1(pair, events[0])
        if w1 is not None:
            claim.events |= w1.events & pair.diffs
            claim.fields |= w1.fields
    return claim


def _w1(pair: Pair, key: tuple[int, str, int]) -> Claim | None:
    c, r = pair.cand_by_key[key], pair.ref_by_key[key]
    if not (_parked_write(c) and _parked_write(r)):
        return None
    C = raw_bytes(pair.cand_final.get("output_raw"))
    R = raw_bytes(pair.ref_final.get("output_raw"))
    P = raw_bytes(c.parked.get("bytes"))
    if C is None or R is None or P is None or P != raw_bytes(r.parked.get("bytes")):
        return None
    for final in (pair.cand_final, pair.ref_final):
        if (final.get("output") or {}).get("complete") is not False:
            return None
    if c.parked.get("via") != r.parked.get("via") or c.outcome != r.outcome:
        return None
    if c.taken or r.taken:
        return None
    via = c.parked["via"]
    output = {"output", "output_raw"}
    if key[1] == "abort" and via == "custom":  # W1a
        if c.parked.get("resumed") is not False or raw_bytes(c.parked.get("accepted")):
            return None
        if pair.cand_final.get("source_calls_after_close") != 0:
            return None
        if r.parked.get("resumed") is not True or not R.startswith(C):
            return None
        E = R[len(C) :]
        accepted = raw_bytes(r.parked.get("accepted")) or b""
        if not (P.startswith(E) and E.startswith(accepted)):
            return None
        no_effect = is_error(r.second, contains="injected sink failure without effect")
        if (not E) is not no_effect:
            return None
        if c.second != r.second and not (
            is_error(r.second, contains="injected sink failure")
            and (
                is_error(c.second, contains="write aborted")
                or is_error(c.second, contains="flush aborted")
            )
        ):
            return None
        return Claim({key}, (output | {"source_calls_after_close"}) & pair.final_diffs)
    if key[1] == "abort" and via == "native":  # W1b
        if C != R + P:
            return None
        aborted = is_error(c.second, contains="write aborted") or is_error(
            c.second, contains="flush aborted"
        )
        if (
            not aborted
            or not is_error(r.second, "OSError")
            or "aborted" in (r.second.get("message", ""))
        ):
            return None
        return Claim({key}, output & pair.final_diffs)
    if key[1] == "cancel" and via == "native":  # W1c
        if R != C + P or c != r:
            return None
        return Claim(set(), output & pair.final_diffs)
    return None


# BC7

# An incomplete trailing character, as each supported codec reports it.
INCOMPLETE_TAIL = (
    "unexpected end of data",
    "truncated data",
    "incomplete multibyte sequence",
)
TEXT_READS = {"read", "readline", "readlines", "next"}


def bc7(pair: Pair) -> Claim:
    claim = Claim()
    if pair.mode != "rt":
        return claim
    keys = sorted(pair.diffs, key=lambda k: pair.cand_order[k])
    f_event: tuple[str, Any, str] | None = None  # clause, reference outcome, F text
    served = ""  # text the reference went on to serve after an F1a event
    for key in keys:
        call = _read_call(pair, key)
        if call is None:
            continue
        op, c, r = call
        if f_event is None:
            found = _f_clause(pair, key, op, c, r)
            if found is not None:
                claim.events.add(key)
                f_event = found
            continue
        # Later events of the same reader that differ only because of the F
        # event: the candidate refuses as broken, while the reference repeats
        # its F1a error, serves the F1a text it held back (cumulatively a
        # prefix of the candidate's F text), or gives the F2 empty result.
        clause, f_outcome, f_text = f_event
        if op["op"] not in TEXT_READS:
            continue
        if is_error(c, contains=READ_BROKEN):
            if r == f_outcome:
                claim.events.add(key)
            elif clause == "F2" and r == _empty(op["op"]):
                claim.events.add(key)
            elif clause == "F1a":
                text = _text_of(r)
                if text is not None and f_text.startswith(served + text):
                    served += text
                    claim.events.add(key)
        elif (
            clause == "F2"
            and is_error(r, contains=READ_BROKEN)
            and c == _empty(op["op"])
        ):
            claim.events.add(key)
    return claim


def _read_call(pair: Pair, key) -> tuple[dict[str, Any], Any, Any] | None:
    """The text read at ``key`` and its two outcomes, if only they differ.

    The read is the op itself, the call of an overlap, close-during-close or
    cancel (its outcome is the row's), or the call of an abort that finished
    before parking (its outcome is the row's second).
    """
    c, r = pair.cand_by_key[key], pair.ref_by_key[key]
    op = pair.op(key)
    if (c.parked, c.taken, c.pulled) != (r.parked, r.taken, r.pulled):
        return None
    if op["op"] in TEXT_READS:
        if c.second != r.second:
            return None
        return op, c.outcome, r.outcome
    if op["op"] in ("overlap", "close_during", "cancel"):
        if c.second != r.second or op["call"]["op"] not in TEXT_READS:
            return None
        return op["call"], c.outcome, r.outcome
    if op["op"] == "abort" and c.parked is None:
        if c.outcome != r.outcome or op["call"]["op"] not in TEXT_READS:
            return None
        return op["call"], c.second, r.second
    return None


def _empty(name: str) -> Any:
    if name == "next":
        return {"stop": True}
    if name == "readlines":
        return {"ok": []}
    if name == "buffer_read":
        return {"ok": {"bytes": ""}}
    return {"ok": {"str": ""}}


def _text_of(outcome: Any) -> str | None:
    if not isinstance(outcome, dict) or "ok" not in outcome:
        return None
    value = outcome["ok"]
    if isinstance(value, list):
        parts = [_text_of({"ok": item}) for item in value]
        return None if None in parts else "".join(parts)  # type: ignore[arg-type]
    if isinstance(value, dict) and value.keys() == {"str"}:
        return value["str"]
    return None


def _f_clause(pair: Pair, key, op, c, r) -> tuple[str, Any, str] | None:
    if op["op"] != "read" or pair.health_before(key) != "VALIDATION_SALVAGE":
        return None
    size = op.get("n", -1)
    unbounded = size is None or size < 0
    if unbounded and is_error(r, "UnicodeDecodeError"):
        if not r["message"].endswith(INCOMPLETE_TAIL):
            return None
        remaining = _remaining_text(pair, key)
        if remaining is None:
            return None
        text, inside = remaining
        if not inside:
            return None
        if text and c == {"ok": encoded(text)}:
            return "F1a", r, text
        if not text and is_error(c, contains=READ_BROKEN):
            return "F1a", r, text  # F1a-empty: nothing complete remains
        return None
    if r == {"ok": {"str": ""}} and is_error(c, contains=READ_BROKEN):
        return "F2", r, ""
    return None


def salvage(scenario: dict[str, Any], engine: str) -> bytes:
    """Exactly the bytes a reader drains before a validation failure."""
    expect = Checker(scenario, engine).expect
    corruption = scenario["corruption"]
    if corruption["kind"] != "truncate":
        return expect.upper
    index = corruption["member"]
    payloads = [unb64(p) for p in scenario["payloads"]]
    before = b"".join(payloads[:index])
    body_start = scenario["member_spans"][index][0] + 10
    body = unb64(scenario["wire"])[body_start : corruption["cut"]]
    output = raw_reference(engine_modules()[engine], body)["output"]
    return before + output[: len(payloads[index])]


def _remaining_text(pair: Pair, key) -> tuple[str, bool] | None:
    """The text the reader still holds at ``key``, and whether its input
    ends inside a character; None when that cannot be established exactly.

    A modeled reader's position indexes the salvage's boundary text. A
    reader the model stopped tracking (a text ``buffer_read`` pulled bytes
    from under the decoder) is replayed: the decoder's input is the salvage
    without the pulled ranges, and the text consumed is everything the
    reader returned since it opened or last rewound to 0.
    """
    text_options = pair.scenario["text"]
    data = salvage(pair.scenario, pair.engine)
    n = pair.cand_order[key]
    position = (pair.cand_info.get("positions") or [None] * (n + 1))[n]
    if position is not None:
        if position[0] != position[1]:
            return None
        consumed: int | str = position[0]
    else:
        replay = _replay_consumed(pair, key)
        if replay is None:
            return None
        consumed, pulled = replay
        kept, at = [], 0
        for start, end in pulled:
            if start < at or end > len(data):
                return None
            kept.append(data[at:start])
            at = end
        data = b"".join(kept) + data[at:]
    decoded = text_model(
        data, text_options["encoding"], text_options["newline"], False, boundary=True
    )
    if isinstance(consumed, str):
        if not decoded.startswith(consumed):
            return None
        consumed = len(consumed)
    if consumed > len(decoded):
        return None
    return decoded[consumed:], not _ends_on_boundary(text_options["encoding"], data)


def _replay_consumed(pair: Pair, key) -> tuple[str, list[list[int]]] | None:
    """Text returned and ranges pulled before ``key``, since the last reset.

    Fails closed (None) on any event whose effect on the text reader's input
    is not exactly known.
    """
    consumed: list[str] = []
    pulled: list[list[int]] = []
    for row in pair.cand[: pair.cand_order[key]]:
        op = pair.op(row.key)
        name = op["op"]
        if name in ("acquire", "tell_mark", "open", "fail_no_effect", "fail_consumed"):
            continue
        if name == "seek0" or (
            name in ("overlap", "close_during", "cancel")
            and op["call"]["op"] == "seek0"
        ):
            if row.outcome == {"ok": 0}:
                consumed, pulled = [], []
                continue
            if is_error(row.outcome) and name in ("seek0", "overlap", "close_during"):
                continue  # a refused rewind leaves the reader as it was
            return None
        if name == "buffer_read":
            if "ok" in row.outcome:
                if row.pulled is None:
                    return None
                pulled.append(row.pulled)
            continue
        texts = []
        if name in TEXT_READS:
            texts.append(row.outcome)
        elif name in ("overlap", "close_during") and op["call"]["op"] in TEXT_READS:
            texts.append(row.outcome)
            if name == "overlap" and op["second"]["op"] in TEXT_READS:
                texts.append(row.second)
        else:
            return None
        returned = []
        for outcome in texts:
            if "ok" in outcome:
                text = _text_of(outcome)
                if text is None:
                    return None
                if text:
                    returned.append(text)
            elif not (is_error(outcome) or "stop" in outcome or "skipped" in outcome):
                return None
        if len(returned) > 1:
            return None  # two concurrent reads: their order is not recorded
        consumed += returned
    return "".join(consumed), pulled


def _ends_on_boundary(encoding: str, data: bytes) -> bool:
    decoder = codecs.getincrementaldecoder(encoding)()
    try:
        decoder.decode(data, final=False)
    except UnicodeDecodeError:
        return False
    return decoder.getstate()[0] == b""


# BC3


def bc3(pair: Pair) -> Claim:
    claim = Claim()
    acquisition = pair.scenario["acquisition"]
    if acquisition["enter"] != "open":
        return claim
    fault = acquisition.get("fault", "none")
    key = (-1, "acquire", 0)
    c, r = pair.cand_by_key.get(key), pair.ref_by_key.get(key)
    if c is None or r is None:
        return claim
    if fault == "overlap_open":
        if c.second == OPEN_IN_PROGRESS and (c.outcome, c.parked, c.taken) == (
            r.outcome,
            r.parked,
            r.taken,
        ):
            native_binary = pair.scenario["source"][
                "kind"
            ] == "native" and pair.mode in ("rb", "wb")
            if (native_binary and "ok" in (r.second or {})) or (
                not native_binary and r.second == ALREADY_OPEN
            ):
                claim.events.add(key)
        return claim
    if fault == "overlap_close" and c.second == CLOSE_DURING_OPEN:
        _o2(pair, c, r, claim)
    return claim


def _o2(pair: Pair, c: Row, r: Row, claim: Claim) -> None:
    key = c.key
    source = pair.scenario["source"]
    writer = pair.mode in ("wb", "wt")
    custom_writer = writer and source["kind"] == "custom"
    if (c.parked, c.taken) != (r.parked, r.taken) or "ok" not in c.outcome:
        return
    if custom_writer:
        if (r.outcome, r.second) != (INVALIDATED, ENCODER_ACTIVE):
            return
    elif not ("ok" in r.outcome and r.second == {"ok": None}):
        return
    claim.events.add(key)
    split = next(
        (i + 1 for i, op in enumerate(pair.ops) if op["op"] == "close"),
        len(pair.ops),
    )
    cleanup = (len(pair.ops), "cleanup_close", 0)
    if cleanup in pair.cand_only:
        claim.one_sided.add(cleanup)
    if custom_writer:
        claim.one_sided |= {
            k for k in pair.cand_only if 0 <= k[0] < split and k != cleanup
        }
    else:
        for k in pair.diffs:
            if k[0] >= 0 and pair.ref_by_key[k] == _closed_row(pair, k):
                claim.events.add(k)
    _o2_final(pair, r, claim, custom_writer)


def _closed_outcome(name: str) -> Any:
    if name == "next":
        return {"stop": True}
    if name in ("close", "cleanup_close"):
        return {"ok": None}
    if name == "open":
        return REOPEN
    if name == "seek_mark":
        return {"skipped": True}
    return CLOSED


def _closed_row(pair: Pair, key) -> Row | None:
    name = key[1]
    if name in ("fail_no_effect", "fail_consumed", "fail_sink_no_effect"):
        return None
    if name == "fail_sink_partial":
        return None
    if name in ("overlap", "close_during", "cancel"):
        call = pair.op(key)["call"]["op"]
        return Row(key, _closed_outcome(call), {"skipped": True})
    return Row(key, _closed_outcome(name))


def _o2_final(pair: Pair, r: Row, claim: Claim, custom_writer: bool) -> None:
    source = pair.scenario["source"]
    cand, ref = pair.cand_final, pair.ref_final
    writer = pair.mode in ("wb", "wt")
    if source["kind"] == "native":
        if (
            isinstance(cand.get("fd_delta"), int)
            and ref.get("fd_delta") == cand["fd_delta"] + 1
        ):
            claim.fields.add("fd_delta")
        if writer:
            _claim_output(pair, b"", claim)
        return
    if not custom_writer:
        return
    header = raw_bytes((r.parked or {}).get("bytes"))
    if header is None:
        return
    _claim_output(pair, header, claim)
    short = source.get("short")
    if source.get("closefd") and short and short < len(header):
        expected = math.ceil(len(header) / short) - 1
        if ref.get("source_calls_after_close") == expected:
            claim.fields.add("source_calls_after_close")


def _claim_output(pair: Pair, data: bytes, claim: Claim) -> None:
    """Claim both output fields when the reference's are exactly ``data``'s,
    in whichever recording (raw or digest) the interpreter chose."""
    ref = pair.ref_final
    fields = ("output", "output_raw")
    for retain in (True, False):
        expected = encoded(final_output(data, retain), "final")
        if all(ref.get(f) == expected[f] for f in fields):
            claim.fields |= set(fields)
            return


SPECIFIC = (
    ("BC3-OPENING", bc3),
    ("BC7-TEXT-SALVAGE", bc7),
    ("BC8-WRITER-ABORT", bc8),
    ("BC9-REWIND-ABORT", bc9),
)


# BC2


@dataclasses.dataclass
class Bc2Request:
    trigger: tuple[int, str, int]
    lossy: dict[str, Any]
    rebase: bool
    clause: str  # "L1" or "L2"
    taken: list[int] = dataclasses.field(default_factory=lambda: [0, 0])
    # The BC3 clause that owns the acquisition exactly, which the lossy model
    # then judges by b1's lifecycle transition (only "O1").
    acquire: str | None = None

    def line(self, scenario: dict[str, Any]) -> dict[str, Any]:
        """The lossy run's request, as the interpreter reads it."""
        return {
            "scenario": scenario,
            "lossy": self.lossy,
            "trigger": self.trigger[0],
            "rebase": self.rebase,
            "taken": self.taken,
            "acquire": self.acquire,
        }


def bc2_request(pair: Pair) -> Bc2Request | None:
    """The first eligible BC2 trigger, and the lossy scenario b1 then saw."""
    scenario = pair.scenario
    if pair.reference != "b1" or pair.mode not in ("rb", "rt"):
        return None
    source = scenario["source"]
    common = [row.key for row in pair.cand if row.key in pair.ref_by_key]
    for key in common:
        c, r = pair.cand_by_key[key], pair.ref_by_key[key]
        health = pair.health_before(key)
        if health != "HEALTHY" and not (
            health == "VALIDATION_SALVAGE" and _g_custom(pair, key, c, r)
        ):
            continue
        trigger = _trigger(pair, key, c, r, source)
        if trigger is None:
            continue
        clause, taken = trigger
        if clause == "G":
            lossy = replay_scenario(scenario, taken[0], pair.engine)
        else:
            lossy = lossy_scenario(scenario, *taken, pair.engine)
        if lossy is None:
            return None
        rebase = source["kind"] == "native" or source["seekable"]
        acquire = None
        if ("event", (-1, "acquire", 0)) in bc3(pair).items() and scenario[
            "acquisition"
        ].get("fault") == "overlap_open":
            acquire = "O1"
        return Bc2Request(key, lossy, rebase, clause, list(taken), acquire)
    return None


def _g_custom(pair: Pair, key, c: Row, r: Row) -> bool:
    """Exactly G custom: a cancelled parked custom ``seek0`` without a
    checkpoint, identical on both sides. The one trigger admitted from
    validation salvage: the cancel lands before the source moves, so b1
    keeps its salvage, which the lossy run then replays."""
    source = pair.scenario["source"]
    return (
        source["kind"] == "custom"
        and not source["checkpoint"]
        and key[1] == "cancel"
        and pair.op(key) == {"op": "cancel", "call": {"op": "seek0"}}
        and c == r
        and c.outcome == {"cancelled": True}
    )


def _trigger(pair: Pair, key, c: Row, r: Row, source) -> tuple[str, list[int]] | None:
    if source["kind"] == "custom":
        if c != r:
            return None
        if c.taken is not None:
            if wire_range(pair, c.taken) is None:
                return None  # malformed evidence proves nothing
            empty = c.taken[0] == c.taken[1]
            if empty and source["checkpoint"]:
                return None  # proven no effect: unchanged, not claimed
            return "L1", c.taken
        if (
            key[1] == "cancel"
            and not source["checkpoint"]
            and c.outcome == {"cancelled": True}
        ):
            # A cancelled read or (G) a cancelled seek0: the source did not
            # move, and b1 keeps its position.
            return "L1", [0, 0]
        return None
    if (
        key[1] == "cancel"
        and pair.op(key)["call"]["op"] != "seek0"
        and c.without_taken() == r.without_taken()
        and c.outcome == {"cancelled": True}
        and (r.parked or {}).get("method") == "read"
        and wire_range(pair, r.taken) is not None
    ):
        return "L2", r.taken
    origin = _seek_origin(pair, key)
    if (
        key[1] == "cancel"
        and pair.op(key)["call"]["op"] == "seek0"
        and c == r
        and c.outcome == {"cancelled": True}
        and r.parked == NATIVE_SEEK
        and origin is not None
    ):
        # G native: the parked seek moved the file to 0 under the cancel and
        # b1 kept its decoder, which has consumed wire[:origin].
        return "G", [origin, origin]
    return None


# The exact parked witness of a native seek (G native).
NATIVE_SEEK = {"via": "native", "method": "seek", "bytes": None}


def _evidence(pair: Pair, name: str, index: int) -> list[list[Any]] | None:
    """The reference's ``name`` evidence records at event ``index``, or None
    when the evidence is malformed anywhere: it must be a list of
    ``[event index, list]`` records whose index is exactly an int."""
    records = pair.ref_info.get(name, [])
    if not isinstance(records, list):
        return None
    found = []
    for record in records:
        if not isinstance(record, list) or len(record) != 2:
            return None
        at, payload = record
        if type(at) is not int or not isinstance(payload, list):
            return None
        if at == index:
            found.append(payload)
    return found


def _seek_origin(pair: Pair, key) -> int | None:
    """The file offset b1's parked native seek left, or None unless the
    reference recorded exactly one seek, to 0, at the event, with exactly one
    origin ``[p, 0]`` where ``[0, p]`` is a valid wire range short of the
    wire's end (a regular file then cannot have reported its end to b1).
    Malformed evidence never raises; it makes no trigger."""
    index = key[0]
    seeks = _evidence(pair, "seeks", index)
    origins = _evidence(pair, "origins", index)
    if seeks is None or origins is None:
        return None
    if len(seeks) != 1 or len(seeks[0]) != 1:
        return None
    (seek,) = seeks[0]
    if type(seek) is not int or seek != 0:
        return None
    if len(origins) != 1 or len(origins[0]) != 1:
        return None
    (witness,) = origins[0]
    if not isinstance(witness, list) or len(witness) != 2:
        return None
    origin, target = witness
    if type(target) is not int or target != 0:
        return None
    if wire_range(pair, [0, origin]) is None:
        return None
    if origin == len(unb64(pair.scenario["wire"])):
        # b1 may already have seen the source's end, and then never reads
        # again; whether it did is not witnessed, so no trigger.
        return None
    return origin


def wire_range(pair: Pair, taken: Any) -> list[int] | None:
    """A witness range, or None unless it is exactly two non-bool ints with
    ``0 <= a <= b <= len(wire)``. An empty range (a completed read at the
    end of input) is valid."""
    if not isinstance(taken, list) or len(taken) != 2:
        return None
    if not all(type(x) is int for x in taken):
        return None
    a, b = taken
    if not 0 <= a <= b <= len(unb64(pair.scenario["wire"])):
        return None
    return [a, b]


def bc2_trigger_only(pair: Pair) -> Claim:
    """E: an L2 trigger that is the seed's only difference.

    b1's cancelled native read took a range no lossy scenario models (an
    endpoint inside a member), but b1 rewound before it observed the loss:
    every other event and every final field matches exactly, so the trigger
    row's one-sided ``taken`` witness is claimed without a lossy run.
    """
    claim = Claim()
    if pair.reference != "b1" or pair.mode not in ("rb", "rt"):
        return claim
    if pair.scenario["source"]["kind"] != "native":
        return claim
    if len(pair.diffs) != 1 or pair.final_diffs or pair.cand_only or pair.ref_only:
        return claim
    (key,) = pair.diffs
    if bc2_request(pair) is not None or pair.health_before(key) != "HEALTHY":
        return claim
    c, r = pair.cand_by_key[key], pair.ref_by_key[key]
    trigger = _trigger(pair, key, c, r, pair.scenario["source"])
    if trigger is not None and trigger[0] == "L2" and c.taken is None:
        claim.events.add(key)
    return claim


def bc2_aborted_native_read(pair: Pair) -> Claim:
    """F1: context exit aborts a native read parked in the executor.

    The candidate's read completes and settles, then reports the abort; b1
    closes the file under the worker, whose read fails on the closed file
    without taking input.
    """
    claim = Claim()
    if pair.reference != "b1" or pair.mode not in ("rb", "rt"):
        return claim
    if pair.scenario["source"]["kind"] != "native":
        return claim
    if pair.cand_final.get("closed") != pair.ref_final.get("closed"):
        return claim
    for key in pair.diffs:
        if key[1] != "abort":
            continue
        c, r = pair.cand_by_key[key], pair.ref_by_key[key]
        injected = {"error": "InjectedAbort", "message": f"abort at {key[0]}"}
        if (
            c.outcome == r.outcome == injected
            and c.parked == r.parked
            and (c.parked or {}).get("via") == "native"
            and (c.parked or {}).get("method") == "read"
            and c.second == {"error": "OSError", "message": READ_ABORTED}
            and wire_range(pair, c.taken) is not None
            and r.second == B1_READ_CLOSED
            and r.taken is None
        ):
            claim.events.add(key)
    return claim


def _f2_abort(pair: Pair) -> tuple[int, str, int] | None:
    """F2's abort key: context exit aborted a custom-source read call (custom
    sources park without a record), the candidate reports the read-aborted
    ``OSError`` with no witness, and b1 let the call finish."""
    if pair.reference != "b1" or pair.mode not in ("rb", "rt"):
        return None
    if pair.scenario["source"]["kind"] != "custom":
        return None
    for key in pair.diffs:
        if key[1] != "abort":
            continue
        c, r = pair.cand_by_key[key], pair.ref_by_key[key]
        injected = {"error": "InjectedAbort", "message": f"abort at {key[0]}"}
        call = pair.op(key).get("call", {}).get("op")
        if (
            call in READ_CALLS | {"buffer_read"}
            and c.outcome == r.outcome == injected
            and c.second == {"error": "OSError", "message": READ_ABORTED}
            and c.parked is None
            and r.parked is None
            and c.taken is None
            and c.pulled is None
            and r.pulled is None
            and (r.taken is None or wire_range(pair, r.taken) is not None)
            and r.second != c.second
        ):
            return key
    return None


def shadow_scenario(pair: Pair) -> dict[str, Any] | None:
    """F2's shadow: the same scenario with the abort's call run without the
    abort, ``ops[:i] + [call]``, on the same candidate and engine."""
    key = _f2_abort(pair)
    if key is None:
        return None
    index = key[0]
    shadow = copy.deepcopy(pair.scenario)
    shadow["ops"] = shadow["ops"][:index] + [shadow["ops"][index]["call"]]
    return shadow


def bc2_shadow_claim(pair: Pair, shadow: dict[str, Any] | None) -> Claim:
    """F2: claim the abort when the shadow run reproduces b1's outcome.

    A fail-closed metamorphic check: the shadow run has no model violation,
    its trace equals the candidate's exactly before the abort's index, and
    its call row equals b1's second outcome with b1's witness exactly.
    """
    claim = Claim()
    key = _f2_abort(pair)
    if key is None or shadow is None or shadow.get("violations") != []:
        return claim
    index = key[0]
    rows = parse(shadow["trace"])
    if [x for x in rows if x.index < index] != [
        x for x in pair.cand if x.index < index
    ]:
        return claim
    r = pair.ref_by_key[key]
    call = (index, pair.op(key)["call"]["op"], 0)
    expected = Row(call, r.second, None, r.parked, r.taken, r.pulled)
    if [x for x in rows if x.index == index] == [expected]:
        claim.events.add(key)
    return claim


F2B_CALL = {"op": "abort", "call": {"op": "readline", "limit": -1}}


def _exact_ints(values: Any, length: int) -> list[int] | None:
    """``values`` as a list of exactly ``length`` non-bool ints, else None."""
    if not isinstance(values, list) or len(values) != length:
        return None
    if not all(type(x) is int for x in values):
        return None
    return values


def _source_read(pair: Pair, index: int) -> list[int] | None:
    """b1's parked source read at ``index`` as ``[start, end]``, or None.

    The whole ``source_reads`` evidence must be well formed: records
    ``[event index, [origin, start, end]]`` of exact ints. Exactly one record
    is at ``index``, its origin (the last completed source seek) is 0, and
    ``0 <= start <= end <= len(wire)``.
    """
    records = pair.ref_info.get("source_reads")
    if not isinstance(records, list):
        return None
    found = []
    for record in records:
        if not isinstance(record, list) or len(record) != 2:
            return None
        if type(record[0]) is not int or _exact_ints(record[1], 3) is None:
            return None
        if record[0] == index:
            found.append(record[1])
    if len(found) != 1:
        return None
    origin, start, end = found[0]
    if origin != 0 or wire_range(pair, [start, end]) is None:
        return None
    return [start, end]


def _seeks_to_zero(pair: Pair) -> bool:
    """Every completed source seek b1 made targets 0, and the evidence is
    well formed: records ``[event index, [target, ...]]`` of exact ints."""
    records = pair.ref_info.get("seeks")
    if not isinstance(records, list):
        return False
    for record in records:
        if not isinstance(record, list) or len(record) != 2:
            return False
        at, targets = record
        if type(at) is not int or not isinstance(targets, list) or not targets:
            return False
        if not all(type(t) is int and t == 0 for t in targets):
            return False
    return True


def _certain(positions: Any, n: int | None) -> int | None:
    """The exact position ``[p, p]`` recorded before row ``n``, else None."""
    if n is None or not isinstance(positions, list) or not 0 <= n < len(positions):
        return None
    position = _exact_ints(positions[n], 2)
    if position is None or position[0] != position[1] or position[0] < 0:
        return None
    return position[0]


def bc2_broken_refusal(pair: Pair, shadow: dict[str, Any] | None) -> Claim:
    """F2b: b1 refuses an aborted ``readline()`` as broken.

    b1's exit marks the stream broken and at EOF under a custom-source
    ``readline(-1)`` parked in its source read. The read then returns and is
    decoded, and b1 reports the abort only when its buffer holds a newline;
    otherwise the EOF branch raises the broken refusal. Every b1 decoder
    reset restarts at wire 0 (a completed seek to 0, or replay of an
    uncapped cache), so the compressed input b1 can have decoded is a
    contiguous prefix of ``wire[:end]``, ``end`` being where its parked read
    returned. Its decoded bytes are then a prefix of the engine-matched
    oracle's output for ``wire[:end]``; with no newline there from b1's
    position ``p``, b1 cannot have found one. The shadow's readline must
    agree, starting with the oracle's bytes from ``p``.
    """
    claim = Claim()
    key = _f2_abort(pair)
    if key is None or pair.mode != "rb" or shadow is None:
        return claim
    if pair.diffs != {key} or pair.final_diffs or pair.cand_only or pair.ref_only:
        return claim
    if pair.op(key) != F2B_CALL:
        return claim
    r = pair.ref_by_key[key]
    if r.second != B1_READ_BROKEN_SEEK0 or r.taken is not None:
        return claim
    source = pair.scenario["source"]
    if not (
        source["seekable"]
        or (
            "max_rewind_cache_size" in pair.scenario
            and pair.scenario["max_rewind_cache_size"] is None
        )
    ):
        return claim
    index = key[0]
    extent = _source_read(pair, index)
    if extent is None or not _seeks_to_zero(pair):
        return claim
    # b1's position: the candidate's and the shadow's, each exactly certain.
    if shadow.get("violations") != []:
        return claim
    p = _certain(pair.cand_info.get("positions"), pair.cand_order.get(key))
    if p is None:
        return claim
    try:
        rows = parse(shadow["trace"])
    except (KeyError, TypeError, ValueError):
        return claim
    if [x for x in rows if x.index < index] != [
        x for x in pair.cand if x.index < index
    ]:
        return claim
    calls = [n for n, x in enumerate(rows) if x.index == index]
    if len(calls) != 1 or rows[calls[0]].key != (index, "readline", 0):
        return claim
    if _certain(shadow.get("positions"), calls[0]) != p:
        return claim
    line = rows[calls[0]]
    if not isinstance(line.outcome, dict) or line.outcome.keys() != {"ok"}:
        return claim
    shadow_bytes = raw_bytes(line.outcome["ok"])
    if shadow_bytes is None or line != Row(line.key, line.outcome):
        return claim
    wire = unb64(pair.scenario["wire"])
    out = wire_reference(engine_modules()[pair.engine], wire[: extent[1]])["output"]
    if p > len(out) or b"\n" in out[p:]:
        return claim
    if not shadow_bytes.startswith(out[p:]):
        return claim
    claim.events.add(key)
    return claim


def lossy_scenario(
    scenario: dict[str, Any], a: int, b: int, engine: str
) -> dict[str, Any] | None:
    """The scenario with wire range ``[a, b)`` removed, or None if ineligible.

    Eligible when the range is empty, or when neither endpoint lies strictly
    inside a recorded member span; for text, the rebuilt payload must also
    satisfy the model's incremental text oracle. A range that starts at 0
    and ends in padding (no span covers ``b``), or with an endpoint inside a
    member, is spliced and judged by the wire oracle instead.
    """
    spans = scenario.get("member_spans")
    if spans is None:
        return None
    if a == b:
        return scenario
    wire = unb64(scenario["wire"])
    if a == 0 and b < len(wire) and not any(s <= b < e for s, e in spans):
        # The lossy wire starts in padding, which only the wire oracle
        # models: zero padding is legal only after a completed member.
        return _wire_scenario(scenario, wire[b:], engine, lossy_range=[a, b])
    if any(s < a < e or s < b < e for s, e in spans):
        return _wire_scenario(scenario, wire[:a] + wire[b:], engine, lossy_range=[a, b])
    lost = b - a
    payloads = scenario["payloads"]
    drop = {i for i, (s, e) in enumerate(spans) if a <= s and e <= b}
    keep = [i for i in range(len(spans)) if i not in drop]
    corruption = dict(scenario["corruption"])
    member = corruption.get("member")
    tail = len(spans) < len(payloads)  # members beyond a truncation or damage
    new_payloads = [payloads[i] for i in keep]
    if tail and member is not None and member not in drop:
        new_payloads += payloads[len(spans) :]
    if member is not None:
        if member in drop:
            corruption = {"kind": "none", "dropped_by_lossy_range": True}
        else:
            corruption["member"] = keep.index(member)
            for field in ("cut", "at", "body_start", "body_end"):
                if field in corruption and corruption[field] >= b:
                    corruption[field] -= lost
    shift = [[s - lost, e - lost] if s >= b else [s, e] for s, e in spans]
    new_spans = [shift[i] for i in keep]
    lossy = dict(scenario)
    lossy.update(
        wire=base64.b64encode(wire[:a] + wire[b:]).decode("ascii"),
        payloads=new_payloads,
        payload_size=sum(len(base64.b64decode(p)) for p in new_payloads),
        member_offsets=[s for s, _ in new_spans],
        member_spans=new_spans,
        corruption=corruption,
        lossy_range=[a, b],
    )
    if scenario["mode"] == "rt":
        text = scenario["text"]
        whole = b"".join(base64.b64decode(p) for p in new_payloads)
        try:
            text_model(whole, text["encoding"], text["newline"], final=True)
            Checker(lossy, engine)
        except (UnicodeDecodeError, ValueError, AssertionError):
            return None
    else:
        try:
            Checker(lossy, engine)
        except (ValueError, AssertionError):
            return None
    return lossy


def replay_scenario(
    scenario: dict[str, Any], origin: int, engine: str
) -> dict[str, Any] | None:
    """G native's view: b1's decoder replays ``wire[:origin]``, then reads
    the true wire again from offset 0 into that same state."""
    wire = unb64(scenario["wire"])
    return _wire_scenario(
        scenario, wire[:origin] + wire, engine, replayed_prefix=origin
    )


def _wire_scenario(
    scenario: dict[str, Any], spliced: bytes, engine: str, **witness: Any
) -> dict[str, Any] | None:
    return wire_view(scenario, spliced, engine, **witness)


def bc2_claim(
    pair: Pair,
    request: Bc2Request,
    lossy: dict[str, Any],
    owned: set[tuple[str, Any]],
) -> Claim:
    """Claim the residual differing events in the span the lossy run accepts."""
    claim = Claim()
    if parse(lossy["trace"]) != pair.ref:
        return claim  # b1's replay was not reproduced; claim nothing
    if not _convergence_ok(pair, lossy):
        return claim  # convergence evidence is malformed; claim nothing
    losses = _losses(pair, request, lossy)
    if losses is None:
        return claim  # malformed loss evidence; claim nothing
    order = pair.cand_order
    start = order[request.trigger]
    converged = _converged(pair, lossy, start)
    span = set(range(start + 1, len(pair.cand) if converged is None else converged + 1))
    for index in losses:
        # H: each later loss opens its own span, from its first row until
        # the models agree again.
        rows = [n for n, row in enumerate(pair.cand) if row.key[0] == index]
        if not rows:
            return Claim()  # a loss the candidate never ran; claim nothing
        begin = min(rows)
        converged = _converged(pair, lossy, begin - 1)
        span.update(
            range(begin, len(pair.cand) if converged is None else converged + 1)
        )
    rejected = {index for index, _message in lossy["violations"]}
    trigger = request.trigger
    if (
        request.clause == "L2"
        and trigger in pair.diffs
        and ("event", trigger) not in owned
        and pair.cand_by_key[trigger].taken is None
    ):
        # The candidate settles the cancel before its parked read enters the
        # file, so only b1's trigger row carries the lost-range witness.
        claim.events.add(trigger)
    for n in sorted(span):
        key = pair.cand[n].key
        if key not in pair.diffs or ("event", key) in owned:
            continue
        if key[0] in rejected or key[1] == "final":
            continue
        claim.events.add(key)
    return claim


def _losses(pair: Pair, request: Bc2Request, lossy: dict[str, Any]) -> list[int] | None:
    """The event indices of the lossy run's later losses (H), or None when
    the record is missing, malformed, or not bound to b1's rows: each index
    is a single b1 row after the trigger that can be a later loss
    (``later_loss_kind``), and its range or empty loss is exactly what
    that row's ``taken`` witnesses (``loss_witness``)."""
    losses = lossy.get("losses")
    if type(losses) is not list:
        return None
    wire_size = len(base64.b64decode(pair.scenario["wire"]))
    source = pair.scenario["source"]
    indices = []
    for loss in losses:
        if type(loss) is not list or len(loss) != 2 or type(loss[0]) is not int:
            return None
        index, taken = loss
        rows = [row for row in pair.ref if row.index == index]
        if index <= request.trigger[0] or len(rows) != 1:
            return None
        (row,) = rows
        outcome = row.outcome if isinstance(row.outcome, dict) else {}
        if outcome == {"cancelled": True}:
            kind, message = "cancelled", None
        elif outcome.keys() == {"error", "message"} and isinstance(
            outcome["message"], str
        ):
            kind, message = "error", outcome["message"]
        else:
            return None
        transition = later_loss_kind(pair.op(row.key), kind, message, source)
        if transition is None:
            return None
        witnessed, witness = loss_witness(transition, row.taken, wire_size)
        if not witnessed:
            return None
        if taken is None:
            if witness is not None:
                return None
        elif not (
            type(taken) is list
            and all(type(x) is int for x in taken)
            and taken == witness
        ):
            return None
        indices.append(index)
    if indices != sorted(set(indices)):
        return None
    return indices


HEALTH_VALUES = (None, "HEALTHY", "VALIDATION_SALVAGE", "BROKEN")


def _convergence_ok(pair: Pair, lossy: dict[str, Any]) -> bool:
    """Whether both runs' convergence evidence is exactly well formed: one
    ``states`` and one ``health`` record per trace row, each state
    ``[position, eof, view, pending]`` (position None or ``[lo, hi]`` ints
    with ``0 <= lo <= hi``, eof a bool, view None for the candidate and
    ``"true"``/``"lossy"`` for the lossy run, pending an injected failure
    kind or None), each health entry two values of ``HEALTH_VALUES``."""
    sides = (
        (pair.cand_info, len(pair.cand), (None,)),
        (lossy, len(pair.ref), ("true", "lossy")),
    )
    for record, rows, views in sides:
        states, health = record.get("states"), record.get("health")
        if type(states) is not list or type(health) is not list:
            return False
        if len(states) != rows or len(health) != rows:
            return False
        for state in states:
            if type(state) is not list or len(state) != 4:
                return False
            position, eof, view, pending = state
            if position is not None and not (
                type(position) is list
                and len(position) == 2
                and all(type(x) is int for x in position)
                and 0 <= position[0] <= position[1]
            ):
                return False
            if type(eof) is not bool:
                return False
            if not _exact(view, views) or not _exact(pending, PENDING):
                return False
        for entry in health:
            if type(entry) is not list or len(entry) != 2:
                return False
            if not all(_exact(value, HEALTH_VALUES) for value in entry):
                return False
    return True


PENDING = (None, "no_effect", "consumed")


def _exact(value: Any, allowed: tuple[str | None, ...]) -> bool:
    """Whether ``value`` is exactly one of ``allowed`` (a str or None)."""
    return (value is None or type(value) is str) and value in allowed


def _converged(pair: Pair, lossy: dict[str, Any], start: int) -> int | None:
    """The candidate-order position of the first event after the trigger
    after which both models agree: the lossy model is back on the true view,
    and both are certain of the same position, with the same health and eof,
    and the same pending injected source failure (which decides the next
    read: seed 5712).
    A physical rewind alone is not enough (a relative seek keeps b1 ahead by
    the lost length)."""
    ref_order = {row.key: n for n, row in enumerate(pair.ref)}
    cand_states = pair.cand_info.get("states") or []
    cand_health = pair.cand_info.get("health") or []
    ref_states = lossy.get("states") or []
    ref_health = lossy.get("health") or []
    for n in range(start + 1, len(pair.cand)):
        m = ref_order.get(pair.cand[n].key)
        if m is None or n >= len(cand_states) or m >= len(ref_states):
            continue
        (c_pos, c_eof, _, c_pending) = cand_states[n]
        (r_pos, r_eof, view, r_pending) = ref_states[m]
        if (
            view == "true"
            and c_pending == r_pending
            and c_pos is not None
            and c_pos[0] == c_pos[1]
            and c_pos == r_pos
            and c_eof == r_eof
            and cand_health[n][1] == ref_health[m][1]
        ):
            return n
    return None


# Runner


def _run_root(root, engine, scenarios, output, flag=None) -> dict[str, Any]:
    command = [
        sys.executable,
        str(HERE / "interpreter.py"),
        "--source-root",
        str(root),
        "--engine",
        engine,
        "--scenarios",
        str(scenarios),
        "--output",
        str(output),
    ]
    if flag:
        command.append(flag)
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    subprocess.run(command, check=True, env=env, cwd=str(HERE))
    return json.loads(Path(output).read_text(encoding="utf-8"))


def _chunks(seeds: list[int], jobs: int) -> list[list[int]]:
    return [seeds[i::jobs] for i in range(jobs) if seeds[i::jobs]]


def run(
    reference: str,
    reference_root: Path,
    candidate_root: Path,
    engine: str,
    seeds: list[int],
    workdir: Path,
    jobs: int,
) -> dict[str, Any]:
    scenarios = {seed: generate(seed) for seed in seeds}

    def side(root, label, chunk, n, flag=None):
        path = workdir / f"{label}-{n}.jsonl"
        with path.open("w", encoding="utf-8") as lines:
            for seed in chunk:
                lines.write(json.dumps(scenarios[seed]) + "\n")
        return _run_root(root, engine, path, workdir / f"{label}-{n}.json", flag)

    cand_runs, ref_runs, records = {}, {}, {}
    with concurrent.futures.ThreadPoolExecutor(jobs) as pool:
        futures = []
        for n, chunk in enumerate(_chunks(seeds, jobs)):
            futures.append(
                pool.submit(side, candidate_root, "cand", chunk, n, "--observe")
            )
            futures.append(pool.submit(side, reference_root, reference, chunk, n))
        for future in futures:
            record = future.result()
            records.setdefault(record["source_import"], record["engines"])
        for n, _chunk in enumerate(_chunks(seeds, jobs)):
            cand_runs.update(
                json.loads((workdir / f"cand-{n}.json").read_text())["runs"]
            )
            ref_runs.update(
                json.loads((workdir / f"{reference}-{n}.json").read_text())["runs"]
            )
    # Both sides inflate with one engine; the oracles use its module name.
    decompression = {record["decompression"] for record in records.values()}
    if len(decompression) != 1:
        raise SystemExit(f"candidate and reference engines differ: {records}")
    (inflater,) = decompression
    pairs = {
        seed: Pair(
            scenarios[seed],
            reference,
            parse(cand_runs[str(seed)]["trace"]),
            parse(ref_runs[str(seed)]["trace"]),
            cand_runs[str(seed)],
            inflater,
            ref_runs[str(seed)],
        )
        for seed in seeds
    }
    requests = {}
    if reference == "b1":
        for seed, pair in pairs.items():
            request = bc2_request(pair)
            if request is not None:
                requests[seed] = request
    lossy_runs: dict[str, Any] = {}
    shadows = {}
    if reference == "b1":
        for seed, pair in pairs.items():
            shadow = shadow_scenario(pair)
            if shadow is not None:
                shadows[seed] = shadow
    shadow_runs: dict[str, Any] = {}
    if shadows:
        path = workdir / "shadow.jsonl"
        with path.open("w", encoding="utf-8") as lines:
            for shadow in shadows.values():
                lines.write(json.dumps(shadow) + "\n")
        shadow_runs = _run_root(
            candidate_root, engine, path, workdir / "shadow.json", "--observe"
        )["runs"]
    if requests:
        path = workdir / "lossy.jsonl"
        with path.open("w", encoding="utf-8") as lines:
            for seed, request in requests.items():
                lines.write(json.dumps(request.line(scenarios[seed])) + "\n")
        lossy_runs = _run_root(
            reference_root, engine, path, workdir / "lossy.json", "--lossy"
        )["runs"]
    results = [
        compare(pairs[s], lossy_runs.get(str(s)), shadow_runs.get(str(s)))
        for s in seeds
    ]
    claimed = {name: 0 for name in APPLIES[reference]}
    retained = []
    for result in results:
        for name, items in result.claims.items():
            claimed[name] += bool(items)
        if result.claimed or not result.ok:
            seed = result.seed
            retained.append(
                {
                    "seed": seed,
                    "scenario": scenarios[seed],
                    "candidate": cand_runs[str(seed)],
                    "reference": ref_runs[str(seed)],
                    "lossy": lossy_runs.get(str(seed)),
                    "shadow": shadow_runs.get(str(seed)),
                    "claims": result.claims,
                    "failures": result.failures,
                }
            )
    return {
        "reference": reference,
        "engine": engine,
        "seeds": [seeds[0], seeds[-1], len(seeds)],
        "imports": records,
        "failed": [r.seed for r in results if not r.ok],
        "seeds_claimed_by": claimed,
        "retained": retained,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", choices=("c0", "b1"), required=True)
    parser.add_argument("--reference-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--engine", choices=("stdlib", "zlib-ng"), required=True)
    parser.add_argument("--seeds", required=True, help="START:STOP")
    parser.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    start, stop = map(int, args.seeds.split(":"))
    with tempfile.TemporaryDirectory(prefix="aiogzip-differential-") as directory:
        report = run(
            args.reference,
            args.reference_root.resolve(),
            args.candidate_root.resolve(),
            args.engine,
            list(range(start, stop)),
            Path(directory),
            args.jobs,
        )
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(report, output, ensure_ascii=False)
        output.write("\n")
    print(
        f"{args.reference} {args.engine} seeds {args.seeds}: "
        f"{len(report['failed'])} failed; claimed {report['seeds_claimed_by']}"
    )
    if report["failed"]:
        print("failed seeds:", report["failed"][:50])
        sys.exit(1)


if __name__ == "__main__":
    main()
