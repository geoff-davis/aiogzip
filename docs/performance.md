# Performance Guide

`aiogzip` is designed to be a high-performance, asynchronous alternative to Python's `gzip` module. This guide details its performance characteristics and provides tips for optimization.

## Benchmark Summary

All benchmarks were conducted on standard hardware using Python 3.12+.

### Text Operations (Winner: `aiogzip`)

`aiogzip` is significantly optimized for text processing, often outperforming the standard `gzip` module due to efficient buffering and async handling.

| Operation | aiogzip | gzip (sync) | Speedup |
|-----------|---------|-------------|---------|
| **Bulk Text Read/Write** | ~35 MB/s | ~14 MB/s | **2.5x Faster** |
| **JSONL Processing** | - | - | **1.8x Faster** |
| **Line Iteration** | 1.2M lines/sec | - | - |

**Why?** `aiogzip` uses optimized UTF-8 decoding strategies (using `codecs.getincrementaldecoder`) and manages buffers efficiently to minimize encoding/decoding overhead.

### Binary Operations (Tie)

For bulk binary I/O, `aiogzip` matches the throughput of standard `gzip`.

| Operation | aiogzip | gzip (sync) | Speedup |
|-----------|---------|-------------|---------|
| **Bulk Binary I/O** | ~52 MB/s | ~53 MB/s | **Equivalent** |
| **Small Chunks** | 1.7M ops/sec | 1.3M ops/sec | **1.3x Faster** |

### Concurrency (Winner: `aiogzip`)

When processing multiple files, especially where I/O latency (disk/network) is involved, `aiogzip` shines by not blocking the event loop.

- **Concurrent Processing**: **1.5x Faster** (simulated I/O latency).
- Allows the main thread to remain responsive (e.g., for a web server) while processing heavy compression tasks.

## Optimization Tips

### 1. Choose the Right Chunk Size

The default `chunk_size` is 64KB.
- **Increase it** (e.g., `128*1024` or `1024*1024`) for large file throughput if you have memory to spare.
- **Decrease it** if you are memory constrained and processing massive files.

```python
# Example: Using a larger chunk size for speed
async with AsyncGzipBinaryFile("large.gz", "rb", chunk_size=1024*1024) as f:
    ...
```

### 2. Use `read(-1)` Carefully

Reading the entire file into memory (`read(-1)`) is the fastest way to process data if it fits in RAM. `aiogzip` optimizes this by reading chunks and joining them at the end.

However, for multi-gigabyte files, always prefer **streaming** (line-by-line or fixed-size reads) to avoid OOM (Out of Memory) crashes.

### 3. Text vs. Binary

- If you need text, use `AsyncGzipTextFile` (or `mode="rt"/"wt"`). It handles decoding more efficiently than you can typically do manually in Python loop.
- If you just need to move bytes (e.g., upload to S3), use `AsyncGzipBinaryFile`.

### 4. Buffer Management

`aiogzip` maintains an internal buffer.
- **Binary Mode**: Uses an efficient offset-pointer strategy to avoid expensive memory copies (`del buffer[:n]`) when reading small chunks.
- **Text Mode**: Buffers decoded text to handle split multi-byte characters and split newlines correctly.
