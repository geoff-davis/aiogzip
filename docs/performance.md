# Performance Guide

`aiogzip` is designed to keep gzip file processing from blocking an asyncio
application while providing competitive codec throughput. It is not uniformly
faster than synchronous `gzip`: the result depends on the codec, access pattern,
line size, storage latency, and how much concurrency the application can use.

## Benchmark Summary

The table below is from a representative Linux x86-64 run on Python 3.12.12.
Each result is the median of five runs. Direct I/O uses 8 MiB of uncompressed
input; the concurrency case uses ten 1 MiB files plus simulated latency. Read
comparisons use the exact same deterministic gzip bytes, and write comparisons
use `compresslevel=6` for both libraries. These numbers illustrate tradeoffs
rather than promising performance on different hardware or data.

| Workload | aiogzip (stdlib) vs `gzip` | aiogzip (zlib-ng) vs `gzip` |
| --- | ---: | ---: |
| Bulk text write, level 6 | ~1.01x slower | ~1.01x faster |
| Bulk text read | ~2.01x slower | ~1.35x slower |
| Tuned JSONL line iteration | ~1.82x slower | ~1.69x slower |
| Tuned JSONL read and parse | ~1.19x slower | ~1.11x slower |
| Highly compressible bulk `read(-1)` | ~1.07x faster | ~5.57x faster |
| Ten files with simulated 10 ms latency | ~6.06x faster | ~6.09x faster |

Run the suite on the target workload before making a capacity or latency
decision:

```bash
AIOGZIP_ENGINE=stdlib uv run python benchmarks/run_benchmarks.py \
  --category io,scenarios,concurrency --size 8 --repeat 5
```

Repeat without `AIOGZIP_ENGINE=stdlib` to measure the optional zlib-ng engine.
See the repository's
[benchmark methodology](https://github.com/geoff-davis/aiogzip/tree/main/benchmarks)
for before/after comparison commands.

### Text operations

For a single warm local file, synchronous `gzip` has less per-operation
overhead. In particular, every `async for` line crosses an async-iterator
boundary, so direct line iteration can be slower even though aiogzip bulk-splits
decoded chunks internally.

That batched line path remains valuable: it made aiogzip 1.7 roughly 1.3x
faster than aiogzip 1.6's previous per-line scanning implementation. It should
not be interpreted as a 1.3x advantage over stdlib `gzip`.

For writing many small records, prefer `writelines()` over an explicit loop of
`await f.write(line)`. It combines inputs into bounded `chunk_size` batches,
reducing Python coroutine and compressor-call overhead without loading the full
iterable into memory.

### Binary operations

Bulk binary I/O with stdlib zlib is close to `gzip`; many tiny awaited calls are
slower. Whole-file reads of highly compressible input are where the optional
zlib-ng engine can produce a substantial throughput gain.

The async write path adds a per-call cost, so batch small writes when throughput
matters. A full `read(-1)` is fastest when the output comfortably fits in
memory; use incremental reads for large or untrusted data.

### Concurrency

Concurrency and event-loop responsiveness are aiogzip's primary advantages over
calling synchronous `gzip` directly inside an async application.

- A synthetic ten-file workload with 10 ms of simulated latency measured about
  6x faster than sequential synchronous processing. The gain comes from
  overlapping the delays; it is not a raw codec-speed comparison.
- A five-operation mixed read/write workload measured about 1.6-1.8x faster in
  the same run.
- CPU-bound `zlib` work above a 256 KiB chunk is offloaded to a thread, so multiple streams compress/decompress in parallel instead of serializing on the loop.
- Independent application tasks can continue while file or offloaded codec
  work is pending.

### Optional Faster Codec (`aiogzip[fast]` / zlib-ng)

Installing the optional extra pulls in [`zlib-ng`](https://pypi.org/project/zlib-ng/),
a drop-in deflate implementation that is faster than stdlib `zlib`:

```bash
pip install "aiogzip[fast]"
```

- **Decompression** uses zlib-ng automatically whenever it is installed. Its
  output is **byte-identical** to stdlib `zlib`, so this is transparent. In the
  representative run above it made aiogzip's bulk text read about 1.46x faster
  than aiogzip with stdlib zlib, and its highly compressible bulk `read(-1)`
  about 5x faster. Gains depend strongly on the data and access pattern.
- **Compression** stays on stdlib `zlib` by default, because zlib-ng's compressed
  *bytes* are not identical to stdlib's — installing the extra alone must not
  change produced `.gz` output. Opt in per file with `fast_compress=True` for
  faster compression; the output is valid gzip readable by any decompressor,
  just not byte-for-byte identical to stdlib. Measure the compression gain on
  representative input rather than assuming a fixed multiplier.

  ```python
  async with AsyncGzipBinaryFile("out.gz", "wb", fast_compress=True) as f:
      await f.write(payload)
  ```

- Set `AIOGZIP_ENGINE=stdlib` to force stdlib everywhere (e.g. for reproducible
  output or debugging). When the extra is not installed, `aiogzip` remains
  pure-Python and behaves exactly as before.

## Optimization Tips

### Async-iterable streaming benchmarks

The focused streaming benchmark compares source and output chunk sizes,
file-reader/file-writer baselines, event-loop ticker progress, and peak Python
allocations for highly compressible data. It also includes zlib-ng compression
when the optional engine is installed:

```bash
uv run python benchmarks/run_benchmarks.py \
  --category streaming --size 32 --repeat 3
```

Inputs below the 256 KiB codec-offload threshold often maximize raw throughput
for short operations but may complete inline without giving an independent
event-loop task a turn. Larger codec calls are offloaded, trading a thread hop
for event-loop responsiveness. Measure with source chunk sizes representative
of the real producer rather than selecting solely from synthetic throughput.

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
