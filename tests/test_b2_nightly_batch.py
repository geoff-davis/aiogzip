"""Nightly batch selection without preparing checkouts or running a benchmark."""

import datetime as dt
import fcntl
import hashlib
import json
import runpy
from pathlib import Path

import pytest

UTC = dt.UTC


@pytest.fixture
def batch(monkeypatch):
    root = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(root))
    return runpy.run_path(str(root / "run_b2_nightly_batch.py"))


def series(id, gate="G08-throughput", baseline="baseline"):
    return dict(
        id=id,
        gate=gate,
        engine="stdlib",
        baseline=baseline,
        candidate="candidate",
        template_sha256="0" * 64,
    )


@pytest.fixture
def plan(tmp_path, batch):
    (tmp_path / "results").mkdir()
    (tmp_path / "scheduled").mkdir()
    return dict(
        name="batch",
        root=str(tmp_path),
        python="venv/bin/python",
        harness="harness",
        service="aiogzip-wp5-onecore-batch.service",
        timezone="UTC",
        first_night="2026-10-03",
        last_night="2026-10-05",
        start="00:30:00",
        end="06:30:00",
        pins=dict(
            checkouts=dict(harness="h" * 40, baseline="a" * 40, candidate="b" * 40),
            files={"venv/bin/python": "p" * 64, "harness/uv.lock": "l" * 64},
            quiet_policy=dict(batch["POLICY"]),
        ),
        series=[series("one"), series("two"), series("g07", "G07", None)],
    )


class Night:
    """Fake clock, prepare and launcher: each launch takes `cost` seconds.

    The fake prepare reports the plan's pinned identity, with the series'
    gate, engine and sources as its template, unless `drift` overrides a
    checkout role or pinned file. Unless `keep_templates`, the plan's template
    hashes are first set from the undrifted fake, as a reviewed plan's are.
    """

    def __init__(self, batch, plan, at, cost=900, drift=None, keep_templates=False):
        self.batch, self.plan, self.time, self.cost = batch, plan, at, cost
        self.root = Path(plan["root"])
        self.launched, self.prepared, self.drift = [], [], {}
        # runpy returns a copy; patch the namespace run_night actually uses.
        namespace = batch["run_night"].__globals__
        namespace["validate"] = lambda manifest, fresh: None
        namespace["prepare"] = self.prepare
        if not keep_templates:
            for item, digest in batch["templates"](plan, self.root).items():
                next(s for s in plan["series"] if s["id"] == item).update(
                    template_sha256=digest
                )
        self.prepared, self.drift = [], drift or {}

    def prepare(self, **kwargs):
        self.prepared.append(kwargs)
        pins = self.plan["pins"]
        checkouts = {}
        for role in ("harness", "runner", "candidate", "baseline"):
            if kwargs[role] is not None:
                name = Path(kwargs[role]).name
                checkouts[str(kwargs[role])] = self.drift.get(
                    name, pins["checkouts"][name]
                )
        files = {
            str(self.root / name): self.drift.get(name, value)
            for name, value in pins["files"].items()
        }
        fields = {k: v if v is None else str(v) for k, v in kwargs.items()}
        return dict(
            fields,
            checkouts=checkouts,
            files=files,
            quiet_policy=dict(self.batch["POLICY"]),
            minimum_measurement_seconds=10800 if kwargs["gate"] == "G06" else 1800,
            blocks=[dict(id=f"block-{i}") for i in range(4)],
        )

    def manifest(self, index, **changes):
        item = dict(self.plan["series"][index], **changes)
        return self.batch["prepare_series"](
            self.plan,
            self.root,
            item,
            output=self.root / "results" / "earlier",
            not_before="2026-10-03T00:30:00+00:00",
            deadline="2026-10-03T04:30:00+00:00",
        )

    def now(self):
        return self.time

    def launch(self, path):
        self.launched.append(path.name)
        self.time += dt.timedelta(seconds=self.cost)
        return 0

    def run(self):
        return self.batch["run_night"](
            self.plan, self.root, now=self.now, launch=self.launch, log=lambda _: None
        )


