#!/usr/bin/env python3
"""Compare release captures or summarize targeted timing investigations.

Usage:
    python bench_compare.py baseline.json current.json
    python bench_compare.py targeted.json [targeted-swapped.json ...]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

from bench_targeted_contract import (
    RAW_CHANGE_FORMULA,
    TARGETED_BENCHMARK,
    validate_canonical_orientation,
)
from run_benchmarks import assert_requested_engine


def load_results(filepath: Path) -> dict[str, Any]:
    """Load benchmark results from JSON file."""
    with filepath.open() as file:
        return json.load(file)


def _attest_source(
    identity: dict[str, Any],
    label: str,
    *,
    commit_field: str,
    describe_field: str,
    dirty_field: str,
) -> dict[str, str]:
    """Validate the source fields shared by main and targeted captures."""
    commit = identity.get(commit_field)
    describe = identity.get(describe_field)
    if not isinstance(commit, str) or not commit:
        raise ValueError(f"{label} lacks source commit provenance")
    if not isinstance(describe, str) or not describe:
        raise ValueError(f"{label} lacks source description provenance")
    if identity.get(dirty_field) is not False:
        raise ValueError(f"{label} does not attest a clean source tree")
    return {"commit": commit, "describe": describe}


def _legacy_requested_engine(
    environment: dict[str, Any], engines: dict[str, Any], label: str
) -> tuple[str, list[str]]:
    requested = environment.get("forced_engine")
    if requested in {"stdlib", "zlib-ng"}:
        return requested, []
    active_values = set(engines.values())
    if active_values == {"stdlib-zlib"}:
        inferred = "stdlib"
    elif engines.get("decompression") == "zlib-ng":
        inferred = "zlib-ng"
    else:
        raise ValueError(f"{label} legacy capture has ambiguous active engines")
    return inferred, [
        f"{label}: inferred requested engine {inferred!r} from active_engines"
    ]


def _capture_identity(
    capture: dict[str, Any], label: str, *, allow_legacy: bool
) -> dict[str, Any]:
    warnings: list[str] = []
    status = capture.get("status")
    if status != "complete":
        if allow_legacy and status is None and isinstance(capture.get("results"), list):
            warnings.append(f"{label}: legacy capture has no completion status")
        else:
            raise ValueError(f"{label} capture is not complete")
    source = capture.get("source")
    environment = capture.get("environment")
    if not isinstance(source, dict) or not isinstance(environment, dict):
        raise ValueError(f"{label} capture lacks source/environment provenance")

    attestation = _attest_source(
        source,
        f"{label} capture",
        commit_field="target_commit",
        describe_field="target_describe",
        dirty_field="target_dirty",
    )
    for field in ("target_commit", "target_describe", "target_dirty"):
        if environment.get(field) != source[field]:
            raise ValueError(
                f"{label} capture has inconsistent source/environment {field}"
            )

    engines = environment.get("active_engines")
    if not isinstance(engines, dict):
        raise ValueError(f"{label} capture lacks active engine provenance")
    requested = environment.get("requested_engine")
    if requested not in {"stdlib", "zlib-ng"}:
        if not allow_legacy:
            raise ValueError(f"{label} capture lacks an explicit requested engine")
        requested, legacy_warnings = _legacy_requested_engine(
            environment, engines, label
        )
        warnings.extend(legacy_warnings)
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
        **attestation,
        "requested_engine": requested,
        "active_engines": engines,
        "system_name": system_name,
        "warnings": warnings,
    }


def _validate_capture_pair(
    baseline: dict[str, Any],
    current: dict[str, Any],
    *,
    allow_legacy: bool,
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

    baseline_identity = _capture_identity(
        baseline, "baseline", allow_legacy=allow_legacy
    )
    current_identity = _capture_identity(current, "current", allow_legacy=allow_legacy)
    for field in ("requested_engine", "active_engines", "system_name"):
        if baseline_identity[field] != current_identity[field]:
            raise ValueError(
                f"capture {field} mismatch: "
                f"baseline={baseline_identity[field]!r}, "
                f"current={current_identity[field]!r}"
            )
    return baseline_identity, current_identity


def compare_results(
    baseline: dict[str, Any], current: dict[str, Any], *, allow_legacy: bool = False
) -> None:
    """Compare two main-harness capture documents."""
    baseline_identity, current_identity = _validate_capture_pair(
        baseline, current, allow_legacy=allow_legacy
    )
    print(f"\n{'=' * 70}")
    print("BENCHMARK COMPARISON")
    print(f"{'=' * 70}")
    for warning in baseline_identity["warnings"] + current_identity["warnings"]:
        print(f"WARNING: {warning}")
    print(
        f"Baseline source: {baseline_identity['describe']} "
        f"({baseline_identity['commit']})"
    )
    print(
        f"Current source:  {current_identity['describe']} "
        f"({current_identity['commit']})"
    )
    print(f"Engine: {baseline_identity['requested_engine']}")

    baseline_results = {r["name"]: r for r in baseline.get("results", [])}
    current_results = {r["name"]: r for r in current.get("results", [])}
    common_names = set(baseline_results) & set(current_results)

    if not common_names:
        print("\nNo common benchmarks found between the two result sets.")
        return

    print(f"\nComparing {len(common_names)} common benchmarks:\n")
    print(f"{'Benchmark':<40} {'Baseline':<12} {'Current':<12} {'Change':<12}")
    print("-" * 70)

    improvements = []
    regressions = []
    for name in sorted(common_names):
        baseline_time = baseline_results[name]["duration"]
        current_time = current_results[name]["duration"]
        change_pct = (
            ((current_time - baseline_time) / baseline_time) * 100
            if baseline_time > 0
            else 0
        )
        if change_pct < -5:
            change_str = f"{change_pct:+.1f}% ✓"
            improvements.append((name, change_pct))
        elif change_pct > 5:
            change_str = f"{change_pct:+.1f}% ✗"
            regressions.append((name, change_pct))
        else:
            change_str = f"{change_pct:+.1f}% ="
        display_name = name[:38] + ".." if len(name) > 40 else name
        print(
            f"{display_name:<40} {baseline_time:>10.3f}s "
            f"{current_time:>10.3f}s {change_str:<12}"
        )

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    if improvements:
        print(f"\n✓ Improvements ({len(improvements)}):")
        for name, pct in sorted(improvements, key=lambda item: item[1]):
            print(f"  {name}: {pct:.1f}% faster")
    if regressions:
        print(f"\n✗ Regressions ({len(regressions)}):")
        for name, pct in sorted(regressions, key=lambda item: item[1], reverse=True):
            print(f"  {name}: {abs(pct):.1f}% slower")
    if not improvements and not regressions:
        print("\n= No significant changes (within ±5%)")

    total_baseline = sum(r["duration"] for r in baseline.get("results", []))
    total_current = sum(r["duration"] for r in current.get("results", []))
    if total_baseline > 0:
        overall_change = ((total_current - total_baseline) / total_baseline) * 100
        print(
            f"\nOverall: {total_baseline:.3f}s → {total_current:.3f}s "
            f"({overall_change:+.1f}%)"
        )


def canonical_change_percent(reported: float, candidate_side: str) -> float:
    """Orient a reported candidate/baseline delta as canonical b1 versus a4."""
    if candidate_side == "candidate":
        return reported
    if candidate_side == "baseline":
        return ((1 / (1 + reported / 100)) - 1) * 100
    raise ValueError(f"invalid canonical candidate side: {candidate_side!r}")


def _quarters(samples: list[float]) -> list[list[float]]:
    """Split retained samples into four ordered, non-empty temporal slices."""
    return [
        samples[start * len(samples) // 4 : (start + 1) * len(samples) // 4]
        for start in range(4)
    ]


def _format_quarters(values: list[float]) -> str:
    return " → ".join(f"{value:.3f}" for value in values)


def _targeted_producer_system(
    capture: dict[str, Any],
    configuration: dict[str, Any],
    label: str,
    *,
    allow_legacy: bool,
    warnings: list[str],
) -> str | None:
    """Validate capture-time command/host metadata and post-capture markers."""
    problems: list[str] = []
    command = capture.get("command")
    if not (
        isinstance(command, list)
        and command
        and all(isinstance(argument, str) and argument for argument in command)
    ):
        problems.append("lacks a producer-recorded command")
    host = capture.get("host")
    system_name = host.get("os_name") if isinstance(host, dict) else None
    if not isinstance(system_name, str) or not system_name:
        system_name = None
        problems.append("lacks capture-time host OS provenance")
    if "annotation_status" in configuration:
        problems.append("contains a post-capture orientation/formula annotation")
    if "post_capture_command_reconstruction" in capture:
        problems.append("contains a post-capture command reconstruction")
    if problems and not allow_legacy:
        raise ValueError(
            f"{label} is not a strict targeted capture: {', '.join(problems)}; "
            "use --allow-legacy to inspect it with warnings"
        )
    warnings.extend(f"{label}: {problem}" for problem in problems)
    return system_name


def _targeted_identity(
    capture: dict[str, Any], label: str, *, allow_legacy: bool
) -> dict[str, Any]:
    schema = capture.get("schema_version")
    if schema != 2:
        raise ValueError(
            f"{label} has unsupported targeted schema {schema!r}; "
            "schema-v1 records are archival and cannot be validated"
        )
    if capture.get("status") != "complete":
        raise ValueError(f"{label} capture is not complete")
    configuration = capture.get("configuration")
    baseline = capture.get("baseline")
    candidate = capture.get("candidate")
    if not all(isinstance(item, dict) for item in (configuration, baseline, candidate)):
        raise ValueError(f"{label} lacks targeted source/configuration provenance")
    requested = configuration.get("requested_engine")
    if requested not in {"stdlib", "zlib-ng"}:
        raise ValueError(f"{label} lacks a requested engine")

    warnings: list[str] = []
    system_name = _targeted_producer_system(
        capture,
        configuration,
        label,
        allow_legacy=allow_legacy,
        warnings=warnings,
    )
    formula = configuration.get("reported_change_formula")
    if formula != RAW_CHANGE_FORMULA:
        if not allow_legacy:
            raise ValueError(f"{label} lacks the canonical raw-change formula")
        warnings.append(f"{label}: raw-change formula was not producer-recorded")

    attestations: dict[str, dict[str, str]] = {}
    active_by_side: dict[str, dict[str, str]] = {}
    for side, identity in (("baseline", baseline), ("candidate", candidate)):
        attestations[side] = _attest_source(
            identity,
            f"{label} {side}",
            commit_field="commit",
            describe_field="describe",
            dirty_field="dirty_tracked",
        )
        version = identity.get("version")
        if not isinstance(version, str) or not version:
            raise ValueError(f"{label} {side} lacks source version provenance")
        engines = identity.get("active_engines")
        if not isinstance(engines, dict):
            raise ValueError(f"{label} {side} lacks active engine provenance")
        active_by_side[side] = engines
    if active_by_side["baseline"] != active_by_side["candidate"]:
        raise ValueError(f"{label} has different active engines on its two sides")

    if system_name is not None or requested == "stdlib":
        assert_requested_engine(
            active_by_side["baseline"],
            requested,
            source_label=f"{label} targeted capture",
            system_name=system_name or "unknown",
        )
    else:
        engines = active_by_side["baseline"]
        if engines.get("compression") != "stdlib-zlib":
            raise RuntimeError(
                f"{label} targeted capture: compression engine mismatch: "
                f"expected 'stdlib-zlib', got {engines.get('compression')!r}"
            )
        if engines.get("decompression") != "zlib-ng":
            raise RuntimeError(
                f"{label} targeted capture: decompression engine mismatch: "
                f"expected 'zlib-ng', got {engines.get('decompression')!r}"
            )
        if engines.get("crc32") not in {"stdlib-zlib", "zlib-ng"}:
            raise RuntimeError(
                f"{label} targeted capture: unrecognized crc32 engine: "
                f"{engines.get('crc32')!r}"
            )
        warnings.append(
            f"{label}: crc32 engine cannot be checked against the platform "
            "because capture-time host OS provenance is absent"
        )

    candidate_side, orientation_warnings = validate_canonical_orientation(
        configuration,
        baseline,
        candidate,
        label=label,
        allow_legacy=allow_legacy,
    )
    warnings.extend(orientation_warnings)

    return {
        "requested_engine": requested,
        "baseline": attestations["baseline"]["describe"],
        "candidate": attestations["candidate"]["describe"],
        "candidate_side": candidate_side,
        "warnings": warnings,
    }


def summarize_targeted(
    capture: dict[str, Any], label: str, *, allow_legacy: bool = False
) -> None:
    """Print min, median, and temporal diagnostics from one targeted record."""
    identity = _targeted_identity(capture, label, allow_legacy=allow_legacy)
    requested = identity["requested_engine"]
    baseline = identity["baseline"]
    candidate = identity["candidate"]
    candidate_side = identity["candidate_side"]
    print(f"\n{'=' * 88}")
    print(f"TARGETED TIMING: {label}")
    print(f"{'=' * 88}")
    for warning in identity["warnings"]:
        print(f"WARNING: {warning}")
    print(f"Raw baseline: {baseline}")
    print(f"Raw candidate: {candidate}")
    print(f"Canonical candidate side: {candidate_side}")
    print(f"Engine: {requested}")
    print(
        f"{'Benchmark':<39} {'raw min':>9} {'canon min':>10} "
        f"{'canon med':>10} {'canon 1/2 min':>13}"
    )
    print("-" * 88)
    for result in capture.get("results", []):
        baseline_samples = result["baseline"]["samples_seconds"]
        candidate_samples = result["candidate"]["samples_seconds"]
        reported_min = ((min(candidate_samples) / min(baseline_samples)) - 1) * 100
        reported_median = (
            (statistics.median(candidate_samples) / statistics.median(baseline_samples))
            - 1
        ) * 100
        halfway = min(len(baseline_samples), len(candidate_samples)) // 2
        reported_first_half = (
            (min(candidate_samples[:halfway]) / min(baseline_samples[:halfway])) - 1
        ) * 100
        canonical_min = canonical_change_percent(reported_min, candidate_side)
        canonical_median = canonical_change_percent(reported_median, candidate_side)
        canonical_first_half = canonical_change_percent(
            reported_first_half, candidate_side
        )
        name = result["name"]
        display_name = name[:37] + ".." if len(name) > 39 else name
        print(
            f"{display_name:<39} {reported_min:>+8.2f}% "
            f"{canonical_min:>+9.2f}% {canonical_median:>+9.2f}% "
            f"{canonical_first_half:>+12.2f}%"
        )
        baseline_quarters = [
            statistics.median(part) * 1000 for part in _quarters(baseline_samples)
        ]
        candidate_quarters = [
            statistics.median(part) * 1000 for part in _quarters(candidate_samples)
        ]
        print(
            "  quarter medians (ms), raw baseline/candidate: "
            f"{_format_quarters(baseline_quarters)} / "
            f"{_format_quarters(candidate_quarters)}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("captures", nargs="+", type=Path, help="capture JSON files")
    parser.add_argument(
        "--allow-legacy",
        action="store_true",
        help="accept pre-hardening captures with explicit provenance warnings",
    )
    args = parser.parse_args()
    missing = [path for path in args.captures if not path.exists()]
    if missing:
        print(f"Error: capture file not found: {missing[0]}")
        return 1

    try:
        captures = [load_results(path) for path in args.captures]
        targeted = [
            capture.get("benchmark") == TARGETED_BENCHMARK for capture in captures
        ]
        if all(targeted):
            for path, capture in zip(args.captures, captures, strict=True):
                summarize_targeted(capture, path.name, allow_legacy=args.allow_legacy)
        elif any(targeted):
            raise ValueError("cannot mix main-harness and targeted capture schemas")
        elif len(captures) != 2:
            raise ValueError("main-harness comparison requires exactly two captures")
        else:
            compare_results(captures[0], captures[1], allow_legacy=args.allow_legacy)
        return 0
    except Exception as error:
        print(f"Error comparing results: {error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
