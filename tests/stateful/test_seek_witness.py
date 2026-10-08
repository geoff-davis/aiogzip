"""The failed-text-seek cursor witness (BC11): recorded raw, on every side.

The interpreter compares the binary reader's logical position and decoder
identity across a text seek that fails or is cancelled. It reads plain
attributes every reference has, so trace-only replays against b1 or b2 record
the witness instead of crashing, and the run record keeps it, ``False``
included, as evidence.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import interpreter
import pytest
from generator import generate

import aiogzip

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
# Seed 4: a failed text seek that leaves the cursor; seed 225: one that moves it.
UNMOVED_SEED, MOVED_SEED = 4, 225


def _record(seed: int) -> dict:
    engine = aiogzip.engine_info().decompression
    return interpreter.recorded_run(aiogzip, generate(seed), engine, None)


@pytest.mark.parametrize(("seed", "moved"), [(UNMOVED_SEED, False), (MOVED_SEED, True)])
def test_run_record_keeps_the_witness(seed, moved):
    record = _record(seed)
    witnesses = record["cursor_moved"]
    assert witnesses, "the seed no longer fails a text seek"
    assert moved in {value for _index, value in witnesses}
    ops = generate(seed)["ops"]
    for index, value in witnesses:
        assert type(value) is bool
        op = ops[index]
        assert op.get("call", op)["op"] in interpreter.TEXT_SEEK_OPS
    json.dumps(witnesses)  # evidence must survive the JSON run record


def test_witness_reads_no_candidate_only_symbol():
    source = (HERE / "interpreter.py").read_text(encoding="utf-8")
    assert "_read_cursor" not in source


def _reference_root(tag: str, into: Path) -> Path | None:
    try:
        archive = subprocess.run(
            ["git", "archive", "--format=tar", tag, "src"],
            cwd=REPO,
            capture_output=True,
            check=False,
        )
    except OSError:
        return None
    if archive.returncode != 0 or not archive.stdout:
        return None
    into.mkdir(parents=True)
    tar = into / "src.tar"
    tar.write_bytes(archive.stdout)
    with tarfile.open(tar) as members:
        members.extractall(into, filter="data")
    return into


@pytest.mark.parametrize("tag", ["v2.0.0b1", "v2.0.0b2"])
def test_reference_replay_records_the_witness(tag, tmp_path):
    root = _reference_root(tag, tmp_path / "ref")
    if root is None:
        pytest.skip(f"{tag} is not available in this checkout")
    scenarios = tmp_path / "scenarios.jsonl"
    with scenarios.open("w", encoding="utf-8") as lines:
        for seed in (UNMOVED_SEED, MOVED_SEED, 899):
            lines.write(json.dumps(generate(seed)) + "\n")
    output = tmp_path / "runs.json"
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    subprocess.run(
        [
            sys.executable,
            str(HERE / "interpreter.py"),
            "--source-root",
            str(root),
            "--engine",
            "stdlib",
            "--scenarios",
            str(scenarios),
            "--output",
            str(output),
        ],
        check=True,
        env=env,
        cwd=str(HERE),
        timeout=300,
    )
    runs = json.loads(output.read_text(encoding="utf-8"))["runs"]
    for seed in (UNMOVED_SEED, MOVED_SEED):
        witnesses = runs[str(seed)]["cursor_moved"]
        assert witnesses
        assert all(type(value) is bool for _index, value in witnesses)
