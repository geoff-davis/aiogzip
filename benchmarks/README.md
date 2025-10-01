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
- Text I/O operations
- Flush operations (100 flushes)
- Line-by-line reading with `readline()` (1000 lines)

### 2. 💾 Memory Benchmarks (`bench_memory.py`)
Memory usage and efficiency:
- Memory consumption during 5MB file operations
- Memory overhead ratios (requires `psutil`)
- Memory efficiency status (OK if < 5.0x ratio)

### 3. ⚡ Concurrency Benchmarks (`bench_concurrency.py`)
Async concurrency benefits:
- Concurrent file operations (50 files)
- Comparison: async concurrent vs sync sequential
- Real-world async performance gains

### 4. 🗜️ Compression Benchmarks (`bench_compression.py`)
Compression analysis:
- Random data (incompressible baseline)
- Highly compressible data (repetitive patterns)
- Text data compression
- Compression ratios vs standard gzip

### 5. 🌍 Real-World Scenarios (`bench_scenarios.py`)
Practical use cases:
- JSONL processing (write → read → parse)
- Complete workflows with realistic data
- End-to-end performance testing

### 6. 🛡️ Error Handling (`bench_errors.py`)
Robustness and error recovery:
- Invalid operation detection
- Corrupted data handling
- Edge case performance
- Error handling overhead

### 7. 🔬 Micro-Benchmarks (`bench_micro.py`)
Fine-grained performance measurements:
- read(-1) on 1MB files (100 iterations)
- Line iteration efficiency (10K lines)
- readline() loop performance (10K lines)
- Small write operations (1000 x 120 bytes)

## Running Benchmarks

### Command Line Options

```bash
uv run python benchmarks/run_benchmarks.py [OPTIONS]

Options:
  --all                 Run all benchmark categories
  --category, -c CAT    Run specific categories (comma-separated)
  --quick              Run quick benchmarks (io, compression)
  --size N             Data size in MB (default: 1)
  --output, -o FILE    Save results to JSON file
```

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
Binary I/O (10-byte chunks): 0.060s
  aiogzip_write: 0.058s
  aiogzip_read: 0.002s
  gzip_write: 0.075s
  gzip_read: 0.001s
  speedup: 1.27x faster
```

### Interpreting Results

- **Local SSD**: Async benefits minimal due to fast I/O
- **Network Storage**: Async shows significant advantages
- **Concurrent Workloads**: Best performance with multiple files
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

3. Register in `run_benchmarks.py` CATEGORIES dict
4. Update documentation

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
