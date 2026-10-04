"""Cancellation during failed-open cleanup preserves b1 control flow."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("engine", ["stdlib", "zlib-ng"])
def test_cleanup_control_flow_matches_b1(tmp_path, engine):
    if engine == "zlib-ng" and importlib.util.find_spec("zlib_ng") is None:
        pytest.skip("optional zlib-ng engine is not installed")
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "cleanup.json"
    subprocess.run(
        [
            sys.executable,
            "-X",
            "warn_default_encoding",
            "-W",
            "error::EncodingWarning",
            str(root / "scripts/capture_b2_cleanup_trace.py"),
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
        (root / "tests/data/open_cleanup_b1.json").read_text(encoding="utf-8")
    )
    after = json.loads(output.read_text(encoding="utf-8"))
    assert after["fixture_sha256"] == before["fixture_sha256"]
    assert after["semantic"] == before["semantic"]
    assert len(after["semantic"]) == 8
    for name, value in after["semantic"].items():
        cancel = name.endswith("-cancel")
        assert value["outcome"]["type"] == (
            "CancelledError" if cancel else "TimeoutError"
        )
        assert value["cancelled"] is cancel
        assert value["cancelling"] == int(cancel)
        assert value["closes"] == 1
