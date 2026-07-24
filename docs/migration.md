# Migrating from `gzip.open`

`aiogzip.open()` accepts the same paths, modes, and keyword arguments as the
stdlib's `gzip.open()`, and it reads and writes the same `.gz` format. Exactly
three things change:

aiogzip 2.0 requires Python 3.11 or newer. On Python 3.8 through 3.10, normal
dependency resolution continues selecting the newest compatible 1.x release;
pin `aiogzip<2` when an explicit upper bound is preferred. Upgrade the
interpreter before selecting a 2.0 prerelease.

| | `gzip` | `aiogzip` |
|---|---|---|
| Opening | `with gzip.open(...) as f:` | `async with aiogzip.open(...) as f:` |
| Line iteration | `for line in f:` | `async for line in f:` |
| Reads and writes | `f.read()`, `f.write(data)` | `await f.read()`, `await f.write(data)` |

## Before / after

```python
# stdlib gzip
import gzip

def count_lines(path):
    with gzip.open(path, "rt") as f:
        return sum(1 for _ in f)
```

```python
# aiogzip
import aiogzip

async def count_lines(path):
    async with aiogzip.open(path, "rt") as f:
        return sum([1 async for _ in f])
```

Everything else carries over unchanged: mode strings (`"rb"`, `"rt"`, `"wb"`,
`"wt"`, append, exclusive), `compresslevel`, text-mode `encoding` / `errors` /
`newline`, and interoperability — files written by either library are read by
the other.

If you forget and use `with` or `for`, aiogzip raises a `TypeError` that says
exactly what to change (e.g. `"must be used with 'async with', not 'with'"`).

## Moving an existing aiogzip application to 2.0

Ordinary asyncio callers do not need to change their code. The high-level
`open()`, `AsyncGzipFile()`, `read()`, `write()`, `inspect()`, `verify()`,
`compress_chunks()`, and `decompress_chunks()` APIs retain their asynchronous
lifecycle and interoperability behavior. The main compatibility change is the
Python 3.11 floor.

The 2.0 alpha also adds synchronous `GzipEncoder` and `GzipDecoder` classes for
applications that own a custom transport and want to drive aiogzip's gzip
state machine directly:

```python
from aiogzip import GzipDecoder

decoder = GzipDecoder(max_decompressed_size=100 * 1024 * 1024)
payload = bytearray()
for compressed_chunk in source:
    payload.extend(b"".join(decoder.feed(compressed_chunk)))
payload.extend(b"".join(decoder.finish()))
```

The codec is synchronous and performs no I/O or executor offload. Its returned
operation iterators are lazy and must be exhausted before the next call, and
decompression integrity is established only after `finish()` is exhausted.
See the [synchronous codec guide](codec.md) before integrating it.

`GzipEncoder` and `GzipDecoder` are provisional during the alpha series. Their
surface may change in a later alpha in response to transport-integration
feedback. This provisional statement does not weaken compatibility promises
for the established high-level asyncio API.

Next steps: [Examples](examples.md) for common tasks,
[Recipes](recipes.md) for streaming patterns, and the
[Performance Guide](performance.md) for tuning.
