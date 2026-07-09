# aiogzip ⚡️

**An asynchronous library for reading and writing gzip-compressed files.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![PyPI version](https://img.shields.io/pypi/v/aiogzip.svg)](https://pypi.org/project/aiogzip/)
[![Python versions](https://img.shields.io/pypi/pyversions/aiogzip.svg)](https://pypi.org/project/aiogzip/)
[![Tests](https://github.com/geoff-davis/aiogzip/workflows/Python%20CI/badge.svg)](https://github.com/geoff-davis/aiogzip/actions)
[![Coverage](https://raw.githubusercontent.com/geoff-davis/aiogzip/python-coverage-comment-action-data/badge.svg)](https://github.com/geoff-davis/aiogzip/tree/python-coverage-comment-action-data)
[![Documentation](https://img.shields.io/badge/docs-mkdocs-blue)](https://geoff-davis.github.io/aiogzip/)

`aiogzip` provides a fast, simple, and asyncio-native interface for handling `.gz` files, making it a useful complement to Python's built-in `gzip` module for asynchronous applications.

**🚀 [Read the Documentation](https://geoff-davis.github.io/aiogzip/)**

## Features

- **Truly Asynchronous**: Built with `asyncio` and `aiofiles`.
- **High-Performance**: Optimized buffer handling for fast I/O.
- **Drop-in Replacement**: Mimics `gzip.open()` with async `seek`, `tell`, `peek`, and `readinto` support; verified against tarfile-style access patterns and aiocsv workflows.
- **Reproducible Archives**: Control gzip `mtime` and embedded filenames.
- **Type-Safe**: Distinct `AsyncGzipBinaryFile` and `AsyncGzipTextFile`.
- **`aiocsv` Ready**: Seamless integration for CSV pipelines.
- **Optional faster codec**: Install `aiogzip[fast]` to use [`zlib-ng`](https://pypi.org/project/zlib-ng/) for decompression automatically (byte-identical output) and, with `fast_compress=True`, for compression.
- **Predictable Performance**: Backward seeks rewind the stream and re-decompress data (same as `gzip.GzipFile`), so treat random access as O(n) and prefer forward-only patterns when possible.

### Append mode and large files

- **Append mode (`"ab"`, `"at"`) writes a new gzip member**. The file ends up as two (or more) concatenated gzip members. Every standards-compliant reader — including `aiogzip`, `gzip.open()`, and command-line `gunzip` — transparently concatenates the output, but each additional open writes a new member rather than extending the existing deflate stream.
- **Backward seeks restart decompression** from the beginning of the file, so forward-only access is much faster than mixed-direction access.
- **Non-seekable input streams use a bounded rewind cache**. By default, up to 128 MiB of compressed input is retained so backward seeks can replay the stream; pass `max_rewind_cache_size=<bytes>` to tune this, or `None` to allow an unbounded cache.
- **Writes past 4 GiB of uncompressed data** produce a gzip trailer whose `ISIZE` field wraps to `size & 0xFFFFFFFF` (this matches the gzip format spec and `gzip.open()`). Pass `strict_size=True` to refuse writes that would exceed the limit instead.
- **Guard against decompression bombs** by passing `max_decompressed_size=<bytes>` when reading untrusted files. The decompressor limits each inflate call to the remaining allowance (plus one byte for overflow detection) and raises `OSError` without materializing the payload beyond that bound.
- **Use one file object per task.** An open `aiogzip` file is not safe for concurrent use by multiple `asyncio` tasks — its internal buffers and decoder/compressor state are mutated without locking, the same contract as standard-library file objects. Give each task its own file object, or serialize access behind your own lock.
- **Reopen after cancelling CPU-heavy reads.** If a task is cancelled while a large decompression call is running in the executor, the open reader becomes unusable because the worker thread cannot be stopped safely. Later reads and seeks raise `OSError`; close that handle and open a new one.

## Quickstart

```bash
pip install aiogzip

# Optional: faster compression/decompression via zlib-ng
pip install "aiogzip[fast]"
```

When `aiogzip[fast]` is installed, decompression transparently uses `zlib-ng`
(its output is byte-identical to stdlib `zlib`). Compression stays on stdlib by
default so produced `.gz` bytes are unchanged; opt in per file with
`fast_compress=True`. Set `AIOGZIP_ENGINE=stdlib` to force stdlib regardless of
what is installed.

```python
import asyncio
from aiogzip import AsyncGzipFile

async def main():
    # Write
    async with AsyncGzipFile("file.gz", "wb") as f:
        await f.write(b"Hello, async world!")

    # Read
    async with AsyncGzipFile("file.gz", "rb") as f:
        print(await f.read())

    # Deterministic metadata
    async with AsyncGzipFile(
        "dataset.gz", "wb", mtime=0, original_filename="dataset.csv"
    ) as f:
        await f.write(b"stable bytes")

asyncio.run(main())
```

> **Default compression level.** As a drop-in replacement, `aiogzip` matches
> `gzip.open()`'s API but **defaults to `compresslevel=6`** (the zlib default — a
> better speed/ratio tradeoff), whereas `gzip.open()` defaults to `9`. Pass
> `compresslevel=9` for byte-size parity with stdlib defaults:
>
> ```python
> async with AsyncGzipFile("file.gz", "wb", compresslevel=9) as f:
>     await f.write(b"...")  # same compression level as gzip.open() defaults
> ```

If you cannot use `async with`, open and close explicitly with try/finally:

```python
f = AsyncGzipFile("file.gz", "rb")
await f.open()
try:
    data = await f.read()
finally:
    await f.close()
```

## Performance

- **Text I/O**: Often ~2-3x faster than standard `gzip` in bulk text workflows.
- **Binary I/O**: Near parity with `gzip` for bulk writes, with fast bulk reads (a full `read(-1)` of compressible data runs at several hundred MB/s); can be slower for very small chunk sizes.
- **Concurrency**: CPU-heavy `zlib` compress/decompress calls run in the default executor above a 256 KiB threshold, so multiple gzip streams on the same event loop compress and decompress in parallel instead of serializing on the loop thread. The repo's concurrent-I/O benchmark runs ~4x faster since this landed in 1.4.0; single-stream throughput stays at parity.
- **Line Iteration**: For the single-character newline modes (`None`, `"\n"`, `"\r"`), lines are bulk-split per chunk and served from a batch, making `async for`/`readline()` roughly ~1.2–1.3x faster (~4M lines/sec).
- **Optional faster codec**: With `aiogzip[fast]` installed, decompression uses `zlib-ng` automatically (~1.2-2x on typical data, up to ~7-10x on highly compressible bulk reads; byte-identical output), and `fast_compress=True` gives ~1.2-1.5x compression. See the [Performance Guide](https://geoff-davis.github.io/aiogzip/performance/).
- **Memory**: Optimized buffer management for stable memory usage.
- **JSONL**: For large gzipped JSONL files, prefer `AsyncGzipTextFile(..., newline="\n", chunk_size=512 * 1024)` to reduce line-iteration overhead.

See the [Performance Guide](https://geoff-davis.github.io/aiogzip/performance/) for detailed benchmarks.

## Python version support

`aiogzip` 1.x supports Python 3.8-3.14. **The 1.x line is the last to support
Python 3.8 and 3.9** (both past end-of-life); `aiogzip` 2.0 will require
Python 3.11+. Older interpreters will continue to resolve the latest 1.x
release from PyPI automatically.

## Contributing

See the [Contributing Guide](https://geoff-davis.github.io/aiogzip/contributing/) for development instructions.
