#!/usr/bin/env python3
"""Execute one bounded WP5 window, preserving independent block outcomes.

No scheduling, automatic policy relaxation, gate closure or automatic retry. Run --check
before registering a dedicated systemd user service with KillMode=control-group.
"""

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import re
import signal
import subprocess
import time
from pathlib import Path

from capture_file_state_trace import git_metadata
from run_quiet_benchmarks import cpu_snapshot, foreign_cores, stop_child

POLICY = dict(
    foreign_cpu_cores_max=1.0,
    load_1_and_5_max=0.5,
    quiet_seconds=120,
    sample_seconds=5,
)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def validate(manifest, *, fresh=False):
    if manifest["quiet_policy"] != POLICY:
        raise ValueError("quiet policy must match the declared provisional thresholds")
    if not re.fullmatch(r"aiogzip-wp5-[a-zA-Z0-9_-]+\.service", manifest["service"]):
        raise ValueError("dedicated aiogzip WP5 service required")
    if not all(isinstance(manifest[k], str) for k in ("not_before", "deadline")):
        raise ValueError("draft manifest needs an explicit window before execution")
    times = [
        dt.datetime.fromisoformat(manifest[key]) for key in ("not_before", "deadline")
    ]
    if any(t.utcoffset() is None for t in times):
        raise ValueError("window timestamps require timezones")
    duration = (times[1] - times[0]).total_seconds()
    if not 0 < duration <= 4 * 3600:
        raise ValueError("window must be positive and at most four hours")
    for key in (
        "command_timeout_seconds",
        "minimum_measurement_seconds",
        "block_timeout_seconds",
    ):
        value = manifest[key]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not 0 < value <= duration
        ):
            raise ValueError(f"invalid {key}")
    output = Path(manifest["output"])
    if not output.is_absolute():
        raise ValueError("absolute output path required")
    if fresh and (output.exists() or times[1].timestamp() <= time.time()):
        raise ValueError("output exists or window has expired")
    if not manifest["checkouts"] or not manifest["files"]:
        raise ValueError("frozen checkouts and files required")
    for root, expected in manifest["checkouts"].items():
        actual = git_metadata(Path(root))
        if actual["sha"] != expected or actual["status"]:
            raise ValueError(f"checkout changed: {root}")
    for path, expected in manifest["files"].items():
        if digest(path) != expected:
            raise ValueError(f"file changed: {path}")
    if type(manifest["cpu"]) is not int or manifest["cpu"] < 0:
        raise ValueError("invalid CPU")
    if hasattr(os, "sched_getaffinity") and manifest["cpu"] not in os.sched_getaffinity(
        0
    ):
        raise ValueError("CPU outside allowed affinity")
    blocks = manifest["blocks"]
    ids = [b["id"] for b in blocks]
    if (
        not blocks
        or len(ids) != len(set(ids))
        or any(not re.fullmatch(r"[a-zA-Z0-9_-]+", i) for i in ids)
    ):
        raise ValueError("unique safe block identifiers required")
    names = set()
    for command in [*manifest["warmups"], *(c for b in blocks for c in b["commands"])]:
        name, argv = command["output"], command["argv"]
        if (
            Path(name).name != name
            or not name.endswith(".json")
            or name in names
            or name in ("status.json", "comparison-index.json")
        ):
            raise ValueError("unique JSON output basenames required")
        names.add(name)
        if (
            not argv
            or not all(isinstance(a, str) and a for a in argv)
            or not Path(argv[0]).is_file()
        ):
            raise ValueError("invalid argument list or executable")
        if argv.count("{capture}") != 1:
            raise ValueError("exactly one capture placeholder required")
        if argv[:3] != ["/usr/bin/taskset", "-c", str(manifest["cpu"])]:
            raise ValueError("commands must use the declared CPU")
    if any(not b["commands"] for b in blocks):
        raise ValueError("empty block")
    return times[0].timestamp(), times[1].timestamp()


