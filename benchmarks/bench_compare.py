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

from run_benchmarks import assert_requested_engine


def load_results(filepath: Path) -> Dict[str, Any]:
    """Load benchmark results from JSON file."""
    with open(filepath) as f:
        return json.load(f)


def _capture_identity(capture: dict[str, Any], label: str) -> dict[str, Any]:
    if capture.get("status") != "complete":
        raise ValueError(f"{label} capture is not complete")
    source = capture.get("source")
    environment = capture.get("environment")
    if not isinstance(source, dict) or not isinstance(environment, dict):
        raise ValueError(f"{label} capture lacks source/environment provenance")

    commit = source.get("target_commit")
    describe = source.get("target_describe")
    if not isinstance(commit, str) or not commit:
        raise ValueError(f"{label} capture lacks a source commit")
    if not isinstance(describe, str) or not describe:
        raise ValueError(f"{label} capture lacks a source description")
    if source.get("target_dirty") is not False:
        raise ValueError(f"{label} capture does not attest a clean source tree")
    for field in ("target_commit", "target_describe", "target_dirty"):
        if environment.get(field) != source[field]:
            raise ValueError(
                f"{label} capture has inconsistent source/environment {field}"
            )

    requested = environment.get("forced_engine")
    if requested not in {"stdlib", "zlib-ng"}:
        raise ValueError(f"{label} capture lacks an explicit requested engine")
    engines = environment.get("active_engines")
    if not isinstance(engines, dict):
        raise ValueError(f"{label} capture lacks active engine provenance")
    system_name = environment.get("os_name")
    if not isinstance(system_name, str) or not system_name:
        raise ValueError(f"{label} capture lacks operating-system provenance")
    assert_requested_engine(
        engines,
        requested,
        source_label=f"{label} capture",
        system_name=system_name,
    )
    return {
        "commit": commit,
        "describe": describe,
        "requested_engine": requested,
        "active_engines": engines,
        "system_name": system_name,
    }


def _validate_capture_pair(
    baseline: dict[str, Any], current: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    baseline_schema = baseline.get("schema_version")
    current_schema = current.get("schema_version")
    if baseline_schema != current_schema:
        raise ValueError(
            "capture schema mismatch: "
            f"baseline={baseline_schema!r}, current={current_schema!r}"
        )
    if baseline_schema != 2:
        raise ValueError(f"unsupported benchmark capture schema: {baseline_schema!r}")

    baseline_identity = _capture_identity(baseline, "baseline")
    current_identity = _capture_identity(current, "current")
    for field in ("requested_engine", "active_engines", "system_name"):
        if baseline_identity[field] != current_identity[field]:
            raise ValueError(
                f"capture {field} mismatch: "
                f"baseline={baseline_identity[field]!r}, "
                f"current={current_identity[field]!r}"
            )
    return baseline_identity, current_identity


def compare_results(baseline: dict, current: dict) -> None:
    """Compare two sets of benchmark results."""
    baseline_identity, current_identity = _validate_capture_pair(baseline, current)
    print(f"\n{'=' * 70}")
    print("BENCHMARK COMPARISON")
    print(f"{'=' * 70}")
    print(
        f"Baseline source: {baseline_identity['describe']} "
        f"({baseline_identity['commit']})"
    )
    print(
        f"Current source:  {current_identity['describe']} "
        f"({current_identity['commit']})"
    )
    print(f"Engine: {baseline_identity['requested_engine']}")

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
