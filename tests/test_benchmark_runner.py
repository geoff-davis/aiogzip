import argparse
import ast
import asyncio
import gzip
import hashlib
import importlib
import json
import struct
import sys
import tracemalloc
import zlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import FramedAsyncReader

BENCHMARKS_DIR = Path(__file__).resolve().parents[1] / "benchmarks"
sys.path.insert(0, str(BENCHMARKS_DIR))
bench_common = importlib.import_module("bench_common")
run_benchmarks = importlib.import_module("run_benchmarks")
bench_compare = importlib.import_module("bench_compare")
bench_targeted_contract = importlib.import_module("bench_targeted_contract")
bench_streaming = importlib.import_module("bench_streaming")
bench_codec_regressions = importlib.import_module("bench_codec_regressions")
bench_a3_regressions = importlib.import_module("bench_a3_regressions")
bench_a4_supplement = importlib.import_module("bench_a4_supplement")
investigate_b1_timing = importlib.import_module("investigate_b1_timing")
verify_a3_writes = importlib.import_module("verify_a3_writes")
verify_a3_headers = importlib.import_module("verify_a3_headers")
BenchmarkResults = bench_common.BenchmarkResults
BenchmarkBase = bench_common.BenchmarkBase
COMPARISON_COMPRESSLEVEL = bench_common.COMPARISON_COMPRESSLEVEL
DataGenerator = bench_common.DataGenerator
median_results = bench_common.median_results
positive_int = run_benchmarks.positive_int
configure_source_root = run_benchmarks.configure_source_root
cpu_tuning = run_benchmarks._cpu_tuning
assert_requested_engine = run_benchmarks.assert_requested_engine
configure_requested_engine = run_benchmarks._configure_requested_engine
write_comparison_fixture = bench_common.write_comparison_fixture
StreamingBenchmarks = bench_streaming.StreamingBenchmarks
RegressionsBenchmarks = bench_codec_regressions.RegressionsBenchmarks
deterministic_bytes = bench_codec_regressions._deterministic_bytes
fixture = bench_codec_regressions._fixture
a3_header_fixture = bench_a3_regressions.optional_header_fixture
a3_combined_header_fixture = bench_a3_regressions.combined_header_fixture
A3SeekableMemorySource = bench_a3_regressions.SeekableMemorySource
a3_read_high_level = bench_a3_regressions._read_high_level
a3_read_direct = bench_a3_regressions._read_direct
a3_write_once = bench_a3_regressions._write_once
a3_verify_member_sample = bench_a3_regressions._verify_member_sample
a3_verify_direct_sample = bench_a3_regressions._verify_direct_sample
A3Sample = bench_a3_regressions.Sample
a3_concurrent_write_once = verify_a3_writes._concurrent_once
a3_path_write_once = verify_a3_writes._path_once
a3_allocation_write_once = verify_a3_writes._allocation_once
a3_expected_header_failure = verify_a3_headers._expected_failure
a4_bounded_jsonl_once = bench_a4_supplement._bounded_jsonl_once
a4_concurrent_reads_once = bench_a4_supplement._concurrent_reads_once
a4_full_binary_read_once = bench_a4_supplement._full_binary_read_once
a4_jsonl_fixture = bench_a4_supplement._jsonl_fixture
b1_assert_requested_engine = investigate_b1_timing._assert_requested_engine
b1_run = investigate_b1_timing.run
b1_source_identity = investigate_b1_timing._source_identity
b1_time_output_bound = investigate_b1_timing._time_output_bound
TARGETED_BENCHMARK = bench_targeted_contract.TARGETED_BENCHMARK
RAW_CHANGE_FORMULA = bench_targeted_contract.RAW_CHANGE_FORMULA


def _result(name, duration, marker):
    return BenchmarkResults(
        name=name,
        category="test",
        duration=duration,
        metrics={"marker": marker},
    )


def test_median_results_uses_representative_sample_metrics():
    runs = [
        [_result("operation", 1.0, "fast")],
        [_result("operation", 100.0, "slow")],
        [_result("operation", 3.0, "median")],
    ]

    [result] = median_results(runs)

    assert result.duration == 3.0
    assert result.metrics == {"marker": "median", "suite_repeats": 3}
    assert result.duration_samples == [1.0, 100.0, 3.0]
    assert result.median_absolute_deviation == 2.0


def test_benchmark_result_json_retains_raw_samples_and_mad():
    result = BenchmarkResults(
        name="operation",
        category="test",
        duration=2.0,
        duration_samples=[1.0, 2.0, 5.0],
        median_absolute_deviation=1.0,
    )

    serialized = json.loads(json.dumps(result.to_dict()))

    assert serialized["duration_samples"] == [1.0, 2.0, 5.0]
    assert serialized["median_absolute_deviation"] == 1.0
    assert serialized["duration_min"] == 1.0
    assert serialized["duration_max"] == 5.0


def test_median_results_preserves_first_run_order():
    runs = [
        [_result("second", 2.0, "a"), _result("first", 1.0, "b")],
        [_result("first", 3.0, "c"), _result("second", 4.0, "d")],
    ]

    assert [result.name for result in median_results(runs)] == ["second", "first"]


def test_median_results_rejects_mismatched_runs():
    with pytest.raises(ValueError, match="different result sets"):
        median_results([[_result("one", 1.0, "a")], [_result("two", 2.0, "b")]])


@pytest.mark.parametrize(("value", "expected"), [("1", 1), ("5", 5)])
def test_positive_int(value, expected):
    assert positive_int(value) == expected


@pytest.mark.parametrize("value", ["0", "-1"])
def test_positive_int_rejects_nonpositive_values(value):
    with pytest.raises(argparse.ArgumentTypeError, match="positive integer"):
        positive_int(value)


def test_b1_investigation_rejects_requested_engine_mismatch(monkeypatch):
    from aiogzip import EngineInfo

    stdlib = SimpleNamespace(
        engine_info=lambda: EngineInfo(
            compression="stdlib-zlib",
            decompression="stdlib-zlib",
            crc32="stdlib-zlib",
        )
    )
    zlib_ng = SimpleNamespace(
        engine_info=lambda: EngineInfo(
            compression="stdlib-zlib",
            decompression="zlib-ng",
            crc32="zlib-ng",
        )
    )
    zlib_ng_with_stdlib_crc = SimpleNamespace(
        engine_info=lambda: EngineInfo(
            compression="stdlib-zlib",
            decompression="zlib-ng",
            crc32="stdlib-zlib",
        )
    )

    assert b1_assert_requested_engine(stdlib, "stdlib", source_label="test") == {
        "compression": "stdlib-zlib",
        "decompression": "stdlib-zlib",
        "crc32": "stdlib-zlib",
    }
    assert b1_assert_requested_engine(zlib_ng, "zlib-ng", source_label="test") == {
        "compression": "stdlib-zlib",
        "decompression": "zlib-ng",
        "crc32": "zlib-ng",
    }
    with pytest.raises(RuntimeError, match="zlib-ng was requested"):
        b1_assert_requested_engine(stdlib, "zlib-ng", source_label="test")
    with pytest.raises(RuntimeError, match="stdlib was requested"):
        b1_assert_requested_engine(zlib_ng, "stdlib", source_label="test")
    with pytest.raises(RuntimeError, match="crc32"):
        b1_assert_requested_engine(
            zlib_ng_with_stdlib_crc, "zlib-ng", source_label="test"
        )

    monkeypatch.setattr(run_benchmarks.platform, "system", lambda: "Darwin")
    assert (
        b1_assert_requested_engine(
            zlib_ng_with_stdlib_crc, "zlib-ng", source_label="test"
        )["crc32"]
        == "stdlib-zlib"
    )


