#!/usr/bin/env python3
"""Archive a stopped timing run and prepare a review bundle without scheduling.

Raw bytes are preserved before analysis. Corrupt/inconsistent evidence is archived
with analysis errors, never converted into a passing report. A live run is refused.
"""

import argparse
import hashlib
import json
import shutil
import tempfile
from pathlib import Path

from compare_b2_timing import compare
from summarize_b2_observations import markdown, observations, scaling

TERMINAL = {"complete", "incomplete", "deferred", "failed"}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save(path, value):
    path.write_text(
        json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


def inventory(directory):
    result = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError("run archive cannot follow symlinks")
        if path.is_file():
            result[str(path.relative_to(directory))] = digest(path.read_bytes())
        elif not path.is_dir():
            raise ValueError("run archive requires regular files")
    return result


def reconcile(manifest, state, raw):
    if state["manifest"] != manifest:
        raise ValueError("status manifest mismatch")
    definitions = manifest["blocks"]
    slots = state["blocks"]
    if len(definitions) != len(slots):
        raise ValueError("block count mismatch")
    accepted = []
    index = dict(manifest.get("comparison", {}), blocks=[])
    for definition, slot in zip(definitions, slots, strict=True):
        if definition["id"] != slot["id"]:
            raise ValueError("block identity mismatch")
        status = slot["status"]
        if status not in ("complete", "rejected", "unstarted"):
            raise ValueError("active or invalid block status")
        if status == "unstarted" and slot["captures"]:
            raise ValueError("started block labelled unstarted")
        if status != "complete" and not slot.get("reason"):
            raise ValueError("non-complete block needs reason")
        commands = definition["commands"]
        entries = []
        for command in commands:
            name = command["output"]
            if Path(name).name != name:
                raise ValueError("unsafe capture name")
            entries.append(dict(side=command["side"], path=name))
        if status == "complete":
            if len(slot["captures"]) != len(commands):
                raise ValueError("complete block missing capture")
            for command, record in zip(commands, slot["captures"], strict=True):
                name = command["output"]
                path = raw / name
                if record["status"] != "complete" or record["returncode"] != 0:
                    raise ValueError("unsuccessful accepted capture")
                if Path(record["output"]) != Path(manifest["output"]) / name:
                    raise ValueError("capture path mismatch")
                if digest(path.read_bytes()) != record["sha256"]:
                    raise ValueError("accepted capture hash mismatch")
                capture = json.loads(path.read_text(encoding="utf-8"))
                argv = command["argv"]
                source = argv[argv.index("--source-root") + 1]
                expected_source = manifest["checkouts"][source]
                if (
                    capture["source"]["sha"] != expected_source
                    or capture["source"]["status"]
                ):
                    raise ValueError("capture source mismatch")
                if (
                    capture["harness"]["status"]
                    or capture["harness"]["sha"]
                    != manifest["checkouts"][str(Path(argv[4]).parent.parent)]
                ):
                    raise ValueError("capture harness mismatch")
                engine = "stdlib-zlib" if command["engine"] == "stdlib" else "zlib-ng"
                if capture["engines"]["decompression"] != engine:
                    raise ValueError("capture engine mismatch")
                affinity = capture.get(
                    "affinity", capture.get("host", {}).get("cpu_affinity")
                )
                if affinity != [manifest["cpu"]]:
                    raise ValueError("capture affinity mismatch")
                accepted.append((name, capture))
        index["blocks"].append(
            dict(status=status, reason=slot.get("reason"), captures=entries)
        )
    # Warmups must have completed too before any accepted retained evidence.
    if accepted:
        if len(state["warmups"]) != len(manifest["warmups"]):
            raise ValueError("warmup count mismatch")
        for command, record in zip(manifest["warmups"], state["warmups"], strict=True):
            if (
                not record
                or record["status"] != "complete"
                or digest((raw / command["output"]).read_bytes()) != record["sha256"]
            ):
                raise ValueError("warmup evidence mismatch")
    return accepted, index


def continuation_plan(manifest, state):
    if state["status"] not in TERMINAL:
        raise ValueError("run must be stopped before continuation planning")
    if any(b["status"] == "running" for b in state["blocks"]):
        raise ValueError("active slot cannot be resumed")
    eligible = []
    preserved = []
    for definition, slot in zip(manifest["blocks"], state["blocks"], strict=True):
        if slot["id"] != definition["id"]:
            raise ValueError("block identity mismatch")
        if slot["status"] == "unstarted":
            if slot["captures"]:
                raise ValueError("unstarted block contains capture records")
            eligible.append(definition)
        elif slot["status"] in ("complete", "rejected"):
            preserved.append(dict(id=slot["id"], status=slot["status"]))
        else:
            raise ValueError("invalid block status")
    started = bool(preserved)
    exhausted = bool(manifest.get("continuation_of"))
    if state["status"] == "failed":
        action = (
            "investigate-failure-before-continuation"
            if started
            else "investigate-failure-before-new-window"
        )
    elif exhausted:
        action = "continuation-limit-review"
    elif not started:
        action = "new-initial-window-after-review"
    else:
        action = "review-one-continuation" if eligible else "no-unstarted-slots"
    return dict(
        executable=False,
        series_started=started,
        next_action=action,
        failure_investigation_required=state["status"] == "failed",
        eligible_blocks=[] if exhausted or not started else eligible,
        preserved_slots=preserved,
        continuation_allowance_exhausted=bool(manifest.get("continuation_of")),
        requirements=[
            "Investigate any runner failure before considering another window.",
            "A fully deferred initial attempt creates no series; review a new initial window instead.",
            "Explicitly schedule at most one continuation after review.",
            "Keep original slot IDs, command sides and ABBA/BAAB order; never renumber into a new series.",
            "Keep source/harness/environment/CPU/sampling/quiet policy pins; only window, service and output paths may change.",
            "Archive the parent manifest/status hashes and mark continuation_of in the new manifest.",
            "Rerun declared warmups; merge only originally unstarted slots, preserving both windows and all rejected work.",
            "The current generator cannot create a continuation; this is a review plan, not a runnable manifest.",
        ],
    )


def collect(manifest_path, run, destination):
    manifest_path = manifest_path.resolve()
    run = run.resolve()
    destination = destination.absolute()
    if destination.exists() or destination.resolve().is_relative_to(run):
        raise ValueError("fresh destination outside run required")
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    initial_status = (run / "status.json").read_bytes()
    state = json.loads(initial_status)
    if state["status"] not in TERMINAL or any(
        b["status"] == "running" for b in state.get("blocks", [])
    ):
        raise ValueError("refusing active or unsettled run; stop and review it first")
    before = inventory(run)
    if before["status.json"] != digest(initial_status):
        raise ValueError("status changed before snapshot")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(
            prefix=destination.name + ".incomplete-", dir=destination.parent
        )
    )
    raw = temporary / "raw"
    shutil.copytree(run, raw)
    if inventory(raw) != before or inventory(run) != before:
        raise ValueError(
            f"run changed during collection; unverified copy retained at {temporary}"
        )
    (temporary / "manifest.json").write_bytes(manifest_bytes)
    hashes = {f"raw/{name}": sha for name, sha in before.items()}
    hashes["manifest.json"] = digest(manifest_bytes)
    save(temporary / "raw-sha256.json", hashes)
    state = json.loads((raw / "status.json").read_text(encoding="utf-8"))
    errors = []
    artifacts = []
    try:
        if state["manifest_sha256"] != digest(manifest_bytes):
            raise ValueError("manifest hash mismatch")
        accepted, index = reconcile(manifest, state, raw)
        plan = continuation_plan(manifest, state)
        plan.update(
            parent_manifest_sha256=digest(manifest_bytes),
            parent_status_sha256=before["status.json"],
        )
        if "comparison" in manifest:
            if (raw / "comparison-index.json").exists():
                archived = json.loads(
                    (raw / "comparison-index.json").read_text(encoding="utf-8")
                )
                if any(archived.get(k) != v for k, v in index.items()):
                    raise ValueError("runner index disagrees with status")
            save(
                temporary / "comparison-index.json",
                dict(
                    index,
                    blocks=[
                        dict(
                            b,
                            captures=[
                                dict(c, path="raw/" + c["path"]) for c in b["captures"]
                            ],
                        )
                        for b in index["blocks"]
                    ],
                ),
            )
            artifacts.append("comparison-index.json")
            report = compare(index, raw)
            report["index"] = json.loads(
                (temporary / "comparison-index.json").read_text(encoding="utf-8")
            )
            # Avoid temporary absolute archive paths in the durable report.
            for entry in report["evidence"]:
                entry["path"] = "raw/" + Path(entry["path"]).name
            save(temporary / "throughput.json", report)
            artifacts.append("throughput.json")
            if report["gate"] == "G06":
                summary = scaling(report)
                save(temporary / "scaling.json", summary)
                (temporary / "scaling.md").write_text(
                    markdown(summary), encoding="utf-8"
                )
                artifacts += ["scaling.json", "scaling.md"]
        elif accepted:
            report = observations(accepted, manifest["scope"])
            save(temporary / "observations.json", report)
            (temporary / "observations.md").write_text(
                markdown(report), encoding="utf-8"
            )
            artifacts += ["observations.json", "observations.md"]
        save(temporary / "continuation-review.json", plan)
        artifacts.append("continuation-review.json")
    except (
        Exception
    ) as exc:  # Raw evidence already preserved; diagnose analysis failures.
        errors.append(f"{type(exc).__name__}: {exc}")
    review = dict(
        runner_status=state["status"],
        requires_review=True,
        analysis_errors=errors,
        derived_artifacts_trusted=not errors,
        artifacts=artifacts,
        raw_manifest_sha256=digest(manifest_bytes),
        collector_sha256=digest(Path(__file__).read_bytes()),
        analysis_tools={
            name: digest(Path(__file__).with_name(name).read_bytes())
            for name in (
                "collect_b2_timing_window.py",
                "summarize_b2_observations.py",
                "compare_b2_timing.py",
            )
        },
        limitations="Raw files preserved byte-for-byte. Runner status is not a gate decision. No service changes, reruns, notifications or scheduling. Missing status/hard-kill requires explicit manual review before collection.",
    )
    save(temporary / "review.json", review)
    lines = [
        "# WP5 morning review bundle",
        "",
        f"Runner outcome: {state['status']}. No gate closed.",
        "",
        "## Block outcomes",
        "",
    ]
    lines += [
        f"- {b.get('id', 'missing id')}: {b.get('status', 'missing status')} ({b.get('reason') or 'no rejection reason'})."
        for b in state["blocks"]
    ]
    lines += [
        "",
        "## Analysis",
        "",
        *(errors or ["Derived reports are ready for review, not acceptance."]),
        "",
        "Read raw-sha256.json, raw/status.json and raw/events.jsonl first. Review raw rejected captures too.",
        "If analysis_errors is nonempty, all derived files are untrusted even if they exist.",
        "Check drift/investigation flags and host telemetry; distinguish missing evidence from a regression.",
        "Review continuation-review.json before proposing any later window. Do not schedule automatically.",
        "",
    ]
    (temporary / "README.md").write_text("\n".join(lines), encoding="utf-8")
    if destination.exists():
        raise FileExistsError(destination)
    temporary.rename(destination)
    return review


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = collect(args.manifest, args.run, args.output)
    print(json.dumps(report, indent=2))
    if report["analysis_errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
