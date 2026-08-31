#!/usr/bin/env python3
"""Targeted same-process timing investigation for the 2.0.0b1 evidence.

This diagnostic loads exact a4 and the b1 candidate under distinct package
aliases, warms both sides, and measures them in repeated A/B/B/A order. It is
not a replacement for the locked release matrices; it exists to distinguish
sub-millisecond process-order noise from source-dependent timing changes.
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import gzip
import hashlib
import importlib.util
import json
import os
import statistics
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path
from types import ModuleType
from typing import Any, Awaitable, Callable

from bench_a3_regressions import (
    _MIB,
    _read_direct,
    _read_high_level,
    _sha256,
    optional_header_fixture,
)

_KIB = 1024
_OUTPUT_BOUND = 256 * _KIB


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _git(source_root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(source_root), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _load_package(alias: str, source_root: Path) -> ModuleType:
    package_dir = source_root.resolve() / "src" / "aiogzip"
    package_init = package_dir / "__init__.py"
    if not package_init.is_file():
        raise ValueError(f"missing source package: {package_init}")
    spec = importlib.util.spec_from_file_location(
        alias,
        package_init,
        submodule_search_locations=[str(package_dir)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load package from {package_init}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module
    spec.loader.exec_module(module)
    return module


def _deterministic_bytes(size: int, *, label: bytes) -> bytes:
    return hashlib.shake_256(b"aiogzip-a2-regressions:" + label).digest(size)


def _time_output_bound(module: Any, wire: bytes, expected_sha256: str) -> float:
    decoder = module.GzipDecoder(output_chunk_size=_OUTPUT_BOUND)
    digest = hashlib.sha256()
    output_bytes = 0
    output_chunks = 0
    maximum_chunk = 0
    started = time.perf_counter()
    for output in decoder.feed(wire):
        digest.update(output)
        output_bytes += len(output)
        output_chunks += 1
        maximum_chunk = max(maximum_chunk, len(output))
    for output in decoder.finish():
        digest.update(output)
        output_bytes += len(output)
        output_chunks += 1
        maximum_chunk = max(maximum_chunk, len(output))
    duration = time.perf_counter() - started
    if output_bytes != 128 * _KIB:
        raise AssertionError("output-bound byte count mismatch")
    if digest.hexdigest() != expected_sha256:
        raise AssertionError("output-bound digest mismatch")
    if output_chunks != 1 or maximum_chunk > _OUTPUT_BOUND:
        raise AssertionError("output-bound chunk contract mismatch")
    return duration


async def _time_header_high_level(
    module: Any, wire: bytes, *, complete: bool, expected_sha256: str
) -> float:
    sample = await _read_high_level(
        module,
        wire,
        chunk_size=_MIB,
        expect_complete=complete,
        measure_memory=False,
    )
    if sample.metrics["output_sha256"] != expected_sha256:
        raise AssertionError("high-level header output mismatch")
    return sample.duration_seconds


def _time_header_direct(
    module: Any, wire: bytes, *, complete: bool, expected_sha256: str
) -> float:
    sample = _read_direct(
        module,
        wire,
        chunk_size=_MIB,
        expect_complete=complete,
    )
    if sample.metrics["output_sha256"] != expected_sha256:
        raise AssertionError("direct header output mismatch")
    return sample.duration_seconds


def _summary(samples: list[float]) -> dict[str, Any]:
    return {
        "samples_seconds": samples,
        "minimum_seconds": min(samples),
        "median_seconds": statistics.median(samples),
        "maximum_seconds": max(samples),
        "sample_count": len(samples),
    }


async def _measure_case(
    name: str,
    baseline: ModuleType,
    candidate: ModuleType,
    measure: Callable[[ModuleType], Awaitable[float]],
    *,
    cycles: int,
) -> dict[str, Any]:
    print(f"  START {name}", flush=True)
    await measure(baseline)
    await measure(candidate)
    samples: dict[str, list[float]] = {"baseline": [], "candidate": []}
    modules = {"baseline": baseline, "candidate": candidate}
    for _ in range(cycles):
        for label in ("baseline", "candidate", "candidate", "baseline"):
            samples[label].append(await measure(modules[label]))
    baseline_summary = _summary(samples["baseline"])
    candidate_summary = _summary(samples["candidate"])
    baseline_minimum = baseline_summary["minimum_seconds"]
    candidate_minimum = candidate_summary["minimum_seconds"]
    return {
        "name": name,
        "ordering": "A/B/B/A per cycle after one untimed warm-up per side",
        "baseline": baseline_summary,
        "candidate": candidate_summary,
        "minimum_change_percent": ((candidate_minimum / baseline_minimum) - 1) * 100,
    }


async def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.engine == "stdlib":
        os.environ["AIOGZIP_ENGINE"] = "stdlib"
    else:
        os.environ.pop("AIOGZIP_ENGINE", None)
    baseline = _load_package("aiogzip_b1_baseline", args.baseline_root)
    candidate = _load_package("aiogzip_b1_candidate", args.candidate_root)

    output_payload = _deterministic_bytes(128 * _KIB, label=b"output-bound")
    output_wire = gzip.compress(output_payload, compresslevel=6, mtime=0)
    output_sha256 = _sha256(output_payload)

    cases: list[tuple[str, Callable[[ModuleType], Awaitable[float]]]] = []

    async def output_bound(module: ModuleType) -> float:
        return _time_output_bound(module, output_wire, output_sha256)

    cases.append(("direct output bound 262144 bytes", output_bound))

    for field, size_mib, complete, surface in (
        ("fcomment", 32, True, "high-level"),
        ("fname", 64, True, "high-level"),
        ("fcomment", 32, True, "direct"),
        ("fcomment", 32, False, "direct"),
        ("fcomment", 64, True, "direct"),
        ("fcomment", 64, False, "direct"),
        ("fname", 64, True, "direct"),
        ("fname", 64, False, "direct"),
    ):
        wire, expected = optional_header_fixture(
            field,
            size_mib * _MIB,
            complete=complete,
            mtime=0,
        )
        expected_sha256 = _sha256(expected)
        fixture_name = (
            f"{field}-{size_mib}MiB-{'complete' if complete else 'incomplete'}"
        )
        name = f"{surface} {fixture_name} throughput"
        if surface == "high-level":

            async def high_level(
                module: ModuleType,
                wire: bytes = wire,
                complete: bool = complete,
                expected_sha256: str = expected_sha256,
            ) -> float:
                return await _time_header_high_level(
                    module,
                    wire,
                    complete=complete,
                    expected_sha256=expected_sha256,
                )

            cases.append((name, high_level))
        else:

            async def direct(
                module: ModuleType,
                wire: bytes = wire,
                complete: bool = complete,
                expected_sha256: str = expected_sha256,
            ) -> float:
                return _time_header_direct(
                    module,
                    wire,
                    complete=complete,
                    expected_sha256=expected_sha256,
                )

            cases.append((name, direct))

    was_enabled = gc.isenabled()
    gc.disable()
    try:
        results = [
            await _measure_case(
                name,
                baseline,
                candidate,
                measure,
                cycles=args.cycles,
            )
            for name, measure in cases
        ]
    finally:
        if was_enabled:
            gc.enable()

    return {
        "schema_version": 1,
        "benchmark": "aiogzip-2.0.0b1-targeted-timing-investigation",
        "created_at_unix": time.time(),
        "configuration": {
            "engine": args.engine,
            "cycles": args.cycles,
            "samples_per_side_per_case": args.cycles * 2,
            "ordering": "A/B/B/A",
            "garbage_collection": "disabled during timed measurements",
            "process_policy": "both source trees loaded under package aliases",
        },
        "baseline": {
            "source_root": str(args.baseline_root.resolve()),
            "package_file": str(Path(baseline.__file__).resolve()),
            "version": baseline.__version__,
            "commit": _git(args.baseline_root, "rev-parse", "HEAD"),
            "engine": asdict(baseline.engine_info()),
        },
        "candidate": {
            "source_root": str(args.candidate_root.resolve()),
            "package_file": str(Path(candidate.__file__).resolve()),
            "version": candidate.__version__,
            "commit": _git(args.candidate_root, "rev-parse", "HEAD"),
            "engine": asdict(candidate.engine_info()),
        },
        "results": results,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--engine", choices=("stdlib", "zlib-ng"), required=True)
    parser.add_argument(
        "--cycles",
        type=_positive_int,
        default=50,
        help="A/B/B/A cycles; each cycle produces two samples per side",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    document = asyncio.run(run(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
