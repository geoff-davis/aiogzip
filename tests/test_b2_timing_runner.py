"""Bounded window behavior without running a benchmark or waiting in real time."""

import io
import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def runner(monkeypatch):
    root = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(root))
    return runpy.run_path(str(root / "run_b2_timing_blocks.py"))


@pytest.fixture
def fake(runner, tmp_path):
    cls = runner["WindowRunner"]
    obj = object.__new__(cls)
    now = [0.0]
    obj.clock = SimpleNamespace(
        time=lambda: now[0],
        monotonic=lambda: now[0],
        sleep=lambda n: now.__setitem__(0, now[0] + n),
    )
    obj.manifest = dict(
        output=str(tmp_path),
        minimum_measurement_seconds=100,
        command_timeout_seconds=20,
        block_timeout_seconds=100,
        cpu=0,
        warmups=[],
        blocks=[dict(id=str(i), commands=[dict(output=f"{i}.json")]) for i in range(4)],
    )
    obj.not_before = 0
    obj.deadline = 1000
    obj.end = 1000
    obj.block_end = 1000
    obj.output = tmp_path
    obj.events = io.StringIO()
    obj.active = None
    obj.state = dict(
        status="waiting",
        warmups=[],
        blocks=[
            dict(id=str(i), status="unstarted", reason="not reached", captures=[])
            for i in range(4)
        ],
    )
    return obj, now


def test_interference_rejects_one_block_and_preserves_others(fake):
    obj, _ = fake
    calls = []
    obj.quiet = lambda **kwargs: True

    def command(declaration):
        calls.append(declaration["output"])
        reason = "interference" if declaration["output"] == "1.json" else None
        return reason, dict(status=reason or "complete")

    obj.command = command
    obj.run()
    assert calls == ["0.json", "1.json", "2.json", "3.json"]
    assert [b["status"] for b in obj.state["blocks"]] == [
        "complete",
        "rejected",
        "complete",
        "complete",
    ]
    assert obj.state["status"] == "incomplete"


def test_deadline_retains_finished_block_and_unstarted_slots(fake):
    obj, now = fake
    obj.quiet = lambda **kwargs: obj.remaining() > 0

    def command(declaration):
        if declaration["output"] == "1.json":
            now[0] = 1000
            return "deadline", dict(status="deadline")
        return None, dict(status="complete")

    obj.command = command
    obj.run()
    assert [b["status"] for b in obj.state["blocks"]] == [
        "complete",
        "rejected",
        "unstarted",
        "unstarted",
    ]


def test_busy_preflight_never_launches(fake):
    obj, _ = fake
    obj.quiet = lambda **kwargs: False
    obj.command = lambda _: pytest.fail("must not launch")
    obj.run()
    assert obj.state["status"] == "deferred"
    assert all(b["status"] == "unstarted" for b in obj.state["blocks"])


def test_warmup_failure_does_not_start_blocks(fake):
    obj, _ = fake
    obj.manifest["warmups"] = [dict(output="warmup.json")]
    obj.quiet = lambda **kwargs: True
    obj.command = lambda _: ("interference", dict(status="interference"))
    obj.run()
    assert len(obj.state["warmups"]) == 1
    assert all(b["status"] == "unstarted" for b in obj.state["blocks"])


def test_exception_preserves_prior_blocks_and_records_active_rejection(fake):
    obj, _ = fake
    obj.quiet = lambda **kwargs: True

    def command(declaration):
        if declaration["output"] == "1.json":
            raise InterruptedError("terminated")
        return None, dict(status="complete")

    obj.command = command
    with pytest.raises(InterruptedError):
        obj.run()
    assert obj.state["status"] == "failed"
    assert obj.state["blocks"][0]["status"] == "complete"
    assert obj.state["blocks"][1]["status"] == "rejected"
    assert obj.state["blocks"][2]["status"] == "unstarted"
    assert (obj.output / "status.json").is_file()


def test_quiet_period_restarts_after_busy_sample(fake):
    obj, now = fake

    def sample():
        now[0] += 5
        return dict(foreign_cores=1.01 if now[0] == 60 else 0, load=(0, 0, 0))

    obj.sample = sample
    assert obj.quiet(initial=True)
    assert now[0] == 180


def test_initial_wait_reserves_measurement_budget(fake):
    obj, now = fake
    now[0] = 901
    obj.sample = lambda: pytest.fail("must defer before sampling")
    assert not obj.quiet(initial=True)


def test_command_is_reaped_on_interference(runner, fake, monkeypatch):
    obj, _ = fake
    function = runner["WindowRunner"].command
    monkeypatch.setitem(function.__globals__, "validate", lambda _: None)
    child = SimpleNamespace(returncode=None, poll=lambda: None)
    stopped = []
    monkeypatch.setitem(function.__globals__, "stop_child", lambda c: stopped.append(c))
    obj.popen = lambda *args, **kwargs: child
    obj.sample = lambda limit: dict(foreign_cores=1.01)
    reason, record = obj.command(
        dict(output="capture.json", argv=["program", "{capture}"])
    )
    assert reason == "interference" and stopped == [child]
    assert record["output"] == str(obj.output / "capture.json")


def test_command_reaps_even_when_monitor_fails(runner, fake, monkeypatch):
    obj, _ = fake
    function = runner["WindowRunner"].command
    monkeypatch.setitem(function.__globals__, "validate", lambda _: None)
    child = SimpleNamespace(returncode=None, poll=lambda: None)
    stopped = []
    monkeypatch.setitem(function.__globals__, "stop_child", lambda c: stopped.append(c))
    obj.popen = lambda *args, **kwargs: child

    def broken(limit):
        raise OSError("cpu accounting unavailable")

    obj.sample = broken
    with pytest.raises(OSError):
        obj.command(dict(output="capture.json", argv=["program", "{capture}"]))
    assert stopped == [child]


