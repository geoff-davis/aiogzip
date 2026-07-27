#!/usr/bin/env python3
"""Render the auditable 2.0.0a2 pre-change benchmark record."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "plans" / "benchmarks" / "data"
OUTPUT = ROOT / "plans" / "benchmarks" / "v2.0.0a1-regression-baseline.md"
FILES = (
    "v1.11.0-a2-comparable-stdlib.json",
    "v1.11.0-a2-comparable-zlib-ng.json",
    "v2.0.0a1-regression-stdlib.json",
    "v2.0.0a1-regression-zlib-ng.json",
    "main-pre-a2-regression-stdlib.json",
    "main-pre-a2-regression-zlib-ng.json",
)
LABELS = {
    "v1.11.0-a2-comparable-stdlib.json": "v1.11.0 / stdlib",
    "v1.11.0-a2-comparable-zlib-ng.json": "v1.11.0 / zlib-ng",
    "v2.0.0a1-regression-stdlib.json": "v2.0.0a1 / stdlib",
    "v2.0.0a1-regression-zlib-ng.json": "v2.0.0a1 / zlib-ng",
    "main-pre-a2-regression-stdlib.json": "main pre-a2 / stdlib",
    "main-pre-a2-regression-zlib-ng.json": "main pre-a2 / zlib-ng",
}


def _load() -> dict[str, dict[str, Any]]:
    return {
        name: json.loads((DATA_DIR / name).read_text(encoding="utf-8"))
        for name in FILES
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _cell(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.9g}"
    if isinstance(value, (list, dict)):
        value = json.dumps(value, separators=(",", ":"), sort_keys=True)
    return str(value).replace("|", r"\|").replace("\n", " ")


def _table(headers: tuple[str, ...], rows: list[tuple[Any, ...]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend(
        "| " + " | ".join(_cell(value) for value in row) + " |" for row in rows
    )
    return lines


def _result(data: dict[str, Any], name: str) -> dict[str, Any]:
    return next(result for result in data["results"] if result["name"] == name)


def _ratio(numerator: float, denominator: float) -> str:
    return f"{numerator / denominator:.3f}x"


def _commands() -> list[str]:
    common = (
        "--environment-label "
        '"Apple M3 MacBook Air (provisional; rerun on Framework Desktop)" '
        "--repeat 5"
    )
    commands = [
        (
            "AIOGZIP_ENGINE=stdlib uv run --frozen python "
            "benchmarks/run_benchmarks.py "
            "--category io,scenarios,concurrency,streaming,regressions "
            "--regression-profile release --regression-mode all --size 8 "
            "--source-root /tmp/aiogzip-v1.11.0-regression "
            f"{common} --output "
            "plans/benchmarks/data/v1.11.0-a2-comparable-stdlib.json"
        ),
        (
            "AIOGZIP_ENGINE=zlib-ng uv run --frozen python "
            "benchmarks/run_benchmarks.py "
            "--category io,scenarios,concurrency,streaming,regressions "
            "--regression-profile release --regression-mode all --size 8 "
            "--source-root /tmp/aiogzip-v1.11.0-regression "
            f"{common} --output "
            "plans/benchmarks/data/v1.11.0-a2-comparable-zlib-ng.json"
        ),
    ]
    for source, stem in (
        ("/tmp/aiogzip-v2.0.0a1-regression", "v2.0.0a1-regression"),
        ("/tmp/aiogzip-main-pre-a2-regression", "main-pre-a2-regression"),
    ):
        for engine in ("stdlib", "zlib-ng"):
            commands.append(
                f"AIOGZIP_ENGINE={engine} uv run --frozen python "
                "benchmarks/run_benchmarks.py --category regressions "
                "--regression-profile release --regression-mode all "
                f"--source-root {source} {common} --output "
                f"plans/benchmarks/data/{stem}-{engine}.json"
            )
    return commands


def render(records: dict[str, dict[str, Any]]) -> str:
    first = records[FILES[0]]
    environment = first["environment"]
    lines = [
        "# v2.0.0a1 Regression Baseline for the 2.0.0a2 Repair",
        "",
        "> [!WARNING]",
        "> These measurements were captured on an Apple M3 MacBook Air and are "
        "**provisional**.",
        "> The release gates remain incomplete until the identical committed "
        "harness is rerun on the Framework Desktop used for the published "
        "GitHub benchmark numbers.",
        "",
        "This record locks the historical and pre-change inputs for the "
        "`2.0.0a2` decoder repair. The M3 results are valid for local "
        "algorithmic comparisons, but absolute timing values are not release "
        "reference values.",
        "",
        "## Provenance",
        "",
    ]

    provenance_rows: list[tuple[Any, ...]] = []
    for filename, data in records.items():
        env = data["environment"]
        skipped = sum(
            result["metrics"].get("status") == "skipped" for result in data["results"]
        )
        provenance_rows.append(
            (
                LABELS[filename],
                env["target_commit"],
                env["target_describe"],
                env["source_root"],
                env["forced_engine"],
                len(data["results"]),
                skipped,
                _sha256(DATA_DIR / filename),
            )
        )
    lines.extend(
        _table(
            (
                "Record",
                "Target commit",
                "Describe",
                "Resolved worktree",
                "Engine",
                "Results",
                "Skips",
                "JSON SHA-256",
            ),
            provenance_rows,
        )
    )
    lines.extend(
        [
            "",
            f"- Harness commit: `{environment['runner_commit']}`",
            "- Harness file: `benchmarks/bench_codec_regressions.py`",
            f"- Harness SHA-256: `{environment['regression_harness_sha256']}`",
            "- Worktree command paths used `/tmp/...`; macOS resolves those "
            "paths to `/private/tmp/...`, as recorded above.",
            "",
            "## Environment",
            "",
            "Hardware was a MacBook Air `Mac15,12` / `MXCV3LL/A` with an Apple "
            "M3, 8 cores (4 performance and 4 efficiency), and 16 GiB RAM. "
            "The temporary directory and worktrees were on the internal APFS "
            "data volume. Serial numbers and host identifiers are deliberately "
            "excluded.",
            "",
        ]
    )
    environment_rows = [
        ("Environment label", environment["environment_label"]),
        ("Python implementation", environment["python_implementation"]),
        ("Python version", environment["python_version"]),
        ("Python executable", environment["python_executable"]),
        ("Platform", environment["platform"]),
        ("OS / release", f"{environment['os_name']} {environment['os_release']}"),
        ("Kernel", environment["kernel_version"]),
        (
            "Architecture / processor",
            f"{environment['architecture']} / {environment['processor']}",
        ),
        ("libc", environment["libc"]),
        ("CPU count", environment["cpu_count"]),
        ("RAM bytes", environment["ram_bytes"]),
        ("Temporary root", environment["filesystem_temp_root"]),
        ("Temporary filesystem", "internal APFS data volume"),
        (
            "zlib compile / runtime",
            f"{environment['zlib_compile_version']} / {environment['zlib_runtime_version']}",
        ),
        ("zlib-ng package", environment["zlib_ng_package_version"]),
        ("uv", environment["uv_version"]),
        ("CPU affinity", environment["cpu_affinity"]),
        ("CPU governor", environment["cpu_governor"]),
        ("CPU boost", environment["cpu_boost"]),
        (
            "GC enabled / thresholds",
            f"{environment['garbage_collection_enabled']} / {environment['garbage_collection_thresholds']}",
        ),
    ]
    lines.extend(_table(("Property", "Value"), environment_rows))
    lines.extend(["", "Per-run material state:", ""])
    state_rows = []
    for filename, data in records.items():
        env = data["environment"]
        state_rows.append(
            (
                LABELS[filename],
                datetime.fromtimestamp(data["timestamp"], UTC).isoformat(),
                env["system_load"],
                env["uv_lock_sha256"],
                env["active_engines"],
            )
        )
    lines.extend(
        _table(
            (
                "Record",
                "Started (UTC)",
                "System load",
                "Target lock SHA-256",
                "Active engines",
            ),
            state_rows,
        )
    )

    lines.extend(
        [
            "",
            "## Method",
            "",
            "- Profile: `release`; modes: `throughput`, `memory`, and `ticker`.",
            "- Repeats: five. There is no separate warm-up run. Each repeat "
            "constructs and tears down a fresh benchmark instance.",
            "- Timing uses `time.perf_counter()`. Correctness assertions and "
            "fixture construction are outside timed regions where the case "
            "permits it.",
            "- GC remains enabled with the CPython default thresholds "
            "`(700, 10, 10)`; no collection policy is changed by the runner.",
            "- Payloads are deterministic SHAKE-256 bytes or a fixed repeated "
            "pattern. Gzip fixtures use level 6 and `mtime=0`. Fixture creation "
            "occurs before timing and before `tracemalloc.start()`.",
            "- Peak Python allocation is the peak from `tracemalloc` while "
            "advancing the decoder operation. It excludes fixture construction "
            "and is not process RSS.",
            "- The ticker repeatedly performs `await asyncio.sleep(0)` while "
            "the async decode runs. The table reports quantiles and maximum "
            "intervals between ticker observations plus the no-work baseline.",
            "- Every decode case checks byte count and SHA-256. Compression "
            "cases decompress their output and check it against the source "
            "digest. Unsupported v1.11 codec cases are explicit skips.",
            "",
            "## Exact Commands",
            "",
            "```bash",
            "\n".join(_commands()),
            "```",
            "",
            "## Fixture and Output Audit",
            "",
        ]
    )

    audit_rows: list[tuple[Any, ...]] = []
    seen_audit: set[tuple[Any, ...]] = set()
    for filename, data in records.items():
        for result in data["results"]:
            metrics = result["metrics"]
            if "fixture_sha256" not in metrics:
                continue
            row = (
                LABELS[filename],
                result["name"],
                metrics.get("fixture_bytes"),
                metrics.get("fixture_sha256"),
                metrics.get("compressed_bytes"),
                metrics.get("compressed_sha256"),
                metrics.get("output_bytes"),
                metrics.get("output_sha256"),
            )
            if row not in seen_audit:
                seen_audit.add(row)
                audit_rows.append(row)
    lines.extend(
        _table(
            (
                "Record",
                "Case",
                "Fixture bytes",
                "Fixture SHA-256",
                "Compressed bytes",
                "Compressed SHA-256",
                "Output bytes",
                "Output SHA-256",
            ),
            audit_rows,
        )
    )

    lines.extend(["", "## Peak Python Memory", ""])
    memory_rows = []
    for filename, data in records.items():
        for result in data["results"]:
            metrics = result["metrics"]
            if "peak_python_bytes" in metrics:
                memory_rows.append(
                    (
                        LABELS[filename],
                        result["name"],
                        metrics["peak_python_bytes"],
                        metrics.get("fixture_bytes"),
                        result["duration"],
                    )
                )
    lines.extend(
        _table(
            ("Record", "Case", "Peak bytes", "Fixture bytes", "Median seconds"),
            memory_rows,
        )
    )

    lines.extend(["", "## Event-Loop Ticker", ""])
    ticker_rows = []
    for filename, data in records.items():
        for result in data["results"]:
            metrics = result["metrics"]
            if "ticker_gap_max_seconds" in metrics:
                ticker_rows.append(
                    (
                        LABELS[filename],
                        result["name"],
                        metrics.get("ticker_count"),
                        metrics.get("ticker_gap_p50_seconds"),
                        metrics.get("ticker_gap_p95_seconds"),
                        metrics.get("ticker_gap_p99_seconds"),
                        metrics["ticker_gap_max_seconds"],
                        metrics.get("first_output_seconds"),
                    )
                )
    lines.extend(
        _table(
            (
                "Record",
                "Case",
                "Ticks",
                "p50 gap s",
                "p95 gap s",
                "p99 gap s",
                "Max gap s",
                "First output s",
            ),
            ticker_rows,
        )
    )

    lines.extend(["", "## Preliminary Comparisons", ""])
    comparison_rows = []
    for filename in FILES[2:]:
        data = records[filename]
        direct_8 = _result(
            data, "direct decode incompressible 8MiB one-feed 256K-output"
        )
        direct_64 = _result(
            data, "direct decode incompressible 64MiB one-feed 256K-output"
        )
        chunked_64 = _result(
            data, "direct decode incompressible 64MiB 256K-feeds 256K-output"
        )
        comparison_rows.append(
            (
                LABELS[filename],
                direct_8["duration"],
                direct_64["duration"],
                _ratio(direct_64["duration"], direct_8["duration"]),
                _ratio(direct_64["duration"], chunked_64["duration"]),
            )
        )
    lines.extend(
        _table(
            (
                "Record",
                "8 MiB one-feed s",
                "64 MiB one-feed s",
                "64/8 scaling",
                "64 MiB one/chunked",
            ),
            comparison_rows,
        )
    )
    lines.extend(["", "Historical high-level medians and alpha/v1 ratios:", ""])
    high_level_names = (
        "decompress_chunks 64K-in 64K-out",
        "decompress_chunks 512K-in 256K-out",
        "compress_chunks 64K-in 64K-out",
        "compress_chunks 512K-in 256K-out",
    )
    high_level_rows = []
    for engine in ("stdlib", "zlib-ng"):
        v1 = records[f"v1.11.0-a2-comparable-{engine}.json"]
        alpha = records[f"v2.0.0a1-regression-{engine}.json"]
        for name in high_level_names:
            old = _result(v1, name)["duration"]
            new = _result(alpha, name)["duration"]
            high_level_rows.append((engine, name, old, new, _ratio(new, old)))
    lines.extend(
        _table(
            ("Engine", "Case", "v1.11 median s", "a1 median s", "a1/v1"),
            high_level_rows,
        )
    )
    lines.extend(
        [
            "",
            "These comparisons are diagnostic only. They do not satisfy the "
            "Framework Desktop release gates.",
            "",
            "## Run Disposition",
            "",
            "The six files listed in Provenance are the final accepted captures. "
            "Earlier same-session smoke and pre-correction runs were discarded "
            "before this baseline commit because the runner did not yet record "
            "header wire hashes, GC policy, sample extrema, or the explicit M3 "
            "environment label. Both historical and pre-change targets were "
            "recaptured after the harness correction. No accepted run was "
            "interrupted, edited, or substituted. There were no invalid final "
            "runs. The v1.11 files contain explicit zero-duration skip records "
            "for API cases that do not exist in that release.",
            "",
            "## Complete Timing Samples",
            "",
            "Durations are seconds. `MAD` is median absolute deviation. Metrics "
            "are the representative median run's structured values.",
            "",
        ]
    )
    for filename, data in records.items():
        lines.extend([f"### {LABELS[filename]}", ""])
        timing_rows = []
        for result in data["results"]:
            metrics = result["metrics"]
            timing_rows.append(
                (
                    result["name"],
                    metrics.get("status", "measured"),
                    result["duration_samples"],
                    result["duration"],
                    result["median_absolute_deviation"],
                    result["duration_min"],
                    result["duration_max"],
                    metrics,
                )
            )
        lines.extend(
            _table(
                (
                    "Case",
                    "Status",
                    "Samples",
                    "Median",
                    "MAD",
                    "Min",
                    "Max",
                    "Metrics",
                ),
                timing_rows,
            )
        )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    OUTPUT.write_text(render(_load()), encoding="utf-8")


if __name__ == "__main__":
    main()
