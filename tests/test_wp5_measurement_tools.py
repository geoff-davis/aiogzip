"""Guard the unattended runner and the starvation measurement's final gap."""

import runpy
import sys
import tracemalloc
from pathlib import Path
from types import SimpleNamespace

import pytest

import aiogzip


@pytest.fixture
def scripts(monkeypatch):
    root = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(root))
    return root


def test_host_load_subtracts_only_our_service_cpu(scripts):
    runner = runpy.run_path(str(scripts / "run_quiet_benchmarks.py"))
    measure = runner["foreign_cores"]
    assert measure((10, 100, 4), (15, 107, 9)) == pytest.approx(0.4)
    assert measure((10, 100, 4), (15, 105, 9)) == 0


def test_changed_checkout_prevents_launch(scripts, monkeypatch, tmp_path):
    import capture_file_state_trace

    monkeypatch.setattr(
        capture_file_state_trace,
        "git_metadata",
        lambda root: {"sha": "expected", "status": " M source.py"},
    )
    runner = runpy.run_path(str(scripts / "run_quiet_benchmarks.py"))
    with pytest.raises(RuntimeError, match="checkout changed"):
        runner["validate"](
            {"checkouts": {str(tmp_path): "expected"}, "commands": [["unused"]]}
        )


async def test_starved_ticker_records_entire_operation_gap(scripts):
    harness = runpy.run_path(str(scripts / "measure_b2_stream_fairness.py"))

    async def wrapper(source):
        async for item in source:
            if item:
                yield item

    result = await harness["sample"](
        SimpleNamespace(decompress_chunks=wrapper),
        [b""] * 1000 + [b"ok"],
        b"ok",
        compress=False,
        fast=False,
        ticker=True,
    )
    assert result["ticks"] == 0
    assert result["ticks_before_final_item"] == 0
    assert result["max_gap_seconds"] == result["seconds"]
    assert result["max_items_between_ticks"] == 1001


@pytest.mark.parametrize(
    "deadline,message",
    [
        ("2026-09-27T06:00:00", "timezone offset"),
        ("2026-09-27T14:00:00+00:00", "agreed 06:00"),
    ],
)
def test_manifest_rejects_ambiguous_or_late_deadline(
    scripts, tmp_path, deadline, message
):
    runner = runpy.run_path(str(scripts / "run_quiet_benchmarks.py"))
    with pytest.raises(ValueError, match=message):
        runner["validate"](
            {
                "checkouts": {},
                "commands": [[sys.executable]],
                "deadline": deadline,
                "output": str(tmp_path / "results"),
            }
        )


def test_manifest_rejects_reused_output(scripts, tmp_path, monkeypatch):
    runner = runpy.run_path(str(scripts / "run_quiet_benchmarks.py"))
    validate = runner["validate"]
    monkeypatch.setitem(validate.__globals__, "time", SimpleNamespace(time=lambda: 0))
    with pytest.raises(ValueError, match="already exist"):
        validate(
            {
                "checkouts": {},
                "commands": [[sys.executable]],
                "deadline": "2026-09-27T13:00:00+00:00",
                "output": str(tmp_path),
            },
            fresh=True,
        )


@pytest.mark.parametrize(
    "surface",
    ["read", "read1", "readinto", "peek", "readline", "text-read", "text-readline"],
)
@pytest.mark.parametrize("seekable", [False, True])
async def test_resource_counter_matches_accounted_inflation(scripts, surface, seekable):
    harness = runpy.run_path(str(scripts / "measure_b2_read_resources.py"))
    row = await harness["measure"](
        aiogzip,
        {
            "size": 32768,
            "fixture": "repeated-x",
            "surface": surface,
            "seekable": seekable,
            "handles": 3,
        },
        "resources",
    )
    assert row["inflation"]["total_inflated_bytes"] == sum(
        handle["inflated_accounted_bytes"] for handle in row["handles"]
    )
    assert row["inflation"]["total_inflated_bytes"] > 0
    assert all(handle["round_trip_verified"] for handle in row["handles"])
    assert row["cohort_seconds"] is None
    assert row["max_gap_seconds"] is None
    assert not tracemalloc.is_tracing()


