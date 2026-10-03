#!/usr/bin/env python3
"""Run a frozen manifest in a dedicated Linux systemd service when the host is quiet.

No unrelated process is stopped. Busy or interrupted attempts are retained and
retried in full until the deadline. Results need human review before gate closure.
"""

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import os
import signal
import subprocess
import time
from pathlib import Path

from capture_file_state_trace import git_metadata


def cpu_snapshot(cgroup):
    fields = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0].split()[1:]
    ticks = [int(n) for n in fields]
    busy = sum(ticks[i] for i in (0, 1, 2, 5, 6, 7)) / os.sysconf("SC_CLK_TCK")
    usage = dict(
        line.split()
        for line in (cgroup / "cpu.stat").read_text(encoding="utf-8").splitlines()
    )
    return time.monotonic(), busy, int(usage["usage_usec"]) / 1e6


def foreign_cores(before, after):
    elapsed = after[0] - before[0]
    return max(0.0, (after[1] - before[1] - (after[2] - before[2])) / elapsed)


def validate(manifest, *, fresh=False):
    for root, expected in manifest["checkouts"].items():
        actual = git_metadata(Path(root))
        if actual["sha"] != expected or actual["status"] != "":
            raise RuntimeError(f"checkout changed: {root}: {actual}")
    if not manifest["commands"]:
        raise ValueError("empty benchmark manifest")
    for command in manifest["commands"]:
        if not command or not all(isinstance(arg, str) for arg in command):
            raise ValueError("commands must be nonempty argument lists")
        if not Path(command[0]).is_file():
            raise ValueError(f"missing executable: {command[0]}")
    deadline = dt.datetime.fromisoformat(manifest["deadline"])
    if deadline.utcoffset() is None:
        raise ValueError("deadline must include a timezone offset")
    if deadline > dt.datetime(2026, 9, 27, 13, tzinfo=dt.UTC):
        raise ValueError("deadline must not exceed the agreed 06:00 Pacific window")
    output = Path(manifest["output"])
    if not output.is_absolute():
        raise ValueError("output path must be absolute")
    if fresh:
        if deadline.timestamp() <= time.time():
            raise ValueError("deadline must be in the future")
        if output.exists():
            raise ValueError("output directory must not already exist")


def stop_child(child):
    if child.poll() is None:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(child.pid, signal.SIGTERM)
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(child.pid, signal.SIGKILL)
            child.wait()


def run(manifest, output, identity):
    validate(manifest, fresh=True)
    # A dedicated service cgroup accounts for exited children too. Subtracting
    # live PID counters would mistake our own completed benchmarks for interference.
    groups = Path("/proc/self/cgroup").read_text(encoding="utf-8").splitlines()
    relative = next(line[3:] for line in groups if line.startswith("0::"))
    if not relative.endswith("/aiogzip-wp5-nightly-20260927.service"):
        raise RuntimeError("must run in the dedicated aiogzip WP5 systemd service")
    cgroup = Path("/sys/fs/cgroup") / relative.lstrip("/")
    deadline = dt.datetime.fromisoformat(manifest["deadline"]).timestamp()
    output.mkdir(parents=True, exist_ok=True)
    events = (output / "events.jsonl").open("a", encoding="utf-8", buffering=1)

    def record(kind, **details):
        entry = {
            "time": dt.datetime.now(dt.UTC).isoformat(),
            "event": kind,
            **identity,
            **details,
        }
        events.write(json.dumps(entry) + "\n")
        print(json.dumps(entry), flush=True)

    def sample():
        before = cpu_snapshot(cgroup)
        time.sleep(min(5, max(0, deadline - time.time())))
        after = cpu_snapshot(cgroup)
        cores = foreign_cores(before, after)
        load = os.getloadavg()
        record("host", foreign_cores=cores, load=load)
        return cores, load

    attempt = 0
    while time.time() < deadline:
        quiet_since = time.monotonic()
        while time.monotonic() - quiet_since < 120 and time.time() < deadline:
            cores, load = sample()
            if cores > 0.25 or max(load[:2]) > 0.5:
                record("busy-defer")
                time.sleep(min(600, max(0, deadline - time.time())))
                quiet_since = time.monotonic()
        if time.time() >= deadline:
            break
        validate(manifest)
        attempt += 1
        directory = output / f"attempt-{attempt:02d}"
        directory.mkdir()
        record("attempt-start", attempt=attempt)
        contaminated = False
        for index, argv in enumerate(manifest["commands"]):
            if time.time() >= deadline:
                contaminated = True
                break
            command = [arg.replace("{output}", str(directory)) for arg in argv]
            with (directory / f"command-{index:02d}.log").open(
                "x", encoding="utf-8"
            ) as log:
                child = subprocess.Popen(
                    command,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                started = time.monotonic()
                try:
                    while child.poll() is None:
                        cores, _ = sample()
                        if cores > 0.25 or time.time() >= deadline:
                            contaminated = True
                            record(
                                "attempt-rejected",
                                attempt=attempt,
                                command=index,
                                foreign_cores=cores,
                            )
                            break
                        if time.monotonic() - started > 1800:
                            raise TimeoutError(f"command {index} exceeded 30 minutes")
                finally:
                    stop_child(child)
                if contaminated:
                    break
                if child.returncode:
                    raise RuntimeError(
                        f"command {index} failed: {child.returncode}; see {log.name}"
                    )
        if not contaminated:
            validate(manifest)
            record("complete", attempt=attempt, results=str(directory))
            (output / "status.json").write_text(
                json.dumps(
                    {
                        "status": "complete",
                        "attempt": attempt,
                        "requires_review": True,
                        **identity,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            events.close()
            return
    record("deferred", reason="no uninterrupted quiet window before deadline")
    (output / "status.json").write_text(
        json.dumps({"status": "deferred", "attempts": attempt, **identity}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    events.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    manifest_bytes = args.manifest.read_bytes()
    manifest = json.loads(manifest_bytes)
    identity = {
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
    }
    validate(manifest, fresh=True)
    if args.check:
        print("Manifest check passed; benchmarks were not started.")
        return

    def interrupted(signum, frame):
        raise InterruptedError(f"received signal {signum}")

    signal.signal(signal.SIGTERM, interrupted)
    output = Path(manifest["output"])
    try:
        run(manifest, output, identity)
    except BaseException as error:
        output.mkdir(parents=True, exist_ok=True)
        (output / "status.json").write_text(
            json.dumps({"status": "failed", "error": repr(error), **identity}, indent=2)
            + "\n",
            encoding="utf-8",
        )
        raise


if __name__ == "__main__":
    main()