def status(directory, state, manifest, slots=("unstarted",) * 4, captures=False):
    directory.mkdir(parents=True)
    (directory / "status.json").write_text(
        json.dumps(
            dict(
                status=state,
                manifest=manifest,
                blocks=[
                    dict(id=block["id"], status=s, captures=[{}] if captures else [])
                    for block, s in zip(manifest["blocks"], slots, strict=True)
                ],
            )
        )
    )


def earlier(plan, day, item):
    return Path(plan["root"]) / "results" / f"aiogzip-wp5-onecore-batch-{day}-{item}"


def at(day, hour, minute=0, second=0):
    return dt.datetime(2026, 10, day, hour, minute, second, tzinfo=UTC)


def test_pending_series_run_in_order_with_fresh_windows(batch, plan):
    night = Night(batch, plan, at(3, 0, 30))
    outcomes = night.run()
    assert night.launched == [
        "aiogzip-wp5-onecore-batch-20261003-one.json",
        "aiogzip-wp5-onecore-batch-20261003-two.json",
        "aiogzip-wp5-onecore-batch-20261003-g07.json",
    ]
    assert list(outcomes.values()) == ["launched, exit 0"] * 3
    starts = [p["not_before"] for p in night.prepared]
    assert starts == [
        "2026-10-03T00:30:00+00:00",
        "2026-10-03T00:45:00+00:00",
        "2026-10-03T01:00:00+00:00",
    ]
    assert night.prepared[2]["baseline"] is None
    assert all(
        (Path(plan["root"]) / "scheduled" / name).exists() for name in night.launched
    )


def test_deadline_is_capped_at_four_hours_and_night_end(batch, plan):
    night = Night(batch, plan, at(3, 0, 30), cost=3 * 3600)
    night.run()
    deadlines = [p["deadline"] for p in night.prepared]
    assert deadlines[0] == "2026-10-03T04:30:00+00:00"
    assert deadlines[1] == "2026-10-03T06:30:00+00:00"


def test_series_after_an_overrunning_launch_get_no_time(batch, plan):
    night = Night(batch, plan, at(3, 0, 30), cost=6 * 3600)
    outcomes = night.run()
    assert outcomes == {"one": "launched, exit 0", "two": "no-time", "g07": "no-time"}


@pytest.mark.parametrize(
    "start,launched",
    [
        (at(3, 3, 28), True),  # 3 h 2 min left: the G06 reserve plus quiet
        (at(3, 3, 28, 1), False),
        (at(3, 6, 0), False),
    ],
)
def test_reserve_includes_the_quiet_period(batch, plan, start, launched):
    plan["series"] = [dict(series("g06"), gate="G06")]
    outcomes = Night(batch, plan, start).run()
    assert (outcomes["g06"] == "launched, exit 0") is launched


def test_short_gate_boundary(batch, plan):
    plan["series"] = plan["series"][:1]
    assert Night(batch, plan, at(3, 5, 58)).run() == {"one": "launched, exit 0"}
    plan["series"] = [series("two")]
    assert Night(batch, plan, at(3, 5, 58, 1)).run() == {"two": "no-time"}


@pytest.mark.parametrize(
    "when", [at(2, 1), at(6, 1), at(3, 0, 29), at(3, 6, 30)], ids=str
)
def test_outside_authorized_nights_or_window_launches_nothing(batch, plan, when):
    night = Night(batch, plan, when)
    assert night.run() == {}
    assert night.launched == []


