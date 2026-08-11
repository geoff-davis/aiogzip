#!/usr/bin/env python3
"""Auditable regression harness for the aiogzip 2.0.0a3 release.

The runner imports aiogzip from an explicit source checkout so this exact file
can measure historical tags without copying benchmark logic into worktrees.
Correctness checks are performed outside the timed regions.
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import gzip
import hashlib
import importlib
import importlib.metadata
import json
import os
import platform
import statistics
import struct
import subprocess
import sys
import sysconfig
import tempfile
import time
import tracemalloc
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = 1
FIXTURE_GENERATOR_VERSION = "a3-fixtures-v1"
_KIB = 1024
_MIB = 1024 * 1024
_WRITE_SIZES = (10, 100, _KIB, 4 * _KIB, 16 * _KIB, 64 * _KIB, 256 * _KIB)


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _csv_positive_ints(value: str) -> tuple[int, ...]:
    try:
        parsed = tuple(int(item.strip()) for item in value.split(","))
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be comma-separated integers") from error
    if not parsed or any(item <= 0 for item in parsed):
        raise argparse.ArgumentTypeError("values must be positive integers")
    return parsed


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _git(source_root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(source_root), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def configure_source_root(source_root: Path, engine: str) -> tuple[Any, dict[str, Any]]:
    """Import aiogzip from exactly ``source_root`` and attest the selection."""
    root = source_root.resolve()
    source_dir = root / "src"
    package_init = source_dir / "aiogzip" / "__init__.py"
    if not package_init.is_file():
        raise ValueError(f"missing source package: {package_init}")
    if "aiogzip" in sys.modules:
        raise RuntimeError("aiogzip was imported before source-root selection")

    if engine == "stdlib":
        os.environ["AIOGZIP_ENGINE"] = "stdlib"
    else:
        os.environ.pop("AIOGZIP_ENGINE", None)
    sys.path.insert(0, str(source_dir))
    aiogzip = importlib.import_module("aiogzip")
    imported = Path(aiogzip.__file__).resolve()
    if not imported.is_relative_to(source_dir):
        raise RuntimeError(f"imported {imported}, expected a module below {source_dir}")

    engines = vars(aiogzip.engine_info())
    if engine == "stdlib" and any("zlib-ng" in value for value in engines.values()):
        raise RuntimeError(f"stdlib was requested but active engines are {engines}")
    if engine == "zlib-ng" and not any(
        "zlib-ng" in value for value in engines.values()
    ):
        raise RuntimeError(f"zlib-ng was requested but active engines are {engines}")

    identity = {
        "source_root": str(root),
        "aiogzip_file": str(imported),
        "package_version": aiogzip.__version__,
        "commit": _git(root, "rev-parse", "HEAD"),
        "describe": _git(root, "describe", "--always", "--dirty", "--tags"),
        "dirty_tracked": bool(
            _git(root, "status", "--porcelain", "--untracked-files=no")
        ),
        "requested_engine": engine,
        "active_engines": engines,
    }
    return aiogzip, identity


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _cpu_policy() -> dict[str, Any]:
    root = Path("/sys/devices/system/cpu")
    governors = {
        value
        for path in root.glob("cpu[0-9]*/cpufreq/scaling_governor")
        if (value := _read_text(path)) is not None
    }
    boost = _read_text(root / "cpufreq" / "boost")
    if boost is None:
        no_turbo = _read_text(root / "intel_pstate" / "no_turbo")
        boost = {"0": "enabled", "1": "disabled"}.get(no_turbo, no_turbo)
    else:
        boost = {"0": "disabled", "1": "enabled"}.get(boost, boost)
    return {
        "governors": sorted(governors) if governors else None,
        "boost": boost,
    }


def _filesystem(path: Path) -> dict[str, str | None]:
    try:
        output = (
            subprocess.run(
                ["df", "-PT", str(path)],
                check=True,
                capture_output=True,
                text=True,
            )
            .stdout.splitlines()[-1]
            .split()
        )
    except (OSError, subprocess.CalledProcessError, IndexError):
        return {"path": str(path), "device": None, "type": None, "mount": None}
    return {
        "path": str(path),
        "device": output[0],
        "type": output[1],
        "mount": output[-1],
    }


def collect_environment(
    source_root: Path, identity: dict[str, Any], runner_root: Path
) -> dict[str, Any]:
    try:
        import psutil

        logical_cores = psutil.cpu_count(logical=True)
        physical_cores = psutil.cpu_count(logical=False)
        ram_bytes = psutil.virtual_memory().total
    except ImportError:
        logical_cores = os.cpu_count()
        physical_cores = None
        ram_bytes = None
    try:
        affinity: list[int] | str = sorted(os.sched_getaffinity(0))
    except AttributeError:
        affinity = "unavailable"
    try:
        zlib_ng_version = importlib.metadata.version("zlib-ng")
    except importlib.metadata.PackageNotFoundError:
        zlib_ng_version = None
    try:
        uv_version = subprocess.run(
            ["uv", "--version"], check=True, capture_output=True, text=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        uv_version = None

    return {
        **identity,
        "runner_root": str(runner_root),
        "runner_commit": _git(runner_root, "rev-parse", "HEAD"),
        "harness_sha256": _file_sha256(Path(__file__)),
        "fixture_generator_version": FIXTURE_GENERATOR_VERSION,
        "python_implementation": platform.python_implementation(),
        "python_version": sys.version,
        "python_executable": sys.executable,
        "python_build": list(platform.python_build()),
        "python_config_args": sysconfig.get_config_var("CONFIG_ARGS"),
        "python_compiler": platform.python_compiler(),
        "os": platform.system(),
        "os_release": platform.release(),
        "kernel": platform.version(),
        "architecture": platform.machine(),
        "libc": list(platform.libc_ver()),
        "processor": platform.processor(),
        "logical_cores": logical_cores,
        "physical_cores": physical_cores,
        "ram_bytes": ram_bytes,
        "cpu_affinity": affinity,
        "cpu_policy": _cpu_policy(),
        "system_load": list(os.getloadavg()) if hasattr(os, "getloadavg") else None,
        "power_source": _power_source(),
        "benchmark_filesystem": _filesystem(source_root),
        "temporary_filesystem": _filesystem(Path(tempfile.gettempdir())),
        "temporary_directory": tempfile.gettempdir(),
        "zlib_compile_version": zlib.ZLIB_VERSION,
        "zlib_runtime_version": zlib.ZLIB_RUNTIME_VERSION,
        "zlib_ng_package_version": zlib_ng_version,
        "uv_version": uv_version,
        "uv_lock_sha256": _file_sha256(source_root / "uv.lock"),
        "garbage_collection_enabled": gc.isenabled(),
        "garbage_collection_thresholds": list(gc.get_threshold()),
    }


def _power_source() -> str | None:
    supplies = Path("/sys/class/power_supply")
    states = []
    for path in supplies.glob("*/online"):
        value = _read_text(path)
        if value is not None:
            states.append(f"{path.parent.name}:{value}")
    return ",".join(sorted(states)) or None


def _raw_deflate(payload: bytes) -> bytes:
    compressor = zlib.compressobj(level=6, wbits=-zlib.MAX_WBITS)
    return compressor.compress(payload) + compressor.flush()


def optional_header_fixture(
    field: str,
    size: int,
    *,
    complete: bool,
    mtime: int = 0,
    fhcrc: bool = False,
) -> tuple[bytes, bytes]:
    """Build a deterministic gzip member with one large optional field."""
    flag = {"fname": 0x08, "fcomment": 0x10}[field]
    if fhcrc:
        flag |= 0x02
    header = bytearray(b"\x1f\x8b\x08")
    header.append(flag)
    header.extend(struct.pack("<I", mtime))
    header.extend(b"\x00\xff")
    header.extend(b"x" * size)
    if not complete:
        return bytes(header), b""
    header.append(0)
    if fhcrc:
        header.extend(struct.pack("<H", zlib.crc32(header) & 0xFFFF))
    payload = b"a3 header fixture payload\n"
    trailer = struct.pack(
        "<II", zlib.crc32(payload) & 0xFFFFFFFF, len(payload) & 0xFFFFFFFF
    )
    return bytes(header) + _raw_deflate(payload) + trailer, payload


def combined_header_fixture(
    *,
    extra_size: int = 17,
    fname_size: int = 19,
    fcomment_size: int = 23,
    mtime: int = 0,
    fhcrc: bool = True,
) -> tuple[bytes, bytes, dict[str, int]]:
    """Build a valid member with every optional field and split landmarks."""
    if not 0 <= extra_size <= 0xFFFF:
        raise ValueError("extra_size must fit the gzip XLEN field")
    if fname_size < 0 or fcomment_size < 0:
        raise ValueError("string field sizes must be non-negative")

    flags = 0x04 | 0x08 | 0x10 | (0x02 if fhcrc else 0)
    header = bytearray(b"\x1f\x8b\x08")
    header.append(flags)
    header.extend(struct.pack("<I", mtime))
    header.extend(b"\x00\xff")
    landmarks = {"fixed_end": len(header)}

    header.extend(struct.pack("<H", extra_size))
    landmarks["xlen_end"] = len(header)
    header.extend(b"e" * extra_size)
    landmarks["extra_end"] = len(header)
    header.extend(b"n" * fname_size + b"\x00")
    landmarks["fname_end"] = len(header)
    header.extend(b"c" * fcomment_size + b"\x00")
    landmarks["fcomment_end"] = len(header)
    if fhcrc:
        header.extend(struct.pack("<H", zlib.crc32(header) & 0xFFFF))
    landmarks["fhcrc_end"] = len(header)

    payload = b"a3 combined header fixture payload\n"
    trailer = struct.pack(
        "<II", zlib.crc32(payload) & 0xFFFFFFFF, len(payload) & 0xFFFFFFFF
    )
    return bytes(header) + _raw_deflate(payload) + trailer, payload, landmarks


def concatenated_fixture(members: int) -> tuple[bytes, bytes, int]:
    wire = bytearray()
    payload = bytearray()
    last_mtime = 0
    for index in range(members):
        row = f"member-{index:05d}\n".encode()
        last_mtime = 0 if index % 2 == 0 else 0xFFFFFFFF
        wire.extend(gzip.compress(row, compresslevel=6, mtime=last_mtime))
        payload.extend(row)
    return bytes(wire), bytes(payload), last_mtime


class SeekableMemorySource:
    """Minimal asynchronous source with bounded reads and observable counts."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.position = 0
        self.read_calls = 0
        self.max_requested = 0
        self.max_returned = 0

    def seekable(self) -> bool:
        return True

    async def read(self, size: int = -1) -> bytes:
        self.read_calls += 1
        self.max_requested = max(self.max_requested, size)
        if size < 0:
            size = len(self.data) - self.position
        end = min(len(self.data), self.position + size)
        result = self.data[self.position : end]
        self.position = end
        self.max_returned = max(self.max_returned, len(result))
        return result

    async def seek(self, offset: int, whence: int = 0) -> int:
        if whence == 0:
            position = offset
        elif whence == 1:
            position = self.position + offset
        elif whence == 2:
            position = len(self.data) + offset
        else:
            raise ValueError(f"invalid whence: {whence}")
        if position < 0:
            raise ValueError("negative seek position")
        self.position = position
        return position


