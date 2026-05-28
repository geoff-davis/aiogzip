# Performance Guide

`aiogzip` is designed to be a high-performance, asynchronous alternative to Python's `gzip` module. This guide details its performance characteristics and provides tips for optimization.

## Benchmark Summary

All benchmarks were conducted on standard hardware using Python 3.12+.

### Text Operations (Winner: `aiogzip`)

`aiogzip` is significantly optimized for text processing, often outperforming the standard `gzip` module due to efficient buffering and async handling.

| Operation | aiogzip | gzip (sync) | Speedup |
|-----------|---------|-------------|---------|
| **Bulk Text Read/Write** | ~37 MB/s | ~13 MB/s | **~2.9x Faster** |
| **JSONL Processing** | - | - | **~1.8x Faster** |
| **Line Iteration** | ~1.35M lines/sec | - | - |

**Why?** `aiogzip` uses optimized UTF-8 decoding strategies (using `codecs.getincrementaldecoder`) and manages buffers efficiently to minimize encoding/decoding overhead.

### Binary Operations (Tie)

For bulk binary I/O, `aiogzip` matches the throughput of standard `gzip`.

| Operation | aiogzip | gzip (sync) | Result |
|-----------|---------|-------------|--------|
| **Bulk Binary I/O** | ~61 MB/s | ~62 MB/s | **Equivalent** |
| **Tiny (10-byte) chunk writes** | ~1.6M ops/sec | ~3.3M ops/sec | **Slower** |

The async write path adds a small per-call cost, so writing in *very* small pieces is slower than synchronous `gzip` — batch writes (or use a larger working buffer) when throughput matters. Bulk reads are fast: a full `read(-1)` of compressible data runs at several hundred MB/s.

### Concurrency (Winner: `aiogzip`)

When processing multiple files, especially where I/O latency (disk/network) is involved, `aiogzip` shines by not blocking the event loop.

- **Concurrent I/O (latency-bound)**: up to **~6x faster** than sequential synchronous processing when each file incurs I/O latency.
- **Mixed read/write workload**: **~1.5x faster**.
- CPU-bound `zlib` work above a 256 KiB chunk is offloaded to a thread, so multiple streams compress/decompress in parallel instead of serializing on the loop.
- Allows the main thread to remain responsive (e.g., for a web server) while processing heavy compression tasks.

## Optimization Tips

### 1. Choose the Right Chunk Size

The default `chunk_size` is 256 KiB. Values must be positive and no larger than
128 MiB, which prevents accidental huge allocations from unsanitized input.

- **Increase it** (e.g., `512*1024` or `1024*1024`) for large-file throughput if you have memory to spare.
- **Decrease it** (e.g., `64*1024`) if you are memory constrained and keeping many files open at once.
- The default also sits at the threshold above which CPU-bound `zlib` work is offloaded to a thread, so the default already benefits from decompression offload.
- If you push chunk sizes into the multi-megabyte range, budget the extra memory per open file to avoid accidental OOMs.

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

### 4. Tune JSONL Reads Explicitly

For gzipped JSONL, prefer text mode and tell the reader exactly what newline
format to expect:

```python
import json
from aiogzip import AsyncGzipTextFile

async with AsyncGzipTextFile(
    "events.jsonl.gz",
    "rt",
    newline="\n",
    chunk_size=512 * 1024,
) as f:
    async for line in f:
        record = json.loads(line)
```

Why this is faster:

- `newline="\n"` avoids universal-newline detection and translation overhead.
- Larger `chunk_size` values reduce the number of async reads and line-scanning passes.
- For JSONL workloads, `AsyncGzipTextFile` is typically faster than iterating
  bytes from `AsyncGzipBinaryFile` and calling `json.loads()` on each line.

In local measurements on gzipped JSONL reads, `newline="\n"` plus a larger
chunk size was materially faster than the default text-mode configuration.

### 5. Buffer Management

`aiogzip` maintains an internal buffer.

- **Binary Mode**: Uses an efficient offset-pointer strategy to avoid expensive memory copies (`del buffer[:n]`) when reading small chunks.
- **Text Mode**: Buffers decoded text to handle split multi-byte characters and split newlines correctly.
- **Non-seekable `fileobj` Inputs**: Retains a bounded compressed-input rewind cache so backward seeks can replay the stream. The default cap is 128 MiB; lower `max_rewind_cache_size` for memory-sensitive streaming, or set it to `None` only when unbounded rewind support is acceptable.