def test_shared_engine_guard_checks_each_field():
    engines = {
        "compression": "stdlib-zlib",
        "decompression": "zlib-ng",
        "crc32": "zlib-ng",
    }

    assert_requested_engine(
        engines, "zlib-ng", source_label="test", system_name="Linux"
    )
    with pytest.raises(RuntimeError, match="decompression"):
        assert_requested_engine(
            {**engines, "decompression": "stdlib-zlib"},
            "zlib-ng",
            source_label="test",
            system_name="Linux",
        )
    with pytest.raises(RuntimeError, match="crc32"):
        assert_requested_engine(
            {**engines, "crc32": "stdlib-zlib"},
            "zlib-ng",
            source_label="test",
            system_name="Linux",
        )
    assert_requested_engine(
        {**engines, "crc32": "stdlib-zlib"},
        "zlib-ng",
        source_label="test",
        system_name="Darwin",
    )
    with pytest.raises(ValueError, match="unsupported requested engine"):
        assert_requested_engine(engines, [], source_label="test")
    with pytest.raises(ValueError, match="operating system provenance"):
        assert_requested_engine(
            engines,
            "zlib-ng",
            source_label="test",
            system_name="<unknown>",
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("compression", "unknown"),
        ("decompression", "stdlib-zlib"),
        ("crc32", "unknown"),
        ("crc32", []),
    ],
)
def test_shared_engine_guard_validates_platform_unknown_records(field, value):
    engines = {
        "compression": "stdlib-zlib",
        "decompression": "zlib-ng",
        "crc32": "stdlib-zlib",
    }
    assert_requested_engine(
        engines,
        "zlib-ng",
        source_label="legacy",
        system_name=run_benchmarks.UNKNOWN_SYSTEM,
    )
    assert_requested_engine(
        {**engines, "crc32": "zlib-ng"},
        "zlib-ng",
        source_label="legacy",
        system_name=run_benchmarks.UNKNOWN_SYSTEM,
    )

    with pytest.raises(RuntimeError) as caught:
        assert_requested_engine(
            {**engines, field: value},
            "zlib-ng",
            source_label="legacy",
            system_name=run_benchmarks.UNKNOWN_SYSTEM,
        )
    mismatch = (
        str(caught.value).split("do not match: ", 1)[1].split("; active engines", 1)[0]
    )
    assert mismatch.startswith(f"{{'{field}':")
    assert all(
        f"'{other}':" not in mismatch
        for other in {"compression", "decompression", "crc32"} - {field}
    )


def test_b1_investigation_attests_clean_source_before_timing(tmp_path, monkeypatch):
    package_init = tmp_path / "src" / "aiogzip" / "__init__.py"
    package_init.parent.mkdir(parents=True)
    package_init.write_text("__version__ = 'test'\n", encoding="utf-8")

    def fake_git(root, *args):
        assert root == tmp_path
        if args == ("rev-parse", "HEAD"):
            return "abc123"
        if args == ("describe", "--always", "--dirty", "--tags"):
            return "v2.0.0a4"
        if args == ("status", "--porcelain", "--untracked-files=no"):
            return ""
        raise AssertionError(args)

    monkeypatch.setattr(investigate_b1_timing, "_git", fake_git)

    assert b1_source_identity(tmp_path) == {
        "source_root": str(tmp_path),
        "commit": "abc123",
        "describe": "v2.0.0a4",
        "dirty_tracked": False,
    }


def test_b1_investigation_rejects_dirty_source(tmp_path, monkeypatch):
    package_init = tmp_path / "src" / "aiogzip" / "__init__.py"
    package_init.parent.mkdir(parents=True)
    package_init.write_text("__version__ = 'test'\n", encoding="utf-8")
    monkeypatch.setattr(
        investigate_b1_timing,
        "_git",
        lambda _root, *args: (
            " M src/aiogzip/__init__.py" if args[0] == "status" else "abc123"
        ),
    )

    with pytest.raises(RuntimeError, match="tracked changes"):
        b1_source_identity(tmp_path)


def test_b1_output_bound_allows_multiple_legal_chunks_and_closes_operations():
    payload = b"x" * (128 * 1024)

    class Operation:
        def __init__(self, outputs):
            self.outputs = outputs
            self.closed = False

        def __iter__(self):
            return iter(self.outputs)

        def close(self):
            self.closed = True

    class Decoder:
        def __init__(self):
            self.feed_operation = Operation([payload[: 64 * 1024]])
            self.finish_operation = Operation([payload[64 * 1024 :]])
            self.discarded = False

        def feed(self, _wire):
            return self.feed_operation

        def finish(self):
            return self.finish_operation

        def discard(self):
            self.discarded = True

    decoder = Decoder()
    module = SimpleNamespace(GzipDecoder=lambda **_kwargs: decoder)

    assert (
        b1_time_output_bound(module, b"wire", hashlib.sha256(payload).hexdigest()) >= 0
    )
    assert decoder.feed_operation.closed
    assert decoder.finish_operation.closed
    assert decoder.discarded


def test_b1_output_bound_discards_decoder_when_iteration_fails():
    class Operation:
        closed = False

        def __iter__(self):
            yield object()

        def close(self):
            self.closed = True

    class Decoder:
        def __init__(self):
            self.feed_operation = Operation()
            self.discarded = False

        def feed(self, _wire):
            return self.feed_operation

        def discard(self):
            self.discarded = True

    decoder = Decoder()
    module = SimpleNamespace(GzipDecoder=lambda **_kwargs: decoder)

    with pytest.raises(TypeError):
        b1_time_output_bound(module, b"wire", "unused")
    assert decoder.feed_operation.closed
    assert decoder.discarded


def _mock_b1_investigation_sources(
    tmp_path,
    monkeypatch,
    *,
    baseline_version="test",
    candidate_version="test",
    baseline_commit="1111111111111111111111111111111111111111",
    candidate_commit="2222222222222222222222222222222222222222",
):
    from aiogzip import EngineInfo

    baseline_root = tmp_path / "baseline"
    candidate_root = tmp_path / "candidate"
    for root in (baseline_root, candidate_root):
        package_init = root / "src" / "aiogzip" / "__init__.py"
        package_init.parent.mkdir(parents=True)
        package_init.write_text("__version__ = 'test'\n", encoding="utf-8")

    def identity(root):
        return {
            "source_root": str(root),
            "commit": baseline_commit if root == baseline_root else candidate_commit,
            "describe": root.name,
            "dirty_tracked": False,
        }

    def package(root):
        return SimpleNamespace(
            __file__=str(root / "src" / "aiogzip" / "__init__.py"),
            __version__=(
                baseline_version if root == baseline_root else candidate_version
            ),
            engine_info=lambda: EngineInfo(
                compression="stdlib-zlib",
                decompression="stdlib-zlib",
                crc32="stdlib-zlib",
            ),
        )

    monkeypatch.setattr(investigate_b1_timing, "_source_identity", identity)
    monkeypatch.setattr(
        investigate_b1_timing,
        "_load_package",
        lambda alias, root: package(root),
    )
    monkeypatch.setenv("AIOGZIP_ENGINE", "test-restore-sentinel")
    return baseline_root, candidate_root


