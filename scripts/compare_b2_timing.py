#!/usr/bin/env python3
"""Report four declared G06/G08 throughput blocks; never close a gate.

Input JSON: gate (G06/G08), sources {A: sha, B: sha}, row_count, sampling,
repeat, max_block_seconds, and blocks.
Each block has status (complete/rejected/unstarted), reason for non-complete,
and captures [{side: A/B, path: relative-to-index}]. Complete block orders must
be ABBA, BAAB, ABBA, BAAB. Rejected data is referenced but excluded from summaries.
Use a separate index per engine. This report does not attest host quietness.
"""

import argparse
import hashlib
import json
import math
import statistics
from pathlib import Path


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True)


def positive(value):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError("timings must be finite and positive")
    return value


def summarize(blocks):
    complete = [b for b in blocks if b.get("ratio") is not None]
    usable = [b for b in complete if max(b["a_drift"], b["b_drift"]) <= 0.02]
    median = statistics.median(b["ratio"] for b in complete) if complete else None
    signs = {
        0
        if math.isclose(b["ratio"], 1, abs_tol=1e-12)
        else (1 if b["ratio"] > 1 else -1)
        for b in usable
    }
    conclusive = len(usable) >= 3 and len(signs) == 1
    largest = max((max(b["a_drift"], b["b_drift"]) for b in complete), default=0)
    return {
        "blocks": blocks,
        "complete_blocks": len(complete),
        "usable_blocks": len(usable),
        "median_ratio": median,
        "investigate": median is not None and median > 1.05,
        "stronger_slowdown_evidence": bool(
            conclusive
            and median > 1.05
            and median - 1 > 2 * largest
            and sum(b["ratio"] > 1.05 for b in complete) >= 3
        ),
        "disposition": "review-required" if conclusive else "inconclusive",
    }


def row_values(capture, gate):
    config = capture["sampling"]
    discard = config["discard_samples"]
    if type(discard) is not int or discard < 0:
        raise ValueError("invalid discard count")
    if gate == "G08" and (not config["throughput_only"] or config["latency_only"]):
        raise ValueError("G08 comparison requires throughput-only captures")
    if gate == "G06" and capture["phase"] != "timing":
        raise ValueError("G06 comparison requires timing captures")
    rows = {}
    for row in capture["rows"]:
        identity = (
            {
                k: row[k]
                for k in (
                    "case",
                    "fixture",
                    "direction",
                    "payload_sha256",
                    "input_sha256",
                )
            }
            if gate == "G08"
            else {k: row[k] for k in ("case", "fixture")}
        )
        key = canonical(identity)
        if key in rows:
            raise ValueError("duplicate case")
        samples = row["samples"]
        if len(samples) <= discard:
            raise ValueError("no retained samples")
        times = [positive(s["seconds"]) for s in samples]
        minimum = min(times[discard:])
        if not math.isclose(row["min_seconds"], minimum, rel_tol=1e-12):
            raise ValueError("capture minimum disagrees with retained samples")
        rows[key] = (identity, minimum, len(samples))
    return rows


