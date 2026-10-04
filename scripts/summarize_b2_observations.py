#!/usr/bin/env python3
"""Descriptive G06 scaling and G07/G08 scheduling summaries, never gate decisions."""

import argparse
import json
import math
import statistics
from pathlib import Path


def key(value):
    return json.dumps(value, sort_keys=True)


def distribution(values):
    if not values or any(
        isinstance(v, bool)
        or not isinstance(v, (int, float))
        or not math.isfinite(v)
        or v < 0
        for v in values
    ):
        raise ValueError("expected nonempty finite nonnegative observations")
    return dict(
        count=len(values),
        minimum=min(values),
        median=statistics.median(values),
        maximum=max(values),
        values=values,
    )


def scaling(report):
    if report["gate"] != "G06":
        raise ValueError("scaling requires a G06 comparison report")
    families = {}
    for row in report["rows"]:
        case = dict(row["identity"]["case"])
        size = case.pop("size")
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            raise ValueError("invalid input size")
        sizes = families.setdefault(key(case), {})
        if size in sizes:
            raise ValueError("ambiguous duplicate size in family")
        sizes[size] = row
    rows = []
    for family, sizes in families.items():
        for size, small in sorted(sizes.items()):
            if 2 * size not in sizes:
                continue
            large = sizes[2 * size]
            large_blocks = {b["block"]: b for b in large["blocks"]}
            for side in ("a", "b"):
                pairs = []
                for lo in small["blocks"]:
                    hi = large_blocks.get(lo["block"])
                    if (
                        lo["status"] != "complete"
                        or not hi
                        or hi["status"] != "complete"
                    ):
                        continue
                    low, high = lo[side + "_minima"], hi[side + "_minima"]
                    if len(low) != len(high):
                        raise ValueError("capture positions differ")
                    if any(v <= 0 or not math.isfinite(v) for v in [*low, *high]):
                        raise ValueError("invalid minima")
                    pairs.append(
                        dict(
                            block=lo["block"],
                            ratios=[b / a for a, b in zip(low, high, strict=True)],
                        )
                    )
                values = [v for p in pairs for v in p["ratios"]]
                rows.append(
                    dict(
                        family=json.loads(family),
                        source=side.upper(),
                        small_size=size,
                        large_size=2 * size,
                        paired_capture_ratios=pairs,
                        summary=distribution(values) if values else None,
                        input_dispositions=[small["disposition"], large["disposition"]],
                    )
                )
    return dict(
        kind="G06 scaling",
        rows=rows,
        limitations="Matched sizes and capture positions only. Ratios describe measured sizes, not a universal complexity proof. No exclusion of noisy complete blocks; input dispositions retained. No gate closure.",
    )