class CountingMemorySink:
    """Minimal asynchronous sink retaining output for correctness checks."""

    def __init__(self) -> None:
        self.output = bytearray()
        self.write_calls = 0
        self.flush_calls = 0

    async def write(self, data: bytes) -> int:
        snapshot = bytes(data)
        self.output.extend(snapshot)
        self.write_calls += 1
        return len(snapshot)

    async def flush(self) -> None:
        self.flush_calls += 1


@dataclass(frozen=True)
class Sample:
    duration_seconds: float
    metrics: dict[str, Any]


def _aggregate(name: str, category: str, samples: list[Sample]) -> dict[str, Any]:
    summary = _aggregate_metrics(
        [
            {"duration_seconds": sample.duration_seconds, **sample.metrics}
            for sample in samples
        ]
    )
    return {
        "name": name,
        "category": category,
        "status": "ok",
        **summary,
    }


def _aggregate_metrics(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate timed metric dictionaries without dropping raw samples."""
    durations = [float(sample["duration_seconds"]) for sample in samples]
    median = float(statistics.median(durations))
    mad = float(statistics.median(abs(sample - median) for sample in durations))
    return {
        "duration_samples_seconds": durations,
        "median_seconds": median,
        "median_absolute_deviation_seconds": mad,
        "minimum_seconds": min(durations),
        "maximum_seconds": max(durations),
        "sample_count": len(samples),
        "sample_metrics": samples,
    }


def _unavailable(name: str, category: str, reason: str) -> dict[str, Any]:
    return {
        "name": name,
        "category": category,
        "status": "unavailable",
        "reason": reason,
    }


def _verify_member_sample(
    sample: Sample,
    *,
    expected_output_sha256: str,
    expected_mtime: int,
) -> None:
    """Fail a members run when payload or live metadata is incorrect."""
    if sample.metrics["output_sha256"] != expected_output_sha256:
        raise AssertionError("many-member output mismatch")
    if sample.metrics["mtime"] != expected_mtime:
        raise AssertionError(
            "many-member mtime mismatch: "
            f"expected {expected_mtime}, observed {sample.metrics['mtime']}"
        )


def _verify_direct_sample(
    sample: Sample,
    *,
    expected_output_sha256: str,
    name: str,
) -> None:
    """Fail a direct-decoder header run when its payload is incorrect."""
    if sample.metrics["output_sha256"] != expected_output_sha256:
        raise AssertionError(f"direct decoder output mismatch for {name}")


async def _read_high_level(
    aiogzip: Any,
    wire: bytes,
    *,
    chunk_size: int,
    expect_complete: bool,
    measure_memory: bool,
) -> Sample:
    source = SeekableMemorySource(wire)
    reader = aiogzip.open(
        None,
        "rb",
        fileobj=source,
        closefd=False,
        chunk_size=chunk_size,
    )
    await reader.open()
    output = b""
    failure: str | None = None
    if measure_memory:
        tracemalloc.start()
    started = time.perf_counter()
    try:
        try:
            output = await reader.read()
        except gzip.BadGzipFile as error:
            failure = f"{type(error).__name__}: {error}"
            if expect_complete:
                raise
    finally:
        duration = time.perf_counter() - started
        if measure_memory:
            current, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
        else:
            current = peak = None
        observed_mtime = reader.mtime
        await reader.close()
    if expect_complete and failure is not None:
        raise AssertionError(f"complete header fixture failed: {failure}")
    if not expect_complete and failure is None:
        raise AssertionError("incomplete header fixture was accepted")
    if source.max_returned > chunk_size:
        raise AssertionError("seekable source returned more bytes than requested")
    return Sample(
        duration,
        {
            "output_bytes": len(output),
            "output_sha256": _sha256(output),
            "failure": failure,
            "mtime": observed_mtime,
            "source_read_calls": source.read_calls,
            "source_max_requested_bytes": source.max_requested,
            "source_max_returned_bytes": source.max_returned,
            "source_position": source.position,
            "peak_python_bytes": peak,
            "current_python_bytes": current,
            "measurement_mode": "tracemalloc" if measure_memory else "wall_time",
        },
    )


def _read_direct(
    aiogzip: Any, wire: bytes, *, chunk_size: int, expect_complete: bool
) -> Sample:
    decoder = aiogzip.GzipDecoder(output_chunk_size=256 * _KIB)
    digest = hashlib.sha256()
    output_bytes = 0
    failure: str | None = None
    started = time.perf_counter()
    try:
        try:
            for offset in range(0, len(wire), chunk_size):
                for piece in decoder.feed(wire[offset : offset + chunk_size]):
                    digest.update(piece)
                    output_bytes += len(piece)
            for piece in decoder.finish():
                digest.update(piece)
                output_bytes += len(piece)
        except gzip.BadGzipFile as error:
            failure = f"{type(error).__name__}: {error}"
            if expect_complete:
                raise
    finally:
        duration = time.perf_counter() - started
        decoder.discard()
    if not expect_complete and failure is None:
        raise AssertionError("direct decoder accepted an incomplete header")
    return Sample(
        duration,
        {
            "output_bytes": output_bytes,
            "output_sha256": digest.hexdigest(),
            "failure": failure,
            "measurement_mode": "wall_time",
        },
    )


def _payload_for_write(write_size: int, total_bytes: int) -> tuple[bytes, bytes]:
    record = hashlib.shake_256(
        f"{FIXTURE_GENERATOR_VERSION}:write:{write_size}".encode()
    ).digest(write_size)
    repetitions, remainder = divmod(total_bytes, write_size)
    payload = record * repetitions + record[:remainder]
    return record, payload


def _records(record: bytes, total_bytes: int) -> Iterable[bytes]:
    full, remainder = divmod(total_bytes, len(record))
    for _ in range(full):
        yield record
    if remainder:
        yield record[:remainder]


async def _write_once(
    aiogzip: Any,
    *,
    write_size: int,
    total_bytes: int,
    method: str,
    fast_compress: bool,
) -> Sample:
    record, expected = _payload_for_write(write_size, total_bytes)
    sink = CountingMemorySink()
    writer = aiogzip.open(
        None,
        "wb",
        fileobj=sink,
        closefd=False,
        mtime=0,
        fast_compress=fast_compress,
    )
    await writer.open()
    started = time.perf_counter()
    if method == "write":
        for item in _records(record, total_bytes):
            written = await writer.write(item)
            if written != len(item):
                raise AssertionError(f"write returned {written}, expected {len(item)}")
    elif method == "writelines":
        await writer.writelines(_records(record, total_bytes))
    elif method.startswith("batch-"):
        batch_size = int(method.removeprefix("batch-"))
        for offset in range(0, len(expected), batch_size):
            item = expected[offset : offset + batch_size]
            written = await writer.write(item)
            if written != len(item):
                raise AssertionError(f"write returned {written}, expected {len(item)}")
    else:
        raise ValueError(f"unknown write method: {method}")
    position_before_close = await writer.tell()
    await writer.close()
    duration = time.perf_counter() - started
    compressed = bytes(sink.output)
    decoded = gzip.decompress(compressed)
    if decoded != expected:
        raise AssertionError("compressed output does not match accepted input")
    if position_before_close != total_bytes:
        raise AssertionError(
            f"writer position {position_before_close} != payload size {total_bytes}"
        )
    return Sample(
        duration,
        {
            "method": method,
            "write_size_bytes": write_size,
            "logical_record_count": (total_bytes + write_size - 1) // write_size,
            "payload_bytes": len(expected),
            "payload_sha256": _sha256(expected),
            "compressed_bytes": len(compressed),
            "compressed_sha256": _sha256(compressed),
            "output_bytes": len(decoded),
            "output_sha256": _sha256(decoded),
            "sink_write_calls": sink.write_calls,
            "sink_flush_calls": sink.flush_calls,
            "position_before_close": position_before_close,
            "measurement_mode": "wall_time",
        },
    )


async def _warm_up(aiogzip: Any, fast_compress: bool) -> None:
    await _write_once(
        aiogzip,
        write_size=1024,
        total_bytes=64 * _KIB,
        method="write",
        fast_compress=fast_compress,
    )
    wire, payload = optional_header_fixture("fname", 4096, complete=True)
    sample = await _read_high_level(
        aiogzip,
        wire,
        chunk_size=1024,
        expect_complete=True,
        measure_memory=False,
    )
    if sample.metrics["output_sha256"] != _sha256(payload):
        raise AssertionError("header warm-up output mismatch")


async def run_benchmarks(args: argparse.Namespace) -> dict[str, Any]:
    runner_root = Path(__file__).resolve().parents[1]
    aiogzip, identity = configure_source_root(args.source_root, args.engine)
    fast_compress = args.engine == "zlib-ng"
    categories = tuple(
        item.strip() for item in args.categories.split(",") if item.strip()
    )
    unknown = set(categories) - {"headers", "members", "writes"}
    if unknown:
        raise ValueError(f"unknown categories: {', '.join(sorted(unknown))}")

    await _warm_up(aiogzip, fast_compress)
    fixtures: dict[str, dict[str, Any]] = {}
    results: list[dict[str, Any]] = []
    discarded_runs: list[dict[str, Any]] = []

    if "headers" in categories:
        for size_mib in args.fixture_sizes_mib:
            size = size_mib * _MIB
            for field in ("fname", "fcomment"):
                for complete in (True, False):
                    wire, expected = optional_header_fixture(
                        field, size, complete=complete, mtime=0
                    )
                    fixture_name = f"{field}-{size_mib}MiB-{'complete' if complete else 'incomplete'}"
                    fixtures[fixture_name] = {
                        "generator_version": FIXTURE_GENERATOR_VERSION,
                        "field": field,
                        "field_bytes": size,
                        "complete": complete,
                        "fixture_bytes": len(wire),
                        "fixture_sha256": _sha256(wire),
                        "expected_output_bytes": len(expected),
                        "expected_output_sha256": _sha256(expected),
                    }
                    measurement_modes = [False]
                    if not complete and size_mib == args.memory_fixture_size_mib:
                        measurement_modes.append(True)
                    for measure_memory in measurement_modes:
                        mode = "memory" if measure_memory else "throughput"
                        name = f"high-level {fixture_name} {mode}"
                        sample_count = (
                            args.memory_repeat if measure_memory else args.repeat
                        )
                        samples = [
                            await _read_high_level(
                                aiogzip,
                                wire,
                                chunk_size=args.source_chunk_bytes,
                                expect_complete=complete,
                                measure_memory=measure_memory,
                            )
                            for _ in range(sample_count)
                        ]
                        if complete:
                            for sample in samples:
                                if sample.metrics["output_sha256"] != _sha256(expected):
                                    raise AssertionError(f"output mismatch for {name}")
                        results.append(_aggregate(name, f"headers-{mode}", samples))

                    direct_name = f"direct {fixture_name} throughput"
                    if hasattr(aiogzip, "GzipDecoder"):
                        samples = [
                            _read_direct(
                                aiogzip,
                                wire,
                                chunk_size=args.source_chunk_bytes,
                                expect_complete=complete,
                            )
                            for _ in range(args.repeat)
                        ]
                        expected_output_sha256 = _sha256(expected)
                        for sample in samples:
                            _verify_direct_sample(
                                sample,
                                expected_output_sha256=expected_output_sha256,
                                name=direct_name,
                            )
                        results.append(
                            _aggregate(direct_name, "headers-direct", samples)
                        )
                    else:
                        results.append(
                            _unavailable(
                                direct_name,
                                "headers-direct",
                                "target predates the public GzipDecoder API",
                            )
                        )

    if "members" in categories:
        for member_count in args.member_counts:
            wire, expected, expected_mtime = concatenated_fixture(member_count)
            expected_observed_mtime = (
                expected_mtime if args.members_mtime_policy == "last-header" else 0
            )
            fixture_name = f"members-{member_count}"
            fixtures[fixture_name] = {
                "generator_version": FIXTURE_GENERATOR_VERSION,
                "members": member_count,
                "fixture_bytes": len(wire),
                "fixture_sha256": _sha256(wire),
                "expected_output_bytes": len(expected),
                "expected_output_sha256": _sha256(expected),
                "expected_final_mtime": expected_mtime,
                "expected_observed_mtime": expected_observed_mtime,
                "mtime_policy": args.members_mtime_policy,
            }
            samples = [
                await _read_high_level(
                    aiogzip,
                    wire,
                    chunk_size=args.source_chunk_bytes,
                    expect_complete=True,
                    measure_memory=False,
                )
                for _ in range(args.repeat)
            ]
            expected_output_sha256 = _sha256(expected)
            for sample in samples:
                _verify_member_sample(
                    sample,
                    expected_output_sha256=expected_output_sha256,
                    expected_mtime=expected_observed_mtime,
                )
            results.append(
                _aggregate(
                    f"high-level concatenated members {member_count}",
                    "members",
                    samples,
                )
            )

    if "writes" in categories:
        methods = ("write", "writelines", "batch-65536", "batch-262144")
        for write_size in args.write_sizes:
            record, payload = _payload_for_write(write_size, args.total_write_bytes)
            fixtures[f"write-{write_size}"] = {
                "generator_version": FIXTURE_GENERATOR_VERSION,
                "record_bytes": len(record),
                "record_sha256": _sha256(record),
                "payload_bytes": len(payload),
                "payload_sha256": _sha256(payload),
            }
            for method in methods:
                samples = [
                    await _write_once(
                        aiogzip,
                        write_size=write_size,
                        total_bytes=args.total_write_bytes,
                        method=method,
                        fast_compress=fast_compress,
                    )
                    for _ in range(args.repeat)
                ]
                results.append(
                    _aggregate(
                        f"{method} {write_size}B records",
                        "writes",
                        samples,
                    )
                )

    environment = collect_environment(args.source_root.resolve(), identity, runner_root)
    return {
        "schema_version": SCHEMA_VERSION,
        "benchmark": "aiogzip-2.0.0a3-regressions",
        "created_at_unix": time.time(),
        "command": [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]],
        "configuration": {
            "categories": categories,
            "fixture_sizes_mib": args.fixture_sizes_mib,
            "memory_fixture_size_mib": args.memory_fixture_size_mib,
            "member_counts": args.member_counts,
            "members_mtime_policy": args.members_mtime_policy,
            "write_sizes": args.write_sizes,
            "total_write_bytes": args.total_write_bytes,
            "source_chunk_bytes": args.source_chunk_bytes,
            "repeat": args.repeat,
            "memory_repeat": args.memory_repeat,
            "warm_up_policy": "one 64KiB 1KiB-write run and one 4KiB header read",
            "garbage_collection_policy": "normal interpreter policy; recorded in environment",
            "ordering_policy": "fixed category/size/method order; no randomization",
        },
        "source": identity,
        "environment": environment,
        "fixtures": fixtures,
        "results": results,
        "discarded_or_excluded_runs": discarded_runs,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-root",
        type=Path,
        required=True,
        help="checkout whose src/aiogzip package is measured",
    )
    parser.add_argument(
        "--engine",
        choices=("stdlib", "zlib-ng"),
        required=True,
        help="engine configuration to attest and measure",
    )
    parser.add_argument(
        "--categories",
        default="headers,members,writes",
        help="comma-separated subset of headers,members,writes",
    )
    parser.add_argument(
        "--fixture-sizes-mib",
        type=_csv_positive_ints,
        default=(16, 32, 64),
        help="comma-separated optional-header sizes (default: 16,32,64)",
    )
    parser.add_argument(
        "--member-counts",
        type=_csv_positive_ints,
        default=(1, 2, 1001),
        help="comma-separated concatenated-member counts (default: 1,2,1001)",
    )
    parser.add_argument(
        "--members-mtime-policy",
        choices=("first-header", "last-header"),
        default="last-header",
        help=(
            "expected high-level mtime contract: last-header for the a3 "
            "candidate, first-header for historical a2 captures"
        ),
    )
    parser.add_argument(
        "--memory-fixture-size-mib",
        type=_positive_int,
        default=32,
        help="incomplete-header size used for tracemalloc (default: 32)",
    )
    parser.add_argument(
        "--write-sizes",
        type=_csv_positive_ints,
        default=_WRITE_SIZES,
        help="comma-separated logical write sizes",
    )
    parser.add_argument(
        "--total-write-bytes",
        type=_positive_int,
        default=8 * _MIB,
        help="fixed uncompressed payload per write case (default: 8 MiB)",
    )
    parser.add_argument(
        "--source-chunk-bytes",
        type=_positive_int,
        default=_MIB,
        help="maximum asynchronous source read (default: 1 MiB)",
    )
    parser.add_argument(
        "--repeat",
        type=_positive_int,
        default=5,
        help="odd primary sample count (default: 5)",
    )
    parser.add_argument(
        "--memory-repeat",
        type=_positive_int,
        default=1,
        help="tracemalloc peak sample count (default: 1; not a timing claim)",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.repeat < 5 or args.repeat % 2 == 0:
        parser.error("--repeat must be an odd integer of at least 5")
    if args.memory_repeat % 2 == 0:
        parser.error("--memory-repeat must be odd")
    categories = tuple(item.strip() for item in args.categories.split(","))
    if (
        "headers" in categories
        and args.memory_fixture_size_mib not in args.fixture_sizes_mib
    ):
        parser.error("--memory-fixture-size-mib must appear in --fixture-sizes-mib")
    try:
        document = asyncio.run(run_benchmarks(args))
    except (RuntimeError, ValueError) as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
