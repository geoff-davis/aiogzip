# Examples

This guide provides practical examples for using `aiogzip` in various scenarios.

## CSV Processing with `aiocsv`

`aiogzip` pairs perfectly with `aiocsv` for efficient, asynchronous CSV processing.

### Reading a CSV File

```python
import asyncio
import aiocsv
from aiogzip import AsyncGzipTextFile

async def read_csv():
    async with AsyncGzipTextFile("data.csv.gz", "rt", encoding="utf-8", newline="") as f:
        # Use AsyncDictReader for dictionary-based access
        async for row in aiocsv.AsyncDictReader(f):
            print(f"Name: {row['name']}, Age: {row['age']}")

asyncio.run(read_csv())
```

### Writing a CSV File

```python
import asyncio
import aiocsv
from aiogzip import AsyncGzipTextFile

async def write_csv():
    data = [
        {"name": "Alice", "age": 30, "city": "New York"},
        {"name": "Bob", "age": 25, "city": "Los Angeles"},
    ]

    async with AsyncGzipTextFile("output.csv.gz", "wt", encoding="utf-8", newline="") as f:
        writer = aiocsv.AsyncDictWriter(f, fieldnames=["name", "age", "city"])
        await writer.writeheader()
        for row in data:
            await writer.writerow(row)

asyncio.run(write_csv())
```

## JSON Lines (JSONL) Processing

Processing large compressed JSONL files is a common task in data engineering.

### Reading JSONL

```python
import asyncio
import json
from aiogzip import AsyncGzipTextFile

async def process_jsonl():
    async with AsyncGzipTextFile("logs.jsonl.gz", "rt") as f:
        async for line in f:
            try:
                record = json.loads(line)
                if record.get("level") == "ERROR":
                    print(f"Error found: {record['message']}")
            except json.JSONDecodeError:
                print(f"Skipping invalid JSON: {line[:50]}...")

asyncio.run(process_jsonl())
```

### Reading JSONL Efficiently

If your data is standard UTF-8 JSONL with `\n` line endings, configure the text
reader explicitly:

```python
import asyncio
import json
from aiogzip import AsyncGzipTextFile

async def process_jsonl_fast():
    async with AsyncGzipTextFile(
        "logs.jsonl.gz",
        "rt",
        newline="\n",
        chunk_size=512 * 1024,
    ) as f:
        async for line in f:
            record = json.loads(line)
            # Process record...

asyncio.run(process_jsonl_fast())
```

Why this helps:

- `newline="\n"` skips universal-newline handling that JSONL does not need.
- A larger `chunk_size` reduces async read overhead during line iteration.

This is a good default for large gzipped JSONL files. If memory pressure matters
more than throughput, lower the chunk size.

## Concurrent File Processing

One of the biggest advantages of `aiogzip` is the ability to process multiple files concurrently without blocking the event loop.

```python
import asyncio
from aiogzip import AsyncGzipTextFile

async def process_file(filename):
    print(f"Starting {filename}...")
    line_count = 0
    async with AsyncGzipTextFile(filename, "rt") as f:
        async for _ in f:
            line_count += 1
    print(f"Finished {filename}: {line_count} lines")
    return line_count

async def main():
    files = ["data1.gz", "data2.gz", "data3.gz"]

    # Create tasks for all files
    tasks = [process_file(f) for f in files]

    # Run them concurrently
    results = await asyncio.gather(*tasks)

    print(f"Total lines processed: {sum(results)}")

# To run this example, ensure the files exist
# asyncio.run(main())
```

## Error Handling

`aiogzip` raises standard `OSError` (or subclasses) for I/O issues, ensuring consistency with Python's built-in file handling.

```python
import asyncio
from aiogzip import AsyncGzipFile

async def safe_read():
    try:
        async with AsyncGzipFile("non_existent.gz", "rb") as f:
            await f.read()
    except FileNotFoundError:
        print("File not found!")
    except OSError as e:
        print(f"An I/O error occurred: {e}")

asyncio.run(safe_read())
```

## Reading Untrusted Files Safely

When reading gzip data from untrusted sources, cap decompressed output to avoid
expanding a small compressed file into unbounded memory usage:

```python
import asyncio
from aiogzip import AsyncGzipFile

async def read_untrusted(path):
    async with AsyncGzipFile(path, "rb", max_decompressed_size=100 * 1024 * 1024) as f:
        return await f.read()

asyncio.run(read_untrusted("upload.gz"))
```

If the input is a non-seekable stream, `aiogzip` may keep compressed bytes so
backward seeks can replay the stream. The cache defaults to 128 MiB; reduce
`max_rewind_cache_size` for memory-sensitive pipelines, or use forward-only
reads and leave backward seeking disabled once the cap is exceeded.