@pytest.mark.parametrize(
    "drift",
    [
        {"candidate": "c" * 40},
        {"baseline": "c" * 40},
        {"harness": "c" * 40},
        {"venv/bin/python": "q" * 64},
        {"harness/uv.lock": "m" * 64},
    ],
    ids=lambda d: next(iter(d)),
)
def test_pin_mismatch_stops_the_night_before_launch(batch, plan, drift):
    night = Night(batch, plan, at(3, 0, 30), drift=drift)
    assert night.run() == {"one": "pin-mismatch"}
    assert night.launched == []
    assert list((Path(plan["root"]) / "scheduled").glob("*.json")) == []


@pytest.mark.parametrize(
    "change", [dict(engine="zlib-ng"), dict(gate="G08-scheduling")], ids=str
)
def test_template_mismatch_stops_the_night_before_launch(batch, plan, change):
    night = Night(batch, plan, at(3, 0, 30))
    plan["series"][0].update(change)
    assert night.run() == {"one": "template-mismatch"}
    assert night.launched == []
    assert list((Path(plan["root"]) / "scheduled").glob("*.json")) == []


def test_earlier_outcomes_decide_each_series(batch, plan):
    night = Night(batch, plan, at(4, 1))
    status(earlier(plan, 20261003, "one"), "complete", night.manifest(0))
    status(earlier(plan, 20261003, "two"), "deferred", night.manifest(1))
    status(earlier(plan, 20261003, "g07"), "failed", night.manifest(2))
    assert night.run() == {
        "one": "done",
        "two": "launched, exit 0",
        "g07": "blocked",
    }
    assert night.launched == ["aiogzip-wp5-onecore-batch-20261004-two.json"]


@pytest.mark.parametrize(
    "change", [dict(engine="zlib-ng"), dict(candidate="baseline")], ids=str
)
def test_earlier_attempt_of_another_template_blocks(batch, plan, change):
    plan["series"] = plan["series"][:1]
    night = Night(batch, plan, at(4, 1))
    status(earlier(plan, 20261003, "one"), "deferred", night.manifest(0, **change))
    assert night.run() == {"one": "blocked"}


def test_earlier_attempt_with_other_pins_blocks(batch, plan):
    plan["series"] = plan["series"][:1]
    night = Night(batch, plan, at(4, 1))
    manifest = night.manifest(0)
    manifest["checkouts"] = {k: "c" * 40 for k in manifest["checkouts"]}
    status(earlier(plan, 20261003, "one"), "deferred", manifest)
    assert night.run() == {"one": "blocked"}


def test_done_on_any_earlier_night_wins_over_later_deferral(batch, plan):
    plan["series"] = plan["series"][:1]
    night = Night(batch, plan, at(5, 1))
    status(
        earlier(plan, 20261003, "one"),
        "incomplete",
        night.manifest(0),
        slots=("complete", "rejected", "unstarted", "unstarted"),
        captures=True,
    )
    status(earlier(plan, 20261004, "one"), "deferred", night.manifest(0))
    assert night.run() == {"one": "done"}


@pytest.mark.parametrize(
    "state,slots,captures,outcome",
    [
        ("deferred", ("unstarted",) * 4, False, "pending"),
        ("deferred", ("rejected", "unstarted", "unstarted", "unstarted"), True, "done"),
        ("complete", ("complete",) * 4, True, "done"),
        (
            "incomplete",
            ("complete", "unstarted", "unstarted", "unstarted"),
            True,
            "done",
        ),
        ("failed", ("unstarted",) * 4, False, "blocked"),
        ("running", ("unstarted",) * 4, False, "blocked"),
    ],
)
def test_classify(batch, plan, tmp_path, state, slots, captures, outcome):
    night = Night(batch, plan, at(4, 1))
    ident = batch["expected_identity"](plan, night.root, plan["series"][0])
    template = plan["series"][0]["template_sha256"]
    status(tmp_path / "attempt", state, night.manifest(0), slots, captures)
    assert batch["classify"](tmp_path / "attempt", ident, template) == outcome


