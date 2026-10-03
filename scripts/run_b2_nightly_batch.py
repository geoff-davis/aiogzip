#!/usr/bin/env python3
"""Run the pending series of a frozen WP5 batch plan, one after another, tonight.

A systemd timer starts this once per night between the plan's first and last
nights. For each series in plan order it looks at that series' earlier nightly
attempts:

- an attempt that started a measurement block, or finished `complete` or
  `incomplete`, is the series: it is never repeated;
- an attempt that is failed, running, unreadable, or not an instance of the
  plan's reviewed manifest template, blocks the series until a person
  investigates;
- otherwise, absent or deferred with every block unstarted, the series is
  pending, and a fresh manifest is prepared and run for tonight.

The reviewed plan pins every checkout commit, the interpreter and lockfile
hashes and the quiet policy, and records each series' manifest template hash:
the SHA-256 of the whole manifest apart from its window and output path. That
covers gate, engine, sources, matrix, sampling, order and reserves. A freshly
prepared manifest that disagrees with either stops the night before anything
launches. The reviewed unit passes `--plan-sha256`, the hash of the exact plan
bytes, so its nights, window, series and their order can't change after review.
`--templates` prints the template hashes for a plan under review. Series run sequentially in
one process holding a batch-wide lock, so two never share the pinned core.
Nothing here closes a gate, relaxes the quiet policy or edits earlier output.
"""

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

from check_b2_prior_windows import blocker
from prepare_b2_timing_window import prepare
from run_b2_timing_blocks import POLICY, validate

MAX_WINDOW = dt.timedelta(hours=4)
GATES = ("G06", "G07", "G08-throughput", "G08-scheduling")
SLUG = re.compile(r"[a-z0-9][a-z0-9-]*")
SHA256 = re.compile(r"[0-9a-f]{64}")
# The only manifest fields that legitimately differ between nightly attempts.
VOLATILE = ("not_before", "deadline", "output")


def load_plan(path, *, templates=True, sha256=None):
    """Load and check a plan; with `sha256`, its exact bytes must match it."""
    raw = Path(path).read_bytes()
    if sha256 is not None and hashlib.sha256(raw).hexdigest() != sha256:
        raise ValueError("plan bytes differ from the reviewed SHA-256")
    plan = json.loads(raw)
    if not SLUG.fullmatch(plan["name"]):
        raise ValueError(f"unsafe plan name {plan['name']!r}")
    ids = [series["id"] for series in plan["series"]]
    if not ids or len(set(ids)) != len(ids):
        raise ValueError("series ids must be unique and non-empty")
    first = dt.date.fromisoformat(plan["first_night"])
    last = dt.date.fromisoformat(plan["last_night"])
    start = dt.time.fromisoformat(plan["start"])
    end = dt.time.fromisoformat(plan["end"])
    if first > last or start >= end:
        raise ValueError("nights and nightly window must be ordered")
    ZoneInfo(plan["timezone"])
    pins = plan["pins"]
    if pins["quiet_policy"] != POLICY:
        raise ValueError("plan quiet policy differs from this runner's")
    if set(pins["files"]) != {plan["python"], f"{plan['harness']}/uv.lock"}:
        raise ValueError("pins must cover exactly the interpreter and harness lock")
    for series in plan["series"]:
        if not SLUG.fullmatch(series["id"]):
            raise ValueError(f"unsafe series id {series['id']!r}")
        if templates and not SHA256.fullmatch(series.get("template_sha256") or ""):
            raise ValueError(f"{series['id']}: template_sha256 missing")
        if series["gate"] not in GATES:
            raise ValueError(f"unknown gate {series['gate']!r}")
        if (series.get("baseline") is None) != (series["gate"] == "G07"):
            raise ValueError(f"{series['id']}: only G07 runs without a baseline")
        for role in ("baseline", "candidate"):
            if series.get(role) is not None and series[role] not in pins["checkouts"]:
                raise ValueError(f"{series['id']}: {role} checkout is not pinned")
    if plan["harness"] not in pins["checkouts"]:
        raise ValueError("harness checkout is not pinned")
    return plan


def attempt_name(plan, night, series):
    return f"aiogzip-wp5-onecore-{plan['name']}-{night:%Y%m%d}-{series['id']}"


def expected_identity(plan, root, series):
    """The pinned checkouts, files and policy a series' manifest must carry."""
    pins = plan["pins"]
    roles = [plan["harness"], series["candidate"]]
    if series.get("baseline") is not None:
        roles.append(series["baseline"])
    return dict(
        checkouts={str(root / role): pins["checkouts"][role] for role in roles},
        files={str(root / name): value for name, value in pins["files"].items()},
        quiet_policy=pins["quiet_policy"],
    )


def identity(manifest):
    return {key: manifest[key] for key in ("checkouts", "files", "quiet_policy")}


