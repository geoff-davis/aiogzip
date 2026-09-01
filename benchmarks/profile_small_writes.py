#!/usr/bin/env python3
"""Profile aiogzip writes without changing their failure boundaries."""

from __future__ import annotations

import argparse
import asyncio
import cProfile
import json
import pstats
import sys
import time
from pathlib import Path
from typing import Any

from bench_a3_regressions import (
    SCHEMA_VERSION,
    _csv_positive_ints,
    _file_sha256,
    _positive_int,
    _write_once,
    collect_environment,
    configure_source_root,
)
from bench_common import ENGINE_CHOICES


def _profile_rows(profile: cProfile.Profile) -> list[dict[str, Any]]:
    rows = []
    for (filename, line, function), values in pstats.Stats(profile).stats.items():
        primitive_calls, total_calls, self_seconds, cumulative_seconds, _ = values
        rows.append(
            {
                "file": filename,
                "line": line,
                "function": function,
                "primitive_calls": primitive_calls,
                "total_calls": total_calls,
                "self_seconds": self_seconds,
                "cumulative_seconds": cumulative_seconds,
            }
        )
    return rows


def _category_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    def count(filename: str, function: str) -> int:
        return sum(
            int(row["total_calls"])
            for row in rows
            if Path(row["file"]).name == filename and row["function"] == function
        )

    def count_matching(fragment: str) -> int:
        return sum(
            int(row["total_calls"]) for row in rows if fragment in str(row["function"])
        )

    reservations = count("codec.py", "_reserve")
    return {
        "operation_constructions": reservations,
        "operation_reservations": reservations,
        "operation_next_calls": count("codec.py", "__next__"),
        "operation_raw_advance_calls": count("codec.py", "_advance_raw"),
        "public_snapshot_calls": count("codec.py", "_snapshot_bytes_input"),
        "file_payload_coercions": count("_binary.py", "_coerce_byteslike"),
        "internal_feed_calls": count("codec.py", "_feed_snapshot"),
        "feed_generator_calls": count("codec.py", "_feed"),
        "binary_write_calls": count("_binary.py", "write"),
        "compressor_calls": count_matching("method 'compress'"),
        "crc32_calls": count_matching("crc32"),
        "codec_output_chunks": count("_binary.py", "_write_all"),
        "write_all_calls": count("_binary.py", "_write_all"),
        "sink_write_calls": count("bench_a3_regressions.py", "write"),
    }


def _cost_centers(rows: list[dict[str, Any]]) -> dict[str, float]:
    def self_seconds(filename: str, function: str) -> float:
        return sum(
            float(row["self_seconds"])
            for row in rows
            if Path(row["file"]).name == filename and row["function"] == function
        )

    def matching_self_seconds(fragment: str) -> float:
        return sum(
            float(row["self_seconds"])
            for row in rows
            if fragment in str(row["function"])
        )

    return {
        "binary_write_self_seconds": self_seconds("_binary.py", "write"),
        "payload_coercion_self_seconds": self_seconds(
            "_binary.py", "_coerce_byteslike"
        ),
        "feed_snapshot_self_seconds": self_seconds("codec.py", "_feed_snapshot"),
        "reservation_self_seconds": self_seconds("codec.py", "_reserve"),
        "operation_next_self_seconds": self_seconds("codec.py", "__next__"),
        "operation_raw_advance_self_seconds": self_seconds("codec.py", "_advance_raw"),
        "feed_generator_self_seconds": self_seconds("codec.py", "_feed"),
        "crc32_self_seconds": matching_self_seconds("crc32"),
        "compressor_self_seconds": matching_self_seconds("method 'compress'"),
        "write_all_self_seconds": self_seconds("_binary.py", "_write_all"),
        "sink_write_self_seconds": self_seconds("bench_a3_regressions.py", "write"),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--engine", choices=ENGINE_CHOICES, required=True)
    parser.add_argument(
        "--write-sizes",
        type=_csv_positive_ints,
        default=(10, 1024, 65536),
        help="comma-separated write sizes (default: 10,1024,65536)",
    )
    parser.add_argument(
        "--total-write-bytes", type=_positive_int, default=8 * 1024 * 1024
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    runner_root = Path(__file__).resolve().parents[1]
    try:
        aiogzip, identity = configure_source_root(args.source_root, args.engine)
    except (RuntimeError, ValueError) as error:
        parser.error(str(error))
    fast_compress = args.engine == "zlib-ng"
    cases = []
    for write_size in args.write_sizes:
        profile = cProfile.Profile()
        started = time.perf_counter()
        sample = profile.runcall(
            asyncio.run,
            _write_once(
                aiogzip,
                write_size=write_size,
                total_bytes=args.total_write_bytes,
                method="write",
                fast_compress=fast_compress,
            ),
        )
        elapsed = time.perf_counter() - started
        rows = _profile_rows(profile)
        cases.append(
            {
                "write_size_bytes": write_size,
                "profiled_duration_seconds": elapsed,
                "sample": sample.metrics,
                "counts": _category_counts(rows),
                "cost_centers": _cost_centers(rows),
                "top_by_cumulative": sorted(
                    rows, key=lambda row: row["cumulative_seconds"], reverse=True
                )[:50],
                "top_by_self": sorted(
                    rows, key=lambda row: row["self_seconds"], reverse=True
                )[:50],
            }
        )
    document = {
        "schema_version": SCHEMA_VERSION,
        "profile": "aiogzip-2.0.0a3-small-writes",
        "command": [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]],
        "source": identity,
        "environment": collect_environment(
            args.source_root.resolve(), identity, runner_root
        ),
        "profiler": "cProfile deterministic single run per requested size",
        "profile_harness_sha256": _file_sha256(Path(__file__)),
        "cases": cases,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
