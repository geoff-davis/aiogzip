#!/usr/bin/env python3
"""
Compare benchmark results from different runs.

Usage:
    python bench_compare.py baseline.json current.json
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict


def load_results(filepath: Path) -> Dict[str, Any]:
    """Load benchmark results from JSON file."""
    with open(filepath) as f:
        return json.load(f)


def compare_results(baseline: dict, current: dict) -> None:
    """Compare two sets of benchmark results."""
    print(f"\n{'=' * 70}")
    print("BENCHMARK COMPARISON")
    print(f"{'=' * 70}")

    # Create lookup dictionaries by benchmark name
    baseline_results = {r["name"]: r for r in baseline.get("results", [])}
    current_results = {r["name"]: r for r in current.get("results", [])}

    # Find common benchmarks
    common_names = set(baseline_results.keys()) & set(current_results.keys())

    if not common_names:
        print("\nNo common benchmarks found between the two result sets.")
        return

    print(f"\nComparing {len(common_names)} common benchmarks:\n")
    print(f"{'Benchmark':<40} {'Baseline':<12} {'Current':<12} {'Change':<12}")
    print("-" * 70)

    improvements = []
    regressions = []

    for name in sorted(common_names):
        baseline_bench = baseline_results[name]
        current_bench = current_results[name]

        baseline_time = baseline_bench["duration"]
        current_time = current_bench["duration"]

        # Calculate percentage change
        if baseline_time > 0:
            change_pct = ((current_time - baseline_time) / baseline_time) * 100
        else:
            change_pct = 0

        # Format change with color indicators
        if change_pct < -5:  # Improvement
            change_str = f"{change_pct:+.1f}% ✓"
            improvements.append((name, change_pct))
        elif change_pct > 5:  # Regression
            change_str = f"{change_pct:+.1f}% ✗"
            regressions.append((name, change_pct))
        else:  # Neutral
            change_str = f"{change_pct:+.1f}% ="

        # Truncate long names
        display_name = name[:38] + ".." if len(name) > 40 else name

        print(
            f"{display_name:<40} {baseline_time:>10.3f}s {current_time:>10.3f}s {change_str:<12}"
        )

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    if improvements:
        print(f"\n✓ Improvements ({len(improvements)}):")
        for name, pct in sorted(improvements, key=lambda x: x[1]):
            print(f"  {name}: {pct:.1f}% faster")

    if regressions:
        print(f"\n✗ Regressions ({len(regressions)}):")
        for name, pct in sorted(regressions, key=lambda x: x[1], reverse=True):
            print(f"  {name}: {abs(pct):.1f}% slower")

    if not improvements and not regressions:
        print("\n= No significant changes (within ±5%)")

    # Overall stats
    total_baseline = sum(r["duration"] for r in baseline.get("results", []))
    total_current = sum(r["duration"] for r in current.get("results", []))

    if total_baseline > 0:
        overall_change = ((total_current - total_baseline) / total_baseline) * 100
        print(
            f"\nOverall: {total_baseline:.3f}s → {total_current:.3f}s ({overall_change:+.1f}%)"
        )


def main():
    parser = argparse.ArgumentParser(description="Compare benchmark results")
    parser.add_argument("baseline", type=Path, help="Baseline results JSON file")
    parser.add_argument("current", type=Path, help="Current results JSON file")

    args = parser.parse_args()

    # Validate files exist
    if not args.baseline.exists():
        print(f"Error: Baseline file not found: {args.baseline}")
        return 1

    if not args.current.exists():
        print(f"Error: Current file not found: {args.current}")
        return 1

    # Load and compare
    try:
        baseline = load_results(args.baseline)
        current = load_results(args.current)
        compare_results(baseline, current)
        return 0
    except Exception as e:
        print(f"Error comparing results: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