@pytest.mark.parametrize("fault", ["crc", "limit"])
async def test_resource_probe_observes_errors_without_losing_counter(scripts, fault):
    harness = runpy.run_path(str(scripts / "measure_b2_read_resources.py"))
    row = await harness["measure"](
        aiogzip,
        {
            "size": 32768,
            "fixture": "repeated-x",
            "surface": "readinto",
            "seekable": False,
            "handles": 2,
            "fault": fault,
            "limit": 1024 if fault == "limit" else None,
        },
        "resources",
    )
    assert all(handle["error"] for handle in row["handles"])
    if fault == "limit":
        assert 0 < row["inflation"]["total_inflated_bytes"] <= 2 * 1025
        assert all(handle["terminal_limit_verified"] for handle in row["handles"])
    else:
        assert all(handle["validation_salvage_verified"] for handle in row["handles"])


async def test_latency_probe_has_no_allocation_or_inflation_instrumentation(scripts):
    harness = runpy.run_path(str(scripts / "measure_b2_read_resources.py"))
    row = await harness["measure"](
        aiogzip,
        {
            "size": 32768,
            "fixture": "repeated-x",
            "surface": "text-read",
            "seekable": True,
            "handles": 1,
        },
        "latency",
    )
    assert row["inflation"] is None
    assert row["tracemalloc_peak_bytes"] is None
    assert row["cohort_seconds"] >= 0
    assert row["max_gap_seconds"] > 0
    assert row["handles"][0]["round_trip_verified"]


@pytest.mark.parametrize("newline", [None, "", "\n", "\r", "\r\n"])
@pytest.mark.parametrize("encoding", ["utf-8", "iso2022_jp"])
@pytest.mark.parametrize("content", ["repeated", "seeded-ascii"])
async def test_longline_resource_phase_validates_reference_without_timing(
    scripts, monkeypatch, newline, encoding, content
):
    harness = runpy.run_path(str(scripts / "measure_b2_long_lines.py"))
    case = dict(
        size=8192,
        newline=newline,
        encoding=encoding,
        chunk_size=31,
        content=content,
        ending="trailing-cr",
        family="long",
    )
    wire, expected, metadata = harness["fixture"](case)

    def forbidden_clock():
        raise AssertionError("resource measurement used a timing clock")

    monkeypatch.setitem(
        harness["sample"].__globals__,
        "time",
        SimpleNamespace(perf_counter=forbidden_clock),
    )
    result = await harness["sample"](aiogzip, case, wire, expected, "resources")
    assert result["verified"]
    assert result["seconds"] is None
    assert result["python_peak_bytes"] > 0
    assert (
        result["work"]["growing_buffer_characters"]
        <= 2 * metadata["input_characters"] + 31
    )
    assert not tracemalloc.is_tracing()


async def test_longline_wrong_reference_fails_and_restores_instrumentation(scripts):
    harness = runpy.run_path(str(scripts / "measure_b2_long_lines.py"))
    case = dict(
        size=1024,
        newline="",
        encoding="utf-8",
        chunk_size=31,
        content="repeated",
        ending="crlf",
        family="long",
    )
    wire, expected, _ = harness["fixture"](case)
    original = aiogzip.AsyncGzipTextFile._append_buffer
    with pytest.raises(AssertionError):
        await harness["sample"](aiogzip, case, wire, expected + ["wrong"], "resources")
    assert aiogzip.AsyncGzipTextFile._append_buffer is original
    assert not tracemalloc.is_tracing()


async def test_shortline_timing_phase_omits_resource_instrumentation(scripts):
    harness = runpy.run_path(str(scripts / "measure_b2_long_lines.py"))
    case = dict(
        size=100,
        newline="\r\n",
        encoding="iso2022_jp",
        chunk_size=31,
        content="repeated",
        ending="crlf",
        family="short",
    )
    wire, expected, metadata = harness["fixture"](case)
    result = await harness["sample"](aiogzip, case, wire, expected, "timing")
    assert metadata["returned_lines"] == 100
    assert result["seconds"] >= 0
    assert result["work"] is None
    assert result["python_peak_bytes"] is None