def test_b1_investigation_checkpoints_partial_results_on_late_failure(
    tmp_path, monkeypatch
):
    baseline_root, candidate_root = _mock_b1_investigation_sources(
        tmp_path,
        monkeypatch,
        candidate_commit="1111111111111111111111111111111111111111",
    )
    monkeypatch.setattr(
        investigate_b1_timing,
        "_output_bound_fixture",
        lambda: (b"wire", "digest"),
    )
    monkeypatch.setattr(
        investigate_b1_timing,
        "optional_header_fixture",
        lambda *_args, **_kwargs: (b"wire", b""),
    )
    calls = 0

    async def measure_case(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("late failure")
        return {"name": "completed"}

    monkeypatch.setattr(investigate_b1_timing, "_measure_case", measure_case)
    snapshots = []
    args = argparse.Namespace(
        baseline_root=baseline_root,
        candidate_root=candidate_root,
        engine="stdlib",
        cycles=1,
        warmup_cycles=1,
        canonical_candidate_side="candidate",
        canonical_candidate_commit="1111111111111111111111111111111111111111",
    )

    with pytest.raises(RuntimeError, match="late failure"):
        asyncio.run(
            b1_run(
                args,
                checkpoint=lambda document: snapshots.append(
                    json.loads(json.dumps(document))
                ),
            )
        )

    assert snapshots[0]["status"] == "running"
    assert snapshots[0]["warnings"] == [
        "targeted capture producer: both sides attest the same source commit; "
        "canonical candidate side labels measurement orientation only"
    ]
    assert snapshots[-1]["status"] == "failed"
    assert snapshots[-1]["results"] == [{"name": "completed"}]
    assert snapshots[-1]["failure"] == {
        "type": "RuntimeError",
        "message": "late failure",
    }


def test_b1_programmatic_capture_round_trips_through_strict_reader(
    tmp_path, monkeypatch, capsys
):
    baseline_root, candidate_root = _mock_b1_investigation_sources(
        tmp_path,
        monkeypatch,
        baseline_version="2.0.0a4",
        candidate_version="2.0.0b1.dev0",
    )
    monkeypatch.setattr(
        investigate_b1_timing,
        "_output_bound_fixture",
        lambda: (b"wire", "digest"),
    )
    monkeypatch.setattr(
        investigate_b1_timing,
        "optional_header_fixture",
        lambda *_args, **_kwargs: (b"wire", b"payload"),
    )

    async def measure_case(name, *_args, **_kwargs):
        return {
            "name": name,
            "baseline": {"samples_seconds": [1.0, 1.1, 1.0, 1.1]},
            "candidate": {"samples_seconds": [1.01, 1.11, 1.01, 1.11]},
        }

    monkeypatch.setattr(investigate_b1_timing, "_measure_case", measure_case)
    args = argparse.Namespace(
        baseline_root=baseline_root,
        candidate_root=candidate_root,
        engine="stdlib",
        cycles=2,
        warmup_cycles=1,
        canonical_candidate_side="candidate",
        canonical_candidate_commit="2222222222222222222222222222222222222222",
    )

    capture = asyncio.run(b1_run(args))
    bench_compare.summarize_targeted(capture, "programmatic")

    assert capture["status"] == "complete"
    assert capture["command"][0] == "programmatic:investigate_b1_timing.run"
    assert capture["configuration"]["canonical_candidate_commit"] == "2" * 40
    assert capture["warnings"] == []
    assert "Canonical candidate side: candidate" in capsys.readouterr().out


def test_b1_producer_rejects_side_that_does_not_match_expected_commit(
    tmp_path, monkeypatch
):
    baseline_root, candidate_root = _mock_b1_investigation_sources(
        tmp_path,
        monkeypatch,
        baseline_version="2.0.0b1.dev0",
        candidate_version="2.0.0a4",
    )
    monkeypatch.setattr(
        investigate_b1_timing,
        "_load_package",
        lambda *_args: pytest.fail("package loaded after invalid commit binding"),
    )
    args = argparse.Namespace(
        baseline_root=baseline_root,
        candidate_root=candidate_root,
        engine="stdlib",
        cycles=1,
        warmup_cycles=1,
        canonical_candidate_side="candidate",
        canonical_candidate_commit="1111111111111111111111111111111111111111",
    )

    with pytest.raises(ValueError, match="contradicts the candidate source commit"):
        asyncio.run(b1_run(args))


def test_b1_producer_rejects_a4_b1_version_contradiction_before_timing(
    tmp_path, monkeypatch
):
    baseline_root, candidate_root = _mock_b1_investigation_sources(
        tmp_path,
        monkeypatch,
        baseline_version="2.0.0b1.dev0",
        candidate_version="2.0.0a4",
    )
    monkeypatch.setattr(
        investigate_b1_timing,
        "_output_bound_fixture",
        lambda: pytest.fail("timing started after invalid source orientation"),
    )
    args = argparse.Namespace(
        baseline_root=baseline_root,
        candidate_root=candidate_root,
        engine="stdlib",
        cycles=1,
        warmup_cycles=1,
        canonical_candidate_side="candidate",
        canonical_candidate_commit="2222222222222222222222222222222222222222",
    )

    with pytest.raises(ValueError, match="contradicts the archived a4/b1"):
        asyncio.run(b1_run(args))


def test_b1_producer_rejects_invalid_side_before_source_loading(monkeypatch):
    monkeypatch.setattr(
        investigate_b1_timing,
        "_source_identity",
        lambda _root: pytest.fail("source loaded after invalid side"),
    )
    args = argparse.Namespace(
        canonical_candidate_side=[],
        canonical_candidate_commit="2" * 40,
    )

    with pytest.raises(ValueError, match="invalid canonical_candidate_side"):
        asyncio.run(b1_run(args))


@pytest.mark.parametrize(
    ("command", "message"),
    [
        (None, "recorded command"),
        ([], "recorded command"),
        ("python", "recorded command"),
        (["python", ""], "recorded command argument 1 is empty"),
        (["python", "--baseline-root="], "--baseline-root has an empty value"),
    ],
)
def test_b1_capture_command_rejects_malformed_present_value(command, message):
    with pytest.raises(ValueError, match=message):
        investigate_b1_timing._capture_command(SimpleNamespace(command=command))


def test_b1_run_rejects_malformed_cli_command_before_source_loading(monkeypatch):
    monkeypatch.setattr(
        investigate_b1_timing,
        "_source_identity",
        lambda _root: pytest.fail("source loaded after malformed CLI provenance"),
    )
    args = argparse.Namespace(
        command=["python", ""],
        canonical_candidate_side="candidate",
        canonical_candidate_commit="2" * 40,
    )

    with pytest.raises(ValueError, match="recorded command argument 1 is empty"):
        asyncio.run(b1_run(args))


@pytest.mark.parametrize(
    "baseline_arguments", [["--baseline-root", ""], ["--baseline-root="]]
)
def test_b1_main_reports_empty_cli_value_without_traceback(
    baseline_arguments, tmp_path, monkeypatch, capsys
):
    output = tmp_path / "capture.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "investigate_b1_timing.py",
            *baseline_arguments,
            "--candidate-root",
            ".",
            "--engine",
            "stdlib",
            "--canonical-candidate-commit",
            "2" * 40,
            "--output",
            str(output),
        ],
    )
    monkeypatch.setattr(
        investigate_b1_timing,
        "_source_identity",
        lambda _root: pytest.fail("source loaded after empty CLI value"),
    )

    with pytest.raises(SystemExit, match="2"):
        investigate_b1_timing.main()

    error = capsys.readouterr().err
    assert "argument --baseline-root: must not be empty" in error
    assert "Traceback" not in error
    assert not output.exists()


def test_b1_main_reports_wrong_commit_without_traceback(tmp_path, monkeypatch, capsys):
    output = tmp_path / "capture.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "investigate_b1_timing.py",
            "--baseline-root",
            "baseline",
            "--candidate-root",
            "candidate",
            "--engine",
            "stdlib",
            "--canonical-candidate-commit",
            "wrong-commit",
            "--output",
            str(output),
        ],
    )
    monkeypatch.setattr(
        investigate_b1_timing,
        "_source_identity",
        lambda root: {
            "source_root": str(root),
            "commit": f"{root}-commit",
            "describe": str(root),
            "dirty_tracked": False,
        },
    )

    with pytest.raises(SystemExit, match="2"):
        investigate_b1_timing.main()

    error = capsys.readouterr().err
    assert "contradicts the candidate source commit 'candidate-commit'" in error
    assert "Traceback" not in error
    assert not output.exists()


def test_comparison_fixture_is_deterministic(tmp_path):
    payload = b"repeatable benchmark payload\n" * 100
    first = tmp_path / "first.gz"
    second = tmp_path / "second.gz"

    write_comparison_fixture(first, payload)
    write_comparison_fixture(second, payload)

    assert COMPARISON_COMPRESSLEVEL == 6
    assert first.read_bytes() == second.read_bytes()
    assert gzip.decompress(first.read_bytes()) == payload


def test_text_generators_are_deterministic():
    assert DataGenerator.generate_text(1) == DataGenerator.generate_text(1)
    assert DataGenerator.generate_jsonl(1) == DataGenerator.generate_jsonl(1)


def test_regression_fixture_is_deterministic_and_self_describing():
    first = fixture(1)
    second = fixture(1)

    assert first == second
    assert len(first.payload) == 1024 * 1024
    assert gzip.decompress(first.compressed) == first.payload
    assert deterministic_bytes(64, label=b"test") == deterministic_bytes(
        64, label=b"test"
    )


@pytest.mark.parametrize("field", ["fname", "fcomment"])
def test_a3_optional_header_fixtures_are_deterministic_and_valid(field):
    first, expected = a3_header_fixture(
        field, 4096, complete=True, mtime=0xFFFFFFFF, fhcrc=True
    )
    second, _ = a3_header_fixture(
        field, 4096, complete=True, mtime=0xFFFFFFFF, fhcrc=True
    )

    assert first == second
    assert gzip.decompress(first) == expected


def test_a3_combined_header_fixture_has_expected_layout_and_valid_fhcrc():
    import aiogzip

    wire, expected, landmarks = a3_combined_header_fixture(
        extra_size=31,
        fname_size=37,
        fcomment_size=41,
        mtime=0xFFFFFFFF,
        fhcrc=True,
    )

    assert wire[:3] == b"\x1f\x8b\x08"
    assert wire[3] == 0x04 | 0x08 | 0x10 | 0x02
    assert struct.unpack("<I", wire[4:8])[0] == 0xFFFFFFFF
    assert struct.unpack("<H", wire[10:12])[0] == 31
    fhcrc_end = landmarks["fhcrc_end"]
    assert struct.unpack("<H", wire[fhcrc_end - 2 : fhcrc_end])[0] == (
        zlib.crc32(wire[: fhcrc_end - 2]) & 0xFFFF
    )
    assert gzip.decompress(wire) == expected

    decoder = aiogzip.GzipDecoder()
    assert b"".join(decoder.feed(wire)) + b"".join(decoder.finish()) == expected


