# aiogzip ⚡️

**An asynchronous library for reading and writing gzip-compressed files.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![PyPI version](https://img.shields.io/pypi/v/aiogzip.svg)](https://pypi.org/project/aiogzip/)
[![Python 3.8-3.14](https://img.shields.io/badge/python-3.8--3.14-blue.svg)](https://www.python.org/downloads/)
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
- **Predictable Performance**: Backward seeks rewind the stream and re-decompress data (same as `gzip.GzipFile`), so treat random access as O(n) and prefer forward-only patterns when possible.

### Append mode and large files

- **Append mode (`"ab"`, `"at"`) writes a new gzip member**. The file ends up as two (or more) concatenated gzip members. Every standards-compliant reader — including `aiogzip`, `gzip.open()`, and command-line `gunzip` — transparently concatenates the output, but each additional open writes a new member rather than extending the existing deflate stream.
- **Backward seeks restart decompression** from the beginning of the file, so forward-only access is much faster than mixed-direction access.
- **Non-seekable input streams use a bounded rewind cache**. By default, up to 128 MiB of compressed input is retained so backward seeks can replay the stream; pass `max_rewind_cache_size=<bytes>` to tune this, or `None` to allow an unbounded cache.
- **Writes past 4 GiB of uncompressed data** produce a gzip trailer whose `ISIZE` field wraps to `size & 0xFFFFFFFF` (this matches the gzip format spec and `gzip.open()`). Pass `strict_size=True` to refuse writes that would exceed the limit instead.
- **Guard against decompression bombs** by passing `max_decompressed_size=<bytes>` when reading untrusted files; the decompressor aborts with `OSError` once the cap is exceeded.

## Quickstart

```bash
pip install aiogzip
```

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

asyncio.run(main())

# Deterministic metadata
async with AsyncGzipFile(
    "dataset.gz", "wb", mtime=0, original_filename="dataset.csv"
) as f:
    await f.write(b"stable bytes")
```

## Performance

- **Text I/O**: Often ~2-3x faster than standard `gzip` in bulk text workflows.
- **Binary I/O**: Typically near parity for bulk reads/writes, and can be slower for very small chunk sizes.
- **Concurrency**: CPU-heavy `zlib` compress/decompress calls run in the default executor above a 256 KiB threshold, so multiple gzip streams on the same event loop compress and decompress in parallel instead of serializing on the loop thread. The repo's concurrent-I/O benchmark runs ~4x faster on 1.4.0 than on 1.3.x as a result; single-stream throughput stays at parity.
- **Memory**: Optimized buffer management for stable memory usage.
- **JSONL**: For large gzipped JSONL files, prefer `AsyncGzipTextFile(..., newline="\n", chunk_size=512 * 1024)` to reduce line-iteration overhead.

See the [Performance Guide](https://geoff-davis.github.io/aiogzip/performance/) for detailed benchmarks.

## Contributing

See [CONTRIBUTING.md](docs/contributing.md) for development instructions.
