# aiogzip Benchmark Suite

A comprehensive, modular benchmark suite for testing aiogzip performance across various scenarios.

## Quick Start

```bash
# Run quick benchmarks (I/O and compression)
uv run python benchmarks/run_benchmarks.py --quick

# Run all benchmarks
uv run python benchmarks/run_benchmarks.py --all

# Run specific categories
uv run python benchmarks/run_benchmarks.py --category io,memory

# Compare results
uv run python benchmarks/bench_compare.py baseline.json current.json
```

## Benchmark Categories

### 1. 🚀 I/O Benchmarks (`bench_io.py`)

Core read/write performance:

- Binary I/O with small (10-byte) chunks
- Separate bulk text read and write comparisons
- Default universal-newline bulk text reads, including the LF-only fast path
- Default and tuned JSONL line iteration against the exact same gzip fixture
- Flush operations (100 flushes)
- Read-all isolated: `read(-1)` timed on its own (write excluded) on compressible data
- Text large reads: a single large `read(size)` and a single long-line `readline()` (guards against O(n^2) accumulation regressions)

### 2. 💾 Memory Benchmarks (`bench_memory.py`)

Memory usage and efficiency:

- Memory consumption during 5MB file operations
- Memory overhead ratios (requires `psutil`)
- Memory efficiency status (OK if < 5.0x ratio)

### 3. ⚡ Concurrency Benchmarks (`bench_concurrency.py`)

Async concurrency benefits:

- Concurrent file operations (10 files, 1 MiB each)
- Comparison: async concurrent vs sync sequential
- Explicit simulated-latency and mixed-operation results

### 4. 🗜️ Compression Benchmarks (`bench_compression.py`)

Compression analysis:

- Random data (incompressible baseline)
- Highly compressible data (repetitive patterns)
- Text data compression
- Compression ratios vs standard gzip

### 5. 🌍 Real-World Scenarios (`bench_scenarios.py`)

Practical use cases:

- Read-only JSONL parsing from one identical fixture
- Bounded-batch JSONL parsing with `readlines(1 MiB)`
- JSON decoding and record validation with realistic data

### 6. 🛡️ Error Handling (`bench_errors.py`)

Robustness and error recovery:

- Invalid operation detection
- Corrupted data handling
- Edge case performance
- Error handling overhead

### 7. 🔬 Micro-Benchmarks (`bench_micro.py`)

Fine-grained performance measurements:

- read(-1) on 1MB files (100 iterations)
- Line iteration efficiency (100K lines)
- readline() loop performance (100K lines)
- Whole-file and bounded-batch readlines() performance (100K lines)
- Small write operations (1000 x 120 bytes)
- Binary readline stress case (200KB line, 17-byte chunks)

### 8. 🔄 Streaming and sans-I/O codec (`bench_streaming.py`)

- Direct synchronous `GzipEncoder` and `GzipDecoder` encode/decode
- Equivalent `gzip.compress` and `gzip.decompress` reference timings
- Async `compress_chunks` and `decompress_chunks` at representative boundaries
- Binary file reader/writer comparisons
- Highly compressible streaming and full-read peak Python memory

The direct codec cases are labeled informational. aiogzip 1.11.0 had no public
sans-I/O codec, so those absolute timings and their same-run stdlib references
do not participate in the release regression thresholds.

### 9. Decoder regression harness (`bench_codec_regressions.py`)

The `regressions` category is the auditable harness for the 2.0.0a2 repair.
It requires an explicit source checkout so historical runs cannot accidentally
import the editable package from another worktree:

```bash
AIOGZIP_ENGINE=stdlib uv run --frozen python \
  benchmarks/run_benchmarks.py \
  --category regressions \
  --regression-profile quick \
  --regression-mode throughput \
  --source-root . \
  --repeat 3 \
  --output /tmp/aiogzip-regressions.json
```

Profiles are `quick` for smoke validation and `release` for the locked 8–64
MiB scaling, scheduler, header, and allocation matrices. Measurement modes are
separate:

- `throughput`: direct one-feed/chunked scaling, historical streaming cases,
  public output bounds and engine-call counts, and header timing
- `memory`: direct-decoder and incomplete-header `tracemalloc` peaks
- `ticker`: async scheduling-gap distributions and the empty-block case
- `all`: runs the three modes sequentially while preserving each result's mode

Fixtures are generated deterministically before measurement and source items
are pre-split before timed or allocation regions. Every decode is consumed
into SHA-256 with byte-count and chunk-bound validation. JSON output records
individual duration samples, median absolute deviation, fixture hashes, source
item statistics, the resolved package file and commit, Python/OS/engine
details, the lockfile hash, and the regression-harness hash.

