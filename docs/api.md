# API Reference

`aiogzip` exposes its supported public API from the top-level package:

- `AsyncGzipBinaryFile`
- `AsyncGzipTextFile`
- `AsyncGzipFile`

Implementation internals live in `aiogzip._common`, `aiogzip._binary`, and `aiogzip._text`. Treat those modules as private and unstable.

## `seek()` and `tell()` in text mode

`AsyncGzipBinaryFile.tell()` returns the current position as a plain non-negative count of decompressed bytes, and `seek(offset)` accepts any such offset.

`AsyncGzipTextFile.tell()` returns one of two things:

- A **plain** non-negative offset (decompressed bytes) when the stream is at a clean boundary — no buffered text, the decoder holds no partial multibyte sequence, and there is no pending `\r`. This is the same value the underlying binary layer reports (`await f.buffer.tell()`).
- An **opaque cookie** (a negative integer) otherwise. The cookie encodes the decoder state needed to resume mid-character, mid-line, or mid-`\r\n`, so round-tripping `seek(await f.tell())` is exact.

`seek()` accepts both: a non-negative argument is treated as a plain offset (decompression is replayed from the start up to that byte), and a negative argument is decoded as a cookie.

### Cookies are bound to the handle that minted them

> **Warning.** A text `tell()` cookie is valid **only on the same open handle**. This differs from `io.TextIOWrapper` and `gzip.open("rt")`, whose `tell()` cookies encode only decoder state and remain usable after re-opening the same file. An `aiogzip` text cookie embeds a random per-instance nonce, which `seek()` validates; a cookie from a different handle (or from before the file was re-opened) is rejected with `OSError` rather than silently restoring the wrong decoder state. Do not persist cookies across processes or re-opens — persist a plain offset instead.

### Resumable processing recipe

Because cookies are not portable, checkpoint progress as a *plain* offset taken at a line boundary, where the decoder is guaranteed clean (`\n` is single-byte, so it never splits a multibyte character). Drive the binary layer — which splits lines without the text layer's read-ahead — so `await f.tell()` is an exact decompressed byte offset, then resume in a new process by opening in `"rt"` and seeking to that offset:

```python
import asyncio
import gzip
from aiogzip import AsyncGzipBinaryFile, AsyncGzipTextFile

async def main():
    path = "events.jsonl.gz"
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for i in range(1000):
            fh.write(f'{{"id": {i}}}\n')

    # Pass 1: process via the binary layer; checkpoint a plain offset per line.
    saved_offset = 0
    async with AsyncGzipBinaryFile(path, "rb") as f:
        async for raw_line in f:
            line = raw_line.decode("utf-8")
            ...                                   # do your work
            saved_offset = await f.tell()         # plain decompressed byte offset
            if line.startswith('{"id": 499}'):
                break                             # simulate interruption

    # Pass 2: a fresh handle resumes by seeking to the saved plain offset.
    async with AsyncGzipTextFile(path, "rt", encoding="utf-8") as f:
        await f.seek(saved_offset)                # non-negative plain offset, not a cookie
        async for line in f:
            ...                                   # continues at id 500

asyncio.run(main())
```

A forward plain `seek()` is **O(n)** in the target offset: gzip has no random access, so `aiogzip` restarts decompression from the start and replays bytes up to the offset. Checkpoint at a coarse granularity if that cost matters. See [Resumable text processing](index.md#resumable-text-processing) for more detail.

::: aiogzip
