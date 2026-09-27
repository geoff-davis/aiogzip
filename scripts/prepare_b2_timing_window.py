#!/usr/bin/env python3
"""Prepare a WP5 timing manifest without scheduling or launching it.

Omitting both window timestamps produces a deliberately non-runnable draft.
Use clean checkouts and one copied environment; review before freezing a window.
"""

import argparse
import json
from pathlib import Path

from capture_file_state_trace import git_metadata
from run_b2_timing_blocks import POLICY, digest, validate


def prepare(
    *,
    gate,
    engine,
    baseline,
    candidate,
    harness,
    runner,
    python,
    output,
    service,
    not_before=None,
    deadline=None,
    cpu=13,
):
    paired = gate != "G07"
    roots = {candidate, harness, runner}
    if paired:
        if baseline is None:
            raise ValueError("paired gate requires baseline")
        roots.add(baseline)
    checkouts = {}
    for root in roots:
        meta = git_metadata(root)
        if not meta["sha"] or meta["status"]:
            raise ValueError(f"unclean checkout: {root}")
        checkouts[str(root)] = meta["sha"]
    manifest = dict(
        schema=1,
        scope=gate,
        service=service,
        not_before=not_before,
        deadline=deadline,
        output=str(output),
        cpu=cpu,
        quiet_policy=dict(POLICY),
        checkouts=checkouts,
        files={
            str(python): digest(python),
            str(runner / "uv.lock"): digest(runner / "uv.lock"),
        },
        command_timeout_seconds=1800,
        block_timeout_seconds=3600 if gate == "G06" else 1800,
        minimum_measurement_seconds=10800 if gate == "G06" else 1800,
        warmups=[],
        blocks=[],
    )
    throughput = gate in ("G06", "G08-throughput")
    sampling = dict(
        warmup_seconds=0.25,
        batch_seconds=0.1,
        batch_min_operations=3,
        discard_samples=2,
    )
    if gate == "G08-throughput":
        sampling.update(throughput_only=True, latency_only=False)

    def command(name, side, selected_engine=engine):
        source = baseline if side == "A" else candidate
        script = {
            "G06": "measure_b2_long_lines.py",
            "G07": "measure_b2_read_resources.py",
            "G08-throughput": "measure_b2_stream_fairness.py",
            "G08-scheduling": "measure_b2_stream_fairness.py",
        }[gate]
        argv = [
            "/usr/bin/taskset",
            "-c",
            str(cpu),
            str(python),
            str(harness / "scripts" / script),
            "--source-root",
            str(source),
            "--engine",
            selected_engine,
        ]
        if gate == "G06":
            argv += ["--phase", "timing"]
        if gate == "G07":
            argv += ["--phase", "latency"]
        if gate == "G08-throughput":
            argv += ["--throughput-only"]
        if gate == "G08-scheduling":
            argv += ["--latency-only"]
        argv += ["--repeat", str(9 if throughput else (1 if gate == "G07" else 7))]
        if throughput:
            argv += [
                "--warmup-seconds",
                ".25",
                "--batch-seconds",
                ".1",
                "--batch-min-operations",
                "3",
                "--discard-samples",
                "2",
            ]
        argv += ["--output", "{capture}"]
        return dict(output=name, side=side, engine=selected_engine, argv=argv)

    if throughput:
        manifest["warmups"] = [
            command(f"warmup-{side}.json", side) for side in ("A", "B")
        ]
    if gate == "G07":
        for number in range(7):
            engines = (
                ("stdlib", "zlib-ng") if number % 2 == 0 else ("zlib-ng", "stdlib")
            )
            manifest["blocks"].append(
                dict(
                    id=f"round-{number}",
                    commands=[
                        command(f"round-{number}-{e}.json", "B", e) for e in engines
                    ],
                )
            )
    else:
        for number, order in enumerate(("ABBA", "BAAB", "ABBA", "BAAB")):
            manifest["blocks"].append(
                dict(
                    id=f"block-{number}",
                    commands=[
                        command(f"block-{number}-{j}-{side}.json", side)
                        for j, side in enumerate(order)
                    ],
                )
            )
    if throughput:
        manifest["comparison"] = dict(
            gate="G06" if gate == "G06" else "G08",
            sources={
                s: checkouts[str(r)] for s, r in [("A", baseline), ("B", candidate)]
            },
            row_count=175 if gate == "G06" else 16,
            sampling=sampling,
            repeat=9,
            max_block_seconds=manifest["block_timeout_seconds"],
        )
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--gate",
        required=True,
        choices=("G06", "G07", "G08-throughput", "G08-scheduling"),
    )
    parser.add_argument("--engine", default="stdlib", choices=("stdlib", "zlib-ng"))
    for key in ("candidate", "harness", "python", "output", "manifest"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--service", required=True)
    parser.add_argument("--not-before")
    parser.add_argument("--deadline")
    args = parser.parse_args()
    if bool(args.not_before) != bool(args.deadline):
        parser.error("provide both timestamps or neither")
    runner = Path(__file__).resolve().parents[1]
    record = prepare(
        gate=args.gate,
        engine=args.engine,
        baseline=args.baseline.resolve() if args.baseline else None,
        candidate=args.candidate.resolve(),
        harness=args.harness.resolve(),
        runner=runner,
        python=args.python.absolute(),
        output=args.output.absolute(),
        service=args.service,
        not_before=args.not_before,
        deadline=args.deadline,
    )
    if args.deadline:
        validate(record, fresh=True)
    with args.manifest.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, indent=2)
        stream.write("\n")
    print("Manifest prepared; nothing scheduled or launched.")


if __name__ == "__main__":
    main()