def compare(index, directory):
    gate = index["gate"]
    if gate not in ("G06", "G08") or len(index["blocks"]) != 4:
        raise ValueError("expected G06/G08 and four block slots")
    if set(index["sources"]) != {"A", "B"} or not all(index["sources"].values()):
        raise ValueError("declare both source commits")
    if index["sources"]["A"] == index["sources"]["B"]:
        raise ValueError("baseline and candidate must be distinct")
    if type(index["repeat"]) is not int or index["repeat"] < 1:
        raise ValueError("invalid expected repeat count")
    if type(index["row_count"]) is not int or index["row_count"] < 1:
        raise ValueError("invalid expected row count")
    expected_sampling = index["sampling"]
    if not isinstance(expected_sampling, dict):
        raise ValueError("declare expected sampling settings")
    positive(expected_sampling["batch_seconds"])
    positive(expected_sampling["warmup_seconds"])
    if (
        type(expected_sampling["discard_samples"]) is not int
        or not 0 < expected_sampling["discard_samples"] < index["repeat"]
    ):
        raise ValueError("declare discarded and retained samples")
    if (
        type(expected_sampling["batch_min_operations"]) is not int
        or expected_sampling["batch_min_operations"] < 1
    ):
        raise ValueError("invalid minimum operation count")
    positive(index["max_block_seconds"])
    previous_end = None
    reference = None
    keys = None
    block_rows = []
    evidence = []
    seen = set()
    for number, block in enumerate(index["blocks"]):
        status = block["status"]
        if status not in ("complete", "rejected", "unstarted"):
            raise ValueError("unknown block status")
        if status != "complete":
            if not block.get("reason"):
                raise ValueError("non-complete block requires reason")
            block_rows.append(None)
            continue
        order = "ABBA" if number % 2 == 0 else "BAAB"
        if "".join(c["side"] for c in block["captures"]) != order:
            raise ValueError("incorrect block order")
        captures = []
        block_started = None
        for entry in block["captures"]:
            path = (directory / entry["path"]).resolve()
            if path in seen:
                raise ValueError("capture reused")
            seen.add(path)
            raw = path.read_bytes()
            capture = json.loads(raw)
            started, ended = (
                positive(capture["started_at"]),
                positive(capture["ended_at"]),
            )
            if ended < started or (previous_end is not None and started < previous_end):
                raise ValueError("captures overlap or violate declared chronology")
            previous_end = ended
            if block_started is None:
                block_started = started
            if ended - block_started > index["max_block_seconds"]:
                raise ValueError("block exceeds declared session span")
            if capture["sampling"] != expected_sampling:
                raise ValueError("capture does not match declared sampling")
            if (
                capture["source"]["sha"] != index["sources"][entry["side"]]
                or capture["source"]["status"]
            ):
                raise ValueError("source provenance mismatch")
            if not capture["harness"]["sha"] or capture["harness"]["status"]:
                raise ValueError("unclean harness")
            common = {
                k: capture[k]
                for k in (
                    "harness",
                    "harness_sha256",
                    "python",
                    "platform",
                    "engines",
                    "affinity",
                    "sampling",
                )
            }
            common["dependencies"] = (
                capture["dependencies"]
                if gate == "G06"
                else {
                    "aiofiles": capture["aiofiles"],
                    "compression_engine_module": capture["compression_engine_module"],
                    "fast_compress": capture["fast_compress"],
                }
            )
            if reference is None:
                reference = common
            elif common != reference:
                raise ValueError("capture environment or protocol mismatch")
            values = row_values(capture, gate)
            signature = {k: v[2] for k, v in values.items()}
            if any(count != index["repeat"] for count in signature.values()):
                raise ValueError("capture does not match declared repeat count")
            if len(values) != index["row_count"]:
                raise ValueError("case count mismatch")
            if keys is None:
                keys = signature
            elif signature != keys:
                raise ValueError("case matrix or sample count mismatch")
            captures.append((entry["side"], values))
            evidence.append(
                dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest())
            )
        block_rows.append(captures)
    rows = []
    for key in keys or {}:
        measurements = []
        for number, captures in enumerate(block_rows):
            if captures is None:
                measurements.append(
                    dict(block=number, status=index["blocks"][number]["status"])
                )
                continue
            a = [values[key][1] for side, values in captures if side == "A"]
            b = [values[key][1] for side, values in captures if side == "B"]
            measurements.append(
                dict(
                    block=number,
                    status="complete",
                    a_minima=a,
                    b_minima=b,
                    ratio=math.exp((sum(map(math.log, b)) - sum(map(math.log, a))) / 2),
                    a_drift=max(a) / min(a) - 1,
                    b_drift=max(b) / min(b) - 1,
                )
            )
        rows.append(dict(identity=json.loads(key), **summarize(measurements)))
    return dict(
        gate=gate,
        index=index,
        evidence=evidence,
        common=reference,
        rows=rows,
        limitations="Operational screens, not confidence intervals. Rejected blocks excluded explicitly. No host-policy attestation or automatic gate closure. Empty rows mean no complete evidence. G07 and scheduling require descriptive review separately.",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("index", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = args.index.read_bytes()
    report = compare(json.loads(raw), args.index.resolve().parent)
    report["index_sha256"] = hashlib.sha256(raw).hexdigest()
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(report, output, indent=2, allow_nan=False)
        output.write("\n")


if __name__ == "__main__":
    main()