def observations(captures, gate):
    if gate not in ("G07", "G08-scheduling"):
        raise ValueError("unsupported observation gate")
    groups = {}
    names = set()
    for name, capture in captures:
        if name in names:
            raise ValueError("duplicate capture input")
        names.add(name)
        provenance = {
            k: capture[k]
            for k in (
                "source",
                "harness",
                "harness_sha256",
                "python",
                "platform",
                "engines",
                "aiofiles",
            )
        }
        for root in ("source", "harness"):
            if not provenance[root]["sha"] or provenance[root]["status"]:
                raise ValueError("unclean capture")
        provenance["affinity"] = capture.get(
            "affinity", capture.get("host", {}).get("cpu_affinity")
        )
        if gate == "G08-scheduling":
            config = capture["sampling"]
            if (
                not config["latency_only"]
                or config["throughput_only"]
                or config["discard_samples"]
                or config["warmup_seconds"]
                or config["batch_seconds"]
            ):
                raise ValueError("scheduling requires undiscarded latency-only samples")
            provenance["sampling"] = config
        for row in capture["rows"]:
            identity = {k: row[k] for k in ("case", "fixture")}
            if gate == "G08-scheduling":
                if not row["case"].startswith("latency-"):
                    raise ValueError("throughput row in scheduling data")
                identity.update(
                    {k: row[k] for k in ("direction", "payload_sha256", "input_sha256")}
                )
                entries = [
                    dict(capture=name, sample=i, **s)
                    for i, s in enumerate(row["samples"])
                ]
                metrics = (
                    "seconds",
                    "ticks",
                    "ticks_before_final_item",
                    "max_gap_seconds",
                    "p99_gap_seconds",
                    "max_items_between_ticks",
                )
            else:
                if row["phase"] != "latency":
                    raise ValueError("resource row cannot supply latency")
                entries = [
                    dict(
                        capture=name,
                        repeat=row["repeat"],
                        cohort_seconds=row["cohort_seconds"],
                        ticker_ticks=row["ticker_ticks"],
                        max_gap_seconds=row["max_gap_seconds"],
                        p99_gap_seconds=row["p99_gap_seconds"],
                        handles=row["handles"],
                    )
                ]
                metrics = (
                    "cohort_seconds",
                    "ticker_ticks",
                    "max_gap_seconds",
                    "p99_gap_seconds",
                )
            group = groups.setdefault(
                key([provenance, identity]),
                dict(
                    provenance=provenance,
                    identity=identity,
                    observations=[],
                    metrics=metrics,
                ),
            )
            group["observations"].extend(entries)
    result = []
    for group in groups.values():
        metrics = group.pop("metrics")
        entries = group["observations"]
        group["summary"] = {m: distribution([e[m] for e in entries]) for m in metrics}
        if gate == "G07":
            handles = {}
            for entry in entries:
                for position, handle in enumerate(entry["handles"]):
                    outcome = (
                        "error:" + handle["error"]["type"]
                        if handle["error"]
                        else (
                            "eof"
                            if handle["returned"] == 0 and handle["binary_eof"]
                            else "output"
                        )
                    )
                    ident = key([position, outcome])
                    bucket = handles.setdefault(
                        ident,
                        dict(handle_position=position, outcome=outcome, seconds=[]),
                    )
                    bucket["seconds"].append(handle["first_result_seconds"])
            group["first_result_by_handle_and_outcome"] = [
                dict(
                    handle_position=h["handle_position"],
                    outcome=h["outcome"],
                    summary=distribution(h["seconds"]),
                )
                for h in handles.values()
            ]
        result.append(group)
    return dict(
        kind=gate,
        rows=result,
        limitations="Descriptive distributions, not throughput ratios or statistical confidence. Provenance, fixture, source and engine groups remain separate. Every input sample retained, including zero-tick starvation. Per-handle times exclude initial task scheduling; cohort time includes it. First-read setup warms the pinned core. No gate closure or preemption guarantee.",
    )


def markdown(report):
    lines = [
        "# " + report.get("kind", report.get("gate", "Timing report")),
        "",
        report["limitations"],
        "",
    ]
    if report.get("kind") == "G06 scaling":
        lines += [
            "| Source | Family | Sizes | Median doubling ratio | Input dispositions |",
            "| --- | --- | --- | ---: | --- |",
        ]
        for row in report["rows"]:
            median = row["summary"]["median"] if row["summary"] else None
            lines.append(
                f"| {row['source']} | {key(row['family'])} | {row['small_size']} → {row['large_size']} | {median} | {', '.join(row['input_dispositions'])} |"
            )
    else:
        lines += [
            "| Group | Metric | N | Min | Median | Max |",
            "| --- | --- | ---: | ---: | ---: | ---: |",
        ]
        for i, row in enumerate(report["rows"]):
            for metric, stats in row["summary"].items():
                lines.append(
                    f"| {i} | {metric} | {stats['count']} | {stats['minimum']:.6g} | {stats['median']:.6g} | {stats['maximum']:.6g} |"
                )
        lines += [
            "",
            "Group identities and raw values are retained in the companion JSON.",
        ]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--gate", choices=("G06", "G07", "G08-scheduling"), required=True
    )
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    captures = [
        (str(p), json.loads(p.read_text(encoding="utf-8"))) for p in args.inputs
    ]
    if args.gate == "G06" and len(captures) != 1:
        parser.error("G06 requires one comparison report")
    report = (
        scaling(captures[0][1])
        if args.gate == "G06"
        else observations(captures, args.gate)
    )
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(report, output, indent=2, allow_nan=False)
        output.write("\n")
    print(markdown(report))


if __name__ == "__main__":
    main()
