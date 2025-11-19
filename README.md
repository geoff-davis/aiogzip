# aiogzip ⚡️

**An asynchronous library for reading and writing gzip-compressed files.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![PyPI version](https://img.shields.io/pypi/v/aiogzip.svg)](https://pypi.org/project/aiogzip/)
![PyPI - Python Version](https://img.shields.io/pypi/pyversions/aiogzip.svg)
[![Tests](https://github.com/geoff-davis/aiogzip/workflows/Python%20CI/badge.svg)](https://github.com/geoff-davis/aiogzip/actions)
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

- **Text I/O**: ~2.5x faster than standard gzip.
- **Concurrency**: Non-blocking I/O allows for efficient concurrent processing.
- **Memory**: Optimized buffer management for stable memory usage.

See the [Performance Guide](https://geoff-davis.github.io/aiogzip/performance/) for detailed benchmarks.

## Contributing

See [CONTRIBUTING.md](docs/contributing.md) for development instructions.