@pytest.mark.parametrize("policy", [0.25, 1.01, float("nan")])
def test_policy_must_match_declared_thresholds(runner, policy):
    declared = dict(runner["POLICY"], foreign_cpu_cores_max=policy)
    with pytest.raises(ValueError, match="quiet policy"):
        runner["validate"](dict(quiet_policy=declared))


@pytest.mark.parametrize(
    "gate,count,warmups",
    [("G06", 4, 2), ("G08-throughput", 4, 2), ("G08-scheduling", 4, 0), ("G07", 7, 0)],
)
def test_manifest_preparation_preserves_full_protocol(
    runner, monkeypatch, tmp_path, gate, count, warmups
):
    root = Path(__file__).resolve().parents[1] / "scripts"
    module = runpy.run_path(str(root / "prepare_b2_timing_window.py"))
    prepare = module["prepare"]
    monkeypatch.setitem(
        prepare.__globals__, "git_metadata", lambda p: dict(sha=p.name, status="")
    )
    monkeypatch.setitem(prepare.__globals__, "digest", lambda p: "hash")
    manifest = prepare(
        gate=gate,
        engine="stdlib",
        baseline=tmp_path / "a",
        candidate=tmp_path / "b",
        harness=tmp_path / "h",
        runner=tmp_path / "r",
        python=tmp_path / "python",
        output=tmp_path / "output",
        service="aiogzip-wp5-test.service",
    )
    assert len(manifest["blocks"]) == count and len(manifest["warmups"]) == warmups
    assert manifest["not_before"] is None and manifest["deadline"] is None
    with pytest.raises(ValueError, match="draft manifest"):
        runner["validate"](manifest)
    if gate == "G07":
        assert [c["engine"] for c in manifest["blocks"][0]["commands"]] == [
            "stdlib",
            "zlib-ng",
        ]
        assert [c["engine"] for c in manifest["blocks"][1]["commands"]] == [
            "zlib-ng",
            "stdlib",
        ]
        assert all(
            c["argv"][c["argv"].index("--repeat") + 1] == "1"
            for b in manifest["blocks"]
            for c in b["commands"]
        )
    else:
        assert [
            "".join(c["side"] for c in b["commands"]) for b in manifest["blocks"]
        ] == ["ABBA", "BAAB", "ABBA", "BAAB"]
    if warmups:
        assert manifest["comparison"]["repeat"] == 9
        assert manifest["comparison"]["sampling"]["discard_samples"] == 2
        assert manifest["comparison"]["row_count"] == (175 if gate == "G06" else 16)


def test_index_preserves_rejected_block(fake):
    obj, _ = fake
    obj.manifest["comparison"] = dict(gate="G06")
    for b in obj.manifest["blocks"]:
        b["commands"][0]["side"] = "A"
    obj.state["blocks"][0].update(status="rejected", reason="interference")
    obj.save()
    import json

    index = json.loads((obj.output / "comparison-index.json").read_text())
    assert index["blocks"][0]["status"] == "rejected"
    assert index["blocks"][0]["reason"] == "interference"
    assert index["blocks"][1]["status"] == "unstarted"


def test_insufficient_block_reserve_leaves_slot_unstarted(fake):
    obj, now = fake
    obj.quiet = lambda **kwargs: True

    def command(declaration):
        now[0] = 950
        return None, dict(status="complete")

    obj.command = command
    obj.run()
    assert [b["status"] for b in obj.state["blocks"]] == [
        "complete",
        "unstarted",
        "unstarted",
        "unstarted",
    ]
    assert obj.state["reason"] == "insufficient reserve for next block"


def test_crash_time_index_never_calls_active_block_unstarted(fake):
    import json

    obj, _ = fake
    obj.manifest["comparison"] = dict(gate="G06")
    for b in obj.manifest["blocks"]:
        b["commands"][0]["side"] = "A"
    obj.state["blocks"][0].update(status="complete", reason=None)
    obj.state["blocks"][1].update(status="running", reason=None)
    obj.save()
    index = json.loads((obj.output / "comparison-index.json").read_text())
    assert index["blocks"][0]["reason"] is None
    assert index["blocks"][1]["status"] == "rejected"
    assert "interrupted" in index["blocks"][1]["reason"]


def test_block_span_reaps_child_and_cannot_complete(runner, fake, monkeypatch):
    obj, now = fake
    function = runner["WindowRunner"].command
    monkeypatch.setitem(function.__globals__, "validate", lambda _: None)
    obj.block_end = 10
    child = SimpleNamespace(returncode=None, poll=lambda: None)
    stopped = []
    monkeypatch.setitem(function.__globals__, "stop_child", lambda c: stopped.append(c))
    obj.popen = lambda *args, **kwargs: child

    def sample(limit):
        assert limit == 10
        now[0] = 10
        return dict(foreign_cores=0)

    obj.sample = sample
    reason, record = obj.command(
        dict(output="capture.json", argv=["program", "{capture}"])
    )
    assert reason == "block-span" and record["status"] == "block-span"
    assert stopped == [child]


@pytest.mark.parametrize(
    "foreign,load,expected", [(1.0, 0.5, True), (1.01, 0.0, False), (0.0, 5.0, True)]
)
def test_foreign_ceiling_gates_and_load_is_only_recorded(fake, foreign, load, expected):
    obj, now = fake
    obj.end = obj.deadline = 130

    def sample():
        now[0] += 5
        return dict(foreign_cores=foreign, load=(load, load, 0))

    obj.sample = sample
    assert obj.quiet() is expected
