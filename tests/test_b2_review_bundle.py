"""Archive evidence before analysis; never infer permission to replay work."""

import hashlib
import json
import runpy
from pathlib import Path

import pytest


@pytest.fixture
def tools(monkeypatch):
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    return runpy.run_path(str(scripts / "collect_b2_timing_window.py")), runpy.run_path(
        str(scripts / "summarize_b2_observations.py")
    )


def write(path, value):
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def evidence(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    sampling = dict(
        warmup_seconds=0.25,
        batch_seconds=0.1,
        batch_min_operations=3,
        discard_samples=2,
        throughput_only=True,
        latency_only=False,
    )
    comparison = dict(
        gate="G08",
        sources=dict(A="A", B="B"),
        row_count=1,
        sampling=sampling,
        repeat=9,
        max_block_seconds=1800,
    )
    manifest = dict(
        scope="G08-throughput",
        cpu=13,
        output=str(run),
        comparison=comparison,
        checkouts={"/frozen/A": "A", "/frozen/B": "B", "/frozen/harness": "H"},
        warmups=[],
        blocks=[],
    )
    state = dict(status="complete", manifest=manifest, warmups=[], blocks=[])
    for n, order in enumerate(("ABBA", "BAAB", "ABBA", "BAAB")):
        block = dict(id=f"b{n}", commands=[])
        slot = dict(id=f"b{n}", status="complete", reason=None, captures=[])
        for i, side in enumerate(order):
            name = f"{n}-{i}.json"
            value = 1 if side == "A" else 1.1
            command = dict(
                output=name,
                side=side,
                engine="stdlib",
                argv=[
                    "taskset",
                    "-c",
                    "13",
                    "python",
                    "/frozen/harness/scripts/measure.py",
                    "--source-root",
                    f"/frozen/{side}",
                ],
            )
            capture = dict(
                source=dict(sha=side, status=""),
                harness=dict(sha="H", status=""),
                harness_sha256="hash",
                python="python",
                platform="linux",
                engines=dict(decompression="stdlib-zlib"),
                aiofiles="23",
                affinity=[13],
                compression_engine_module="zlib",
                fast_compress=False,
                sampling=sampling,
                started_at=1 + n * 100 + i * 10,
                ended_at=2 + n * 100 + i * 10,
                rows=[
                    dict(
                        case="throughput-64",
                        fixture="random",
                        direction="decompress",
                        payload_sha256="payload",
                        input_sha256="wire",
                        samples=[dict(seconds=value) for _ in range(9)],
                        min_seconds=value,
                    )
                ],
            )
            sha = write(run / name, capture)
            block["commands"].append(command)
            slot["captures"].append(
                dict(
                    output=str(run / name), status="complete", returncode=0, sha256=sha
                )
            )
        manifest["blocks"].append(block)
        state["blocks"].append(slot)
    mp = tmp_path / "manifest.json"
    state["manifest_sha256"] = write(mp, manifest)
    write(run / "status.json", state)
    (run / "events.jsonl").write_text('{"event":"host"}\n')
    (run / "partial.log").write_bytes(b"raw partial output\x00\xff")
    return mp, run, tmp_path / "bundle", state


def test_complete_bundle_preserves_bytes_and_reports_slowdown(tools, evidence):
    collector, _ = tools
    mp, run, dest, state = evidence
    before = {p.name: p.read_bytes() for p in run.iterdir()}
    review = collector["collect"](mp, run, dest)
    assert not review["analysis_errors"]
    assert {p.name: p.read_bytes() for p in (dest / "raw").iterdir()} == before
    report = json.loads((dest / "throughput.json").read_text())
    assert report["rows"][0]["investigate"]
    assert report["rows"][0]["median_ratio"] == pytest.approx(1.1)
    assert report["rows"][0]["disposition"] == "review-required"
    assert (
        json.loads((dest / "continuation-review.json").read_text())["eligible_blocks"]
        == []
    )
    with pytest.raises(ValueError, match="fresh destination"):
        collector["collect"](mp, run, dest)


def test_live_run_cannot_be_collected(tools, evidence):
    collector, _ = tools
    mp, run, dest, state = evidence
    state["status"] = "running"
    write(run / "status.json", state)
    with pytest.raises(ValueError, match="active"):
        collector["collect"](mp, run, dest)
    assert not dest.exists()


def test_corrupt_capture_is_archived_but_not_accepted(tools, evidence):
    collector, _ = tools
    mp, run, dest, state = evidence
    (run / "0-0.json").write_text("corrupted")
    review = collector["collect"](mp, run, dest)
    assert "hash mismatch" in review["analysis_errors"][0]
    assert (dest / "raw/0-0.json").read_text() == "corrupted"
    assert not (dest / "throughput.json").exists()
    assert not (dest / "continuation-review.json").exists()


def test_rejected_capture_never_enters_summary_and_only_unstarted_is_eligible(
    tools, evidence
):
    collector, _ = tools
    mp, run, dest, state = evidence
    state["status"] = "incomplete"
    state["blocks"][1].update(status="rejected", reason="interference")
    state["blocks"][3].update(status="unstarted", reason="reserve", captures=[])
    # Remove files from the never-started slot, preserving all rejected raw data.
    for i in range(4):
        (run / f"3-{i}.json").unlink()
    write(run / "status.json", state)
    collector["collect"](mp, run, dest)
    row = json.loads((dest / "throughput.json").read_text())["rows"][0]
    assert row["complete_blocks"] == 2 and row["disposition"] == "inconclusive"
    plan = json.loads((dest / "continuation-review.json").read_text())
    assert [b["id"] for b in plan["eligible_blocks"]] == ["b3"]
    assert [c["side"] for c in plan["eligible_blocks"][0]["commands"]] == list("BAAB")
    assert (dest / "raw/1-0.json").exists()


def test_started_slot_cannot_be_replayed(tools, evidence):
    collector, _ = tools
    mp, run, dest, state = evidence
    state["blocks"][0]["status"] = "unstarted"
    with pytest.raises(ValueError, match="contains capture"):
        collector["continuation_plan"](state["manifest"], state)
    state["blocks"][0].update(captures=[], reason="not started")
    state["manifest"]["continuation_of"] = "parent-hash"
    assert (
        collector["continuation_plan"](state["manifest"], state)["eligible_blocks"]
        == []
    )


def test_symlink_not_followed(tools, evidence, tmp_path):
    collector, _ = tools
    mp, run, dest, _ = evidence
    (run / "external").symlink_to(mp)
    with pytest.raises(ValueError, match="symlinks"):
        collector["collect"](mp, run, dest)


def test_scaling_pairs_matching_capture_positions_and_keeps_noise(tools):
    _, summary = tools
    rows = []
    for size, times in [(1, [1, 2]), (2, [2, 6]), (4, [8, 12])]:
        rows.append(
            dict(
                identity=dict(case=dict(size=size, encoding="utf8", newline=None)),
                disposition="inconclusive",
                blocks=[
                    dict(block=0, status="complete", a_minima=times, b_minima=times),
                    dict(block=1, status="rejected"),
                ],
            )
        )
    report = summary["scaling"](dict(gate="G06", rows=rows))
    assert len(report["rows"]) == 4
    assert report["rows"][0]["summary"]["values"] == [2, 3]
    assert report["rows"][0]["input_dispositions"] == ["inconclusive", "inconclusive"]
    assert "| Source |" in summary["markdown"](report)


def capture():
    return dict(
        source=dict(sha="A", status=""),
        harness=dict(sha="H", status=""),
        harness_sha256="hash",
        python="py",
        platform="linux",
        engines=dict(decompression="stdlib"),
        aiofiles="23",
        affinity=[13],
        rows=[],
    )


def test_scheduling_zero_ticks_and_final_gap_are_retained(tools):
    _, summary = tools
    data = capture()
    data["sampling"] = dict(
        latency_only=True,
        throughput_only=False,
        discard_samples=0,
        warmup_seconds=0,
        batch_seconds=0,
    )
    data["rows"] = [
        dict(
            case="latency-empty",
            fixture="text",
            direction="decompress",
            payload_sha256="p",
            input_sha256="w",
            samples=[
                dict(
                    seconds=2,
                    ticks=0,
                    ticks_before_final_item=0,
                    max_gap_seconds=2,
                    p99_gap_seconds=2,
                    max_items_between_ticks=20001,
                )
            ],
        )
    ]
    result = summary["observations"]([("baseline", data)], "G08-scheduling")
    assert result["rows"][0]["summary"]["ticks"]["minimum"] == 0
    assert result["rows"][0]["summary"]["max_gap_seconds"]["maximum"] == 2
    data["sampling"]["discard_samples"] = 1
    with pytest.raises(ValueError, match="undiscarded"):
        summary["observations"]([("baseline", data)], "G08-scheduling")


def test_g07_separates_outcome_and_handle_from_cohort_time(tools):
    _, summary = tools
    data = capture()
    data["rows"] = [
        dict(
            case=dict(surface="read", size=1),
            fixture=dict(hash="p"),
            phase="latency",
            repeat=0,
            cohort_seconds=3,
            ticker_ticks=0,
            max_gap_seconds=3,
            p99_gap_seconds=3,
            handles=[
                dict(first_result_seconds=1, error=None, returned=1, binary_eof=False),
                dict(
                    first_result_seconds=2,
                    error=dict(type="OSError"),
                    returned=0,
                    binary_eof=False,
                ),
            ],
        )
    ]
    row = summary["observations"]([("candidate", data)], "G07")["rows"][0]
    assert row["summary"]["cohort_seconds"]["median"] == 3
    outcomes = row["first_result_by_handle_and_outcome"]
    assert [r["outcome"] for r in outcomes] == ["output", "error:OSError"]
    assert [r["summary"]["median"] for r in outcomes] == [1, 2]
    data["rows"][0]["phase"] = "resources"
    with pytest.raises(ValueError, match="resource row"):
        summary["observations"]([("candidate", data)], "G07")


@pytest.mark.parametrize("warmups", [[], [dict(status="interference")]])
def test_fully_deferred_attempt_is_not_a_continuation(tools, evidence, warmups):
    collector, _ = tools
    mp, run, dest, state = evidence
    state["status"] = "deferred"
    state["warmups"] = warmups
    for slot in state["blocks"]:
        slot.update(status="unstarted", reason="not reached", captures=[])
    plan = collector["continuation_plan"](state["manifest"], state)
    assert not plan["series_started"]
    assert plan["eligible_blocks"] == []
    assert plan["next_action"] == "new-initial-window-after-review"


def test_analysis_programming_error_still_produces_raw_bundle(
    tools, evidence, monkeypatch
):
    collector, _ = tools
    mp, run, dest, state = evidence

    def broken(*args):
        raise IndexError("malformed case")

    monkeypatch.setitem(collector["collect"].__globals__, "compare", broken)
    report = collector["collect"](mp, run, dest)
    assert report["analysis_errors"] == ["IndexError: malformed case"]
    assert not report["derived_artifacts_trusted"]
    assert (dest / "README.md").is_file() and (dest / "raw/status.json").is_file()
    assert "comparison-index.json" in report["artifacts"]
    assert not (dest / "continuation-review.json").exists()


def test_failed_run_requires_investigation_before_any_continuation(tools, evidence):
    collector, _ = tools
    mp, run, dest, state = evidence
    state["status"] = "failed"
    state["blocks"][3].update(status="unstarted", captures=[])
    plan = collector["continuation_plan"](state["manifest"], state)
    assert plan["failure_investigation_required"]
    assert plan["next_action"] == "investigate-failure-before-continuation"


def test_failed_warmup_headline_requires_investigation(tools, evidence):
    collector, _ = tools
    mp, run, dest, state = evidence
    state["status"] = "failed"
    for slot in state["blocks"]:
        slot.update(status="unstarted", captures=[])
    plan = collector["continuation_plan"](state["manifest"], state)
    assert plan["next_action"] == "investigate-failure-before-new-window"
    assert plan["eligible_blocks"] == []


def test_missing_block_identity_still_archives_analysis_error(tools, evidence):
    collector, _ = tools
    mp, run, dest, state = evidence
    del state["blocks"][0]["id"]
    write(run / "status.json", state)
    report = collector["collect"](mp, run, dest)
    assert report["analysis_errors"] and not report["derived_artifacts_trusted"]
    assert "missing id" in (dest / "README.md").read_text()
