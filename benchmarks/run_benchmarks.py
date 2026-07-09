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
import importlib
import sys
from pathlib import Path

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
    "micro": "bench_micro",
}

QUICK_CATEGORIES = ["io", "compression"]


async def run_category(category: str, data_size_mb: int = 1, repeat: int = 3):
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
        benchmark = benchmark_class(data_size_mb=data_size_mb)
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

    # Run benchmarks
    all_results = []
    for category in categories_to_run:
        results = await run_category(
            category, data_size_mb=args.size, repeat=args.repeat
        )
        if results:
            all_results.extend(results)

    # Save results if requested
    if args.output and all_results:
        output_path = Path(args.output)
        # Save consolidated results
        import json

        data = {
            "categories": categories_to_run,
            "data_size_mb": args.size,
            "repeat": args.repeat,
            "results": [r.to_dict() for r in all_results],
        }
        with open(output_path, "w") as f:
            json.dump(data, f, indent=2)
        print(f"\nResults saved to {output_path}")

    print(f"\n{'=' * 60}")
    print("Benchmarks Complete")
    print(f"{'=' * 60}")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
