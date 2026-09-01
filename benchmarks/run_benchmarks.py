#!/usr/bin/env python3
"""
Main entry point for running aiogzip benchmarks.

Usage:
    python run_benchmarks.py --all
    python run_benchmarks.py --category io
    python run_benchmarks.py --category io,memory,compression
    python run_benchmarks.py --quick
"""

import argparse
import asyncio
import gc
import hashlib
import importlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import zlib
from functools import partial
from pathlib import Path
from typing import Any, Callable

try:
    from .bench_common import BenchmarkResults, median_results
except ImportError:  # Direct script execution: benchmarks/ is on sys.path.
    from bench_common import BenchmarkResults, median_results

# Available benchmark categories
CATEGORIES = {
    "io": "bench_io",
    "memory": "bench_memory",
    "concurrency": "bench_concurrency",
    "compression": "bench_compression",
    "scenarios": "bench_scenarios",
    "errors": "bench_errors",
    "inspection": "bench_inspection",
    "streaming": "bench_streaming",
    "micro": "bench_micro",
    "regressions": "bench_codec_regressions",
}

QUICK_CATEGORIES = ["io", "compression"]
_CPU_SYSFS_ROOT = Path("/sys/devices/system/cpu")


async def run_category(
    category: str,
    data_size_mb: int = 1,
    repeat: int = 3,
    *,
    benchmark_options: dict[str, Any] | None = None,
    result_checkpoint: (
        Callable[
            [
                str,
                int,
                int,
                list[list[BenchmarkResults]],
                list[BenchmarkResults],
                bool,
            ],
            None,
        ]
        | None
    ) = None,
):
    """Run a category repeatedly and return median-duration results."""
    if category not in CATEGORIES:
        print(f"Error: Unknown category '{category}'")
        print(f"Available categories: {', '.join(CATEGORIES.keys())}")
        return None

    module_name = CATEGORIES[category]
    try:
        module = importlib.import_module(module_name)
    except ImportError as e:
        print(f"Error: Could not import {module_name}: {e}")
        return None

    # Instantiate the benchmark class
    benchmark_class_name = (
        "".join(word.capitalize() for word in category.split("_")) + "Benchmarks"
    )
    if not hasattr(module, benchmark_class_name):
        print(f"Error: {module_name} does not have class {benchmark_class_name}")
        return None

    benchmark_class = getattr(module, benchmark_class_name)

    print(f"\n{'=' * 60}")
    print(f"Running {category.upper()} Benchmarks (median of {repeat} runs)")
    print(f"{'=' * 60}")

    repeated_results = []
    for repeat_index in range(1, repeat + 1):
        benchmark = benchmark_class(
            data_size_mb=data_size_mb, **(benchmark_options or {})
        )
        if result_checkpoint is not None:
            completed_repeats = [list(results) for results in repeated_results]
            benchmark._result_checkpoint = partial(
                result_checkpoint,
                category,
                repeat_index,
                repeat,
                completed_repeats,
                persist=False,
            )
            result_checkpoint(
                category, repeat_index, repeat, completed_repeats, [], True
            )
        try:
            benchmark.setup()
            await benchmark.run_all()
            repeated_results.append(benchmark.get_results())
            if result_checkpoint is not None:
                result_checkpoint(
                    category,
                    repeat_index,
                    repeat,
                    [list(results) for results in repeated_results],
                    [],
                    True,
                )
        finally:
            benchmark.cleanup()

    results = median_results(repeated_results)
    for result in results:
        print(f"\n{result}")

    return results