@pytest.mark.parametrize(
    "split_name",
    [
        "magic-1",
        "magic-2",
        "method",
        "flags",
        "fixed-9",
        "fixed-end",
        "xlen-1",
        "xlen-end",
        "extra-end",
        "fname-terminator",
        "fcomment-terminator",
        "fhcrc-1",
    ],
)
@pytest.mark.asyncio
async def test_a3_high_level_combined_header_adversarial_splits(split_name):
    import aiogzip

    wire, expected, landmarks = a3_combined_header_fixture(mtime=123456789)
    splits = {
        "magic-1": 1,
        "magic-2": 2,
        "method": 3,
        "flags": 4,
        "fixed-9": 9,
        "fixed-end": landmarks["fixed_end"],
        "xlen-1": landmarks["fixed_end"] + 1,
        "xlen-end": landmarks["xlen_end"],
        "extra-end": landmarks["extra_end"],
        "fname-terminator": landmarks["fname_end"] - 1,
        "fcomment-terminator": landmarks["fcomment_end"] - 1,
        "fhcrc-1": landmarks["fhcrc_end"] - 1,
    }
    split = splits[split_name]
    source = FramedAsyncReader(wire[:split], wire[split:])

    async with aiogzip.open(
        None,
        "rb",
        fileobj=source,
        closefd=False,
        chunk_size=len(wire),
    ) as stream:
        assert await stream.read() == expected
        assert stream.mtime == 123456789


@pytest.mark.asyncio
async def test_a3_corrupt_fhcrc_is_rejected_before_mtime_commit():
    import aiogzip

    wire, _, landmarks = a3_combined_header_fixture(mtime=987654321)
    damaged = bytearray(wire)
    damaged[landmarks["fhcrc_end"] - 1] ^= 0xFF
    source = FramedAsyncReader(bytes(damaged))

    async with aiogzip.open(
        None,
        "rb",
        fileobj=source,
        closefd=False,
        chunk_size=len(damaged),
    ) as stream:
        with pytest.raises(gzip.BadGzipFile, match="Header CRC"):
            await stream.read()
        assert stream.mtime is None


@pytest.mark.asyncio
async def test_a3_incomplete_header_fails_only_when_source_reports_eof():
    import aiogzip

    wire, _ = a3_header_fixture("fname", 4096, complete=False, mtime=42)
    eof_requested = asyncio.Event()
    release_eof = asyncio.Event()

    class EofGateSource(FramedAsyncReader):
        async def read(self, size=-1):
            if self._frame_index < len(self._frames):
                return await super().read(size)
            eof_requested.set()
            await release_eof.wait()
            return b""

    source = EofGateSource(wire)
    stream = aiogzip.open(
        None,
        "rb",
        fileobj=source,
        closefd=False,
        chunk_size=len(wire),
    )
    await stream.open()
    try:
        task = asyncio.create_task(stream.read())
        await eof_requested.wait()
        assert not task.done()
        assert stream.mtime is None
        release_eof.set()
        with pytest.raises(gzip.BadGzipFile, match="truncated"):
            await task
        assert stream.mtime is None
    finally:
        await stream.close()


@pytest.mark.asyncio
async def test_a3_over_limit_header_does_not_commit_public_mtime(monkeypatch):
    import aiogzip
    import aiogzip.codec as codec_module

    limit = 32
    monkeypatch.setattr(codec_module, "_MAX_CHUNK_SIZE", limit)
    fixed = b"\x1f\x8b\x08\x08" + struct.pack("<I", 777) + b"\x00\xff"
    wire = fixed + b"x" * (limit - len(fixed) + 1)
    source = FramedAsyncReader(wire[:limit], wire[limit:])

    async with aiogzip.open(
        None,
        "rb",
        fileobj=source,
        closefd=False,
        chunk_size=limit,
    ) as stream:
        with pytest.raises(gzip.BadGzipFile, match="header exceeds"):
            await stream.read()
        assert stream.mtime is None
        assert source.read_calls == 2


def test_a3_parser_rejects_before_consuming_first_byte_over_limit():
    from aiogzip._codec_buffer import _InputQueue
    from aiogzip._gzip_header import _GzipHeaderParser

    limit = 32
    fixed = b"\x1f\x8b\x08\x08" + struct.pack("<I", 777) + b"\x00\xff"
    pending = _InputQueue()
    pending.append(fixed + b"x" * (limit - len(fixed)))
    parser = _GzipHeaderParser(collect_metadata=False, limit=limit)

    assert parser.advance(pending) is None
    assert parser.size == limit
    assert not pending

    pending.append(b"x")
    with pytest.raises(gzip.BadGzipFile, match="header exceeds"):
        parser.advance(pending)
    assert parser.size == limit
    assert len(pending) == 1


@pytest.mark.asyncio
async def test_a3_source_read_count_is_linear_and_seekable_reader_has_no_cache():
    import aiogzip

    chunk_size = 257
    counts = []
    expected_counts = []
    for field_size in (4096, 8192):
        wire, _ = a3_header_fixture("fname", field_size, complete=False)
        expected_counts.append((len(wire) + chunk_size - 1) // chunk_size + 1)
        source = A3SeekableMemorySource(wire)
        async with aiogzip.open(
            None,
            "rb",
            fileobj=source,
            closefd=False,
            chunk_size=chunk_size,
        ) as stream:
            with pytest.raises(gzip.BadGzipFile, match="truncated"):
                await stream.read()
            assert source.max_returned <= chunk_size
            assert stream._compressed_cache == b""
            assert stream._cache_rewindable_reads is False
            counts.append(source.read_calls)

    assert counts == expected_counts
    assert counts[1] - counts[0] == 16
    assert "_header_probe_buffer" not in aiogzip.AsyncGzipBinaryFile.__slots__


@pytest.mark.asyncio
async def test_a3_high_level_smoke_checks_complete_and_incomplete_headers():
    import aiogzip

    complete, expected = a3_header_fixture("fname", 4096, complete=True)
    complete_sample = await a3_read_high_level(
        aiogzip,
        complete,
        chunk_size=257,
        expect_complete=True,
        measure_memory=False,
    )
    incomplete, _ = a3_header_fixture("fcomment", 4096, complete=False)
    incomplete_sample = await a3_read_high_level(
        aiogzip,
        incomplete,
        chunk_size=257,
        expect_complete=False,
        measure_memory=False,
    )

    assert (
        complete_sample.metrics["output_sha256"] == hashlib.sha256(expected).hexdigest()
    )
    assert complete_sample.metrics["source_max_returned_bytes"] <= 257
    assert incomplete_sample.metrics["failure"] is not None


@pytest.mark.asyncio
async def test_a3_high_level_incomplete_rejects_unexpected_oserror():
    class WrongFailureReader:
        mtime = None

        async def open(self):
            return self

        async def read(self):
            raise OSError("wrong failure class")

        async def close(self):
            pass

    class FakeAiogzip:
        @staticmethod
        def open(*args, **kwargs):
            return WrongFailureReader()

    with pytest.raises(OSError, match="wrong failure class"):
        await a3_read_high_level(
            FakeAiogzip,
            b"incomplete",
            chunk_size=4,
            expect_complete=False,
            measure_memory=False,
        )


def test_a3_direct_incomplete_catches_feed_time_badgzipfile():
    class FeedFailureDecoder:
        def __init__(self, **kwargs):
            self.discarded = False

        def feed(self, data):
            raise gzip.BadGzipFile("feed-time failure")

        def finish(self):
            raise AssertionError("finish must not run after feed failure")

        def discard(self):
            self.discarded = True

    class FakeAiogzip:
        GzipDecoder = FeedFailureDecoder

    sample = a3_read_direct(
        FakeAiogzip,
        b"bad",
        chunk_size=1,
        expect_complete=False,
    )

    assert sample.metrics["failure"] == "BadGzipFile: feed-time failure"


def test_a3_direct_incomplete_rejects_unexpected_oserror():
    class WrongFailureDecoder:
        def __init__(self, **kwargs):
            pass

        def feed(self, data):
            raise OSError("wrong direct failure class")

        def discard(self):
            pass

    class FakeAiogzip:
        GzipDecoder = WrongFailureDecoder

    with pytest.raises(OSError, match="wrong direct failure class"):
        a3_read_direct(
            FakeAiogzip,
            b"bad",
            chunk_size=1,
            expect_complete=False,
        )


@pytest.mark.asyncio
async def test_a3_write_smoke_validates_position_and_output_digest():
    import aiogzip

    sample = await a3_write_once(
        aiogzip,
        write_size=10,
        total_bytes=4096,
        method="write",
        fast_compress=False,
    )

    assert sample.metrics["payload_bytes"] == 4096
    assert sample.metrics["output_sha256"] == sample.metrics["payload_sha256"]
    assert sample.metrics["position_before_close"] == 4096


@pytest.mark.asyncio
async def test_a3_concurrent_write_verifier_checks_independent_streams():
    import aiogzip

    sample = await a3_concurrent_write_once(
        aiogzip,
        writer_count=4,
        write_size=10,
        aggregate_bytes=4096,
        fast_compress=False,
    )

    assert sample["aggregate_payload_bytes"] == 4096
    assert sample["positions"] == [1024] * 4
    assert len(sample["compressed_sha256"]) == 4


@pytest.mark.asyncio
async def test_a3_path_and_allocation_write_verifier_smoke():
    import aiogzip

    path_sample = await a3_path_write_once(
        aiogzip,
        write_size=100,
        total_bytes=4096,
        fast_compress=False,
    )
    allocation_sample = await a3_allocation_write_once(
        aiogzip,
        write_size=1024,
        total_bytes=4096,
        fast_compress=False,
    )

    assert path_sample["payload_bytes"] == 4096
    assert path_sample["position"] == 4096
    assert allocation_sample["payload_bytes"] == 4096
    assert allocation_sample["position"] == 4096
    assert allocation_sample["peak_python_bytes"] > 0


@pytest.mark.asyncio
async def test_a3_seekable_source_never_returns_more_than_requested():
    source = A3SeekableMemorySource(b"0123456789")

    assert await source.read(3) == b"012"
    assert await source.read(3) == b"345"
    assert source.max_returned == 3
    assert await source.seek(0) == 0
    assert await source.read(20) == b"0123456789"
    assert source.max_returned == 10


def test_a3_members_gate_rejects_wrong_live_mtime():
    sample = A3Sample(
        0.1,
        {
            "output_sha256": "expected",
            "mtime": 11,
        },
    )

    with pytest.raises(AssertionError, match="many-member mtime mismatch"):
        a3_verify_member_sample(
            sample,
            expected_output_sha256="expected",
            expected_mtime=22,
        )


def test_a3_direct_header_gate_rejects_wrong_output_digest():
    sample = A3Sample(
        0.1,
        {
            "output_sha256": "wrong",
            "failure": None,
        },
    )

    with pytest.raises(AssertionError, match="direct decoder output mismatch"):
        a3_verify_direct_sample(
            sample,
            expected_output_sha256="expected",
            name="direct fname complete throughput",
        )


def test_a3_main_strips_categories_before_header_guard(monkeypatch, tmp_path):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "bench_a3_regressions.py",
            "--source-root",
            str(BENCHMARKS_DIR.parent),
            "--engine",
            "stdlib",
            "--categories",
            " members, headers ",
            "--fixture-sizes-mib",
            "16,32",
            "--memory-fixture-size-mib",
            "64",
            "--output",
            str(tmp_path / "unused.json"),
        ],
    )

    with pytest.raises(SystemExit, match="2"):
        bench_a3_regressions.main()


