import argparse
import ast
import asyncio
import gzip
import importlib
import json
import sys
from pathlib import Path

import pytest

BENCHMARKS_DIR = Path(__file__).resolve().parents[1] / "benchmarks"
sys.path.insert(0, str(BENCHMARKS_DIR))
bench_common = importlib.import_module("bench_common")
run_benchmarks = importlib.import_module("run_benchmarks")
bench_streaming = importlib.import_module("bench_streaming")
bench_codec_regressions = importlib.import_module("bench_codec_regressions")
BenchmarkResults = bench_common.BenchmarkResults
COMPARISON_COMPRESSLEVEL = bench_common.COMPARISON_COMPRESSLEVEL
DataGenerator = bench_common.DataGenerator
median_results = bench_common.median_results
positive_int = run_benchmarks.positive_int
configure_source_root = run_benchmarks.configure_source_root
cpu_tuning = run_benchmarks._cpu_tuning
write_comparison_fixture = bench_common.write_comparison_fixture
StreamingBenchmarks = bench_streaming.StreamingBenchmarks
RegressionsBenchmarks = bench_codec_regressions.RegressionsBenchmarks
deterministic_bytes = bench_codec_regressions._deterministic_bytes
fixture = bench_codec_regressions._fixture


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


def test_source_root_attestation_identifies_current_checkout():
    repository_root = BENCHMARKS_DIR.parent

    identity = configure_source_root(repository_root)

    assert identity["source_root"] == str(repository_root.resolve())
    assert Path(identity["aiogzip_file"]).is_relative_to(repository_root / "src")
    assert identity["target_commit"]
    assert identity["package_version"]


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
