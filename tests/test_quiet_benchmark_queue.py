"""Sequential quiet phases preserve completed evidence and share one deadline."""

import hashlib
import json
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def setup_queue(tmp_path, monkeypatch):
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    module = runpy.run_path(str(scripts / "run_quiet_benchmark_queue.py"))
    runner = tmp_path / "runner.py"
    runner.write_text("# stub, never executed\n", encoding="utf-8")
    deadline = "2026-09-27T06:00:00-07:00"
    phases = []
    for gate in ("G08", "G06", "G07"):
        manifest = tmp_path / f"{gate}.json"
        manifest.write_text(
            json.dumps({"deadline": deadline, "output": str(tmp_path / gate)}),
            encoding="utf-8",
        )
        phases.append(
            dict(
                gate=gate,
                manifest=str(manifest),
                runner=str(runner),
                manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
                runner_sha256=hashlib.sha256(runner.read_bytes()).hexdigest(),
            )
        )
    queue = dict(
        deadline=deadline,
        output=str(tmp_path / "queue"),
        python=sys.executable,
        phases=phases,
    )
    clock = SimpleNamespace(now=0)
    monkeypatch.setitem(
        module["run"].__globals__, "time", SimpleNamespace(time=lambda: clock.now)
    )
    monkeypatch.setattr(
        module["run"].__globals__["subprocess"], "run", lambda *a, **k: None
    )
    return module, queue, clock


def test_queue_runs_sequentially_and_preserves_completed_phases(
    setup_queue, monkeypatch
):
    module, queue, _ = setup_queue
    active = []
    finished = []

    class Child:
        returncode = 0

        def __init__(self, argv, **kwargs):
            assert not active
            self.manifest = json.loads(Path(argv[2]).read_text())
            active.append(Path(self.manifest["output"]).name)

        def wait(self, timeout):
            gate = active.pop()
            finished.append(gate)
            output = Path(self.manifest["output"])
            output.mkdir()
            module["write_status"](
                output, {"status": "complete" if gate != "G06" else "failed"}
            )
            self.returncode = 0 if gate != "G06" else 1

    monkeypatch.setattr(module["run"].__globals__["subprocess"], "Popen", Child)
    module["run"](queue)
    assert finished == ["G08", "G06", "G07"]
    result = json.loads((Path(queue["output"]) / "status.json").read_text())
    assert [p["status"] for p in result["phases"]] == ["complete", "failed", "complete"]
    assert result["status"] == "incomplete"


def test_queue_defers_unstarted_phases_at_shared_deadline(setup_queue, monkeypatch):
    module, queue, clock = setup_queue

    class Child:
        returncode = 0

        def __init__(self, argv, **kwargs):
            self.manifest = json.loads(Path(argv[2]).read_text())
            assert Path(self.manifest["output"]).name == "G08"

        def wait(self, timeout):
            output = Path(self.manifest["output"])
            output.mkdir()
            module["write_status"](output, {"status": "complete"})
            clock.now = 2_000_000_000

    monkeypatch.setattr(module["run"].__globals__["subprocess"], "Popen", Child)
    module["run"](queue)
    result = json.loads((Path(queue["output"]) / "status.json").read_text())
    assert [p["status"] for p in result["phases"]] == [
        "complete",
        "deferred",
        "deferred",
    ]
    for gate in ("G06", "G07"):
        assert (
            json.loads(
                (Path(queue["output"]).parent / gate / "status.json").read_text()
            )["status"]
            == "deferred"
        )


def test_queue_rejects_changed_frozen_manifest(setup_queue):
    module, queue, _ = setup_queue
    Path(queue["phases"][1]["manifest"]).write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="manifest changed"):
        module["validate"](queue)


def test_queue_stops_current_runner_and_never_launches_next_after_timeout(
    setup_queue, monkeypatch
):
    import subprocess

    module, queue, clock = setup_queue
    events = []

    class Child:
        returncode = -15

        def __init__(self, argv, **kwargs):
            events.append("start")

        def wait(self, timeout):
            if events == ["start"]:
                clock.now = 2_000_000_000
                raise subprocess.TimeoutExpired("runner", timeout)
            events.append("settled")

        def send_signal(self, signum):
            events.append("terminate")

    monkeypatch.setattr(module["run"].__globals__["subprocess"], "Popen", Child)
    module["run"](queue)
    assert events == ["start", "terminate", "settled"]
    status = json.loads((Path(queue["output"]) / "status.json").read_text())
    assert [phase["status"] for phase in status["phases"]] == ["deferred"] * 3


def test_queue_aborts_when_runner_cannot_settle(setup_queue, monkeypatch):
    import subprocess

    module, queue, _ = setup_queue
    events = []

    class Child:
        returncode = -9

        def __init__(self, argv, **kwargs):
            events.append("start")

        def wait(self, timeout=None):
            if "kill" not in events:
                raise subprocess.TimeoutExpired("runner", timeout)
            events.append("settled")

        def send_signal(self, signum):
            events.append("terminate")

        def kill(self):
            events.append("kill")

    monkeypatch.setattr(module["run"].__globals__["subprocess"], "Popen", Child)
    with pytest.raises(RuntimeError, match="failed to settle"):
        module["run"](queue)
    assert events == ["start", "terminate", "kill", "settled"]
    status = json.loads((Path(queue["output"]) / "status.json").read_text())
    assert status["status"] == "failed"