@pytest.mark.asyncio
async def test_a3_expected_failure_stops_tracemalloc_on_unexpected_success():
    class SuccessfulReader:
        _compressed_cache = b""
        _cache_rewindable_reads = False
        mtime = None

        async def open(self):
            return self

        async def read(self):
            return b"accepted"

        async def close(self):
            pass

    class FakeAiogzip:
        @staticmethod
        def open(*args, **kwargs):
            return SuccessfulReader()

    source = A3SeekableMemorySource(b"not-used")
    with pytest.raises(AssertionError, match="expected header failure"):
        await a3_expected_header_failure(
            FakeAiogzip,
            source,
            chunk_size=16,
            error_fragment="truncated",
            measure_memory=True,
        )

    assert not tracemalloc.is_tracing()


@pytest.mark.asyncio
async def test_a3_allocation_verifier_stops_tracemalloc_on_write_failure(monkeypatch):
    import aiogzip

    async def fail_write_stream(*args, **kwargs):
        raise OSError("controlled allocation failure")

    monkeypatch.setattr(verify_a3_writes, "_write_stream", fail_write_stream)

    with pytest.raises(OSError, match="controlled allocation failure"):
        await a3_allocation_write_once(
            aiogzip,
            write_size=10,
            total_bytes=100,
            fast_compress=False,
        )

    assert not tracemalloc.is_tracing()


@pytest.mark.asyncio
async def test_a4_supplement_validates_bounded_jsonl(tmp_path):
    import aiogzip

    payload = a4_jsonl_fixture(16 * 1024)
    path = tmp_path / "events.jsonl.gz"
    path.write_bytes(gzip.compress(payload, mtime=0))

    sample = await a4_bounded_jsonl_once(aiogzip, path, batch_hint=1024)

    assert sample.metrics["output_bytes"] == len(payload)
    assert sample.metrics["output_sha256"] == hashlib.sha256(payload).hexdigest()
    assert sample.metrics["line_count"] == payload.count(b"\n")
    assert sample.metrics["batch_count"] > 1


@pytest.mark.asyncio
async def test_a4_supplement_measures_full_read_peak(tmp_path):
    import aiogzip

    payload = b"bounded-full-read" * 4096
    path = tmp_path / "binary.gz"
    path.write_bytes(gzip.compress(payload, mtime=0))

    sample = await a4_full_binary_read_once(aiogzip, path, measure_memory=True)

    assert sample.metrics["output_bytes"] == len(payload)
    assert sample.metrics["output_sha256"] == hashlib.sha256(payload).hexdigest()
    assert sample.metrics["peak_python_bytes"] > 0
    assert not tracemalloc.is_tracing()


@pytest.mark.asyncio
async def test_a4_supplement_validates_concurrent_independent_reads(tmp_path):
    import aiogzip

    payloads = (b"stream-zero" * 1024, b"stream-one" * 1024, b"stream-two" * 1024)
    paths = tuple(tmp_path / f"stream-{index}.gz" for index in range(len(payloads)))
    for path, payload in zip(paths, payloads, strict=True):
        path.write_bytes(gzip.compress(payload, mtime=0))

    sample = await a4_concurrent_reads_once(aiogzip, paths)

    assert sample.metrics["stream_count"] == len(paths)
    assert sample.metrics["maximum_active_handles"] == len(paths)
    assert sample.metrics["output_sha256_by_stream"] == [
        hashlib.sha256(payload).hexdigest() for payload in payloads
    ]


def test_source_root_attestation_identifies_current_checkout(monkeypatch):
    repository_root = BENCHMARKS_DIR.parent

    def fake_git(_root, *args):
        if args == ("rev-parse", "HEAD"):
            return "abc123"
        if args == ("describe", "--always", "--dirty", "--tags"):
            return "v2.0.0b1-test"
        if args == ("status", "--porcelain", "--untracked-files=no"):
            return ""
        raise AssertionError(args)

    monkeypatch.setattr(run_benchmarks, "_git_value", fake_git)

    identity = configure_source_root(repository_root)

    assert identity["source_root"] == str(repository_root.resolve())
    assert Path(identity["aiogzip_file"]).is_relative_to(repository_root / "src")
    assert identity["target_commit"] == "abc123"
    assert identity["target_describe"] == "v2.0.0b1-test"
    assert identity["target_dirty"] is False
    assert identity["package_version"]


def test_source_root_attestation_rejects_dirty_tree_before_import(
    tmp_path, monkeypatch
):
    package_init = tmp_path / "src" / "aiogzip" / "__init__.py"
    package_init.parent.mkdir(parents=True)
    package_init.write_text(
        "raise AssertionError('must not import')\n", encoding="utf-8"
    )

    def fake_git(_root, *args):
        if args == ("status", "--porcelain", "--untracked-files=no"):
            return " M src/aiogzip/__init__.py"
        return "abc123"

    monkeypatch.setattr(run_benchmarks, "_git_value", fake_git)

    with pytest.raises(RuntimeError, match="tracked changes"):
        configure_source_root(tmp_path)


def test_cpu_tuning_reads_linux_sysfs(tmp_path, monkeypatch):
    governor = tmp_path / "cpu0" / "cpufreq" / "scaling_governor"
    governor.parent.mkdir(parents=True)
    governor.write_text("powersave\n", encoding="utf-8")
    boost = tmp_path / "cpufreq" / "boost"
    boost.parent.mkdir()
    boost.write_text("1\n", encoding="utf-8")
    monkeypatch.setattr(run_benchmarks.platform, "system", lambda: "Linux")
    monkeypatch.setattr(run_benchmarks, "_CPU_SYSFS_ROOT", tmp_path)

    assert cpu_tuning() == ("powersave", "enabled")


