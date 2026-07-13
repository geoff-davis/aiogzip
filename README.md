# aiogzip ⚡️

An asynchronous API modeled after Python's `gzip` module for reading and
writing gzip-compressed files.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![PyPI version](https://img.shields.io/pypi/v/aiogzip.svg)](https://pypi.org/project/aiogzip/)
[![Python versions](https://img.shields.io/pypi/pyversions/aiogzip.svg)](https://pypi.org/project/aiogzip/)
[![Tests](https://github.com/geoff-davis/aiogzip/workflows/Python%20CI/badge.svg)](https://github.com/geoff-davis/aiogzip/actions)
[![Coverage](https://raw.githubusercontent.com/geoff-davis/aiogzip/python-coverage-comment-action-data/badge.svg)](https://github.com/geoff-davis/aiogzip/tree/python-coverage-comment-action-data)
[![Documentation](https://img.shields.io/badge/docs-mkdocs-blue)](https://geoff-davis.github.io/aiogzip/)

## Installation

```bash
pip install aiogzip
```

Python 3.8 through 3.14 are supported by the 1.x release line.

## Text-mode quickstart

File methods are asynchronous, and line iteration uses `async for`:

```python
import aiogzip

async with aiogzip.open("events.jsonl.gz", "rt") as f:
    async for line in f:
        print(line)
```

## Binary-mode quickstart

```python
import aiogzip

async with aiogzip.open("payload.bin.gz", "wb") as f:
    await f.write(b"Hello, async world!")

async with aiogzip.open("payload.bin.gz", "rb") as f:
    payload = await f.read()
```

For small files that comfortably fit in memory, use the binary whole-file
helpers:

```python
import aiogzip

data = await aiogzip.read("payload.bin.gz")
await aiogzip.write("copy.bin.gz", data)
```

`read()` and `write()` load the entire decompressed or uncompressed payload
into memory. Use `open()` to stream large files. The existing
`AsyncGzipFile()` factory remains fully supported for compatibility.

For arbitrary asynchronous byte sources, compress or decompress without
adapting the source to a file object:

```python
async for data in aiogzip.decompress_chunks(compressed_source()):
    await consume(data)

async for data in aiogzip.compress_chunks(raw_source(), mtime=0):
    await send(data)
```

Complete decompression integrity validation occurs only if the iterator is
consumed to the end. Compression output is incomplete if its source fails or
the consumer exits early. See the
[async-iterable streaming guide](https://geoff-davis.github.io/aiogzip/streaming/)
for backpressure, limits, cancellation, metadata, and lifecycle behavior.

See the [recipes](https://geoff-davis.github.io/aiogzip/recipes/) for JSON
Lines, untrusted input, reproducible output, append mode, seeking,
cancellation recovery, and external async streams.

## Why use aiogzip?

- Async file I/O built on `asyncio` and `aiofiles`.
- Binary and text modes with distinct, typed concrete classes.
- Async `read`, `write`, `readline`, `seek`, `tell`, `peek`, `readinto`, and
  line iteration.
- Interoperable gzip output, concatenated-member reads, and append support.
- Configurable gzip metadata for reproducible archives.
- Bounded decompression and rewind-cache controls for untrusted or
  non-seekable input.
- Pull-driven compression and decompression for `AsyncIterable[bytes]` sources.
- Optional zlib-ng acceleration without a required runtime dependency.
- Verified tarfile-style access patterns and `aiocsv` workflows.

## Migrating from `gzip`

The API follows `gzip`, but file operations must be awaited:

| Standard library | aiogzip |
| --- | --- |
| `gzip.open(path, "rt")` | `aiogzip.open(path, "rt")` |
| `f.read()` | `await f.read()` |
| `f.readline()` | `await f.readline()` |
| `for line in f` | `async for line in f` |
| `f.seek(offset)` | `await f.seek(offset)` |
| `f.close()` | `await f.close()` |

Synchronous code:

```python
import gzip

with gzip.open("events.jsonl.gz", "rt") as f:
    for line in f:
        process(line)
```

becomes asynchronous code:

```python
import aiogzip

async with aiogzip.open("events.jsonl.gz", "rt") as f:
    async for line in f:
        await process(line)
```

Important differences and caveats:

- `aiogzip` defaults to `compresslevel=6`; `gzip.open()` defaults to `9`.
  Pass `compresslevel=9` when that parity matters.
- Paths (including `pathlib.Path`) are accepted directly. Supported external
  asynchronous sources and destinations are passed with `filename=None` and
  `fileobj=...`; their `read()` or `write()` methods must be async.
- Append modes (`"ab"` and `"at"`) create a new gzip member. Both libraries
  transparently read concatenated members as one decompressed stream.
- An open file object is stateful and is not safe for simultaneous use by
  multiple tasks. Use one handle per task or serialize access.
- Gzip has no random-access index. Backward seeks rewind and replay
  decompression, so mixed-direction access can be O(n).
- Cancelling an executor-backed decompression can leave that reader unusable;
  close it and open a new handle before continuing.

## Compatibility and operational behavior

`aiogzip` reads and writes standard gzip streams and supports text and binary
modes, `tarfile`-style reads, `aiocsv`, append mode, and concatenated members.
It is an asynchronous API modeled after `gzip`, not a synchronous drop-in
replacement.

- **Lifecycle:** Prefer `async with`. When that is impractical, call
  `await f.open()` and pair it with `await f.close()` in `finally`.
- **Seeking:** Backward seeks replay decompression from the start. Forward
  access is fastest. Text `tell()` may return a handle-bound opaque cookie
  when decoder state is buffered; do not persist that cookie across reopens.
- **Non-seekable sources:** Up to 128 MiB of compressed input is cached by
  default for replay. Tune `max_rewind_cache_size`, or pass `None` for an
  unbounded cache.
- **Untrusted input:** `max_decompressed_size` caps cumulative decompressed
  output for a read pass. Overflow raises `OSError` without first materializing
  the complete expansion.
- **Task safety:** Do not operate on one open handle concurrently from several
  tasks; internal codec and buffer state is mutable and intentionally unlocked.
- **Cancellation:** If cancellation occurs during executor-backed
  decompression, later reads and seeks raise `OSError`. Close and reopen the
  reader. A similarly cancelled compression makes that output member unusable;
  discard it and start a new writer.
- **Append mode:** Each append creates another member instead of extending the
  existing deflate stream. Standards-compliant readers concatenate the members.
- **Large writes:** Gzip's 32-bit `ISIZE` wraps after 4 GiB, as it does in
  `gzip.open()`. Pass `strict_size=True` to reject a member that would cross
  that limit.
- **Compression metadata:** `mtime` and the embedded original filename affect
  output bytes. Set both explicitly when reproducibility across paths matters.

## Performance and optional acceleration

Text bulk workflows are commonly faster than synchronous `gzip`; binary bulk
writes are near parity, while very small calls can be slower due to async
overhead. Large codec calls are offloaded to the default executor, allowing
independent streams to make progress concurrently. Line iteration and
`writelines()` use bounded batching.

For large UTF-8 JSON Lines files with `\n` terminators, the measured fast path
uses `newline="\n"` and `chunk_size=512 * 1024`. Tune memory and throughput for
your workload rather than assuming one chunk size fits every application.

Install the optional codec with:

```bash
pip install "aiogzip[fast]"
```

When installed, zlib-ng is selected automatically for decompression.
Compression remains on stdlib zlib so installation alone does not change gzip
bytes; pass `fast_compress=True` per writer to opt in. Set
`AIOGZIP_ENGINE=stdlib` to force stdlib behavior. Inspect the default selections
for a diagnostic report:

```python
import aiogzip

print(aiogzip.engine_info())
```

The engine names are informational, not a stable machine-readable interface.
See the [performance guide](https://geoff-davis.github.io/aiogzip/performance/)
for benchmarks and tuning guidance.

## Development and contributing

The 1.x line is the last to support Python 3.8 and 3.9; aiogzip 2.0 will
require Python 3.11+. Older interpreters will continue to resolve the latest
compatible 1.x release from PyPI.

See the [contributing guide](https://geoff-davis.github.io/aiogzip/contributing/)
for setup, tests, linting, typing, documentation, and benchmark workflows.