def test_classify_absent_and_unreadable(batch, plan, tmp_path):
    ident = batch["expected_identity"](plan, Path(plan["root"]), plan["series"][0])
    classify = batch["classify"]
    assert classify(tmp_path / "absent", ident, "0" * 64) == "pending"
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "status.json").write_text("{")
    assert classify(tmp_path / "broken", ident, "0" * 64) == "blocked"
    (tmp_path / "empty").mkdir()
    assert classify(tmp_path / "empty", ident, "0" * 64) == "blocked"


def test_template_ignores_only_window_and_output(batch, plan):
    night = Night(batch, plan, at(3, 1))
    digest = batch["template_digest"]
    manifest = night.manifest(0)
    moved = dict(manifest, not_before="x", deadline="y", output="z")
    assert digest(moved) == digest(manifest) == plan["series"][0]["template_sha256"]
    assert digest(dict(manifest, service="other")) != digest(manifest)


def test_second_invocation_tonight_never_repeats(batch, plan):
    Night(batch, plan, at(3, 0, 30)).run()
    night = Night(batch, plan, at(3, 2))
    assert set(night.run().values()) == {"attempted-tonight"}
    assert night.launched == []


def test_concurrent_invocation_is_refused_by_the_batch_lock(batch, plan):
    path = Path(plan["root"]) / "scheduled" / "batch.lock"
    with path.open("a") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        night = Night(batch, plan, at(3, 0, 30))
        assert night.run() == {"batch": "locked"}
    assert night.launched == []


@pytest.mark.parametrize(
    "change",
    [
        lambda p: p["series"].append(series("one")),
        lambda p: p["series"][0].update(id="../one"),
        lambda p: p["series"][0].update(id=""),
        lambda p: p.update(name="Batch 1"),
        lambda p: p["series"][0].update(gate="G05"),
        lambda p: p["series"][0].update(baseline=None),
        lambda p: p["series"][2].update(baseline="baseline"),
        lambda p: p["series"][0].update(candidate="unpinned"),
        lambda p: p["series"][0].update(template_sha256="abc"),
        lambda p: p["series"][0].pop("template_sha256"),
        lambda p: p.update(series=[]),
        lambda p: p.update(first_night="2026-10-06"),
        lambda p: p.update(last_night="2026-13-01"),
        lambda p: p.update(start="06:30:00", end="00:30:00"),
        lambda p: p.update(timezone="Nowhere/Else"),
        lambda p: p["pins"]["quiet_policy"].update(foreign_cpu_cores_max=2.0),
        lambda p: p["pins"]["checkouts"].pop("harness"),
        lambda p: p["pins"]["files"].pop("harness/uv.lock"),
        lambda p: p["pins"]["files"].update(extra="e" * 64),
    ],
)
def test_plan_validation(batch, plan, tmp_path, change):
    change(plan)
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    with pytest.raises((ValueError, KeyError)):
        batch["load_plan"](path)


def test_valid_plan_loads_and_templates_may_be_absent_for_review(batch, plan, tmp_path):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    assert batch["load_plan"](path)["name"] == "batch"
    for item in plan["series"]:
        item.pop("template_sha256")
    path.write_text(json.dumps(plan))
    assert batch["load_plan"](path, templates=False)["name"] == "batch"


def test_plan_bytes_must_match_the_reviewed_hash(batch, plan, tmp_path):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    reviewed = hashlib.sha256(path.read_bytes()).hexdigest()
    assert batch["load_plan"](path, sha256=reviewed)["name"] == "batch"
    plan["last_night"] = "2026-10-30"
    path.write_text(json.dumps(plan))
    with pytest.raises(ValueError, match="reviewed SHA-256"):
        batch["load_plan"](path, sha256=reviewed)


def test_templates_refuse_checkouts_that_disagree_with_pins(batch, plan):
    night = Night(batch, plan, at(3, 1), drift={"candidate": "c" * 40})
    with pytest.raises(ValueError, match="differ from the plan's pins"):
        batch["templates"](plan, night.root)