def test_cpu_tuning_reports_mixed_governors_and_intel_no_turbo(tmp_path, monkeypatch):
    for cpu, governor in (("cpu0", "powersave"), ("cpu1", "performance")):
        path = tmp_path / cpu / "cpufreq" / "scaling_governor"
        path.parent.mkdir(parents=True)
        path.write_text(governor, encoding="utf-8")
    no_turbo = tmp_path / "intel_pstate" / "no_turbo"
    no_turbo.parent.mkdir()
    no_turbo.write_text("1\n", encoding="utf-8")
    monkeypatch.setattr(run_benchmarks.platform, "system", lambda: "Linux")
    monkeypatch.setattr(run_benchmarks, "_CPU_SYSFS_ROOT", tmp_path)

    assert cpu_tuning() == ("mixed: performance, powersave", "disabled")


def test_cpu_tuning_is_explicitly_unavailable_off_linux(monkeypatch):
    monkeypatch.setattr(run_benchmarks.platform, "system", lambda: "Darwin")

    assert cpu_tuning() == (
        "unavailable on this platform",
        "unavailable on this platform",
    )


@pytest.mark.parametrize(
    "arguments",
    [
        ["run_benchmarks.py", "--category", "io", "--regression-profile", "quick"],
        ["run_benchmarks.py", "--category", "regressions"],
    ],
)
def test_regression_flags_require_category_and_source_root(monkeypatch, arguments):
    monkeypatch.setattr(sys, "argv", arguments)

    with pytest.raises(SystemExit, match="2"):
        asyncio.run(run_benchmarks.main())


def test_release_capture_requires_explicit_engine(monkeypatch, tmp_path):
    monkeypatch.delenv("AIOGZIP_ENGINE", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_benchmarks.py",
            "--category",
            "regressions",
            "--source-root",
            str(tmp_path),
        ],
    )

    with pytest.raises(SystemExit, match="2"):
        asyncio.run(run_benchmarks.main())


def test_requested_engine_uses_cli_for_zlib_ng(monkeypatch):
    monkeypatch.setenv("AIOGZIP_ENGINE", "zlib-ng")

    assert configure_requested_engine("zlib-ng", source_root_supplied=True) == "zlib-ng"
    assert "AIOGZIP_ENGINE" not in run_benchmarks.os.environ


def test_requested_engine_sets_real_stdlib_override(monkeypatch):
    monkeypatch.delenv("AIOGZIP_ENGINE", raising=False)

    assert configure_requested_engine("stdlib", source_root_supplied=True) == "stdlib"
    assert run_benchmarks.os.environ["AIOGZIP_ENGINE"] == "stdlib"


def test_requested_engine_rejects_noop_zlib_ng_environment(monkeypatch):
    monkeypatch.setenv("AIOGZIP_ENGINE", "zlib-ng")

    with pytest.raises(ValueError, match="use --engine zlib-ng"):
        configure_requested_engine(None, source_root_supplied=True)


def test_main_verifies_engine_without_source_root(monkeypatch, capsys):
    from aiogzip import EngineInfo

    fake_aiogzip = SimpleNamespace(
        engine_info=lambda: EngineInfo(
            compression="stdlib-zlib",
            decompression="stdlib-zlib",
            crc32="stdlib-zlib",
        )
    )
    benchmark_started = False

    async def fail_if_started(*_args, **_kwargs):
        nonlocal benchmark_started
        benchmark_started = True
        raise AssertionError("benchmark ran after failed engine verification")

    monkeypatch.setenv("AIOGZIP_ENGINE", "stdlib")
    monkeypatch.setitem(sys.modules, "aiogzip", fake_aiogzip)
    monkeypatch.setattr(run_benchmarks, "run_category", fail_if_started)
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_benchmarks.py", "--quick", "--engine", "zlib-ng"],
    )

    with pytest.raises(SystemExit, match="2"):
        asyncio.run(run_benchmarks.main())

    error = capsys.readouterr().err
    assert "engine fields do not match" in error
    assert "decompression" in error
    assert not benchmark_started


def test_main_checkpoints_completed_categories_on_late_failure(tmp_path, monkeypatch):
    output = tmp_path / "capture.json"
    source_root = tmp_path / "source"
    source_root.mkdir()
    monkeypatch.setenv("AIOGZIP_ENGINE", "stdlib")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_benchmarks.py",
            "--category",
            "io,memory",
            "--source-root",
            str(source_root),
            "--output",
            str(output),
        ],
    )
    identity = {
        "source_root": str(source_root),
        "target_commit": "abc123",
        "target_describe": "abc123",
        "target_dirty": False,
    }
    environment = {
        **identity,
        "os_name": "Linux",
        "forced_engine": "stdlib",
        "active_engines": {
            "compression": "stdlib-zlib",
            "decompression": "stdlib-zlib",
            "crc32": "stdlib-zlib",
        },
    }
    monkeypatch.setattr(run_benchmarks, "configure_source_root", lambda _root: identity)
    monkeypatch.setattr(
        run_benchmarks,
        "collect_environment",
        lambda _identity, *, environment_label, requested_engine: environment,
    )

    async def fake_run_category(category, **_kwargs):
        if category == "memory":
            raise RuntimeError("controlled late failure")
        return [_result("completed io", 1.0, "checkpoint")]

    monkeypatch.setattr(run_benchmarks, "run_category", fake_run_category)

    with pytest.raises(RuntimeError, match="controlled late failure"):
        asyncio.run(run_benchmarks.main())

    capture = json.loads(output.read_text(encoding="utf-8"))
    assert capture["status"] == "failed"
    assert capture["completed_categories"] == ["io"]
    assert [result["name"] for result in capture["results"]] == ["completed io"]
    assert capture["failure"] == {
        "type": "RuntimeError",
        "message": "controlled late failure",
    }
    assert not (tmp_path / ".capture.json.tmp").exists()


def test_run_category_checkpoints_each_completed_result(monkeypatch):
    class PartialBenchmarks(BenchmarkBase):
        async def run_all(self):
            self.add_result("first row", "partial", 1.0)
            raise RuntimeError("failure after first row")

    module = SimpleNamespace(PartialBenchmarks=PartialBenchmarks)
    monkeypatch.setitem(run_benchmarks.CATEGORIES, "partial", "bench_partial")
    monkeypatch.setattr(
        run_benchmarks.importlib,
        "import_module",
        lambda name: (
            module if name == "bench_partial" else importlib.import_module(name)
        ),
    )
    snapshots = []

    with pytest.raises(RuntimeError, match="failure after first row"):
        asyncio.run(
            run_benchmarks.run_category(
                "partial",
                result_checkpoint=lambda category, index, count, completed, partial, persist: (
                    snapshots.append(
                        (
                            category,
                            index,
                            count,
                            [
                                [result.name for result in results]
                                for results in completed
                            ],
                            [result.name for result in partial],
                            persist,
                        )
                    )
                ),
            )
        )

    assert snapshots == [
        ("partial", 1, 3, [], [], True),
        ("partial", 1, 3, [], ["first row"], False),
    ]


def _comparison_capture(
    commit: str,
    *,
    engine: str = "stdlib",
    schema_version: int = 2,
    dirty: bool = False,
) -> dict:
    active_engines = {
        "compression": "stdlib-zlib",
        "decompression": "zlib-ng" if engine == "zlib-ng" else "stdlib-zlib",
        "crc32": "zlib-ng" if engine == "zlib-ng" else "stdlib-zlib",
    }
    source = {
        "target_commit": commit,
        "target_describe": commit,
        "target_dirty": dirty,
    }
    return {
        "schema_version": schema_version,
        "status": "complete",
        "source": source,
        "environment": {
            **source,
            "os_name": "Linux",
            "requested_engine": engine,
            "forced_engine": engine,
            "active_engines": active_engines,
        },
        "results": [{"name": "row", "duration": 1.0 if commit == "before" else 1.01}],
    }


def test_compare_results_validates_and_prints_capture_provenance(capsys):
    bench_compare.compare_results(
        _comparison_capture("before"), _comparison_capture("after")
    )

    output = capsys.readouterr().out
    assert "Baseline source: before (before)" in output
    assert "Current source:  after (after)" in output
    assert "Engine: stdlib" in output


def test_compare_results_rejects_schema_mismatch():
    with pytest.raises(ValueError, match="schema mismatch"):
        bench_compare.compare_results(
            _comparison_capture("before"),
            _comparison_capture("after", schema_version=1),
        )


def test_compare_results_rejects_engine_mismatch():
    with pytest.raises(ValueError, match="requested_engine mismatch"):
        bench_compare.compare_results(
            _comparison_capture("before"),
            _comparison_capture("after", engine="zlib-ng"),
        )


