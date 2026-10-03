#!/usr/bin/env python3
"""Sequence frozen quiet-runner manifests without mixing their evidence batches."""

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import signal
import subprocess
import time
from pathlib import Path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate(queue, *, fresh=True):
    deadline = dt.datetime.fromisoformat(queue["deadline"])
    if deadline.utcoffset() is None:
        raise ValueError("deadline must include timezone")
    if deadline > dt.datetime(2026, 9, 27, 13, tzinfo=dt.UTC):
        raise ValueError("deadline exceeds agreed 06:00 Pacific cutoff")
    if fresh and deadline.timestamp() <= time.time():
        raise ValueError("queue deadline has passed")
    output = Path(queue["output"])
    if not output.is_absolute() or (fresh and output.exists()):
        raise ValueError("queue output must be a new absolute path")
    if [phase["gate"] for phase in queue["phases"]] != ["G08", "G06", "G07"]:
        raise ValueError("expected sequential G08, G06, G07 phases")
    outputs = {str(output)}
    for phase in queue["phases"]:
        for key in ("runner", "manifest"):
            if digest(phase[key]) != phase[key + "_sha256"]:
                raise ValueError(f"{phase['gate']} {key} changed")
        manifest = json.loads(Path(phase["manifest"]).read_text(encoding="utf-8"))
        if dt.datetime.fromisoformat(manifest["deadline"]) != deadline:
            raise ValueError("all phases must share the same cutoff")
        if manifest["output"] in outputs:
            raise ValueError("phase outputs must be distinct")
        outputs.add(manifest["output"])
        if fresh:
            subprocess.run(
                [queue["python"], phase["runner"], phase["manifest"], "--check"],
                check=True,
            )
    return deadline.timestamp()


def write_status(output, record):
    temporary = output / "status.tmp"
    temporary.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output / "status.json")


def stop_runner(child):
    with contextlib.suppress(ProcessLookupError):
        child.send_signal(signal.SIGTERM)
    try:
        child.wait(timeout=10)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            child.kill()
        child.wait()
        # Do not launch another phase while an unresponsive runner could have
        # left descendants. Exiting invokes systemd's control-group cleanup.
        raise RuntimeError("runner failed to settle after termination") from None


def run(queue, identity=None):
    deadline = validate(queue)
    output = Path(queue["output"])
    output.mkdir(parents=True)
    record = {
        "status": "running",
        "requires_review": True,
        "phases": [],
        **(identity or {}),
    }
    write_status(output, record)
    try:
        run_phases(queue, deadline, output, record)
    except BaseException as error:
        record["status"] = "failed"
        record["error"] = repr(error)
        write_status(output, record)
        raise


def run_phases(queue, deadline, output, record):
    for phase in queue["phases"]:
        # Recheck frozen files at the phase boundary too.
        validate(queue, fresh=False)
        manifest = json.loads(Path(phase["manifest"]).read_text(encoding="utf-8"))
        phase_output = Path(manifest["output"])
        identity = {
            "gate": phase["gate"],
            "manifest_sha256": phase["manifest_sha256"],
            "runner_sha256": phase["runner_sha256"],
        }
        if time.time() >= deadline:
            result = {
                **identity,
                "status": "deferred",
                "reason": "earlier phases consumed overnight window",
            }
            phase_output.mkdir(parents=True)
            write_status(phase_output, result)
        else:
            record["active_gate"] = phase["gate"]
            write_status(output, record)
            with (output / f"{phase['gate'].lower()}.log").open(
                "x", encoding="utf-8"
            ) as log:
                child = subprocess.Popen(
                    [queue["python"], phase["runner"], phase["manifest"]],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
                cutoff = False
                try:
                    # The frozen runner stops benchmark work at the cutoff.
                    # Allow cleanup/final provenance writes before its watchdog
                    # sends SIGTERM; this does not extend any phase deadline.
                    child.wait(timeout=max(0, deadline - time.time()) + 15)
                except subprocess.TimeoutExpired:
                    stop_runner(child)
                    cutoff = True
                except BaseException:
                    stop_runner(child)
                    raise
            status_file = phase_output / "status.json"
            status = (
                json.loads(status_file.read_text(encoding="utf-8"))
                if status_file.exists()
                else {}
            )
            result = {
                **identity,
                "status": status.get("status", "failed"),
                "returncode": child.returncode,
                "output": str(phase_output),
            }
            if cutoff:
                result["runner_status"] = result["status"]
                result["status"] = "deferred"
                result["reason"] = "queue stopped active phase at shared cutoff"
            elif child.returncode:
                result["status"] = "failed"
        record["phases"].append(result)
        record.pop("active_gate", None)
        write_status(output, record)
    record["status"] = (
        "complete"
        if all(p["status"] == "complete" for p in record["phases"])
        else "incomplete"
    )
    write_status(output, record)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("queue", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    queue = json.loads(args.queue.read_text(encoding="utf-8"))
    if args.check:
        validate(queue)
        print("Queue check passed; benchmarks were not started.")
        return

    def interrupted(signum, frame):
        raise InterruptedError(f"received signal {signum}")

    signal.signal(signal.SIGTERM, interrupted)
    run(
        queue,
        {"queue_sha256": digest(args.queue), "queue_runner_sha256": digest(__file__)},
    )


if __name__ == "__main__":
    main()