Use the harness from the implementation checkout while targeting detached
historical worktrees:

```bash
uv run --frozen python benchmarks/run_benchmarks.py \
  --category regressions --regression-profile release \
  --regression-mode all \
  --source-root /tmp/aiogzip-v2.0.0a1-regression \
  --repeat 5 --output /tmp/v2.0.0a1-regressions.json
```

The public codec cases are emitted as explicit skips for targets such as
`v1.11.0` that predate `GzipDecoder`; supported high-level streaming cases
still run normally.

### 10. 2.0.0a3 file-header and write harness (`bench_a3_regressions.py`)

The `a3` harness targets an explicit checkout and captures the high-level
optional-header path, concatenated-member metadata overhead, and a fixed-total
write-size curve. It retains individual samples, medians, MAD/min/max values,
fixture and output digests, source/sink counts, tracemalloc peaks, and complete
environment/source attestations:

```bash
uv run --frozen python benchmarks/bench_a3_regressions.py \
  --source-root /tmp/aiogzip-v2.0.0a2-a3 \
  --engine stdlib --repeat 5 \
  --output /tmp/v2.0.0a2-a3-stdlib.json
```

Use `--fixture-sizes-mib`, `--member-counts`, `--write-sizes`,
`--total-write-bytes`, and `--source-chunk-bytes` to select an explicitly
recorded matrix. `profile_small_writes.py` captures cProfile tables and hot-path
call counts for the diagnostic 10 B, 1 KiB, and 64 KiB write sizes. Correctness
checks and fixture construction are kept outside ordinary wall-time regions;
tracemalloc cases are labeled separately and are not used as wall-time claims.

## Running Benchmarks

### Command Line Options

```bash
uv run python benchmarks/run_benchmarks.py [OPTIONS]

Options:
  --all                 Run all benchmark categories
  --category, -c CAT    Run specific categories (comma-separated)
  --quick              Run quick benchmarks (io, compression)
  --size N             Data size in MB (default: 1)
  --repeat N           Run each category N times, report median (default: 3)
  --output, -o FILE    Save results to JSON file
  --source-root PATH   Verify and import aiogzip from PATH/src
  --regression-profile {quick,release}
                       Select the regression matrix size
  --regression-mode {throughput,memory,ticker,all}
                       Keep timing, allocation, and ticker runs distinct
  --environment-label TEXT
                       Record the benchmark machine and purpose in JSON
```

Each category runs three times by default. Reported durations are medians, and
the displayed secondary metrics come from the sample closest to that median.
Use `--repeat 1` for a faster smoke run or a larger odd count for more stable
release comparisons.

## Comparison Methodology

Comparisons with stdlib `gzip` follow these rules:

- Read benchmarks consume the exact same deterministic compressed bytes.
- Comparative writes explicitly use compression level 6 for both libraries;
  their different defaults (`aiogzip=6`, `gzip=9`) must not affect the result.
- Reads and writes are timed and reported separately unless the benchmark is
  explicitly labeled as an end-to-end workflow.
- Correctness checks run outside or alongside the timed work so a fast but
  incomplete result cannot be reported.
- Results use the same Python process, engine selection, filesystem, and data
  size. Absolute timings from different machines are not directly comparable.

An async API is not expected to beat synchronous `gzip` in every single-file
microbenchmark. Report event-loop concurrency, optional-codec throughput, and
per-call async overhead as separate effects.

## Before/After Regression Workflow

For changes to codecs, buffering, text decoding, line iteration, executor
offloading, or parser hot paths, capture a baseline before editing:

```bash
AIOGZIP_ENGINE=stdlib uv run python benchmarks/run_benchmarks.py \
  --category io,scenarios,concurrency --size 8 --repeat 5 \
  --output /tmp/aiogzip-before.json
```

Run the identical command after the change, using a different output file,
then compare the results:

```bash
AIOGZIP_ENGINE=stdlib uv run python benchmarks/run_benchmarks.py \
  --category io,scenarios,concurrency --size 8 --repeat 5 \
  --output /tmp/aiogzip-after.json

uv run python benchmarks/bench_compare.py \
  /tmp/aiogzip-before.json /tmp/aiogzip-after.json
```

Repeat without `AIOGZIP_ENGINE=stdlib` when the change can affect zlib-ng.
Record the command, environment, and any material wins or regressions in the
review or pull request.

### Usage Examples

