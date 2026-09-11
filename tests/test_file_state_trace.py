"""Cross-process trace determinism and exact-b1 semantic continuity."""

import json
import subprocess
import sys
from pathlib import Path


def test_symbolic_trace_matches_b1_in_independent_processes(tmp_path):
    root = Path(__file__).resolve().parents[1]
    historical = json.loads((root / "tests/data/file_state_b1.json").read_text())
    for run in range(2):
        output = tmp_path / f"trace-{run}.json"
        subprocess.run(
            [
                sys.executable,
                str(root / "scripts/capture_file_state_trace.py"),
                "--source-root",
                str(root),
                "--engine",
                "stdlib",
                "--output",
                str(output),
            ],
            check=True,
            timeout=30,
        )
        candidate = json.loads(output.read_text())
        assert candidate["semantic"] == historical["semantic"]
        assert candidate["fixture_sha256"] == historical["fixture_sha256"]
        assert candidate["diagnostic"]  # Retained, deliberately not byte-gated.
