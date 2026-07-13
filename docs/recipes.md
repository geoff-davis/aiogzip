# Recipes

These recipes use the public API and the behavior covered by aiogzip's test
suite. Use `open()` for streaming; the whole-file `read()` and `write()` helpers
are intended for payloads that comfortably fit in memory.

## Reading JSON Lines

```python
import json

import aiogzip

async with aiogzip.open("events.jsonl.gz", "rt") as f:
    async for line in f:
        event = json.loads(line)
        await process(event)
```

For large UTF-8 JSON Lines files that are known to use `\n` terminators,
`newline="\n"` avoids universal-newline translation. Benchmarks in this
project use `chunk_size=512 * 1024` to reduce async read overhead; tune that
value for your memory budget and workload.

For CPU-bound parsing, bounded `readlines()` batches avoid one async transition
per input line while retaining a predictable application-level working set:

```python
async with aiogzip.open(
    "events.jsonl.gz",
    "rt",
    newline="\n",
    chunk_size=512 * 1024,
) as f:
    while True:
        lines = await f.readlines(1024 * 1024)
        if not lines:
            break
        for line in lines:
            event = json.loads(line)
            process(event)
```

The hint counts decoded characters and reading stops after the whole line that
reaches it, so it is an approximate batch target rather than a strict memory
limit. Prefer `async for` when each record is handed to an asynchronous
consumer and per-line backpressure is desirable.

## Writing JSON Lines

Write records as they become available instead of building the complete file
in memory:

```python
import json

import aiogzip

async with aiogzip.open("events.jsonl.gz", "wt", newline="\n") as f:
    async for event in events:
        await f.write(json.dumps(event) + "\n")
```

If the records already exist as a synchronous iterable of strings,
`await f.writelines(records)` batches small writes while keeping memory use
bounded.

## Processing untrusted gzip input

Set an application-appropriate decompressed-size ceiling:

```python
import aiogzip

async with aiogzip.open(
    "uploaded-data.gz",
    "rb",
    max_decompressed_size=100 * 1024 * 1024,
) as f:
    while chunk := await f.read(64 * 1024):
        await process(chunk)
```

The right limit depends on the file format, account quotas, and available
resources. Crossing it raises `OSError`; the inflater is bounded to the
remaining allowance plus one byte for overflow detection instead of first
allocating the complete expanded payload.

When the payload is not needed, use `verify()` to perform the same complete
validation scan while discarding decompressed bytes:

```python
result = await aiogzip.verify(
    "uploaded-data.gz",
    max_decompressed_size=100 * 1024 * 1024,
)
print(result.uncompressed_size)
```

## Reproducible gzip output

The gzip header timestamp and embedded filename both affect output bytes. Set
`mtime` and `original_filename` explicitly when output must be identical even
if the destination path changes:

```python
import aiogzip

await aiogzip.write(
    "build/output.gz",
    b"stable payload",
    mtime=0,
    original_filename="payload.bin",
)
```

Use `original_filename=""` to omit the filename header field. Keep the
compression engine and level fixed as well: default compression uses stdlib
zlib at level 6, while `fast_compress=True` can produce different valid gzip
bytes.

## Append mode and concatenated gzip members

```python
import aiogzip

async with aiogzip.open("events.gz", "wb") as f:
    await f.write(b"first\n")

async with aiogzip.open("events.gz", "ab") as f:
    await f.write(b"second\n")

assert await aiogzip.read("events.gz") == b"first\nsecond\n"
```

Append mode adds a new gzip member; it does not rewrite or extend the first
deflate stream. `aiogzip`, `gzip.open()`, and other standards-compliant readers
return the concatenated decompressed contents.

## Seeking

```python
import aiogzip

async with aiogzip.open("events.gz", "rb") as f:
    header = await f.read(100)
    await f.seek(0)
    complete_data = await f.read()
```

Backward seeking rewinds and replays decompression because gzip has no random
access index. Prefer sequential processing when possible. If repeated replay
is expensive, reopening can make lifecycle intent clearer but does not avoid
the decompression cost required to reach a later uncompressed offset.

## Cancellation

Large compression and decompression calls may run in an executor. A worker
thread cannot be stopped after its awaiting task is cancelled, so the codec
state may still advance.

If an executor-backed read is cancelled, close that reader and open a new one;
later reads and seeks on the old handle raise `OSError`. If an executor-backed
write is cancelled, discard that incomplete output member and create a new
writer rather than continuing on the broken stream.

```python
import asyncio

import aiogzip

async def read_payload(path):
    try:
        return await aiogzip.read(path)
    except asyncio.CancelledError:
        # aiogzip.read() closes its handle before propagating cancellation.
        raise
```

## External async file objects

The `fileobj` argument accepts objects with asynchronous `read()` or `write()`
methods. For example, an existing `aiofiles` handle can be wrapped without
transferring ownership:

```python
import aiofiles

import aiogzip

async with aiofiles.open("payload.gz", "rb") as raw:
    async with aiogzip.open(None, "rb", fileobj=raw, closefd=False) as f:
        payload = await f.read()
```

With `closefd=False`, closing the gzip wrapper leaves the external object open.
Pass `closefd=True` only when the wrapper should close it. Non-seekable readers
use a bounded compressed-input replay cache for backward seeks.
