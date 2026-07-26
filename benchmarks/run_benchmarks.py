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
from pathlib import Path
from typing import Any

try:
    from .bench_common import median_results
except ImportError:  # Direct script execution: benchmarks/ is on sys.path.
    from bench_common import median_results

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


async def run_category(
    category: str,
    data_size_mb: int = 1,
    repeat: int = 3,
    *,
    benchmark_options: dict[str, Any] | None = None,
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
    for _ in range(repeat):
        benchmark = benchmark_class(
            data_size_mb=data_size_mb, **(benchmark_options or {})
        )
        try:
            benchmark.setup()
            await benchmark.run_all()
            repeated_results.append(benchmark.get_results())
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


def configure_source_root(source_root: Path) -> dict[str, Any]:
    """Import and attest aiogzip from one explicit source checkout."""
    resolved_root = source_root.resolve()
    source_dir = resolved_root / "src"
    package_init = source_dir / "aiogzip" / "__init__.py"
    if not package_init.is_file():
        raise ValueError(
            f"source root does not contain src/aiogzip/__init__.py: {resolved_root}"
        )

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
        "target_commit": _git_value(resolved_root, "rev-parse", "HEAD"),
        "target_describe": _git_value(
            resolved_root, "describe", "--always", "--dirty", "--tags"
        ),
        "target_dirty": bool(
            _git_value(resolved_root, "status", "--porcelain", "--untracked-files=no")
        ),
    }


def collect_environment(
    source_identity: dict[str, Any], *, environment_label: str | None = None
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
        "forced_engine": os.environ.get("AIOGZIP_ENGINE"),
        "uv_version": uv_version,
        "uv_lock_sha256": _file_sha256(
            Path(source_identity["source_root"]) / "uv.lock"
        ),
        "cpu_affinity": affinity,
        "cpu_governor": "unavailable on this platform",
        "cpu_boost": "unavailable on this platform",
        "system_load": list(os.getloadavg()) if hasattr(os, "getloadavg") else None,
        "garbage_collection_enabled": gc.isenabled(),
        "garbage_collection_thresholds": list(gc.get_threshold()),
    }


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
    if args.source_root is not None:
        try:
            source_identity = configure_source_root(args.source_root)
        except (ValueError, RuntimeError, subprocess.CalledProcessError) as error:
            parser.error(str(error))
        environment = collect_environment(
            source_identity, environment_label=args.environment_label
        )

    # Run benchmarks
    all_results = []
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
        )
        if results:
            all_results.extend(results)

    # Save results if requested
    if args.output and all_results:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "schema_version": 2,
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
            "results": [r.to_dict() for r in all_results],
        }
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        print(f"\nResults saved to {output_path}")

    print(f"\n{'=' * 60}")
    print("Benchmarks Complete")
    print(f"{'=' * 60}")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
