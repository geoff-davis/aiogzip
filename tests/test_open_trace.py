"""BC3 permits only exact named corrections to the clean b1 opening trace."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("engine", ["stdlib", "zlib-ng"])
def test_open_trace_matches_exact_bc3_exceptions(tmp_path, engine):
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
            str(root / "scripts/capture_b2_open_trace.py"),
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
    before = json.loads((root / "tests/data/open_b1.json").read_text(encoding="utf-8"))
    after = json.loads(output.read_text(encoding="utf-8"))
    exceptions = json.loads(
        (root / "tests/data/open_bc3.json").read_text(encoding="utf-8")
    )
    spec = importlib.util.spec_from_file_location(
        "open_trace_comparison", root / "scripts/compare_file_state_trace.py"
    )
    comparison = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(comparison)
    report = comparison.compare(before, after, exceptions)
    assert report["passed"], report
    assert len(before["semantic"]) == len(after["semantic"]) == 30
    assert len(report["differences"]) == len(exceptions) == 26
    assert {row["exception_id"] for row in report["differences"]} == {"BC3"}
    for name, value in after["semantic"].items():
        if name.endswith("-normal"):
            assert value == dict(
                opener="ok",
                closed_after_open=False,
                close="ok",
                closed=True,
                resource_closes=[1],
            )
