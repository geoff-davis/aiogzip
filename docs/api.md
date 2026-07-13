# API Reference

`aiogzip` exposes its supported public API from the top-level package:

- `AsyncGzipBinaryFile` — binary-mode reader/writer
- `AsyncGzipTextFile` — text-mode reader/writer
- `open` — recommended factory returning the right class for a mode string (accepts `r`/`w`/`a`/`x` ops with a `b` or `t` suffix)
- `AsyncGzipFile` — compatibility name for the same factory behavior; it remains fully supported
- `WithAsyncRead`, `WithAsyncWrite`, `WithAsyncReadWrite` — runtime-checkable protocols describing the async file objects accepted via `fileobj=`
- `ZlibEngine` — type alias for zlib compressor/decompressor objects (currently `Any`; the concrete C types are not exposed in type stubs)
- `GZIP_WBITS`, `GZIP_METHOD_DEFLATE`, `GZIP_OS_UNKNOWN`, and the `GZIP_FLAG_FNAME` / `GZIP_FLAG_FHCRC` / `GZIP_FLAG_FEXTRA` / `GZIP_FLAG_FCOMMENT` header-flag constants — useful when inspecting gzip headers alongside this library
- `__version__`

Implementation internals live in `aiogzip._common`, `aiogzip._binary`, and `aiogzip._text`. Treat those modules as private and unstable.

```python
import aiogzip

async with aiogzip.open("events.jsonl.gz", "rt") as stream:
    async for line in stream:
        print(line)
```

When writing through an external asynchronous `fileobj`, its `write()` method
may accept fewer bytes than requested as long as it returns the accepted byte
count. `aiogzip` retries short writes until the complete gzip block is written.
A zero-progress or otherwise invalid count raises `OSError`.

## Safety limits

Set `max_decompressed_size=<bytes>` when reading untrusted gzip data. The
limit applies to cumulative decompressed output for the current pass through
the stream. Each inflate call is restricted to the remaining allowance plus
one byte, so an over-limit member raises `OSError` without first materializing
its full expansion in memory. Rewinding resets the accounting because the new
read pass starts again at byte zero.

## Text encodings

`AsyncGzipTextFile` keeps one incremental encoder for the lifetime of a write
stream. Multiple `write()` or `writelines()` calls therefore produce one
continuous encoded byte stream, including for stateful encodings such as
UTF-16, UTF-32, and ISO-2022-JP. Any final encoder shift sequence is written
before the gzip member's final block and trailer.

Both binary and text `writelines()` collect small inputs into bounded
`chunk_size` batches before compression. Inputs larger than a batch are written
directly, so generators remain streaming and memory use stays bounded.

Byte-count and compression tuning parameters are integer-only:
`chunk_size`, `compresslevel`, `max_decompressed_size`, and
`max_rewind_cache_size` reject floats, strings, and booleans with `TypeError`.

## `seek()` and `tell()` in text mode

`AsyncGzipBinaryFile.tell()` returns the current position as a plain non-negative count of decompressed bytes, and `seek(offset)` accepts any such offset.

`AsyncGzipTextFile.tell()` returns one of two things:

- A **plain** non-negative offset (decompressed bytes) when the stream is at a clean boundary — no buffered text, the decoder holds no partial multibyte sequence, and there is no pending `\r`. This is the same value the underlying binary layer reports (`await f.buffer.tell()`).
- An **opaque cookie** (a negative integer) otherwise. The cookie encodes the decoder state needed to resume mid-character, mid-line, or mid-`\r\n`, so round-tripping `seek(await f.tell())` is exact.

`seek()` accepts both: a non-negative argument is treated as a plain offset (decompression is replayed forward to that byte — from the current position when the decoder is at a clean boundary at or behind the target, from the start of the stream otherwise), and a negative argument is decoded as a cookie.

### Cookies are bound to the handle that minted them

> **Warning.** A text `tell()` cookie is valid **only on the same open handle**. This differs from `io.TextIOWrapper` and `gzip.open("rt")`, whose `tell()` cookies encode only decoder state and remain usable after re-opening the same file. An `aiogzip` text cookie embeds a random per-instance nonce, which `seek()` validates; a cookie from a different handle (or from before the file was re-opened) is rejected with `OSError` rather than silently restoring the wrong decoder state. Do not persist cookies across processes or re-opens — persist a plain offset instead.

### Resumable processing recipe

Because cookies are not portable, checkpoint progress as a *plain* offset taken at a line boundary, where the decoder is guaranteed clean (`\n` is single-byte, so it never splits a multibyte character). Drive the binary layer — which splits lines without the text layer's read-ahead — so `await f.tell()` is an exact decompressed byte offset, then resume in a new process by opening in `"rt"` and seeking to that offset.

A forward plain `seek()` is **O(n)** in the target offset: gzip has no random access, so `aiogzip` replays decompressed bytes up to the offset. Checkpoint at a coarse granularity if that cost matters. See [Resumable text processing](index.md#resumable-text-processing) for the full worked example.

::: aiogzip
