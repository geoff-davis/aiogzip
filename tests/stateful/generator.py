"""Seeded scenario generator for the WP10 stateful differential harness.

``generate(seed)`` returns a plain-JSON scenario: a fixed configuration, the
exact gzip wire bytes, the clean payload of every member, the injected
corruption, and an operation list. The interpreter replays the JSON unchanged
against b1, C0 and the candidate, so nothing here may depend on the aiogzip
under test. Wire bytes are stored rather than regenerated, so every source
root sees identical input even if zlib output differs between builds.
"""

from __future__ import annotations

import base64
import codecs
import gzip
import itertools
import random
import zlib
from typing import Any

from oracle import engine_modules, raw_reference

SCHEMA = 2  # 2: read scenarios record member_spans
ENCODINGS = ("utf-8", "utf-16", "shift_jis")
NEWLINES = (None, "", "\n", "\r", "\r\n")
CHUNK_SIZES = (7, 64, 512, 4096, 65536)
TEXT_ALPHABET = {
    "utf-8": ("a", "b", "z", " ", "α", "€", "😀", "\n", "\r", "\r\n"),
    "utf-16": ("a", "b", " ", "α", "😀", "\n", "\r", "\r\n"),
    "shift_jis": ("a", "b", " ", "日", "本", "カ", "\n", "\r", "\r\n"),
}
# Share of scenarios that exercise the writer instead of the reader.
WRITE_SHARE = 0.2
WRITE_SIZES = (0, 1, 10, 1000, 70_000)
# Sink accepting at most this many bytes per write() (None: everything).
SHORT_WRITES = (None, None, None, 1, 7, 4096)
# Body corruptions most engines never detect inflate to garbage and fail only
# at the trailer; those are not body-corruption scenarios, so re-roll.
MAX_BODY_REROLLS = 400


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def unb64(text: str) -> bytes:
    return base64.b64decode(text)


def _binary_payload(rng: random.Random, size: int) -> bytes:
    parts = []
    while sum(map(len, parts)) < size:
        kind = rng.random()
        if kind < 0.6:
            line = bytes(rng.choice(b"abcdefgh \t") for _ in range(rng.randrange(80)))
            parts.append(line + b"\n")
        elif kind < 0.8:
            parts.append(rng.randbytes(rng.randrange(1, 300)))
        else:
            parts.append(b"\r\n" * rng.randrange(1, 4) + b"\0")
    return b"".join(parts)[:size]


def _text_payload(rng: random.Random, encoding: str, chars: int) -> str:
    alphabet = TEXT_ALPHABET[encoding]
    return "".join(rng.choice(alphabet) for _ in range(chars))


def _split(rng: random.Random, payload: bytes) -> list[bytes]:
    count = rng.choice((1, 1, 1, 2, 3, 4))
    cuts = sorted(rng.randrange(len(payload) + 1) for _ in range(count - 1))
    bounds = [0, *cuts, len(payload)]
    return [payload[a:b] for a, b in itertools.pairwise(bounds)]


def _member(rng: random.Random, payload: bytes) -> bytes:
    return gzip.compress(payload, compresslevel=rng.choice((1, 6, 9)), mtime=0)


def _character_boundary(encoding: str, data: bytes) -> bool:
    """Whether ``data`` ends on a character boundary (no pending bytes)."""
    decoder = codecs.getincrementaldecoder(encoding)()
    decoder.decode(data, final=False)
    return decoder.getstate()[0] == b""