def telemetry(cpu):
    """Best-effort diagnostic sensors; missing values never mean zero activity."""
    result = {
        "cpu_ticks": {},
        "frequency_khz": {},
        "temperatures_millic": {},
        "unavailable": [],
    }
    try:
        sibling_text = (
            Path(f"/sys/devices/system/cpu/cpu{cpu}/topology/thread_siblings_list")
            .read_text()
            .strip()
        )
        cpus = set()
        for span in sibling_text.split(","):
            ends = list(map(int, span.split("-")))
            cpus.update(range(ends[0], ends[-1] + 1))
        result["siblings"] = sorted(cpus)
        for line in Path("/proc/stat").read_text().splitlines():
            fields = line.split()
            if fields[0] in {f"cpu{c}" for c in cpus}:
                result["cpu_ticks"][fields[0]] = list(map(int, fields[1:]))
        for c in cpus:
            try:
                result["frequency_khz"][str(c)] = int(
                    Path(
                        f"/sys/devices/system/cpu/cpu{c}/cpufreq/scaling_cur_freq"
                    ).read_text()
                )
            except (OSError, ValueError) as exc:
                result["unavailable"].append(f"cpu{c} frequency: {exc}")
        for directory in Path("/sys/class/hwmon").glob("hwmon*"):
            if (directory / "name").read_text().strip() == "k10temp":
                for path in directory.glob("temp*_input"):
                    result["temperatures_millic"][str(path)] = int(path.read_text())
        if not result["temperatures_millic"]:
            result["unavailable"].append("k10temp temperature unavailable")
    except (OSError, ValueError) as exc:
        result["unavailable"].append(str(exc))
    return result