def test_compare_results_rejects_unhashable_requested_engine():
    baseline = _comparison_capture("before")
    baseline["environment"]["requested_engine"] = []

    with pytest.raises(ValueError, match="explicit requested engine"):
        bench_compare.compare_results(baseline, _comparison_capture("after"))


def test_compare_results_rejects_in_band_unknown_host_label():
    baseline = _comparison_capture("before")
    baseline["environment"]["os_name"] = "<unknown>"

    with pytest.raises(ValueError, match="operating-system provenance"):
        bench_compare.compare_results(baseline, _comparison_capture("after"))


def test_compare_results_rejects_dirty_source():
    with pytest.raises(ValueError, match="clean source tree"):
        bench_compare.compare_results(
            _comparison_capture("before", dirty=True),
            _comparison_capture("after"),
        )


def test_compare_results_requires_explicit_legacy_opt_in(capsys):
    baseline = _comparison_capture("before")
    current = _comparison_capture("after")
    for capture in (baseline, current):
        capture.pop("status")
        capture["environment"].pop("requested_engine")

    with pytest.raises(ValueError, match="not complete"):
        bench_compare.compare_results(baseline, current)

    bench_compare.compare_results(baseline, current, allow_legacy=True)
    output = capsys.readouterr().out
    assert "WARNING: baseline: legacy capture has no completion status" in output


def _targeted_capture(
    candidate_side: str = "candidate",
    *,
    system_name: str = "Linux",
    crc32: str = "zlib-ng",
) -> dict:
    engines = {
        "compression": "stdlib-zlib",
        "decompression": "zlib-ng",
        "crc32": crc32,
    }
    a4 = {
        "commit": "a4-commit",
        "describe": "v2.0.0a4",
        "version": "2.0.0a4",
        "dirty_tracked": False,
        "active_engines": engines,
    }
    b1 = {
        "commit": "b1-commit",
        "describe": "v2.0.0a4-20-gb1",
        "version": "2.0.0b1.dev0",
        "dirty_tracked": False,
        "active_engines": engines,
    }
    baseline, candidate = (b1, a4) if candidate_side == "baseline" else (a4, b1)
    canonical_candidate = baseline if candidate_side == "baseline" else candidate
    return {
        "schema_version": 2,
        "benchmark": TARGETED_BENCHMARK,
        "status": "complete",
        "configuration": {
            "requested_engine": "zlib-ng",
            "canonical_candidate_side": candidate_side,
            "canonical_candidate_commit": canonical_candidate["commit"],
            "reported_change_formula": RAW_CHANGE_FORMULA,
        },
        "command": ["python", "benchmarks/investigate_b1_timing.py"],
        "host": {"os_name": system_name},
        "baseline": baseline,
        "candidate": candidate,
        "results": [
            {
                "name": "row",
                "baseline": {"samples_seconds": [1.0, 1.1, 0.9, 1.0]},
                "candidate": {"samples_seconds": [1.1, 1.2, 0.99, 1.1]},
            }
        ],
    }


def test_targeted_summary_marks_orientation_and_temporal_statistics(capsys):
    bench_compare.summarize_targeted(
        _targeted_capture(candidate_side="baseline"), "swapped"
    )

    output = capsys.readouterr().out
    assert "Canonical candidate side: baseline" in output
    assert "quarter medians (ms)" in output
    assert bench_compare.canonical_change_percent(10.0, "baseline") == pytest.approx(
        -9.090909
    )


def test_targeted_legacy_orientation_fallback_is_used_by_summary(capsys):
    capture = _targeted_capture()
    capture["configuration"].pop("canonical_candidate_side")
    capture["configuration"].pop("canonical_candidate_commit")

    bench_compare.summarize_targeted(capture, "legacy", allow_legacy=True)

    output = capsys.readouterr().out
    assert "canonical candidate side inferred from source versions" in output
    assert "canonical candidate commit was not producer-recorded" in output
    assert "Canonical candidate side: candidate" in output


def test_targeted_strict_mode_describes_missing_orientation(capsys):
    capture = _targeted_capture()
    capture["configuration"].pop("canonical_candidate_side")

    with pytest.raises(
        ValueError, match="lacks canonical_candidate_side; use --allow-legacy"
    ):
        bench_compare.summarize_targeted(capture, "missing-side")

    assert capsys.readouterr().out == ""


def test_targeted_invalid_orientation_fails_before_output(capsys):
    capture = _targeted_capture()
    capture["configuration"]["canonical_candidate_side"] = "invalid"

    with pytest.raises(ValueError, match="invalid canonical_candidate_side"):
        bench_compare.summarize_targeted(capture, "invalid", allow_legacy=True)

    assert capsys.readouterr().out == ""


def test_targeted_unhashable_orientation_reports_value_error(capsys):
    capture = _targeted_capture()
    capture["configuration"]["canonical_candidate_side"] = []

    with pytest.raises(ValueError, match="invalid canonical_candidate_side"):
        bench_compare.summarize_targeted(capture, "invalid-list")

    assert capsys.readouterr().out == ""


def test_targeted_unhashable_requested_engine_reports_value_error(capsys):
    capture = _targeted_capture()
    capture["configuration"]["requested_engine"] = []

    with pytest.raises(ValueError, match="lacks a requested engine"):
        bench_compare.summarize_targeted(capture, "invalid-engine")

    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("version", ["2.0.0b10", "2.0.0b1rc1"])
def test_non_archival_version_is_not_treated_as_archived_b1(version, capsys):
    capture = _targeted_capture()
    capture["candidate"]["version"] = version
    capture["configuration"].pop("canonical_candidate_side")
    capture["configuration"].pop("canonical_candidate_commit")

    with pytest.raises(ValueError, match="orientation cannot be inferred"):
        bench_compare.summarize_targeted(capture, "b10", allow_legacy=True)

    assert capsys.readouterr().out == ""


def test_targeted_strict_mode_requires_candidate_commit_binding(capsys):
    capture = _targeted_capture()
    capture["configuration"].pop("canonical_candidate_commit")

    with pytest.raises(
        ValueError, match="lacks canonical_candidate_commit; use --allow-legacy"
    ):
        bench_compare.summarize_targeted(capture, "missing-commit")

    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("commit", ["", 7, ["b1-commit"]])
def test_targeted_rejects_invalid_candidate_commit_binding(commit, capsys):
    capture = _targeted_capture()
    capture["configuration"]["canonical_candidate_commit"] = commit

    with pytest.raises(ValueError, match="invalid canonical_candidate_commit"):
        bench_compare.summarize_targeted(capture, "invalid-commit")

    assert capsys.readouterr().out == ""


def test_targeted_rejects_contradictory_candidate_commit_binding(capsys):
    capture = _targeted_capture()
    capture["configuration"]["canonical_candidate_commit"] = "wrong-commit"

    with pytest.raises(ValueError, match="contradicts the candidate source commit"):
        bench_compare.summarize_targeted(capture, "wrong-commit")

    assert capsys.readouterr().out == ""


def test_targeted_orientation_must_match_source_versions():
    capture = _targeted_capture()
    capture["configuration"]["canonical_candidate_side"] = "baseline"
    capture["configuration"]["canonical_candidate_commit"] = capture["baseline"][
        "commit"
    ]

    with pytest.raises(ValueError, match="contradicts the archived a4/b1"):
        bench_compare.summarize_targeted(capture, "wrong")


@pytest.mark.parametrize("commit", [None, ""])
def test_targeted_same_source_warning_requires_attested_commit(commit):
    warnings = bench_targeted_contract.validate_source_orientation(
        "candidate",
        {"commit": commit},
        {"commit": commit},
        label="missing-commit",
    )

    assert warnings == []


@pytest.mark.parametrize("same_source", [False, True])
def test_targeted_strict_orientation_supports_future_and_same_source_pairs(
    same_source, capsys
):
    capture = _targeted_capture()
    capture["baseline"].update(
        commit="future-before",
        describe="v2.1.0",
        version="2.1.0",
    )
    capture["candidate"].update(
        commit="future-before" if same_source else "future-after",
        describe="v2.1.0" if same_source else "v2.2.0",
        version="2.1.0" if same_source else "2.2.0",
    )
    capture["configuration"]["canonical_candidate_commit"] = capture["candidate"][
        "commit"
    ]

    bench_compare.summarize_targeted(
        capture, "same-source" if same_source else "future"
    )

    output = capsys.readouterr().out
    assert "Canonical candidate side: candidate" in output
    if same_source:
        assert "both sides attest the same source commit" in output