def _choose_corruption(
    rng: random.Random,
    members: list[bytes],
    payloads: list[bytes],
    offsets: list[int],
    text: dict[str, Any] | None,
) -> tuple[bytes, dict[str, Any]]:
    """Return damaged wire and the corruption record (kind ``none`` if clean)."""
    wire = b"".join(members_with_padding(members, offsets))
    kind = rng.choices(
        ("none", "crc", "isize", "truncate", "body", "limit"),
        weights=(40, 10, 6, 18, 14, 12),
    )[0]
    nonempty = [i for i, p in enumerate(payloads) if p]
    if kind == "body" and not nonempty:
        kind = "truncate"
    if kind == "none":
        return wire, {"kind": "none"}
    if kind == "limit":
        total = sum(map(len, payloads))
        if total <= 1 or rng.random() < 0.25:
            # Exactly the full size is allowed; the stream must validate.
            return wire, {"kind": "limit", "limit": max(total, 1)}
        return wire, {"kind": "limit", "limit": rng.randrange(1, total)}
    index = rng.randrange(len(members))
    if kind == "body":
        index = rng.choice(nonempty)
    start = offsets[index]
    member = members[index]
    record: dict[str, Any] = {"kind": kind, "member": index}
    if kind in ("crc", "isize"):
        damaged = bytearray(wire)
        base = start + len(member) - (8 if kind == "crc" else 4)
        damaged[base + rng.randrange(4)] ^= 1 << rng.randrange(8)
        return bytes(damaged), record
    if kind == "truncate":
        want_boundary = rng.random() < 0.5 if text else None
        for _attempt in range(64):
            cut = start + rng.randrange(1, len(member))
            record["cut"] = cut
            if text is None:
                break
            prefix_end = _truncated_payload_end(members, payloads, offsets, index, cut)
            on_boundary = _character_boundary(
                text["encoding"], b"".join(payloads)[:prefix_end]
            )
            if on_boundary == want_boundary:
                record["character_boundary"] = on_boundary
                break
        else:
            record["character_boundary"] = on_boundary
        return wire[: record["cut"]], record
    # Body corruption: overwrite bytes inside the DEFLATE body until every
    # available engine reports an error under the reference schedule.
    body_start, body_end = start + 10, start + len(member) - 8
    for reroll in range(MAX_BODY_REROLLS):
        damaged = bytearray(wire)
        span = rng.choice((1, 4, 16, 64))
        at = rng.randrange(body_start, max(body_start + 1, body_end - span))
        damaged[at : at + span] = rng.randbytes(min(span, body_end - at))
        body = bytes(damaged[body_start:body_end])
        if not all(_detects(m, body) for m in engine_modules().values()):
            continue
        references = {
            name: raw_reference(module, body)
            for name, module in engine_modules().items()
        }
        if all(ref["error"] is not None for ref in references.values()):
            if text is not None and not _text_reference_valid(
                text, payloads, index, references
            ):
                continue
            record.update(
                at=at,
                span=span,
                rerolls=reroll,
                body_start=body_start,
                body_end=body_end,
                detected_by=sorted(references),
            )
            return bytes(damaged), record
    # No detected corruption in the budget: record the downgrade honestly.
    return wire, {"kind": "none", "downgraded_from": "body"}


def _detects(module, body: bytes) -> bool:
    """Cheap pre-check; agrees with the reference schedule's error outcome."""
    try:
        module.decompressobj(-15).decompress(body)
    except module.error:
        return True
    return False


def _text_reference_valid(text, payloads, index, references) -> bool:
    """Text body corruption is kept only if every reference decodes cleanly."""
    before = b"".join(payloads[:index])
    for reference in references.values():
        decoder = codecs.getincrementaldecoder(text["encoding"])()
        try:
            decoder.decode(before + reference["output"], final=False)
        except UnicodeError:
            return False
    return True


def _truncated_payload_end(members, payloads, offsets, index, cut) -> int:
    """Payload end a clean decode of the member truncated at ``cut`` reaches."""
    start = sum(len(p) for p in payloads[:index])
    body_start = offsets[index] + 10
    body_end = offsets[index] + len(members[index]) - 8
    body = b""
    if cut > body_start:
        wire = b"".join(members_with_padding(members, offsets))
        body = wire[body_start : min(cut, body_end)]
    produced = len(raw_reference(zlib, body)["output"])
    return start + min(produced, len(payloads[index]))


def members_with_padding(members: list[bytes], offsets: list[int]) -> list[bytes]:
    """Members interleaved with the NUL padding implied by ``offsets``."""
    parts, position = [], 0
    for member, offset in zip(members, offsets, strict=True):
        parts.append(b"\0" * (offset - position))
        parts.append(member)
        position = offset + len(member)
    return parts


