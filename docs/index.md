# aiogzip ⚡️

**An asynchronous library for reading and writing gzip-compressed files.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![PyPI version](https://img.shields.io/pypi/v/aiogzip.svg)](https://pypi.org/project/aiogzip/)
![PyPI - Python Version](https://img.shields.io/pypi/pyversions/aiogzip.svg)
[![Tests](https://github.com/geoff-davis/aiogzip/workflows/Python%20CI/badge.svg)](https://github.com/geoff-davis/aiogzip/actions)

`aiogzip` provides a fast, simple, and asyncio-native interface for handling `.gz` files, making it a useful complement to Python's built-in `gzip` module for asynchronous applications.

It is designed for high-performance I/O operations, especially for text-based data pipelines, and integrates seamlessly with other `async` libraries like `aiocsv`.

## Features

- **Truly Asynchronous**: Built with `asyncio` and `aiofiles` for non-blocking file I/O.
- **High-Performance Text Processing**: Significantly faster than the standard `gzip` library for text and JSONL file operations.
- **Simple API**: Mimics the interface of `gzip.open()`, making it easy to adopt.
- **Separate Binary and Text Modes**: `AsyncGzipBinaryFile` and `AsyncGzipTextFile` provide clear, type-safe handling of data.
- **Excellent Compression Quality**: Achieves compression ratios nearly identical to the standard `gzip` module.
- **`aiocsv` Integration**: Read and write compressed CSV files effortlessly.
- **Optional Faster Codec**: Install `aiogzip[fast]` to use [`zlib-ng`](https://pypi.org/project/zlib-ng/) for faster decompression automatically (byte-identical output) and, with `fast_compress=True`, for compression. See the [Performance Guide](performance.md).

---

## Quick Links

- [Installation & Usage](examples.md)
- [Focused Recipes](recipes.md)
- [Async-iterable Streaming](streaming.md)
- [Performance Benchmarks](performance.md)
- [API Reference](api.md)
- [Contributing](contributing.md)

---

## Quickstart

Using `aiogzip` is as simple as using the standard `gzip` module, but with `async`/`await`.

### Writing to a Compressed File

```python
import asyncio

import aiogzip

async def main():
    # Write binary data
    async with aiogzip.open("file.gz", "wb") as f:
        await f.write(b"Hello, async world!")

    # Write text data
    async with aiogzip.open("file.txt.gz", "wt") as f:
        await f.write("This is a text file.")

asyncio.run(main())
```

### Reading from a Compressed File

```python
import asyncio

import aiogzip

async def main():
    # Read the entire file
    async with aiogzip.open("file.gz", "rb") as f:
        content = await f.read()
        print(content)

    # Iterate over lines in a text file
    async with aiogzip.open("file.txt.gz", "rt") as f:
        async for line in f:
            print(line.strip())

asyncio.run(main())
```

### Manual lifecycle (`open()` / `close()`)

`async with` is the recommended way to use a file, but when a `with` block is
impractical you can manage the lifecycle imperatively with `open()` and
`close()`. Always pair them with `try`/`finally` so the file is closed even if
an error occurs:

```python
f = aiogzip.open("file.txt.gz", "rt")
await f.open()        # initializes the stream and returns the file; __aenter__ calls this
try:
    async for line in f:
        print(line.strip())
finally:
    await f.close()
```

`open()` returns the file object. Calling it on an already-open file raises
`ValueError`, and a closed instance cannot be reopened (it raises `ValueError`,
matching standard `io` objects) — create a new instance instead. Operations
before `open()` raise `ValueError` ("File not opened. Call await open() or
use async with.").

## Compatibility

`aiogzip` provides comprehensive compatibility with the standard `gzip` module's `GzipFile` API, including:

- ✅ `seek()` and `tell()` methods for stream navigation (with the same performance characteristics as `gzip.GzipFile`)
- ✅ `peek()` and `readinto()` for advanced reading patterns
- ✅ Reading and writing gzip headers and metadata (e.g., `mtime`, `original_filename`)
- ✅ Text and binary mode operations with proper encoding/decoding
- ✅ Full compatibility with `tarfile` for reading `.tar.gz` archives
- ✅ Seamless integration with `aiocsv` for CSV processing

> **Default compression level.** `aiogzip` defaults to `compresslevel=6` (the
> zlib default — a better speed/ratio tradeoff), whereas `gzip.open()` defaults
> to `9`. The two therefore produce different `.gz` sizes by default. For
> byte-size parity with stdlib defaults, pass `compresslevel=9`:
>
> ```python
> async with aiogzip.open("file.gz", "wb", compresslevel=9) as f:
>     await f.write(b"...")
> ```

For `AsyncGzipTextFile`, `tell()` returns a plain non-negative byte offset when the stream is at a clean boundary, and an opaque cookie value (a negative integer encoding the decoder state) when it is mid-character, mid-line, or mid-`\r\n`. Use a cookie only with `seek(cookie)` on the **same open handle**.

> **Warning — text cookies are not portable across handles.** This differs from `io.TextIOWrapper` and `gzip.open("rt")`, whose `tell()` cookies encode only decoder state and stay valid after re-opening the same file. An `aiogzip` text cookie embeds a random per-instance nonce, so a cookie minted by one handle is rejected with `OSError` by any other handle (and after the file is re-opened). This is deliberate: a stale cookie fails fast instead of silently restoring the wrong decoder state against an unrelated stream. To checkpoint progress for a later run or a different process, persist a *plain* offset (see [Resumable text processing](#resumable-text-processing)), never a cookie.

Backward seeks restart decompression from the beginning of the gzip stream. For non-seekable `fileobj` inputs, `aiogzip` keeps a bounded compressed-input replay cache so rewind can work without loading unbounded data; tune it with `max_rewind_cache_size` or set it to `None` for the previous unbounded behavior.

**Concurrency:** An open `aiogzip` file is not safe for concurrent use by multiple `asyncio` tasks. Its internal buffers and decoder/compressor state are mutated without locking — the same contract as standard-library file objects. Give each task its own file object, or serialize access behind your own lock.

**Note:** `aiogzip` does not provide whole-buffer `compress()` or
`decompress()` helpers analogous to `gzip.compress()` and `gzip.decompress()`.
For asynchronous byte sources, use [`compress_chunks()` and
`decompress_chunks()`](streaming.md).

## Resumable text processing

To stop processing and resume later — especially in a **different process** — you cannot persist a `tell()` cookie, because it is bound to the handle that produced it (see the warning above). Instead, checkpoint a *plain* offset: a non-negative count of decompressed bytes that any handle can `seek()` to.

A plain offset is only meaningful where the text stream is "plain" — no buffered text and a clean decoder, i.e. the offset does not fall in the middle of a multibyte character. Line boundaries delimited by `\n` are always such positions: `\n` (`0x0A`) can never be part of a UTF-8 (or any ASCII-compatible) multibyte sequence.

The supported pattern is to drive the **binary layer** (`f.buffer`, or `AsyncGzipBinaryFile` directly), which splits lines without the text layer's read-ahead, so `await f.tell()` after each line is an exact decompressed byte offset. Decode each line yourself with the file's encoding, and persist that offset as your checkpoint:

```python
import asyncio
import gzip
from aiogzip import AsyncGzipBinaryFile, AsyncGzipTextFile

async def main():
    path = "events.jsonl.gz"
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for i in range(1000):
            fh.write(f'{{"id": {i}}}\n')

    # Pass 1: process lines via the binary layer, checkpointing a plain
    # offset after each line, then "crash" partway through.
    saved_offset = 0
    async with AsyncGzipBinaryFile(path, "rb") as f:
        async for raw_line in f:                  # tell() counts only consumed bytes
            line = raw_line.decode("utf-8")
            ...                                   # do your work with `line`
            saved_offset = await f.tell()         # plain decompressed byte offset
            if line.startswith('{"id": 499}'):
                break                             # simulate interruption

    # Pass 2: a brand-new handle (e.g. a fresh process) resumes by opening
    # the file in text mode and seeking to the saved plain offset.
    async with AsyncGzipTextFile(path, "rt", encoding="utf-8") as f:
        await f.seek(saved_offset)                # non-negative plain offset, not a cookie
        async for line in f:
            ...                                   # continues at id 500

asyncio.run(main())
```

`seek()` to a forward plain offset is **O(n)**: gzip cannot index into a compressed stream, so `aiogzip` restarts decompression from the beginning and replays `offset` bytes. If the replay cost matters, checkpoint at a coarse granularity (e.g. every N lines) rather than after every line.
