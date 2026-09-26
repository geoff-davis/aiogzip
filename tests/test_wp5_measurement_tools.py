"""Guard the unattended runner and the starvation measurement's final gap."""

import runpy
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def scripts(monkeypatch):
    root = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(root))
    return root


def test_host_load_subtracts_only_our_service_cpu(scripts):
    runner = runpy.run_path(str(scripts / "run_quiet_benchmarks.py"))
    measure = runner["foreign_cores"]
    assert measure((10, 100, 4), (15, 107, 9)) == pytest.approx(0.4)
    assert measure((10, 100, 4), (15, 105, 9)) == 0


def test_changed_checkout_prevents_launch(scripts, monkeypatch, tmp_path):
    import capture_file_state_trace

    monkeypatch.setattr(
        capture_file_state_trace,
        "git_metadata",
        lambda root: {"sha": "expected", "status": " M source.py"},
    )
    runner = runpy.run_path(str(scripts / "run_quiet_benchmarks.py"))
    with pytest.raises(RuntimeError, match="checkout changed"):
        runner["validate"](
            {"checkouts": {str(tmp_path): "expected"}, "commands": [["unused"]]}
        )


async def test_starved_ticker_records_entire_operation_gap(scripts):
    harness = runpy.run_path(str(scripts / "measure_b2_stream_fairness.py"))

    async def wrapper(source):
        async for item in source:
            if item:
                yield item

    result = await harness["sample"](
        SimpleNamespace(decompress_chunks=wrapper),
        [b""] * 1000 + [b"ok"],
        b"ok",
        compress=False,
        fast=False,
        ticker=True,
    )
    assert result["ticks"] == 0
    assert result["ticks_before_final_item"] == 0
    assert result["max_gap_seconds"] == result["seconds"]
    assert result["max_items_between_ticks"] == 1001


@pytest.mark.parametrize(
    "deadline,message",
    [
        ("2026-09-27T06:00:00", "timezone offset"),
        ("2026-09-27T14:00:00+00:00", "agreed 06:00"),
    ],
)
def test_manifest_rejects_ambiguous_or_late_deadline(
    scripts, tmp_path, deadline, message
):
    runner = runpy.run_path(str(scripts / "run_quiet_benchmarks.py"))
    with pytest.raises(ValueError, match=message):
        runner["validate"](
            {
                "checkouts": {},
                "commands": [[sys.executable]],
                "deadline": deadline,
                "output": str(tmp_path / "results"),
            }
        )


def test_manifest_rejects_reused_output(scripts, tmp_path, monkeypatch):
    runner = runpy.run_path(str(scripts / "run_quiet_benchmarks.py"))
    validate = runner["validate"]
    monkeypatch.setitem(validate.__globals__, "time", SimpleNamespace(time=lambda: 0))
    with pytest.raises(ValueError, match="already exist"):
        validate(
            {
                "checkouts": {},
                "commands": [[sys.executable]],
                "deadline": "2026-09-27T13:00:00+00:00",
                "output": str(tmp_path),
            },
            fresh=True,
        )