def member_spans(
    members: list[bytes],
    offsets: list[int],
    corruption: dict[str, Any],
    written: int,
) -> list[list[int]]:
    """Each member's ``[start, end)`` in the wire as written.

    ``written`` is the damaged wire's length before trailing padding. A
    truncated member ends at the cut, which is EOF, and the members after it
    are not in the wire. A body corruption whose span runs past the body
    replaces it with fewer bytes, shortening its member. Padding is whatever
    no span covers. A deletion that runs past that member's trailer leaves
    the rest of the wire as unparsed damage, so the member's span then runs
    to the end of the written wire and no later span is recorded. Recorded
    in the scenario so the lossy-input predicate never depends on
    regeneration.
    """
    spans = [[o, o + len(m)] for m, o in zip(members, offsets, strict=True)]
    clean = spans[-1][1] if spans else 0
    if corruption["kind"] == "body" and written < clean:
        index, shrink = corruption["member"], clean - written
        deleted_end = min(corruption["at"] + corruption["span"], clean)
        if deleted_end > spans[index][1]:
            return spans[:index] + [[spans[index][0], written]]
        spans[index][1] -= shrink
        for span in spans[index + 1 :]:
            span[0] -= shrink
            span[1] -= shrink
    if corruption["kind"] == "truncate":
        index = corruption["member"]
        spans = spans[: index + 1]
        spans[index][1] = corruption["cut"]
    return spans


def _layout(rng: random.Random, members: list[bytes]) -> list[int]:
    offsets, position = [], 0
    for member in members:
        if position and rng.random() < 0.15:
            position += rng.choice((1, 4, 512))
        offsets.append(position)
        position += len(member)
    return offsets


def _frames(rng: random.Random, size: int) -> list[int]:
    if rng.random() < 0.5:
        return []
    frames, total = [], 0
    while total < size:
        step = rng.choice((1, 3, 10, 100, 1000, 10_000))
        frames.append(step)
        total += step
    return frames