class WindowRunner:
    def __init__(self, manifest, identity, *, clock=time, popen=subprocess.Popen):
        self.manifest, self.clock, self.popen = manifest, clock, popen
        self.output = Path(manifest["output"])
        self.not_before, self.deadline = validate(manifest, fresh=True)
        self.end = clock.monotonic() + max(0, self.deadline - clock.time())
        relative = next(
            s[3:]
            for s in Path("/proc/self/cgroup").read_text().splitlines()
            if s.startswith("0::")
        )
        if Path(relative).name != manifest["service"]:
            raise ValueError("must execute inside the declared dedicated service")
        self.cgroup = Path("/sys/fs/cgroup") / relative.lstrip("/")
        self.state = dict(
            status="waiting",
            requires_review=True,
            manifest=manifest,
            **identity,
            warmups=[],
            blocks=[
                dict(id=b["id"], status="unstarted", reason="not reached", captures=[])
                for b in manifest["blocks"]
            ],
        )
        self.output.mkdir()
        self.events = (self.output / "events.jsonl").open(
            "x", encoding="utf-8", buffering=1
        )
        self.active = None
        self.block_end = self.end
        self.save()

    def save(self):
        write_json(self.output / "status.json", self.state)

        if "comparison" in self.manifest:
            index = dict(self.manifest["comparison"], blocks=[])
            for definition, slot in zip(
                self.manifest["blocks"], self.state["blocks"], strict=True
            ):
                status = slot["status"] if slot["status"] != "running" else "rejected"
                index["blocks"].append(
                    dict(
                        status=status,
                        reason="interrupted (runner did not finish)"
                        if slot["status"] == "running"
                        else slot.get("reason"),
                        captures=[
                            dict(side=c["side"], path=c["output"])
                            for c in definition["commands"]
                        ],
                    )
                )
            index["runner_status"] = "status.json"
            index["manifest_sha256"] = self.state.get("manifest_sha256")
            write_json(self.output / "comparison-index.json", index)

    def event(self, kind, **fields):
        self.events.write(
            json.dumps(
                dict(time=self.clock.time(), event=kind, **fields), allow_nan=False
            )
            + "\n"
        )

    def remaining(self):
        return max(
            0, min(self.end - self.clock.monotonic(), self.deadline - self.clock.time())
        )

    def sample(self, limit=None):
        before = cpu_snapshot(self.cgroup)
        delay = min(POLICY["sample_seconds"], self.remaining())
        if limit is not None:
            delay = min(delay, max(0, limit - self.clock.monotonic()))
        if delay <= 0:
            return None
        self.clock.sleep(delay)
        after = cpu_snapshot(self.cgroup)
        row = dict(
            foreign_cores=foreign_cores(before, after),
            load=os.getloadavg(),
            telemetry=telemetry(self.manifest["cpu"]),
        )
        self.event("host", **row)
        return row

    def quiet(self, *, initial=False):
        since = self.clock.monotonic()
        while self.remaining() > 0:
            if (
                initial
                and self.remaining() < self.manifest["minimum_measurement_seconds"]
            ):
                return False
            row = self.sample()
            if row is None:
                return False
            if (
                row["foreign_cores"] > POLICY["foreign_cpu_cores_max"]
                or max(row["load"][:2]) > POLICY["load_1_and_5_max"]
            ):
                since = self.clock.monotonic()
            elif self.clock.monotonic() - since >= POLICY["quiet_seconds"]:
                return (
                    not initial
                    or self.remaining() >= self.manifest["minimum_measurement_seconds"]
                )
        return False

    def command(self, declaration):
        if self.remaining() <= 0:
            return "deadline", None
        validate(self.manifest)
        if self.remaining() <= 0:
            return "deadline", None
        if self.clock.monotonic() >= self.block_end:
            return "block-span", None
        path = self.output / declaration["output"]
        if path.exists():
            raise FileExistsError(path)
        argv = [str(path) if a == "{capture}" else a for a in declaration["argv"]]
        stop_at = min(
            self.end,
            self.block_end,
            self.clock.monotonic() + self.manifest["command_timeout_seconds"],
        )
        record = dict(output=str(path), argv=argv, started_at=self.clock.time())
        self.event("command-start", **record)
        reason = None
        with path.with_suffix(".log").open("x", encoding="utf-8") as log:
            child = self.popen(
                argv, stdout=log, stderr=subprocess.STDOUT, start_new_session=True
            )
            try:
                while True:
                    row = self.sample(stop_at)
                    if self.remaining() <= 0:
                        reason = "deadline"
                    elif self.clock.monotonic() >= self.block_end:
                        reason = "block-span"
                    elif self.clock.monotonic() >= stop_at:
                        reason = "command-timeout"
                    elif (
                        row is not None
                        and row["foreign_cores"] > POLICY["foreign_cpu_cores_max"]
                    ):
                        reason = "interference"
                    if reason or child.poll() is not None:
                        break
            except BaseException as exc:
                record.update(
                    status="interrupted", ended_at=self.clock.time(), error=repr(exc)
                )
                target = (
                    self.active["captures"]
                    if self.active is not None
                    else self.state["warmups"]
                )
                target.append(record)
                self.event("command-interrupted", **record)
                self.save()
                raise
            finally:
                stop_child(child)
        record.update(ended_at=self.clock.time(), returncode=child.returncode)
        if reason is None and child.returncode:
            reason = "command-failed"
        if reason is None:
            validate(self.manifest)
            if not path.is_file():
                raise RuntimeError("successful command omitted capture")
            json.loads(path.read_text(encoding="utf-8"))
            record["sha256"] = digest(path)
        record["status"] = reason or "complete"
        self.event("command-end", **record)
        return reason, record

    def run(self):
        try:
            while self.clock.time() < self.not_before and self.remaining() > 0:
                self.clock.sleep(
                    min(5, self.not_before - self.clock.time(), self.remaining())
                )
            if not self.quiet(initial=True):
                self.state.update(
                    status="deferred",
                    reason="quiet period or initial measurement reserve unavailable",
                )
                return
            self.state["status"] = "running"
            self.save()
            for declaration in self.manifest["warmups"]:
                reason, record = self.command(declaration)
                self.state["warmups"].append(record)
                self.save()
                if reason:
                    self.state.update(
                        status="failed"
                        if reason in ("command-failed", "command-timeout")
                        else "deferred",
                        reason=f"warmup: {reason}",
                    )
                    return
            for number, block in enumerate(self.manifest["blocks"]):
                slot = self.state["blocks"][number]
                if self.remaining() < self.manifest["block_timeout_seconds"]:
                    self.state["reason"] = "insufficient reserve for next block"
                    break
                self.block_end = min(
                    self.end,
                    self.clock.monotonic() + self.manifest["block_timeout_seconds"],
                )
                slot.update(status="running", reason=None)
                self.active = slot
                self.save()
                for declaration in block["commands"]:
                    reason, record = self.command(declaration)
                    if record is not None:
                        slot["captures"].append(record)
                    self.save()
                    if reason:
                        slot.update(status="rejected", reason=reason)
                        break
                else:
                    slot.update(status="complete")
                self.active = None
                self.save()
                if slot["status"] == "rejected":
                    if slot["reason"] in ("command-failed", "command-timeout"):
                        self.state["status"] = "failed"
                        return
                    if number == len(self.manifest["blocks"]) - 1 or not self.quiet():
                        break
            self.state["status"] = (
                "complete"
                if all(b["status"] == "complete" for b in self.state["blocks"])
                else "incomplete"
            )
        except BaseException as exc:
            if self.active is not None:
                self.active.update(status="rejected", reason=repr(exc))
            self.state.update(status="failed", error=repr(exc))
            raise
        finally:
            self.save()
            self.events.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    raw = args.manifest.read_bytes()
    manifest = json.loads(raw)
    validate(manifest, fresh=True)
    root = Path(__file__).resolve().parents[1]
    if str(root) not in manifest["checkouts"]:
        raise ValueError("runner checkout must be frozen in manifest")
    if args.check:
        print("Manifest validated; nothing launched.")
        return

    def interrupted(signum, frame):
        raise InterruptedError(f"received signal {signum}")

    signal.signal(signal.SIGTERM, interrupted)
    identity = dict(
        manifest_sha256=hashlib.sha256(raw).hexdigest(), runner_sha256=digest(__file__)
    )
    WindowRunner(manifest, identity).run()


if __name__ == "__main__":
    main()