def template_digest(manifest):
    template = {k: v for k, v in manifest.items() if k not in VOLATILE}
    canonical = json.dumps(template, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def classify(directory, expected, template):
    """Return 'pending', 'done' or 'blocked' for one earlier attempt."""
    if not directory.exists():
        return "pending"
    try:
        state = json.loads((directory / "status.json").read_text(encoding="utf-8"))
        manifest = state["manifest"]
        if identity(manifest) != expected or template_digest(manifest) != template:
            return "blocked"
    except (OSError, ValueError, KeyError, TypeError):
        return "blocked"
    if blocker(directory) is None:
        return "pending"
    try:
        if state["status"] in ("complete", "incomplete") or any(
            slot["status"] != "unstarted" or slot["captures"]
            for slot in state["blocks"]
        ):
            return "done"
    except (KeyError, TypeError):
        pass
    return "blocked"


def series_state(plan, root, series, tonight):
    """Combine every earlier night's attempt for this series."""
    expected = expected_identity(plan, root, series)
    states = []
    night = dt.date.fromisoformat(plan["first_night"])
    while night < tonight:
        directory = root / "results" / attempt_name(plan, night, series)
        states.append(classify(directory, expected, series["template_sha256"]))
        night += dt.timedelta(days=1)
    for outcome in ("done", "blocked"):
        if outcome in states:
            return outcome
    return "pending"


def night_bounds(plan, now):
    zone = ZoneInfo(plan["timezone"])
    local = now.astimezone(zone)
    start = dt.datetime.combine(
        local.date(), dt.time.fromisoformat(plan["start"]), tzinfo=zone
    )
    end = dt.datetime.combine(
        local.date(), dt.time.fromisoformat(plan["end"]), tzinfo=zone
    )
    return local.date(), start, end


def prepare_series(plan, root, series, *, output, not_before, deadline):
    return prepare(
        gate=series["gate"],
        engine=series["engine"],
        baseline=root / series["baseline"] if series.get("baseline") else None,
        candidate=root / series["candidate"],
        harness=root / plan["harness"],
        runner=root / plan["harness"],
        python=root / plan["python"],
        output=output,
        service=plan["service"],
        not_before=not_before,
        deadline=deadline,
    )


def templates(plan, root):
    """Template hash per series, for a plan under review. Launches nothing.

    Refuses checkouts or files that disagree with the plan's pins, so a
    reviewer cannot record a template the night would then reject.
    """
    digests = {}
    for series in plan["series"]:
        manifest = prepare_series(
            plan, root, series, output=root, not_before=None, deadline=None
        )
        if identity(manifest) != expected_identity(plan, root, series):
            raise ValueError(f"{series['id']}: sources differ from the plan's pins")
        digests[series["id"]] = template_digest(manifest)
    return digests


def run_night(plan, root, *, now, launch, log=print):
    """Prepare and launch tonight's pending series. Returns the outcomes."""
    with (root / "scheduled" / f"{plan['name']}.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log("another invocation of this batch is running")
            return {"batch": "locked"}
        return _run_night(plan, root, now=now, launch=launch, log=log)


def _run_night(plan, root, *, now, launch, log):
    tonight, start, end = night_bounds(plan, now())
    first = dt.date.fromisoformat(plan["first_night"])
    last = dt.date.fromisoformat(plan["last_night"])
    if not first <= tonight <= last:
        log(f"{tonight} is outside the authorized nights {first}..{last}")
        return {}
    if not start <= now() < end:
        log(f"outside tonight's window {start:%H:%M:%S}-{end:%H:%M:%S}")
        return {}
    outcomes = {}
    for series in plan["series"]:
        state = series_state(plan, root, series, tonight)
        if state != "pending":
            outcomes[series["id"]] = state
            log(f"{series['id']}: {state}, skipped")
            continue
        name = attempt_name(plan, tonight, series)
        path = root / "scheduled" / f"{name}.json"
        if path.exists() or (root / "results" / name).exists():
            # A second invocation tonight never repeats or replaces an attempt.
            outcomes[series["id"]] = "attempted-tonight"
            log(f"{series['id']}: already attempted tonight, skipped")
            continue
        current = now()
        deadline = min(end, current + MAX_WINDOW).replace(microsecond=0)
        manifest = prepare_series(
            plan,
            root,
            series,
            output=root / "results" / name,
            not_before=current.replace(microsecond=0).isoformat(),
            deadline=deadline.isoformat(),
        )
        if identity(manifest) != expected_identity(plan, root, series):
            outcomes[series["id"]] = "pin-mismatch"
            log(f"{series['id']}: sources differ from the plan's pins; night stopped")
            break
        if template_digest(manifest) != series["template_sha256"]:
            outcomes[series["id"]] = "template-mismatch"
            log(f"{series['id']}: manifest differs from the reviewed template")
            break
        remaining = (deadline - current).total_seconds()
        # The runner needs the quiet period before its measurement reserve.
        needed = manifest["minimum_measurement_seconds"] + POLICY["quiet_seconds"]
        if remaining < needed:
            outcomes[series["id"]] = "no-time"
            log(f"{series['id']}: {remaining:.0f}s left tonight, not started")
            continue
        validate(manifest, fresh=True)
        with path.open("x", encoding="utf-8") as stream:
            json.dump(manifest, stream, indent=2)
            stream.write("\n")
        log(f"{series['id']}: launching {path.name} until {deadline:%H:%M:%S}")
        outcomes[series["id"]] = f"launched, exit {launch(path)}"
    return outcomes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    selection = parser.add_mutually_exclusive_group(required=True)
    # The reviewed unit passes this, so nights, window, order and series can't
    # change after review: the plan bytes themselves are authenticated.
    selection.add_argument("--plan-sha256")
    selection.add_argument("--templates", action="store_true")
    args = parser.parse_args()
    plan = load_plan(args.plan, templates=not args.templates, sha256=args.plan_sha256)
    root = Path(plan["root"])
    harness = root / plan["harness"]
    if Path(__file__).resolve().parents[1] != harness.resolve():
        raise ValueError("run this driver from the plan's pinned harness checkout")
    if args.templates:
        print(json.dumps(templates(plan, root), indent=2))
        return 0
    runner = harness / "scripts" / "run_b2_timing_blocks.py"

    def launch(manifest):
        return subprocess.run(
            [str(root / plan["python"]), str(runner), str(manifest)], check=False
        ).returncode

    outcomes = run_night(
        plan,
        root,
        now=lambda: dt.datetime.now(dt.UTC),
        launch=launch,
        log=lambda line: print(line, flush=True),
    )
    print(json.dumps(outcomes, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
