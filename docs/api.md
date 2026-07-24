# API Reference

`aiogzip` exposes its supported public API from the top-level package:

- `AsyncGzipBinaryFile` — binary-mode reader/writer
- `AsyncGzipTextFile` — text-mode reader/writer
- `open` — recommended factory returning the right class for a mode string (accepts `r`/`w`/`a`/`x` ops with a `b` or `t` suffix)
- `AsyncGzipFile` — compatibility name for the same factory behavior; it remains fully supported
- `read` — read and decompress a complete binary stream into memory
- `write` — compress and write a complete bytes-like payload
- `EngineInfo` and `engine_info` — immutable diagnostic information about the default compression and active decompression engines
- `GzipMemberInfo`, `GzipInfo`, and `inspect` — validated per-member metadata and aggregate sizes from a complete decompression scan
- `VerificationResult` and `verify` — lightweight aggregate counts after complete integrity verification
- `decompress_chunks` — pull-driven decompression from an `AsyncIterable[bytes]` with bounded output chunks
- `compress_chunks` — one-member gzip compression from an `AsyncIterable[bytes]` with bounded output chunks
- `GzipEncoder` and `GzipDecoder` — synchronous sans-I/O state machines for
  transport-independent, bounded gzip encoding and decoding
- `WithAsyncRead`, `WithAsyncWrite`, `WithAsyncReadWrite` — runtime-checkable protocols describing the async file objects accepted via `fileobj=`
- `ZlibEngine` — type alias for zlib compressor/decompressor objects (currently `Any`; the concrete C types are not exposed in type stubs)
- `GZIP_WBITS`, `GZIP_METHOD_DEFLATE`, `GZIP_OS_UNKNOWN`, and the `GZIP_FLAG_FNAME` / `GZIP_FLAG_FHCRC` / `GZIP_FLAG_FEXTRA` / `GZIP_FLAG_FCOMMENT` header-flag constants — useful when inspecting gzip headers alongside this library
- `__version__`

The synchronous codec is implemented in the public `aiogzip.codec` module.
Implementation internals live in `aiogzip._common`, `aiogzip._binary`,
`aiogzip._text`, `aiogzip._inspection`, and `aiogzip._streaming`. Treat those
modules as private and unstable.

```python
import aiogzip

async with aiogzip.open("events.jsonl.gz", "rt") as stream:
    async for line in stream:
        print(line)
```

For small files that fit comfortably in memory, the whole-file helpers avoid
manual lifecycle management:

```python
data = await aiogzip.read("payload.bin.gz")
await aiogzip.write("copy.bin.gz", data, mtime=0)
```

Both helpers operate in binary mode and load the entire uncompressed payload
into memory. Use `open()` for streaming large files.

## Synchronous codec

Use `GzipEncoder` and `GzipDecoder` when an application owns a synchronous or
custom transport and needs aiogzip's framing, concatenated-member traversal,
integrity validation, and output limits without any I/O or executor policy.
Each state-changing call returns a lazy iterator that must be exhausted before
another operation begins.

```python
import aiogzip

encoder = aiogzip.GzipEncoder(mtime=0)
wire = b"".join(encoder.start())
wire += b"".join(encoder.feed(b"payload"))
wire += b"".join(encoder.finish())

decoder = aiogzip.GzipDecoder()
payload = b"".join(decoder.feed(wire)) + b"".join(decoder.finish())
```

> **Warning:** Decoder output can precede its trailer. Integrity is established
> only after the operation returned by `finish()` is exhausted.

The codec API is provisional during the 2.0 alpha series. See the
[synchronous codec guide](codec.md) for constructor validation, immutable
input snapshots, lifecycle hazards, thread safety, and error behavior.

::: aiogzip.codec.GzipEncoder

::: aiogzip.codec.GzipDecoder

## Engine diagnostics

`engine_info()` reports the default compression implementation and the active
decompression implementation without exposing internal codec objects:

```python
import aiogzip

print(aiogzip.engine_info())
```

Compression is reported as `stdlib-zlib` because that is the default even when
zlib-ng is installed. A writer created with `fast_compress=True` opts that
individual stream into zlib-ng; that per-stream choice is not reflected by
`engine_info()`. The strings are human-readable diagnostics and are not a
stable machine-readable feature-detection API.

## Inspection and verification

`inspect()` scans and validates the complete gzip stream but discards its
decompressed payload. It returns one immutable `GzipMemberInfo` per member,
including exact compressed offsets and sizes, actual uncompressed sizes,
literal trailer `ISIZE` values, and optional header metadata. Header `mtime=0`
is preserved as `0`; `FNAME` and `FCOMMENT` use deterministic Latin-1 decoding.

```python
import aiogzip

info = await aiogzip.inspect("events.gz", max_decompressed_size=1024**3)
for member in info.members:
    print(member.index, member.compressed_offset, member.uncompressed_size)
```

`verify()` performs the same complete structural, deflate, CRC-32, and `ISIZE`
validation without retaining per-member metadata:

```python
result = await aiogzip.verify("events.gz")
print(result.member_count, result.uncompressed_size)
```

Successful return means the entire stream is valid. Corruption raises
`gzip.BadGzipFile`; I/O and decompression-limit failures raise `OSError`.
Zero-byte input is valid and returns zero members and zero sizes. NUL padding
after a valid member is accepted and included in the aggregate compressed size;
other trailing data is treated as a malformed next member.

## Async-iterable decompression

`decompress_chunks()` accepts only an asynchronous iterable of `bytes` and
returns an `AsyncIterator[bytes]`. Empty source chunks are ignored, yielded
chunks are non-empty, and `output_chunk_size` is a strict upper bound.

```python
async for data in aiogzip.decompress_chunks(
    compressed_source(),
    output_chunk_size=64 * 1024,
    max_decompressed_size=1024**3,
):
    await consume(data)
```

The stream is validated incrementally. Payload can be yielded before its final
CRC and trailer are available, so complete integrity validation occurs only
when iteration ends normally. Corruption raises `gzip.BadGzipFile`, output
limit violations raise `OSError`, invalid source items raise `TypeError`, and
source exceptions and cancellation propagate. See the
[streaming guide](streaming.md) for backpressure and lifecycle details.

`compress_chunks()` accepts an asynchronous iterable of uncompressed `bytes`
and yields exactly one gzip member. It emits the header promptly, before
requesting the first source item. Empty sources therefore produce a valid empty
member rather than zero bytes.

```python
async for data in aiogzip.compress_chunks(
    raw_source(),
    mtime=0,
    output_chunk_size=64 * 1024,
):
    await send(data)
```

The trailer is emitted only after the source ends normally. If the source
raises, compression is cancelled, or output consumption stops early, bytes
already yielded form an incomplete member and must be discarded. Compression
levels, metadata, `strict_size`, and `fast_compress` match the file writer.

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