def test_targeted_same_source_quick_capture_uses_nonempty_temporal_slices(capsys):
    capture = _targeted_capture()
    capture["baseline"].update(
        commit="same-commit",
        describe="same-commit",
        version="2.1.0",
    )
    capture["candidate"].update(
        commit="same-commit",
        describe="same-commit",
        version="2.1.0",
    )
    capture["configuration"]["canonical_candidate_commit"] = "same-commit"
    capture["configuration"]["cycles"] = 1
    capture["configuration"]["samples_per_side_per_case"] = 2
    capture["results"][0]["baseline"]["samples_seconds"] = [1.0, 1.1]
    capture["results"][0]["candidate"]["samples_seconds"] = [1.01, 1.11]
    second_result = json.loads(json.dumps(capture["results"][0]))
    second_result["name"] = "second quick row"
    capture["results"].append(second_result)

    bench_compare.summarize_targeted(capture, "quick-a-a")

    output = capsys.readouterr().out
    assert "both sides attest the same source commit" in output
    assert "temporal slice medians (2/2)" in output
    assert output.count("* first-half minimum uses one sample per side") == 1


def test_targeted_one_sample_capture_summarizes_without_empty_slice(capsys):
    capture = _targeted_capture()
    capture["results"][0]["baseline"]["samples_seconds"] = [1.0]
    capture["results"][0]["candidate"]["samples_seconds"] = [1.01]

    bench_compare.summarize_targeted(capture, "one-sample")

    output = capsys.readouterr().out
    assert "temporal slice medians (1/1)" in output
    assert "+1.00%*" in output
    assert "* first-half minimum uses one sample per side" in output


@pytest.mark.parametrize("field", ["commit", "describe"])
def test_targeted_requires_source_attestation_fields(field):
    capture = _targeted_capture()
    capture["baseline"].pop(field)
    provenance_name = "description" if field == "describe" else field

    with pytest.raises(ValueError, match=f"source {provenance_name} provenance"):
        bench_compare.summarize_targeted(capture, "missing")


def test_targeted_post_capture_annotations_require_legacy_mode(capsys):
    capture = _targeted_capture()
    capture["configuration"]["annotation_status"] = "untrusted free text"
    capture["post_capture_command_reconstruction"] = {"recorded_at_capture": False}

    with pytest.raises(ValueError, match="not a strict targeted capture"):
        bench_compare.summarize_targeted(capture, "annotated")
    assert capsys.readouterr().out == ""

    bench_compare.summarize_targeted(capture, "annotated", allow_legacy=True)
    output = capsys.readouterr().out
    assert "contains a post-capture orientation/formula annotation" in output
    assert "contains a post-capture command reconstruction" in output
    assert "untrusted free text" not in output


def test_targeted_strict_mode_requires_producer_command(capsys):
    capture = _targeted_capture()
    capture.pop("command")

    with pytest.raises(ValueError, match="producer-recorded command"):
        bench_compare.summarize_targeted(capture, "stripped")

    assert capsys.readouterr().out == ""


def test_targeted_formula_requires_explicit_legacy_mode(capsys):
    capture = _targeted_capture()
    capture["configuration"].pop("reported_change_formula")

    with pytest.raises(ValueError, match="canonical raw-change formula"):
        bench_compare.summarize_targeted(capture, "missing-formula")
    assert capsys.readouterr().out == ""

    bench_compare.summarize_targeted(capture, "missing-formula", allow_legacy=True)
    assert "raw-change formula was not producer-recorded" in capsys.readouterr().out


def test_targeted_legacy_missing_host_does_not_infer_crc_platform(capsys):
    capture = _targeted_capture(crc32="stdlib-zlib")
    capture.pop("host")

    with pytest.raises(ValueError, match="capture-time host OS provenance"):
        bench_compare.summarize_targeted(capture, "missing-host")
    assert capsys.readouterr().out == ""

    bench_compare.summarize_targeted(capture, "missing-host", allow_legacy=True)
    output = capsys.readouterr().out
    assert "lacks capture-time host OS provenance" in output
    assert "crc32 engine cannot be checked against the platform" in output


def test_targeted_unknown_host_rejects_unhashable_crc_engine(capsys):
    capture = _targeted_capture()
    capture.pop("host")
    capture["baseline"]["active_engines"] = {
        **capture["baseline"]["active_engines"],
        "crc32": [],
    }
    capture["candidate"]["active_engines"] = capture["baseline"]["active_engines"]

    with pytest.raises(RuntimeError, match="engine fields do not match"):
        bench_compare.summarize_targeted(capture, "unhashable", allow_legacy=True)

    assert capsys.readouterr().out == ""


def test_targeted_legacy_missing_host_validates_stdlib_without_crc_warning(capsys):
    capture = _targeted_capture(crc32="stdlib-zlib")
    capture["configuration"]["requested_engine"] = "stdlib"
    stdlib_engines = {
        "compression": "stdlib-zlib",
        "decompression": "stdlib-zlib",
        "crc32": "stdlib-zlib",
    }
    capture["baseline"]["active_engines"] = stdlib_engines
    capture["candidate"]["active_engines"] = stdlib_engines
    capture.pop("host")

    bench_compare.summarize_targeted(capture, "stdlib-no-host", allow_legacy=True)

    output = capsys.readouterr().out
    assert "lacks capture-time host OS provenance" in output
    assert "Engine: stdlib" in output
    assert "crc32 engine cannot be checked" not in output


def test_targeted_engine_validation_uses_recorded_host():
    linux_capture = _targeted_capture(system_name="Linux", crc32="stdlib-zlib")
    with pytest.raises(RuntimeError, match="crc32"):
        bench_compare.summarize_targeted(linux_capture, "linux")

    darwin_capture = _targeted_capture(system_name="Darwin", crc32="stdlib-zlib")
    bench_compare.summarize_targeted(darwin_capture, "darwin")


def test_targeted_rejects_in_band_unknown_host_label(capsys):
    capture = _targeted_capture(system_name="<unknown>", crc32="stdlib-zlib")

    with pytest.raises(ValueError, match="capture-time host OS provenance"):
        bench_compare.summarize_targeted(capture, "unknown-label")

    assert capsys.readouterr().out == ""


def test_targeted_schema_one_is_explicitly_archival():
    capture = _targeted_capture()
    capture["schema_version"] = 1

    with pytest.raises(ValueError, match="archival"):
        bench_compare.summarize_targeted(capture, "schema-one", allow_legacy=True)


def test_quick_regression_output_matrix_validates_outputs():
    benchmark = RegressionsBenchmarks(
        regression_profile="quick", regression_mode="throughput"
    )
    try:
        benchmark.setup()
        benchmark._output_bound_matrix()
    finally:
        benchmark.cleanup()

    results = benchmark.get_results()
    assert {result.metrics["output_chunk_size"] for result in results} == {
        1,
        1024,
        64 * 1024,
        256 * 1024,
    }
    assert all(
        result.metrics["max_output_chunk"] <= result.metrics["output_chunk_size"]
        for result in results
    )
    assert all(result.metrics["output_sha256"] for result in results)


def test_direct_codec_benchmarks_are_informational_and_validate_output():
    benchmark = StreamingBenchmarks(data_size_mb=0)
    try:
        benchmark.setup()
        benchmark._measure_direct_codecs()
    finally:
        benchmark.cleanup()

    results = {result.name: result for result in benchmark.get_results()}
    assert set(results) == {
        "stdlib gzip.compress reference",
        "sans-I/O codec encode (informational)",
        "stdlib gzip.decompress reference",
        "sans-I/O codec decode (informational)",
    }
    assert all(result.metrics["informational"] for result in results.values())
    assert (
        results["sans-I/O codec encode (informational)"].metrics[
            "stdlib_reference_seconds"
        ]
        >= 0
    )
    assert (
        results["sans-I/O codec decode (informational)"].metrics[
            "stdlib_reference_seconds"
        ]
        >= 0
    )


def _gzip_open_write_calls(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if not (
            isinstance(function, ast.Attribute)
            and isinstance(function.value, ast.Name)
            and function.value.id == "gzip"
            and function.attr == "open"
        ):
            continue
        mode = None
        if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
            mode = node.args[1].value
        for keyword in node.keywords:
            if keyword.arg == "mode" and isinstance(keyword.value, ast.Constant):
                mode = keyword.value.value
        if isinstance(mode, str) and any(operation in mode for operation in "wax"):
            yield node


def test_comparative_gzip_writes_set_compression_level_explicitly():
    benchmark_paths = sorted(BENCHMARKS_DIR.glob("bench_*.py"))
    write_calls = [
        (path, call)
        for path in benchmark_paths
        for call in _gzip_open_write_calls(path)
    ]

    assert write_calls
    for path, call in write_calls:
        assert any(keyword.arg == "compresslevel" for keyword in call.keywords), (
            f"{path.name}:{call.lineno} uses gzip's implicit compression level"
        )
