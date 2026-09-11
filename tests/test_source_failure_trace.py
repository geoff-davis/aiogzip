"""BC2 permits only exact named corrections to a clean b1 source-failure trace."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("engine", ["stdlib", "zlib-ng"])
def test_source_failure_trace_matches_exact_bc2_exceptions(tmp_path, engine):
    if engine == "zlib-ng" and importlib.util.find_spec("zlib_ng") is None:
        pytest.skip("optional zlib-ng engine is not installed")
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "trace.json"
    subprocess.run(
        [
            sys.executable,
            "-X",
            "warn_default_encoding",
            "-W",
            "error::EncodingWarning",
            str(root / "scripts/capture_b2_source_failure_trace.py"),
            "--source-root",
            str(root),
            "--engine",
            engine,
            "--output",
            str(output),
        ],
        check=True,
        timeout=30,
    )
    before = json.loads(
        (root / "tests/data/source_failure_b1.json").read_text(encoding="utf-8")
    )
    after = json.loads(output.read_text(encoding="utf-8"))
    exceptions = json.loads(
        (root / "tests/data/source_failure_bc2.json").read_text(encoding="utf-8")
    )
    spec = importlib.util.spec_from_file_location(
        "source_trace_comparison", root / "scripts/compare_file_state_trace.py"
    )
    comparison = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(comparison)
    report = comparison.compare(before, after, exceptions)
    assert report["passed"], report
    assert len(before["semantic"]) == len(after["semantic"]) == 18
    assert len(report["differences"]) == len(exceptions) == 14
    assert {row["exception_id"] for row in report["differences"]} == {"BC2"}