```bash
# Quick test (I/O and compression only)
uv run python benchmarks/run_benchmarks.py --quick

# Run all benchmarks
uv run python benchmarks/run_benchmarks.py --all

# Run specific categories
uv run python benchmarks/run_benchmarks.py --category io,memory

# Test with larger data (10 MB)
uv run python benchmarks/run_benchmarks.py --all --size 10

# Save results for comparison
uv run python benchmarks/run_benchmarks.py --all --output baseline.json

# After making changes
uv run python benchmarks/run_benchmarks.py --all --output current.json

# Compare results
uv run python benchmarks/bench_compare.py baseline.json current.json
```

### Prerequisites

Core benchmarks work out of the box. For memory benchmarks, install `psutil`:

```bash
uv add psutil
```

## Understanding Results

### Performance Metrics

- **Speedup**: Ratio comparing aiogzip vs standard gzip
  - `> 1.0x`: aiogzip is faster
  - `< 1.0x`: standard gzip is faster
  - `≈ 1.0x`: Similar performance

- **Memory Ratio**: Memory increase / data size
  - `< 2.0x`: Excellent efficiency
  - `2.0-5.0x`: Good (status: OK)
  - `> 5.0x`: High memory usage (status: HIGH)

- **Operations per second**: Higher is better

### Sample Output

```
Text line iteration (tuned, identical fixture): 0.019s
  aiogzip_time: 0.0187s
  gzip_time: 0.0133s
  speedup: 1.41x slower
  lines: 73849

Read-all isolated (compressible, read-only timing): 0.003s
  aiogzip_read_best: 2.82ms
  gzip_read_best: 14.79ms
  speedup: 5.25x faster
```

These are illustrative results from the 2026-07-16 Python 3.12.12 run at
commit `ec931cd` on one zlib-ng-enabled machine, not expected values or
acceptance thresholds.

### Interpreting Results

- **Local SSD / page cache**: synchronous `gzip` often wins small single-file
  operations because it has no coroutine handoff.
- **Latency-bound storage**: async can overlap waits across independent files.
- **Concurrent workloads**: compare total completion time and event-loop
  responsiveness, not only per-file codec time.
- **Small Chunks**: Stress test for overhead measurement

## File Structure

```
benchmarks/
├── bench_common.py        # Shared infrastructure
│   ├── BenchmarkResults   # Result storage and formatting
│   ├── TempFileManager    # Temp file management
│   ├── DataGenerator      # Test data generation
│   └── BenchmarkBase      # Base class for benchmarks
├── run_benchmarks.py      # Main CLI entry point
├── bench_io.py            # I/O benchmarks
├── bench_memory.py        # Memory benchmarks
├── bench_concurrency.py   # Concurrency benchmarks
├── bench_compression.py   # Compression benchmarks
├── bench_scenarios.py     # Real-world scenarios
├── bench_errors.py        # Error handling
├── bench_micro.py         # Micro-benchmarks
├── bench_codec_regressions.py # 2.0.0a2 regression matrices
├── bench_compare.py       # Result comparison tool
└── README.md              # This file
```

## Adding New Benchmarks

1. Choose or create a category file (e.g., `bench_mycategory.py`)
2. Create a benchmark class inheriting from `BenchmarkBase`:

```python
from bench_common import BenchmarkBase
import time

class MycategoryBenchmarks(BenchmarkBase):
    async def benchmark_my_feature(self):
        """Test my feature."""
        test_data = self.data_gen.generate_binary(1)
        test_file = self.temp_mgr.get_path("test.gz")

        start = time.perf_counter()
        # ... benchmark code ...
        duration = time.perf_counter() - start

        self.add_result(
            "My feature",
            "mycategory",
            duration,
            custom_metric="value"
        )

    async def run_all(self):
        await self.benchmark_my_feature()
```

1. Register in `run_benchmarks.py` CATEGORIES dict
2. Update documentation

## Comparing Results

Use `bench_compare.py` to track performance over time:

```bash
# Establish baseline
uv run python benchmarks/run_benchmarks.py --all --output baseline.json

# Make code changes...

# Run current benchmarks
uv run python benchmarks/run_benchmarks.py --all --output current.json

# Compare
uv run python benchmarks/bench_compare.py baseline.json current.json
```

The comparison tool shows:

- Side-by-side benchmark times
- Percentage changes
- Improvements (>5% faster) marked with ✓
- Regressions (>5% slower) marked with ✗
- Overall summary statistics

## Benefits

- **Modularity**: Each category is self-contained
- **Flexibility**: Run only needed benchmarks
- **Maintainability**: Easy to add/modify benchmarks
- **Consistency**: Shared infrastructure
- **Comparison**: Track performance over time
- **Performance**: Faster iteration on specific areas
