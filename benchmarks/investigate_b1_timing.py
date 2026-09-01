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
import platform
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
    _positive_int,
    _read_direct,
    _read_high_level,
    _sha256,
    optional_header_fixture,
)
from bench_targeted_contract import (
    RAW_CHANGE_FORMULA,
    TARGETED_BENCHMARK,
    validate_canonical_orientation,
)
from run_benchmarks import assert_requested_engine

_KIB = 1024
_OUTPUT_BOUND = 256 * _KIB


def _git(source_root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(source_root), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _source_identity(source_root: Path) -> dict[str, Any]:
    """Validate and attest a clean git source tree before measurement."""
    root = source_root.resolve()
    package_init = root / "src" / "aiogzip" / "__init__.py"
    if not package_init.is_file():
        raise ValueError(f"missing source package: {package_init}")
    commit = _git(root, "rev-parse", "HEAD")
    describe = _git(root, "describe", "--always", "--dirty", "--tags")
    dirty_tracked = bool(_git(root, "status", "--porcelain", "--untracked-files=no"))
    if dirty_tracked:
        raise RuntimeError(f"source tree has tracked changes: {root}")
    return {
        "source_root": str(root),
        "commit": commit,
        "describe": describe,
        "dirty_tracked": False,
    }


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


def _active_engines(module: ModuleType) -> dict[str, str]:
    return asdict(module.engine_info())


def _assert_requested_engine(
    module: ModuleType, requested: str, *, source_label: str
) -> dict[str, str]:
    engines = _active_engines(module)
    return assert_requested_engine(engines, requested, source_label=source_label)


def _output_bound_fixture() -> tuple[bytes, str]:
    # Import lazily so the requested engine environment is established before
    # bench_codec_regressions imports its canonical aiogzip package.
    from bench_codec_regressions import _deterministic_bytes

    payload = _deterministic_bytes(128 * _KIB, label=b"output-bound")
    return gzip.compress(payload, compresslevel=6, mtime=0), _sha256(payload)


def _time_output_bound(module: Any, wire: bytes, expected_sha256: str) -> float:
    decoder = module.GzipDecoder(output_chunk_size=_OUTPUT_BOUND)
    digest = hashlib.sha256()
    output_bytes = 0
    maximum_chunk = 0
    started = time.perf_counter()
    try:
        feed_operation = decoder.feed(wire)
        try:
            for output in feed_operation:
                digest.update(output)
                output_bytes += len(output)
                maximum_chunk = max(maximum_chunk, len(output))
        finally:
            feed_operation.close()
        finish_operation = decoder.finish()
        try:
            for output in finish_operation:
                digest.update(output)
                output_bytes += len(output)
                maximum_chunk = max(maximum_chunk, len(output))
        finally:
            finish_operation.close()
        duration = time.perf_counter() - started
    finally:
        decoder.discard()
    if output_bytes != 128 * _KIB:
        raise AssertionError("output-bound byte count mismatch")
    if digest.hexdigest() != expected_sha256:
        raise AssertionError("output-bound digest mismatch")
    if maximum_chunk > _OUTPUT_BOUND:
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


def _output_bound_measure(
    wire: bytes, expected_sha256: str
) -> Callable[[ModuleType], Awaitable[float]]:
    async def measure(module: ModuleType) -> float:
        return _time_output_bound(module, wire, expected_sha256)

    return measure


def _header_measure(
    surface: str,
    wire: bytes,
    *,
    complete: bool,
    expected_sha256: str,
) -> Callable[[ModuleType], Awaitable[float]]:
    if surface == "high-level":

        async def measure(module: ModuleType) -> float:
            return await _time_header_high_level(
                module,
                wire,
                complete=complete,
                expected_sha256=expected_sha256,
            )

    else:

        async def measure(module: ModuleType) -> float:
            return _time_header_direct(
                module,
                wire,
                complete=complete,
                expected_sha256=expected_sha256,
            )

    return measure


async def _measure_case(
    name: str,
    baseline: ModuleType,
    candidate: ModuleType,
    measure: Callable[[ModuleType], Awaitable[float]],
    *,
    cycles: int,
    warmup_cycles: int,
) -> dict[str, Any]:
    print(f"  START {name}", flush=True)
    samples: dict[str, list[float]] = {"baseline": [], "candidate": []}
    modules = {"baseline": baseline, "candidate": candidate}
    for _ in range(warmup_cycles):
        for label in ("baseline", "candidate", "candidate", "baseline"):
            await measure(modules[label])
    for _ in range(cycles):
        for label in ("baseline", "candidate", "candidate", "baseline"):
            samples[label].append(await measure(modules[label]))
    baseline_summary = _summary(samples["baseline"])
    candidate_summary = _summary(samples["candidate"])
    baseline_minimum = baseline_summary["minimum_seconds"]
    candidate_minimum = candidate_summary["minimum_seconds"]
    return {
        "name": name,
        "ordering": (
            f"A/B/B/A per measured cycle after {warmup_cycles} untimed A/B/B/A cycles"
        ),
        "baseline": baseline_summary,
        "candidate": candidate_summary,
        "minimum_change_percent": ((candidate_minimum / baseline_minimum) - 1) * 100,
    }


def _complete_identity(
    identity: dict[str, Any], module: ModuleType, engines: dict[str, str]
) -> dict[str, Any]:
    imported = Path(module.__file__).resolve()
    source_dir = Path(identity["source_root"]) / "src"
    if not imported.is_relative_to(source_dir):
        raise RuntimeError(f"imported {imported}, expected a module below {source_dir}")
    return {
        **identity,
        "package_file": str(imported),
        "version": module.__version__,
        "active_engines": engines,
    }


def _checkpoint(
    document: dict[str, Any], writer: Callable[[dict[str, Any]], None] | None
) -> None:
    if writer is not None:
        writer(document)


def _capture_command(args: argparse.Namespace) -> list[str]:
    """Record either the exact CLI or an equivalent programmatic invocation."""
    if hasattr(args, "command"):
        command = args.command
        if not (
            isinstance(command, list)
            and command
            and all(isinstance(argument, str) and argument for argument in command)
        ):
            raise ValueError("args.command must be a non-empty list of strings")
        return list(command)
    return [
        "programmatic:investigate_b1_timing.run",
        f"baseline_root={Path(args.baseline_root).resolve()}",
        f"candidate_root={Path(args.candidate_root).resolve()}",
        f"engine={args.engine}",
        f"cycles={args.cycles}",
        f"warmup_cycles={args.warmup_cycles}",
        f"canonical_candidate_side={args.canonical_candidate_side}",
        f"canonical_candidate_commit={args.canonical_candidate_commit}",
    ]


async def run(
    args: argparse.Namespace,
    *,
    checkpoint: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    canonical_candidate_commit = getattr(args, "canonical_candidate_commit", None)
    if (
        not isinstance(canonical_candidate_commit, str)
        or not canonical_candidate_commit
    ):
        raise ValueError("args.canonical_candidate_commit must be a non-empty string")
    command = _capture_command(args)
    # Git and cleanliness checks intentionally precede package loading and all
    # fixture construction so invalid provenance fails before a timed run.
    baseline_identity = _source_identity(args.baseline_root)
    candidate_identity = _source_identity(args.candidate_root)
    if args.engine == "stdlib":
        os.environ["AIOGZIP_ENGINE"] = "stdlib"
    else:
        os.environ.pop("AIOGZIP_ENGINE", None)
    baseline = _load_package("aiogzip_b1_baseline", args.baseline_root)
    candidate = _load_package("aiogzip_b1_candidate", args.candidate_root)
    baseline_engines = _assert_requested_engine(
        baseline, args.engine, source_label="baseline"
    )
    candidate_engines = _assert_requested_engine(
        candidate, args.engine, source_label="candidate"
    )
    baseline_record = _complete_identity(baseline_identity, baseline, baseline_engines)
    candidate_record = _complete_identity(
        candidate_identity, candidate, candidate_engines
    )
    orientation = {
        "canonical_candidate_side": args.canonical_candidate_side,
        "canonical_candidate_commit": canonical_candidate_commit,
    }
    validate_canonical_orientation(
        orientation,
        baseline_record,
        candidate_record,
        label="targeted capture producer",
        allow_legacy=False,
    )

    document: dict[str, Any] = {
        "schema_version": 2,
        "benchmark": TARGETED_BENCHMARK,
        "status": "running",
        "created_at_unix": time.time(),
        "configuration": {
            "requested_engine": args.engine,
            "cycles": args.cycles,
            "samples_per_side_per_case": args.cycles * 2,
            "warmup_cycles": args.warmup_cycles,
            "ordering": "A/B/B/A",
            **orientation,
            "reported_change_formula": RAW_CHANGE_FORMULA,
            "garbage_collection": "disabled during timed measurements",
            "process_policy": "both source trees loaded under package aliases",
            "checkpoint_policy": "atomic write before timing and after every case",
        },
        "command": command,
        "host": {
            "os_name": platform.system(),
            "platform": platform.platform(),
            "python_version": sys.version,
            "python_executable": sys.executable,
        },
        "baseline": baseline_record,
        "candidate": candidate_record,
        "results": [],
    }
    _checkpoint(document, checkpoint)

    was_enabled = gc.isenabled()
    gc.disable()
    try:
        output_wire, output_sha256 = _output_bound_fixture()
        output_bound = _output_bound_measure(output_wire, output_sha256)
        document["results"].append(
            await _measure_case(
                "direct output bound 262144 bytes",
                baseline,
                candidate,
                output_bound,
                cycles=args.cycles,
                warmup_cycles=args.warmup_cycles,
            )
        )
        _checkpoint(document, checkpoint)
        del output_bound, output_wire

        # Construct and release one optional-header fixture at a time. Keeping
        # all closures alive together retains hundreds of MiB unnecessarily.
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
            measure = _header_measure(
                surface,
                wire,
                complete=complete,
                expected_sha256=expected_sha256,
            )
            document["results"].append(
                await _measure_case(
                    name,
                    baseline,
                    candidate,
                    measure,
                    cycles=args.cycles,
                    warmup_cycles=args.warmup_cycles,
                )
            )
            _checkpoint(document, checkpoint)
            del measure, wire, expected
    except BaseException as error:
        document["status"] = "failed"
        document["failure"] = {
            "type": type(error).__name__,
            "message": str(error),
        }
        _checkpoint(document, checkpoint)
        raise
    finally:
        if was_enabled:
            gc.enable()
    document["status"] = "complete"
    document["completed_at_unix"] = time.time()
    _checkpoint(document, checkpoint)
    return document


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
    parser.add_argument(
        "--warmup-cycles",
        type=_positive_int,
        default=25,
        help="untimed A/B/B/A cycles per case before measurement",
    )
    parser.add_argument(
        "--canonical-candidate-side",
        choices=("baseline", "candidate"),
        default="candidate",
        help="which raw side is the candidate in the canonical comparison",
    )
    parser.add_argument(
        "--canonical-candidate-commit",
        required=True,
        help="expected exact commit for the canonical candidate source",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _write_document(path: Path, document: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    args = build_parser().parse_args()
    args.command = [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(
        run(
            args,
            checkpoint=lambda document: _write_document(args.output, document),
        )
    )
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
