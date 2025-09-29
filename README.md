# aiogzip ⚡️

**An asynchronous library for reading and writing gzip-compressed files.**

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

## Installation

Install `aiogzip` using pip. To include optional `aiocsv` support, specify the `[csv]` extra.

```bash
# Standard installation
pip install aiogzip

# With aiocsv support
pip install aiogzip[csv]
```

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

---

## Performance

`aiogzip` is a specialized tool that excels in text-based, async workflows but may be slower than the standard library for binary operations.

According to the benchmarks, `aiogzip` is:

- **4.3x faster** for general text file operations.
- **1.6x faster** when processing structured text like JSONL files.
- **1.1x slower** for binary file operations using 1KB chunk sizes.

The key is to match the tool to the task. Use `aiogzip` where its async and text-handling capabilities provide the most significant advantage.

### Async and Concurrent Processing Benefits

`aiogzip` excels in scenarios where you need to process multiple files concurrently or integrate with other async libraries:

- **Concurrent file processing**: Process multiple `.gz` files simultaneously without blocking
- **Async pipeline integration**: Seamlessly works with `aiocsv`, `aiohttp`, and other async libraries
- **Non-blocking I/O**: Allows your application to handle other tasks while file operations are in progress
- **Better resource utilization**: More efficient use of system resources in I/O-bound applications

**Note**: The benefits of async are most visible when there's actual I/O latency (network storage, remote APIs, etc.) or when mixing file operations with other async tasks. For purely local file processing on SSDs, the async overhead may exceed the benefits due to minimal I/O wait times.

### When to Use `aiogzip`

✅ **Recommended for:**

- Async applications processing text, CSV, or JSONL files.
- Streaming text-based data pipelines.
- Applications where async integration and concurrent file processing are more important than raw binary I/O speed.

### When to Use Standard `gzip`

❌ **Consider standard `gzip` for:**

- Purely synchronous applications.
- Applications that are highly memory-constrained, as `aiogzip` may use more memory during decompression of highly compressible data due to internal buffering.
- Workloads dominated by binary file I/O where maximum performance is essential.

---

## Limitations

`aiogzip` focuses on the most common file-based read/write operations and does not implement the full API of the standard `gzip` module. Notably, it does not currently support:

- In-memory compression/decompression (e.g., `gzip.compress`/`gzip.decompress`).
- The `seek()` and `tell()` methods for navigating within a file stream.
- Reading or writing gzip headers and metadata like `mtime`.

## Development

This project uses `setuptools` for packaging.

1. **Clone the repository**:

   ```bash
   git clone https://github.com/geoff-davis/aiogzip.git
   cd aiogzip
   ```

2. **Create a virtual environment and install dependencies**:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -e ".[csv]"  # Install in editable mode with extras
   pip install -e ".[dev]" # Install dev dependencies
   ```

3. **Run tests**:

   ```bash
   pytest
   ```

## License

This project is licensed under the **MIT License**. See the `LICENSE` file for details.
