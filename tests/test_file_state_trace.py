"""Checkout-source trace continuity; not installed-wheel qualification."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("engine", ["stdlib", "zlib-ng"])
def test_symbolic_trace_matches_b1_in_independent_processes(tmp_path, engine):
    if engine == "zlib-ng" and importlib.util.find_spec("zlib_ng") is None:
        pytest.skip("optional zlib-ng engine is not installed")
    root = Path(__file__).resolve().parents[1]
    historical = json.loads(
        (root / "tests/data/file_state_b1.json").read_text(encoding="utf-8")
    )
    for run in range(2):
        output = tmp_path / f"trace-{run}.json"
        subprocess.run(
            [
                sys.executable,
                "-X",
                "warn_default_encoding",
                "-W",
                "error::EncodingWarning",
                str(root / "scripts/capture_file_state_trace.py"),
                "--source-root",
                str(root),
                "--engine",
                engine,
                "--extended",
                "--output",
                str(output),
            ],
            check=True,
            timeout=30,
        )
        candidate = json.loads(output.read_text(encoding="utf-8"))
        assert candidate["semantic"] == historical["semantic"]
        assert candidate["fixture_sha256"] == historical["fixture_sha256"]
        assert candidate["diagnostic"]  # Retained, deliberately not byte-gated.
