"""A fallback timing window runs only when no earlier window started a series."""

import json
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_b2_prior_windows.py"


@pytest.fixture
def blocker():
    return runpy.run_path(str(SCRIPT))["blocker"]


DECLARED = dict(blocks=[dict(id=f"block-{i}", commands=[]) for i in range(4)])


def window(tmp_path, name, status, blocks, warmups=(), manifest=DECLARED):
    directory = tmp_path / name
    directory.mkdir()
    state = dict(status=status, manifest=manifest, warmups=list(warmups), blocks=blocks)
    (directory / "status.json").write_text(json.dumps(state))
    return directory


def unstarted(count=4):
    return [
        dict(id=f"block-{i}", status="unstarted", reason="not reached", captures=[])
        for i in range(count)
    ]


def test_missing_output_never_initialized(blocker, tmp_path):
    assert blocker(tmp_path / "absent") is None


def test_deferred_before_blocks_permits_fallback(blocker, tmp_path):
    # Includes a warmup interrupted by interference: still no series.
    warmup = dict(output="warmup-A.json", status="interference")
    directory = window(tmp_path, "w", "deferred", unstarted(), [warmup])
    assert blocker(directory) is None


@pytest.mark.parametrize("status", ["complete", "incomplete", "failed", "running"])
def test_other_outcomes_block_fallback(blocker, tmp_path, status):
    assert "not 'deferred'" in blocker(window(tmp_path, "w", status, unstarted()))


@pytest.mark.parametrize(
    "slot",
    [
        dict(status="rejected", reason="interference", captures=[]),
        dict(status="complete", reason=None, captures=[{}]),
        dict(status="unstarted", reason="not reached", captures=[{}]),
    ],
)
def test_started_block_blocks_fallback(blocker, tmp_path, slot):
    blocks = unstarted()
    blocks[1] = dict(id="block-1", **slot)
    assert blocker(window(tmp_path, "w", "deferred", blocks)) == (
        "a measurement block started"
    )


@pytest.mark.parametrize(
    "blocks",
    [[], {}, "", unstarted(1), unstarted(5), unstarted()[::-1]],
    ids=["empty-list", "dict", "string", "truncated", "extra", "reordered"],
)
def test_incomplete_slot_record_blocks_fallback(blocker, tmp_path, blocks):
    assert blocker(window(tmp_path, "w", "deferred", blocks)) == (
        "block slots do not match the embedded manifest"
    )


@pytest.mark.parametrize("manifest", [dict(blocks=[]), {}, None])
def test_missing_declared_slots_blocks_fallback(blocker, tmp_path, manifest):
    reason = blocker(window(tmp_path, "w", "deferred", [], manifest=manifest))
    assert reason == "block slots do not match the embedded manifest" or (
        reason.startswith("unreadable status")
    )


@pytest.mark.parametrize("captures", [None, {}, [{}]])
def test_capture_field_must_be_empty_list(blocker, tmp_path, captures):
    blocks = unstarted()
    blocks[2]["captures"] = captures
    assert blocker(window(tmp_path, "w", "deferred", blocks)) == (
        "a measurement block started"
    )


@pytest.mark.parametrize("content", [None, "{", "[]", '{"status": "deferred"}'])
def test_unreadable_status_blocks_fallback(blocker, tmp_path, content):
    directory = tmp_path / "w"
    directory.mkdir()
    if content is not None:
        (directory / "status.json").write_text(content)
    assert blocker(directory).startswith("unreadable status")


def run(*arguments):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *map(str, arguments)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_permits_only_when_every_earlier_window_is_clear(tmp_path):
    deferred = window(tmp_path, "first", "deferred", unstarted())
    started = window(tmp_path, "second", "incomplete", unstarted())
    assert run(deferred, tmp_path / "absent").returncode == 0
    result = run(deferred, started)
    assert result.returncode == 1 and "second" in result.stdout


def test_cli_requires_absolute_paths():
    assert run("relative").returncode == 2