def positive_int(value: str) -> int:
    """Argparse type for strictly positive repeat counts."""
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _git_value(source_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(source_root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_sysfs_value(path: Path) -> str | None:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def _cpu_tuning() -> tuple[str, str]:
    """Return Linux CPU governor and boost state when sysfs exposes them."""
    if platform.system() != "Linux":
        unavailable = "unavailable on this platform"
        return unavailable, unavailable

    governors = {
        value
        for path in _CPU_SYSFS_ROOT.glob("cpu[0-9]*/cpufreq/scaling_governor")
        if (value := _read_sysfs_value(path)) is not None
    }
    if not governors:
        governor = "unavailable on Linux"
    elif len(governors) == 1:
        governor = governors.pop()
    else:
        governor = f"mixed: {', '.join(sorted(governors))}"

    boost_value = _read_sysfs_value(_CPU_SYSFS_ROOT / "cpufreq" / "boost")
    if boost_value is not None:
        boost = {"0": "disabled", "1": "enabled"}.get(
            boost_value, f"unknown: {boost_value}"
        )
    else:
        no_turbo = _read_sysfs_value(_CPU_SYSFS_ROOT / "intel_pstate" / "no_turbo")
        boost = (
            {"0": "enabled", "1": "disabled"}.get(no_turbo, f"unknown: {no_turbo}")
            if no_turbo is not None
            else "unavailable on Linux"
        )
    return governor, boost


def assert_requested_engine(
    engines: dict[str, str],
    requested: str,
    *,
    source_label: str,
    system_name: str | None = None,
) -> dict[str, str]:
    """Require the exact default engines expected for an evidence capture."""
    if requested not in {"stdlib", "zlib-ng"}:
        raise ValueError(f"unsupported requested engine: {requested}")
    system_name = system_name or platform.system()
    expected = {
        "compression": "stdlib-zlib",
        "decompression": "zlib-ng" if requested == "zlib-ng" else "stdlib-zlib",
        "crc32": (
            "zlib-ng"
            if requested == "zlib-ng" and system_name != "Darwin"
            else "stdlib-zlib"
        ),
    }
    mismatches = {
        field: {"expected": expected_value, "actual": engines.get(field)}
        for field, expected_value in expected.items()
        if engines.get(field) != expected_value
    }
    if mismatches:
        raise RuntimeError(
            f"{requested} was requested for {source_label}, but engine fields "
            f"do not match: {mismatches}; active engines are {engines}"
        )
    return engines


def _configure_requested_engine(
    requested: str | None, *, source_root_supplied: bool
) -> str | None:
    """Resolve the benchmark engine and apply the library's real env contract."""
    environment_value = os.environ.get("AIOGZIP_ENGINE", "").strip().lower()
    if requested is None:
        if environment_value == "stdlib":
            requested = "stdlib"
        elif environment_value:
            raise ValueError(
                "AIOGZIP_ENGINE accepts only stdlib; use --engine zlib-ng "
                "for an explicit zlib-ng benchmark capture"
            )
    if source_root_supplied and requested is None:
        raise ValueError("--source-root requires --engine stdlib or --engine zlib-ng")
    if requested == "stdlib":
        os.environ["AIOGZIP_ENGINE"] = "stdlib"
    elif requested == "zlib-ng":
        os.environ.pop("AIOGZIP_ENGINE", None)
    return requested


def _verify_unattested_engine(requested: str) -> dict[str, str]:
    """Verify an engine request when no source checkout was attested."""
    import aiogzip

    return assert_requested_engine(
        aiogzip.engine_info().__dict__,
        requested,
        source_label="unattested benchmark environment",
    )


def configure_source_root(source_root: Path) -> dict[str, Any]:
    """Import and attest aiogzip from one explicit source checkout."""
    resolved_root = source_root.resolve()
    source_dir = resolved_root / "src"
    package_init = source_dir / "aiogzip" / "__init__.py"
    if not package_init.is_file():
        raise ValueError(
            f"source root does not contain src/aiogzip/__init__.py: {resolved_root}"
        )

    target_commit = _git_value(resolved_root, "rev-parse", "HEAD")
    target_describe = _git_value(
        resolved_root, "describe", "--always", "--dirty", "--tags"
    )
    target_dirty = bool(
        _git_value(resolved_root, "status", "--porcelain", "--untracked-files=no")
    )
    if target_dirty:
        raise RuntimeError(f"source tree has tracked changes: {resolved_root}")

    loaded = sys.modules.get("aiogzip")
    if loaded is not None:
        loaded_file = Path(loaded.__file__).resolve()
        if not loaded_file.is_relative_to(source_dir):
            raise RuntimeError(
                "aiogzip is already imported from a different checkout; "
                "rerun the benchmark in a clean subprocess"
            )
    else:
        sys.path.insert(0, str(source_dir))
        loaded = importlib.import_module("aiogzip")

    imported_file = Path(loaded.__file__).resolve()
    if not imported_file.is_relative_to(source_dir):
        raise RuntimeError(
            f"source-root mismatch: imported {imported_file}, expected {source_dir}"
        )

    return {
        "source_root": str(resolved_root),
        "aiogzip_file": str(imported_file),
        "package_version": loaded.__version__,
        "target_commit": target_commit,
        "target_describe": target_describe,
        "target_dirty": False,
    }


def collect_environment(
    source_identity: dict[str, Any],
    *,
    environment_label: str | None = None,
    requested_engine: str | None = None,
) -> dict[str, Any]:
    """Collect the reproducibility metadata shared by every result file."""
    try:
        import psutil

        ram_bytes: int | None = psutil.virtual_memory().total
    except ImportError:  # pragma: no cover - psutil is in the dev environment.
        ram_bytes = None

    try:
        zlib_ng_version: str | None = importlib.metadata.version("zlib-ng")
    except importlib.metadata.PackageNotFoundError:
        zlib_ng_version = None

    try:
        affinity: list[int] | str = sorted(os.sched_getaffinity(0))
    except AttributeError:
        affinity = "unavailable"

    cpu_governor, cpu_boost = _cpu_tuning()

    uv_path = shutil.which("uv")
    uv_version = None
    if uv_path:
        uv_version = subprocess.run(
            [uv_path, "--version"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    import aiogzip

    runner_root = Path(__file__).resolve().parents[1]
    harness_path = Path(__file__).with_name("bench_codec_regressions.py")
    try:
        runner_commit = _git_value(runner_root, "rev-parse", "HEAD")
    except subprocess.CalledProcessError:
        runner_commit = None
    return {
        **source_identity,
        "environment_label": environment_label,
        "runner_root": str(runner_root),
        "runner_commit": runner_commit,
        "regression_harness_sha256": _file_sha256(harness_path),
        "python_implementation": platform.python_implementation(),
        "python_version": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "os_name": platform.system(),
        "os_release": platform.release(),
        "kernel_version": platform.version(),
        "architecture": platform.machine(),
        "libc": platform.libc_ver(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
        "ram_bytes": ram_bytes,
        "filesystem_temp_root": tempfile.gettempdir(),
        "zlib_compile_version": zlib.ZLIB_VERSION,
        "zlib_runtime_version": zlib.ZLIB_RUNTIME_VERSION,
        "zlib_ng_package_version": zlib_ng_version,
        "active_engines": aiogzip.engine_info().__dict__,
        "requested_engine": requested_engine,
        "forced_engine": os.environ.get("AIOGZIP_ENGINE"),
        "uv_version": uv_version,
        "uv_lock_sha256": _file_sha256(
            Path(source_identity["source_root"]) / "uv.lock"
        ),
        "cpu_affinity": affinity,
        "cpu_governor": cpu_governor,
        "cpu_boost": cpu_boost,
        "system_load": list(os.getloadavg()) if hasattr(os, "getloadavg") else None,
        "garbage_collection_enabled": gc.isenabled(),
        "garbage_collection_thresholds": list(gc.get_threshold()),
    }


def _write_document(path: Path, document: dict[str, Any]) -> None:
    """Atomically replace a benchmark checkpoint document."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


async def main():
    parser = argparse.ArgumentParser(description="Run aiogzip benchmarks")
    parser.add_argument(
        "--all", action="store_true", help="Run all benchmark categories"
    )
    parser.add_argument(
        "--category",
        "-c",
        type=str,
        help=f"Run specific categories (comma-separated). Options: {', '.join(CATEGORIES.keys())}",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help=f"Run quick benchmarks ({', '.join(QUICK_CATEGORIES)})",
    )
    parser.add_argument(
        "--size", type=int, default=1, help="Data size in MB (default: 1)"
    )
    parser.add_argument(
        "--repeat",
        type=positive_int,
        default=3,
        help="Run each category N times and report medians (default: 3)",
    )
    parser.add_argument("--output", "-o", type=str, help="Save results to JSON file")
    parser.add_argument(
        "--source-root",
        type=Path,
        help="Import aiogzip from this checkout's src directory and verify it",
    )
    parser.add_argument(
        "--engine",
        choices=("stdlib", "zlib-ng"),
        help="Require and record the active engine for an attested capture",
    )
    parser.add_argument(
        "--regression-profile",
        choices=("quick", "release"),
        help="Select the regression matrix size (requires regressions category)",
    )
    parser.add_argument(
        "--regression-mode",
        choices=("throughput", "memory", "ticker", "all"),
        help="Select an isolated regression measurement mode (default: throughput)",
    )
    parser.add_argument(
        "--environment-label",
        help="Human-readable benchmark machine/purpose label stored in JSON",
    )

    args = parser.parse_args()

    # Determine which categories to run
    categories_to_run = []
    if args.all:
        categories_to_run = list(CATEGORIES.keys())
    elif args.quick:
        categories_to_run = QUICK_CATEGORIES
    elif args.category:
        categories_to_run = [c.strip() for c in args.category.split(",")]
    else:
        parser.print_help()
        return 1

    unknown_categories = [
        category for category in categories_to_run if category not in CATEGORIES
    ]
    if unknown_categories:
        parser.error(f"unknown categories: {', '.join(unknown_categories)}")
    regressions_selected = "regressions" in categories_to_run
    if (args.regression_profile or args.regression_mode) and not regressions_selected:
        parser.error(
            "--regression-profile and --regression-mode require --category regressions"
        )
    if regressions_selected and args.source_root is None:
        parser.error("--category regressions requires --source-root")

    source_identity = None
    environment = None
    try:
        requested_engine = _configure_requested_engine(
            args.engine, source_root_supplied=args.source_root is not None
        )
    except ValueError as error:
        parser.error(str(error))
    if args.source_root is not None:
        try:
            source_identity = configure_source_root(args.source_root)
        except (ValueError, RuntimeError, subprocess.CalledProcessError) as error:
            parser.error(str(error))
        environment = collect_environment(
            source_identity,
            environment_label=args.environment_label,
            requested_engine=requested_engine,
        )
        try:
            assert_requested_engine(
                environment["active_engines"],
                requested_engine,
                source_label="benchmark source",
                system_name=environment["os_name"],
            )
        except (ValueError, RuntimeError) as error:
            parser.error(str(error))
    elif requested_engine is not None:
        try:
            _verify_unattested_engine(requested_engine)
        except (ValueError, RuntimeError) as error:
            parser.error(str(error))

    output_path = Path(args.output) if args.output else None
    document: dict[str, Any] | None = None
    if output_path is not None:
        document = {
            "schema_version": 2,
            "status": "running",
            "timestamp": time.time(),
            "categories": categories_to_run,
            "data_size_mb": args.size,
            "repeat": args.repeat,
            "regression_profile": (
                args.regression_profile or "quick" if regressions_selected else None
            ),
            "regression_mode": (
                args.regression_mode or "throughput" if regressions_selected else None
            ),
            "source": source_identity,
            "environment": environment,
            "completed_categories": [],
            "results": [],
        }
        _write_document(output_path, document)

    # Run benchmarks
    all_results = []
    completed_categories: list[str] = []

    def checkpoint_category_results(
        category: str,
        repeat_index: int,
        repeat_count: int,
        completed_repeats: list[list[BenchmarkResults]],
        partial_results: list[BenchmarkResults],
        persist: bool,
    ) -> None:
        if document is None or output_path is None:
            return
        document["in_progress_category"] = {
            "name": category,
            "repeat_index": repeat_index,
            "repeat_count": repeat_count,
            "completed_repeats": [
                [result.to_dict() for result in results]
                for results in completed_repeats
            ],
            "partial_results": [result.to_dict() for result in partial_results],
        }
        if persist:
            _write_document(output_path, document)

    try:
        for category in categories_to_run:
            benchmark_options = None
            if category == "regressions":
                benchmark_options = {
                    "regression_profile": args.regression_profile or "quick",
                    "regression_mode": args.regression_mode or "throughput",
                }
            results = await run_category(
                category,
                data_size_mb=args.size,
                repeat=args.repeat,
                benchmark_options=benchmark_options,
                result_checkpoint=checkpoint_category_results,
            )
            if results:
                all_results.extend(results)
            completed_categories.append(category)
            if document is not None and output_path is not None:
                document.pop("in_progress_category", None)
                document["results"] = [result.to_dict() for result in all_results]
                document["completed_categories"] = list(completed_categories)
                _write_document(output_path, document)
    except BaseException as error:
        if document is not None and output_path is not None:
            document["status"] = "failed"
            document["failure"] = {
                "type": type(error).__name__,
                "message": str(error),
            }
            _write_document(output_path, document)
        raise

    if document is not None and output_path is not None:
        document["status"] = "complete"
        document["completed_at"] = time.time()
        _write_document(output_path, document)
        print(f"\nResults saved to {output_path}")

    print(f"\n{'=' * 60}")
    print("Benchmarks Complete")
    print(f"{'=' * 60}")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
