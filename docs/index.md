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

---

## Quick Links

- [Installation & Usage](examples.md)
- [Performance Benchmarks](performance.md)
- [API Reference](api.md)
- [Contributing](contributing.md)

---

## Quickstart

Using `aiogzip` is as simple as using the standard `gzip` module, but with `async`/`await`.

### Writing to a Compressed File

```python
import asyncio
from aiogzip import AsyncGzipFile

async def main():
    # Write binary data
    async with AsyncGzipFile("file.gz", "wb") as f:
        await f.write(b"Hello, async world!")

    # Write text data
    async with AsyncGzipFile("file.txt.gz", "wt") as f:
        await f.write("This is a text file.")

asyncio.run(main())
```

### Reading from a Compressed File

```python
import asyncio
from aiogzip import AsyncGzipFile

async def main():
    # Read the entire file
    async with AsyncGzipFile("file.gz", "rb") as f:
        content = await f.read()
        print(content)

    # Iterate over lines in a text file
    async with AsyncGzipFile("file.txt.gz", "rt") as f:
        async for line in f:
            print(line.strip())

asyncio.run(main())
```

## Limitations

`aiogzip` focuses on the most common file-based read/write operations and does not implement the full API of the standard `gzip` module. Notably, it does not currently support:

- In-memory compression/decompression (e.g., `gzip.compress`/`gzip.decompress`).
- The `seek()` and `tell()` methods for navigating within a file stream.
- Reading or writing gzip headers and metadata like `mtime`.
