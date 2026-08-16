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

import pytest
from conftest import FramedAsyncReader

BENCHMARKS_DIR = Path(__file__).resolve().parents[1] / "benchmarks"
sys.path.insert(0, str(BENCHMARKS_DIR))
bench_common = importlib.import_module("bench_common")
run_benchmarks = importlib.import_module("run_benchmarks")
bench_streaming = importlib.import_module("bench_streaming")
bench_codec_regressions = importlib.import_module("bench_codec_regressions")
bench_a3_regressions = importlib.import_module("bench_a3_regressions")
verify_a3_writes = importlib.import_module("verify_a3_writes")
verify_a3_headers = importlib.import_module("verify_a3_headers")
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