@pytest.mark.parametrize("newline", ["", "\r\n"])
@pytest.mark.parametrize("encoding", ["utf-8", "iso2022_jp"])
async def test_longline_split_fixture_crosses_real_decode_refills(
    scripts, monkeypatch, newline, encoding
):
    harness = runpy.run_path(str(scripts / "measure_b2_long_lines.py"))
    case = next(
        case
        for case in harness["matrix"]()
        if case["family"] == "split"
        and case["encoding"] == encoding
        and case["newline"] == newline
    )
    wire, expected, _ = harness["fixture"](case)
    pieces = []
    original = aiogzip.AsyncGzipBinaryFile.read

    async def read(handle, size=-1):
        data = await original(handle, size)
        pieces.append(data)
        return data

    monkeypatch.setattr(aiogzip.AsyncGzipBinaryFile, "read", read)
    await harness["sample"](aiogzip, case, wire, expected, "resources")
    assert any(
        a.endswith(b"\r") and b.startswith(b"\n")
        for a, b in zip(pieces, pieces[1:], strict=False)
    )


@pytest.mark.parametrize("newline", [None, "", "\n", "\r", "\r\n"])
async def test_longline_incompressible_control_preserves_full_line(scripts, newline):
    harness = runpy.run_path(str(scripts / "measure_b2_long_lines.py"))
    case = next(
        case
        for case in harness["matrix"]()
        if case["content"] == "seeded-bytes" and case["newline"] == newline
    )
    wire, expected, metadata = harness["fixture"](case)
    assert metadata["compressed_to_encoded_ratio"] >= 0.99
    assert len(expected) == 1
    assert len(expected[0]) == case["size"]
    result = await harness["sample"](aiogzip, case, wire, expected, "resources")
    assert result["verified"] and result["seconds"] is None


async def test_throughput_batch_reaches_timed_budget_and_records_raw_samples(
    scripts, monkeypatch
):
    harness = runpy.run_path(str(scripts / "measure_b2_stream_fairness.py"))
    durations = iter([0.02, 0.03, 0.05])

    async def sample(*args, **kwargs):
        assert kwargs["ticker"] is False
        return {"seconds": next(durations)}

    monkeypatch.setitem(harness["throughput_batch"].__globals__, "sample", sample)
    result = await harness["throughput_batch"](
        None, [], b"", compress=False, fast=False, target_seconds=0.075
    )
    assert result["iterations"] == 3
    assert result["timed_total_seconds"] == pytest.approx(0.1)
    assert result["seconds"] == pytest.approx(0.1 / 3)
    assert result["operation_seconds"] == [0.02, 0.03, 0.05]


async def test_throughput_warmup_is_excluded_from_batch_minima(scripts, monkeypatch):
    harness = runpy.run_path(str(scripts / "measure_b2_stream_fairness.py"))
    count = 0

    async def sample(*args, **kwargs):
        nonlocal count
        duration = 0.2 if count % 7 == 0 else 0.01
        count += 1
        return {"seconds": duration}

    monkeypatch.setitem(harness["run"].__globals__, "sample", sample)
    rows = await harness["run"](
        None,
        repeat=2,
        fast=False,
        size=1024,
        fixture="random",
        throughput_only=True,
        warmup_seconds=0.1,
        batch_seconds=0.025,
    )
    assert len(rows) == 8
    for row in rows:
        assert row["warmup"]["seconds"] == 0.2
        assert row["min_seconds"] == pytest.approx(0.01)
        assert [sample["iterations"] for sample in row["samples"]] == [3, 3]


async def test_throughput_batch_still_checks_complete_output(scripts):
    harness = runpy.run_path(str(scripts / "measure_b2_stream_fairness.py"))

    async def broken_wrapper(source):
        async for _item in source:
            yield b"wrong"

    with pytest.raises(AssertionError):
        await harness["throughput_batch"](
            SimpleNamespace(decompress_chunks=broken_wrapper),
            [b"input"],
            b"expected",
            compress=False,
            fast=False,
            target_seconds=0.1,
        )


async def test_slow_throughput_batch_still_uses_minimum_operation_count(
    scripts, monkeypatch
):
    harness = runpy.run_path(str(scripts / "measure_b2_stream_fairness.py"))

    async def sample(*args, **kwargs):
        return {"seconds": 0.2}

    monkeypatch.setitem(harness["throughput_batch"].__globals__, "sample", sample)
    result = await harness["throughput_batch"](
        None, [], b"", compress=False, fast=False, target_seconds=0.1, min_operations=3
    )
    assert result["iterations"] == 3
    assert result["timed_total_seconds"] == pytest.approx(0.6)
    assert result["seconds"] == pytest.approx(0.2)
    assert result["wall_seconds"] >= 0
