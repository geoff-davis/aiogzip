"""Timing report rejects incompatible evidence and never converts noise to a pass."""

import copy
import json
import runpy
from pathlib import Path

import pytest


@pytest.fixture
def reporter():
    return runpy.run_path(
        str(Path(__file__).resolve().parents[1] / "scripts/compare_b2_timing.py")
    )


@pytest.fixture
def evidence(tmp_path):
    index = dict(
        gate="G06",
        sources={"A": "old", "B": "new"},
        row_count=1,
        blocks=[],
        sampling=dict(
            discard_samples=1,
            batch_seconds=0.1,
            warmup_seconds=0.25,
            batch_min_operations=3,
        ),
        repeat=2,
        max_block_seconds=100,
    )
    for n, order in enumerate(("ABBA", "BAAB", "ABBA", "BAAB")):
        entries = []
        for j, side in enumerate(order):
            value = 1 if side == "A" else 1.1
            capture = dict(
                source={"sha": index["sources"][side], "status": ""},
                harness={"sha": "harness", "status": ""},
                harness_sha256="hash",
                started_at=1 + n * 100 + j * 10,
                ended_at=2 + n * 100 + j * 10,
                python="python",
                platform="linux",
                engines={"decompression": "stdlib"},
                affinity=[13],
                dependencies={"aiofiles": "23.2.1"},
                phase="timing",
                sampling=copy.deepcopy(index["sampling"]),
                rows=[
                    dict(
                        case={"size": 1},
                        fixture={"hash": "same"},
                        samples=[{"seconds": 0.001}, {"seconds": value}],
                        min_seconds=value,
                    )
                ],
            )
            name = f"{n}-{j}.json"
            (tmp_path / name).write_text(json.dumps(capture))
            entries.append(dict(side=side, path=name))
        index["blocks"].append(dict(status="complete", captures=entries))
    return index, tmp_path


def test_report_uses_retained_minima_and_flags_consistent_slowdown(reporter, evidence):
    index, root = evidence
    row = reporter["compare"](index, root)["rows"][0]
    assert row["median_ratio"] == pytest.approx(1.1)
    assert row["usable_blocks"] == 4 and row["investigate"]
    assert row["stronger_slowdown_evidence"]
    assert row["disposition"] == "review-required"


@pytest.mark.parametrize(
    "field,value",
    [
        ("affinity", [0]),
        ("python", "other"),
        ("engines", {"decompression": "other"}),
        ("source", {"sha": "wrong", "status": ""}),
        ("harness", {"sha": "harness", "status": "dirty"}),
        ("sampling", {"discard_samples": 0, "batch_seconds": 0.1}),
    ],
)
def test_report_rejects_incompatible_capture(reporter, evidence, field, value):
    index, root = evidence
    path = root / "0-1.json"
    data = json.loads(path.read_text())
    data[field] = value
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        reporter["compare"](index, root)


def test_rejected_blocks_are_visible_and_cannot_pass(reporter, evidence):
    index, root = evidence
    for block in index["blocks"][:2]:
        block.update(status="rejected", reason="interference")
    row = reporter["compare"](index, root)["rows"][0]
    assert row["complete_blocks"] == 2 and row["disposition"] == "inconclusive"
    assert row["blocks"][0]["status"] == "rejected"
    assert row["investigate"] and not row["stronger_slowdown_evidence"]


def test_noisy_slowdown_still_requires_investigation(reporter):
    blocks = [dict(ratio=1.1, a_drift=0.04, b_drift=0) for _ in range(4)]
    row = reporter["summarize"](blocks)
    assert row["investigate"] and row["disposition"] == "inconclusive"
    assert not row["stronger_slowdown_evidence"]


def test_mixed_directions_are_inconclusive(reporter):
    blocks = [dict(ratio=r, a_drift=0, b_drift=0) for r in (0.99, 1.01, 0.99, 1.01)]
    assert reporter["summarize"](blocks)["disposition"] == "inconclusive"


@pytest.mark.parametrize(
    "mutation", ["minimum", "nan", "matrix", "duplicate", "order", "reused"]
)
def test_report_rejects_malformed_evidence(reporter, evidence, mutation):
    index, root = evidence
    path = root / "0-1.json"
    data = json.loads(path.read_text())
    if mutation == "minimum":
        data["rows"][0]["min_seconds"] = 0.001
    if mutation == "nan":
        data["rows"][0]["samples"][1]["seconds"] = float("nan")
    if mutation == "matrix":
        data["rows"][0]["case"]["size"] = 2
    if mutation == "duplicate":
        data["rows"].append(copy.deepcopy(data["rows"][0]))
    if mutation == "order":
        index["blocks"][0]["captures"][0]["side"] = "B"
    if mutation == "reused":
        index["blocks"][1]["captures"][1]["path"] = "0-0.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        reporter["compare"](index, root)


@pytest.mark.parametrize(
    "change", ["sampling", "repeat", "span", "same-source", "overlap"]
)
def test_report_requires_declared_protocol_and_chronology(reporter, evidence, change):
    index, root = evidence
    if change == "sampling":
        index["sampling"]["warmup_seconds"] = 1
    elif change == "repeat":
        index["repeat"] = 3
    elif change == "span":
        index["max_block_seconds"] = 5
    elif change == "same-source":
        index["sources"]["B"] = index["sources"]["A"]
    else:
        path = root / "0-1.json"
        capture = json.loads(path.read_text())
        capture["started_at"] = 1
        path.write_text(json.dumps(capture))
    with pytest.raises(ValueError):
        reporter["compare"](index, root)


def test_g08_report_requires_throughput_selection(reporter, evidence):
    index, root = evidence
    index["gate"] = "G08"
    index["sampling"].update(throughput_only=True, latency_only=False)
    for path in root.glob("*.json"):
        capture = json.loads(path.read_text())
        capture["sampling"] = copy.deepcopy(index["sampling"])
        capture.update(
            aiofiles="23.2.1", compression_engine_module="zlib", fast_compress=False
        )
        row = capture["rows"][0]
        row.update(
            case="throughput-64",
            fixture="text",
            direction="decompress",
            payload_sha256="payload",
            input_sha256="input",
        )
        path.write_text(json.dumps(capture))
    assert reporter["compare"](index, root)["rows"][0]["investigate"]
    index["sampling"].update(throughput_only=False, latency_only=True)
    for path in root.glob("*.json"):
        capture = json.loads(path.read_text())
        capture["sampling"] = copy.deepcopy(index["sampling"])
        path.write_text(json.dumps(capture))
    with pytest.raises(ValueError, match="throughput-only"):
        reporter["compare"](index, root)
