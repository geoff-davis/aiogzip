"""The oracle must distinguish diagnostic changes from exact behavioral exceptions."""

import importlib.util
from pathlib import Path


def test_comparison_requires_exact_scenario_exception():
    path = Path(__file__).resolve().parents[1] / "scripts/compare_file_state_trace.py"
    spec = importlib.util.spec_from_file_location("trace_comparison", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    before = {
        "fixture_sha256": "same",
        "semantic": {"read": ["old"], "close": [True]},
        "diagnostic": [1],
    }
    after = {**before, "diagnostic": [2]}
    assert module.compare(before, after)["passed"]
    after = {**after, "semantic": {"read": ["new"], "close": [True]}}
    assert not module.compare(before, after)["passed"]
    exceptions = {"read": {"before": ["old"], "after": ["new"], "exception_id": "BC2"}}
    assert module.compare(before, after, exceptions)["passed"]
    after["semantic"]["close"] = [False]
    report = module.compare(before, after, exceptions)
    assert not report["passed"]
    assert report["differences"][0]["exception_id"] is None