def _operations(rng: random.Random, config: dict[str, Any]) -> list[dict[str, Any]]:
    text = config["mode"] == "rt"
    custom = config["source"]["kind"] == "custom"
    native = config["source"]["kind"] == "native"
    # A physical rewind reaches the source (custom seek, or native work), so
    # it can park even when an unhealthy reader refuses every read.
    rewindable = native or config["source"]["seekable"]
    total = config["payload_size"]
    sizes = (-1, 0, 1, 2, 3, 7, 64, 1000, max(1, total // 3))
    if text:
        names = ["read", "readline", "readlines", "next", "tell_mark", "seek_mark"]
        names += ["seek0", "buffer_read"]
    else:
        names = ["read", "read1", "readinto", "peek", "readline", "readlines"]
        names += ["next", "tell", "seek_abs", "seek_rel", "seek_back", "seek0"]
    events = ["overlap", "close_during", "cancel"]
    if custom:
        events += ["fail_no_effect", "fail_consumed"]
    ops: list[dict[str, Any]] = []
    marks = 0
    for _ in range(rng.randrange(1, 14)):
        if rng.random() < 0.15 and (custom or native):
            name = rng.choice(events)
        elif rng.random() < 0.03:
            name = "open"  # already open: ValueError, no state change
        else:
            name = rng.choice(names)
        op: dict[str, Any] = {"op": name}
        if name in ("read", "read1", "peek", "buffer_read"):
            op["n"] = rng.choice(sizes)
        elif name == "readinto":
            op["n"] = rng.choice((0, 1, 5, 64, 4096))
        elif name == "readline":
            op["limit"] = rng.choice((-1, -1, 0, 1, 3, 40))
        elif name == "readlines":
            op["hint"] = rng.choice((-1, 0, 1, 50))
        elif name == "seek_abs":
            op["target"] = rng.randrange(total + 2)
        elif name == "seek_rel":
            op["delta"] = rng.choice((0, 1, 5, 100))
        elif name == "seek_back":
            op["back"] = rng.choice((1, 10, 1000))
        elif name == "tell_mark":
            op["label"] = f"m{marks}"
            marks += 1
        elif name == "seek_mark":
            if not marks:
                op = {"op": "seek0"}
            else:
                op["label"] = f"m{rng.randrange(marks)}"
        elif name in ("overlap", "close_during", "cancel"):
            op["call"] = _blocking_call(rng, text, rewindable)
            if name == "overlap":
                op["second"] = _blocking_call(rng, text)
        ops.append(op)
    end = rng.random()
    if (
        config["acquisition"]["enter"] == "async_with"
        and end < 0.2
        and (custom or native)
    ):
        ops.append({"op": "abort", "call": _blocking_call(rng, text, rewindable)})
    elif config["acquisition"]["enter"] == "async_with" and end < 0.35:
        ops.append({"op": "raise_exit"})
    elif end < 0.7:
        ops.append({"op": "close"})
    # Post-close probes: every surface must refuse a closed handle.
    if ops[-1]["op"] in ("close", "abort", "raise_exit"):
        if rng.random() < 0.5:
            ops.append({"op": rng.choice(("read", "readline", "close", "open"))})
            if ops[-1]["op"] == "read":
                ops[-1]["n"] = -1
            elif ops[-1]["op"] == "readline":
                ops[-1]["limit"] = -1
    return ops


def _blocking_call(
    rng: random.Random, text: bool, rewindable: bool = False
) -> dict[str, Any]:
    if rewindable and rng.random() < 0.25:
        return {"op": "seek0"}
    if text:
        return rng.choice(({"op": "read", "n": -1}, {"op": "readline", "limit": -1}))
    return rng.choice(
        (
            {"op": "read", "n": -1},
            {"op": "read", "n": 100_000},
            {"op": "readline", "limit": -1},
            {"op": "read1", "n": 100_000},
        )
    )


def generate(seed: int) -> dict[str, Any]:
    rng = random.Random(seed)
    if rng.random() < WRITE_SHARE:
        return _generate_write(rng, seed)
    text_mode = rng.random() < 0.4
    text = None
    if text_mode:
        encoding = rng.choice(ENCODINGS)
        newline = rng.choice(NEWLINES)
        source_text = _text_payload(rng, encoding, rng.choice((0, 5, 200, 3000)))
        whole = source_text.encode(encoding)
        text = {"encoding": encoding, "newline": newline}
    else:
        whole = _binary_payload(rng, rng.choice((0, 1, 50, 2000, 40_000, 300_000)))
    payloads = _split(rng, whole)
    members = [_member(rng, payload) for payload in payloads]
    offsets = _layout(rng, members)
    trailing = b"\0" * rng.choice((0, 0, 0, 1, 7))
    wire, corruption = _choose_corruption(rng, members, payloads, offsets, text)
    spans = member_spans(members, offsets, corruption, len(wire))
    if corruption["kind"] in ("none", "limit", "crc", "isize", "body"):
        wire += trailing
    kind = rng.choices(("custom", "native"), weights=(3, 1))[0]
    source: dict[str, Any] = {"kind": kind}
    if kind == "custom":
        source["seekable"] = rng.random() < 0.5
        source["checkpoint"] = rng.random() < 0.5
        source["frames"] = _frames(rng, len(wire))
        source["closefd"] = rng.random() < 0.5
    config: dict[str, Any] = {
        "schema": SCHEMA,
        "seed": seed,
        "mode": "rt" if text_mode else "rb",
        "text": text,
        "chunk_size": rng.choice(CHUNK_SIZES),
        "source": source,
        "acquisition": {
            "construct": rng.choice(("class", "factory")),
            "enter": rng.choice(("open", "async_with")),
        },
        "payload_size": len(whole),
        "payloads": [b64(p) for p in payloads],
        "member_offsets": offsets,
        "member_spans": spans,
        "corruption": corruption,
        "wire": b64(wire),
    }
    if corruption["kind"] == "limit":
        config["max_decompressed_size"] = corruption["limit"]
    if source["kind"] == "custom" and not source["seekable"]:
        config["max_rewind_cache_size"] = rng.choice((None, None, 16))
    config["acquisition"]["fault"] = _acquisition_fault(rng, config)
    if config["acquisition"]["fault"] in ("missing", "directory"):
        # The open fails, so the body probes the unopened handle, retries the
        # open, then closes it.
        config["ops"] = [
            {"op": "read", "n": -1},
            {"op": "open"},
            {"op": "close"},
            {"op": "read", "n": -1},
        ]
    else:
        config["ops"] = _operations(rng, config)
    return config


def _acquisition_fault(rng: random.Random, config: dict[str, Any]) -> str:
    """Choose an opening fault. Faults use explicit ``open()`` only.

    A parked open waits in the native acquisition (executor) or, for custom
    sources, in the first awaited source call (``seekable()`` for readers,
    the header ``write()`` for writers).
    """
    if config["acquisition"]["enter"] != "open" or rng.random() >= 0.2:
        return "none"
    faults = ["cancel_open", "overlap_open", "overlap_close"]
    if config["source"]["kind"] == "native":
        faults += ["missing", "directory"]
    elif config["mode"] in ("wb", "wt"):
        faults.append("init_fail")
    return rng.choice(faults)


def body_member_bytes(scenario: dict[str, Any]) -> bytes:
    corruption = scenario["corruption"]
    wire = unb64(scenario["wire"])
    return wire[corruption["body_start"] : corruption["body_end"]]


def write_payload(spec: dict[str, Any], text: dict[str, Any] | None) -> Any:
    """Deterministic payload for a write spec (``size`` units from ``seed``)."""
    rng = random.Random(spec["seed"])
    if text is None:
        return rng.randbytes(spec["size"])
    return "".join(rng.choices(TEXT_ALPHABET[text["encoding"]], k=spec["size"]))


def _write_spec(
    rng: random.Random, sizes: tuple[int, ...] = WRITE_SIZES
) -> dict[str, Any]:
    return {"size": rng.choice(sizes), "seed": rng.randrange(2**32)}


def _write_blocking_call(rng: random.Random) -> dict[str, Any]:
    # Encoder output is batched, so only a flush is sure to reach the sink;
    # the call parks in the flush's sink write.
    return {"op": "write_flush", **_write_spec(rng, (1, 1000))}


def _write_call(rng: random.Random) -> dict[str, Any]:
    name = rng.choice(("write", "write", "writelines", "flush"))
    if name == "write":
        return {"op": "write", **_write_spec(rng)}
    if name == "writelines":
        return {
            "op": "writelines",
            "parts": [_write_spec(rng) for _ in range(rng.randrange(4))],
        }
    return {"op": "flush"}


def _write_operations(
    rng: random.Random, config: dict[str, Any]
) -> list[dict[str, Any]]:
    custom = config["source"]["kind"] == "custom"
    events = ["overlap", "close_during", "cancel"]
    if custom:
        events += ["fail_sink_no_effect", "fail_sink_partial"]
    ops: list[dict[str, Any]] = []
    for _ in range(rng.randrange(1, 12)):
        roll = rng.random()
        if roll < 0.2:
            name = rng.choice(events)
            op: dict[str, Any] = {"op": name}
            if name in ("overlap", "close_during", "cancel"):
                op["call"] = _write_blocking_call(rng)
                if name == "overlap":
                    op["second"] = _write_call(rng)
        elif roll < 0.23:
            op = {"op": "open"}
        else:
            op = _write_call(rng)
        ops.append(op)
    end = rng.random()
    if config["acquisition"]["enter"] == "async_with" and end < 0.2:
        ops.append({"op": "abort", "call": _write_blocking_call(rng)})
    elif config["acquisition"]["enter"] == "async_with" and end < 0.35:
        ops.append({"op": "raise_exit"})
    elif end < 0.7:
        ops.append({"op": "close"})
    if ops[-1]["op"] in ("close", "abort", "raise_exit") and rng.random() < 0.5:
        probe = rng.choice(("write", "flush", "close", "open"))
        ops.append(
            {"op": probe, **_write_spec(rng)} if probe == "write" else {"op": probe}
        )
    return ops


def _generate_write(rng: random.Random, seed: int) -> dict[str, Any]:
    text = None
    if rng.random() < 0.4:
        text = {"encoding": rng.choice(ENCODINGS), "newline": rng.choice(NEWLINES)}
    kind = rng.choices(("custom", "native"), weights=(3, 1))[0]
    source: dict[str, Any] = {"kind": kind}
    if kind == "custom":
        source["closefd"] = rng.random() < 0.5
        source["short"] = rng.choice(SHORT_WRITES)
    config: dict[str, Any] = {
        "schema": SCHEMA,
        "seed": seed,
        "mode": "wt" if text else "wb",
        "text": text,
        "chunk_size": rng.choice(CHUNK_SIZES),
        "source": source,
        "acquisition": {
            "construct": rng.choice(("class", "factory")),
            "enter": rng.choice(("open", "async_with")),
        },
    }
    config["acquisition"]["fault"] = _acquisition_fault(rng, config)
    if config["acquisition"]["fault"] in ("missing", "directory"):
        config["ops"] = [
            {"op": "write", **_write_spec(rng)},
            {"op": "open"},
            {"op": "close"},
            {"op": "write", **_write_spec(rng)},
        ]
    else:
        config["ops"] = _write_operations(rng, config)
    return config
