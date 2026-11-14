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
- `CodecOperation` — the closeable iterator returned by codec state changes
- `ConcurrentOperationError` — an `OSError` subtype for operations that
  overlap on one single-task-owned async file handle
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

## Parameters

`open()`, `AsyncGzipFile`, `AsyncGzipBinaryFile` and `AsyncGzipTextFile` take
the same parameters. The text class adds `encoding`, `errors` and `newline`.
`open()` and `AsyncGzipFile` choose the class from `mode` and pass the other
arguments to it.

| Parameter | Default | Used when | Accepted by |
| --- | --- | --- | --- |
| [`filename`](#filename) | required | reading and writing | binary and text |
| [`mode`](#mode) | `"rb"` (`"rt"` for `AsyncGzipTextFile`) | reading and writing | binary and text |
| [`chunk_size`](#chunk_size) | `262144` (256 KiB) | reading and writing | binary and text |
| [`encoding`](#encoding) | `"utf-8"` | reading and writing | text |
| [`errors`](#errors) | `"strict"` | reading and writing | text |
| [`newline`](#newline) | `None` | reading and writing | text |
| [`compresslevel`](#compresslevel) | `6` | writing | binary and text |
| [`mtime`](#mtime) | `None` | writing | binary and text |
| [`original_filename`](#original_filename) | `None` | writing | binary and text |
| [`fileobj`](#fileobj) | `None` | reading and writing | binary and text |
| [`closefd`](#closefd) | `None` | reading and writing | binary and text |
| [`max_decompressed_size`](#max_decompressed_size) | `None` | reading | binary and text |
| [`max_rewind_cache_size`](#max_rewind_cache_size) | `134217728` (128 MiB) | reading | binary and text |
| [`strict_size`](#strict_size) | `False` | writing | binary and text |
| [`fast_compress`](#fast_compress) | `False` | writing | binary and text |

`open()` and `AsyncGzipFile` take `filename` and `mode` positionally and
everything else by keyword. The two classes also accept the other parameters
positionally, but their order differs (the text class has `encoding`, `errors`
and `newline` after `chunk_size`), so pass them by keyword. An unknown keyword
raises `TypeError`.

### When arguments are checked

Calling `open()`, `AsyncGzipFile` or a class constructs a handle and checks
its arguments. It does not open or create anything: the file is opened by
`async with` or `await f.open()`. An invalid argument therefore raises before
any file is opened, and before any method of a `fileobj` is called. Each
parameter below names the exception it raises. There are two exceptions to
the rule:

- An unknown `errors` name is not detected until the first encoding or
  decoding error.
- The text class emits the `fast_compress` fallback warning when the handle
  is opened, not when it is constructed.

A parameter that is used only for writing is ignored by a reader, and a
parameter that is used only for reading is ignored by a writer. Its value is
still checked in the other mode, with one exception: `compresslevel` is not
checked on a reader.

### `filename`

A path as `str`, `bytes` or an `os.PathLike` object such as `pathlib.Path`,
or `None` when `fileobj` is given.

- With no `fileobj`, the path is opened when the handle is opened.
- With a `fileobj`, the path is not opened. It is reported by the handle's
  `name` property and, on a writer, supplies the name stored in the gzip
  header unless `original_filename` is given.
- With `filename=None`, `name` falls back to the `name` attribute of the
  `fileobj`, if it has one.

Raises `ValueError` if `filename` and `fileobj` are both `None`, or if
`filename` is the empty string. Raises `TypeError` for any other type; if the
value looks like a file object, the message says to pass it as `fileobj=`.

### `mode`

One of `r` (read), `w` (write, truncating), `x` (write, failing with
`FileExistsError` if the path exists) or `a` (append), with an optional `b`
(binary) or `t` (text). The characters may come in any order.

- `open()` and `AsyncGzipFile` default to `"rb"`. They return an
  `AsyncGzipTextFile` when the mode contains `t` and an `AsyncGzipBinaryFile`
  otherwise, so `"r"` is binary, as in `gzip.open()`.
- `AsyncGzipBinaryFile` defaults to `"rb"` and rejects `t`.
  `AsyncGzipTextFile` defaults to `"rt"` and rejects `b`.
- Append mode adds a new gzip member after the existing data. See
  [Append mode and concatenated gzip members](recipes.md#append-mode-and-concatenated-gzip-members).
- A `+` is accepted and added to the mode used to open the path. It does not
  make the handle both readable and writable: a handle opened with `r` only
  reads, and one opened with `w`, `x` or `a` only writes.

Raises `TypeError` if `mode` is not a string. Raises `ValueError` if it is
empty, has no `r`, `w`, `x` or `a`, has more than one of them, repeats `b`,
`t` or `+`, has both `b` and `t`, or contains any other character. In a
binary mode, `open()` and `AsyncGzipFile` raise `ValueError` for an
`encoding`, `errors` or `newline` other than `None`.

### `chunk_size`

A number of bytes from 1 to 134217728 (128 MiB). The default is 262144
(256 KiB), also available as `AsyncGzipBinaryFile.DEFAULT_CHUNK_SIZE`.

- Reading: the number of compressed bytes requested from the file or
  `fileobj` in each read. A text reader also asks its binary layer for at
  most this many decompressed bytes at a time.
- Writing: `writelines()` joins items smaller than `chunk_size` into batches
  of at most `chunk_size` (bytes in binary mode, characters in text mode) and
  writes larger items directly.

`chunk_size` is not a memory limit and does not bound what a `read()`
returns. See [Choose the Right Chunk Size](performance.md#1-choose-the-right-chunk-size)
for tuning and
[Processing untrusted gzip input](recipes.md#processing-untrusted-gzip-input)
for memory.

Raises `TypeError` if the value is not an `int` (a `bool` or `float` is
rejected). Raises `ValueError` if it is below 1 or above 128 MiB.

### `encoding`

Text only. The name of the text encoding. The default is `"utf-8"`, and
`None` means the default.

Raises `ValueError` for the empty string and `LookupError` for an unknown
encoding.

### `errors`

Text only. The name of the codec error handler, such as `"strict"`,
`"replace"`, `"ignore"` or `"surrogateescape"`. It applies to decoding on a
reader and to encoding on a writer. The default is `"strict"`, and `None`
means the default.

With `"strict"`, undecodable input raises `UnicodeDecodeError` from the read
and unencodable text raises `UnicodeEncodeError` from the write. The name is
not checked when the handle is constructed: an unknown name raises
`LookupError` from the first read or write that meets an encoding or decoding
error.

### `newline`

Text only. One of `None`, `""`, `"\n"`, `"\r"` or `"\r\n"`, with the same
meaning as in `io.TextIOWrapper`. The default is `None`.

| `newline` | Reading | Writing |
| --- | --- | --- |
| `None` | `\r\n` and `\r` are returned as `\n`; lines end at `\n` | `\n` is written as `os.linesep` |
| `""` | nothing is translated; lines end at `\n`, `\r` or `\r\n` | nothing is translated |
| `"\n"` | nothing is translated; lines end at `\n` | nothing is translated |
| `"\r"` | nothing is translated; lines end at `\r` | `\n` is written as `\r` |
| `"\r\n"` | nothing is translated; lines end at `\r\n` | `\n` is written as `\r\n` |

Because `newline=None` writes `\n` as `os.linesep`, the same program produces
`\r\n` on Windows and `\n` elsewhere. Pass `newline=""` or `newline="\n"` to
write the text unchanged on every platform.

Raises `ValueError` for any other string.

### `compresslevel`

Writing only. An integer from `-1` to `9`. The default is `6`. `0` stores
the data without compression, `1` is fastest, `9` compresses most, and `-1`
selects the compression library's default level.

Raises `TypeError` if the value is not an `int` (a `bool` or `float` is
rejected) and `ValueError` if it is outside `-1` to `9`. A reader ignores
`compresslevel` and does not check it.

### `mtime`

Writing only. The timestamp stored in the gzip header, in seconds since the
epoch, from `0` to `4294967295` (2³² − 1). A `float` is truncated to an
integer. The default, `None`, stores the current time when the handle is
opened. Pass a fixed value such as `mtime=0` for
[reproducible gzip output](recipes.md#reproducible-gzip-output).

Raises `TypeError` if the value is not an `int` or `float` (a `bool` is
rejected). Raises `ValueError` if it is negative, infinite or NaN, or if
its truncated value is above 2³² − 1 (so `4294967295.9` is accepted as
`4294967295`).

A reader checks the value and then ignores it. The `mtime` *property* of a
reader reports the timestamp read from the stream; see
[Live member timestamps](#live-member-timestamps).

### `original_filename`

Writing only. The name stored in the gzip header's `FNAME` field, as `str`
or `bytes`. The default, `None`, takes the name from `filename`; if
`filename` is also `None`, no name is stored.

In either case the stored name is the final path component with a trailing
`.gz` removed, so `original_filename="/a/b/c.tar.gz"` stores `c.tar`. A `str`
is stored as Latin-1; a name that cannot be encoded as Latin-1 is left out.
Pass `original_filename=""` to store no name. See
[Reproducible gzip output](recipes.md#reproducible-gzip-output).

Raises `TypeError` if the value is not `str` or `bytes` (an `os.PathLike`
object is rejected) and `ValueError` if it contains a NUL. A reader checks
the value and then ignores it.

### `fileobj`

An already-open asynchronous file object to read from or write to in place of
a path. A reader needs an `async read(size)` method that returns `bytes`; a
writer needs an `async write(data)` method that returns the number of bytes
it accepted. `close()`, `seek()` and `seekable()` are used when present. The
default is `None`.

A synchronous file object such as `io.BytesIO` is not rejected when the
handle is constructed. It raises `TypeError` (on a writer) when the handle is
opened, or `OSError` (on a reader) at the first read. See
[External async file objects](recipes.md#external-async-file-objects).

### `closefd`

Whether closing the handle also closes `fileobj`. It must be `True`, `False`
or `None`.

- `None` (the default) and `False`: the `fileobj` is left open.
- `True`: the `fileobj` is closed with the handle.

`closefd` has no effect on a file that the handle opened from a path. That
file is always closed with the handle. See
[Opening ownership](recipes.md#opening-ownership) for what happens when
opening fails.

Raises `TypeError` for any value other than `True`, `False` or `None`; see
[Exact boolean options](#exact-boolean-options).

### `max_decompressed_size`

Reading only. The largest number of decompressed bytes the reader will
produce in one pass through the stream, as a positive integer. The limit is
in bytes in text mode too. The default, `None`, sets no limit. Crossing the
limit raises `OSError` from the read. A stream of exactly the limit is
accepted. Set it when reading untrusted input; see [Safety limits](#safety-limits) and
[Processing untrusted gzip input](recipes.md#processing-untrusted-gzip-input).

Raises `TypeError` if the value is not an `int` or `None` (a `bool` or
`float` is rejected) and `ValueError` if it is below 1. A writer checks the
value and then ignores it.

### `max_rewind_cache_size`

Reading only, and only when the source cannot seek. To let such a reader
`seek()` backward, the handle keeps the compressed bytes it has read so that
it can replay them. This parameter is the largest size of that cache in
bytes, as a positive integer. The default is 134217728 (128 MiB). `None`
sets no limit.

When the next chunk would take the cache over the limit, the cache is
discarded. From then on `seekable()` returns `False` and a backward `seek()`
raises `OSError`; forward reading is unaffected. A source that can seek is
rewound directly and uses no cache. See [Seeking](recipes.md#seeking).

Raises `TypeError` if the value is not an `int` or `None` (a `bool` or
`float` is rejected) and `ValueError` if it is below 1. A writer checks the
value and then ignores it.

### `strict_size`

Writing only. The gzip trailer stores the uncompressed size of a member
modulo 2³². With `False` (the default), a larger member is written and its
stored size wraps, as the format allows. With `True`, a write that would
take the member past 4294967295 bytes raises `OSError`.

Raises `TypeError` for any value other than `True` or `False`. A reader
checks the value and then ignores it.

### `fast_compress`

Writing only. With `True`, the writer compresses with zlib-ng if the
`aiogzip[fast]` extra is installed. The output is valid gzip but is not
byte-for-byte identical to the default output. If zlib-ng is not available,
the writer warns (`UserWarning`) and uses the standard library's zlib. The
default is `False`. See
[Optional Faster Codec](performance.md#optional-faster-codec-aiogzipfast-zlib-ng).

Raises `TypeError` for any value other than `True` or `False`. A reader
checks the value, then ignores it and does not warn.

### Parameters of the whole-file helpers

`read()`, `write()`, `inspect()` and `verify()` take `filename` positionally
and a subset of the parameters above by keyword. Each has the meaning,
default, range and exceptions given above. The helpers are coroutines, so an
invalid argument raises when the call is awaited.

| Function | Keyword parameters |
| --- | --- |
| `read(filename)` | `chunk_size`, `fileobj`, `closefd`, `max_decompressed_size`, `max_rewind_cache_size` |
| `write(filename, data)` | `chunk_size`, `compresslevel`, `mtime`, `original_filename`, `fileobj`, `closefd`, `strict_size`, `fast_compress` |
| `inspect(filename)` | `chunk_size`, `fileobj`, `closefd`, `max_decompressed_size` |
| `verify(filename)` | `chunk_size`, `fileobj`, `closefd`, `max_decompressed_size` |

`write()` takes `data` as `bytes`, `bytearray` or `memoryview`.
`compress_chunks()`, `decompress_chunks()`, `GzipEncoder` and `GzipDecoder`
document their own parameters in the reference below.

## Exact boolean options

Public boolean configuration uses exact built-in booleans. `fast_compress`,
`strict_size`, and the codec's `collect_member_info` accept only `True` or
`False`. `closefd` accepts `True`, `False`, or `None`; `None` keeps the ownership
default, closing path-opened resources while preserving caller-supplied file
objects. Integer substitutes such as `0` and `1`, strings, and custom truthy or
falsy objects raise `TypeError` with the parameter name.

The contract is identical across `AsyncGzipBinaryFile`,
`AsyncGzipTextFile`, `open()`, `AsyncGzipFile`, the whole-file helpers, the
async-iterable compressor, and the synchronous codec. Validation happens
before file acquisition, external file methods, source iteration, zlib-ng
warning logic, or codec operation reservation. This contract was tightened
during the alpha series and is frozen for 2.0; it is not a security fix.

For writers, `strict_size=False` preserves gzip's normal modulo-2³² `ISIZE`;
`strict_size=True` rejects a member crossing that field's range.
`fast_compress=False` keeps stdlib-compatible output, while
`fast_compress=True` opts that writer into zlib-ng when available and otherwise
emits the documented fallback warning. Explicit `closefd=False` preserves a
caller-supplied file object; `closefd=True` closes it with the wrapper.

## Live member timestamps

In read mode, `AsyncGzipBinaryFile.mtime` is `None` until the shared gzip
parser completes the first valid member header. It then holds that header's
32-bit timestamp. Each later valid header in a concatenated stream replaces
the value, including repeated timestamps and zero.

The property follows parser progress rather than only the bytes returned to
the caller. If one compressed source chunk contains several members, decoder
read-ahead can leave `mtime` at the last header in that chunk even when the
current `read()` returned bytes from an earlier member. This means the exact
point at which the property advances can depend on `chunk_size` and source read
boundaries.

A complete header updates `mtime` before its DEFLATE body or trailer is
validated, so a later body, CRC, or ISIZE error does not roll the timestamp
back. An invalid or incomplete header does not commit; a rejected first header
therefore leaves `mtime=None`, while a rejected later header preserves the
last valid value. After a rewind, the old value remains visible until a header
is parsed again. `AsyncGzipTextFile.mtime` delegates to the same binary reader
state.

## Synchronous codec

Use `GzipEncoder` and `GzipDecoder` when an application owns a synchronous or
custom transport and needs aiogzip's framing, concatenated-member traversal,
integrity validation, and output limits without any I/O or executor policy.
Each state-changing call returns a lazy `CodecOperation` that must be exhausted
before another operation begins. Its idempotent `close()` method provides
deterministic cleanup when a caller exits before exhaustion.

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

The public codec API is frozen for the 2.0 line. See the
[stability policy](stability.md) and [synchronous codec guide](codec.md) for
the compatibility boundary, constructor validation, immutable input
snapshots, lifecycle hazards, thread safety, and error behavior.

With `collect_member_info=True`, `GzipDecoder.members` contains immutable
records only for members whose trailers validated. Those completed records
remain available if a later member fails or the codec is explicitly discarded;
the incomplete member is absent and the codec remains unusable. Retained
records prove only those members, not the entire concatenated stream. Use
`decoder.finished` as the whole-stream completion indicator. Collection is
opt-in because its memory use grows with the member count.

::: aiogzip.codec.CodecOperation

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

`inspect()` holds every member's record until it returns, so its memory grows
with the number of members; `verify()` keeps only running totals. While it
parses a header, `inspect()` (like `GzipDecoder` with
`collect_member_info=True`) buffers each `FNAME`, `FCOMMENT` and `FEXTRA` field
whole and keeps it in the member's record. `FEXTRA` is at most 64 KiB by the
format, but `FNAME` and `FCOMMENT` are bounded only by the header limit: any
single gzip header larger than 128 MiB raises `gzip.BadGzipFile`.
`max_decompressed_size` does not count header bytes. Scanning untrusted input
with many members or very large header fields can therefore use substantial
memory; prefer `verify()` when per-member metadata is not needed.

Cancelling `inspect()` or `verify()` waits for any native open, read or close
already running in a worker thread to finish before the cancellation
propagates. A native read still queued for a worker is skipped and never
touches the source. A file opened by path is closed once, and only after its last
read; if that close itself fails, the failure is reported as below. A
borrowed `fileobj` is closed only when `closefd=True`.

If the scan fails and closing the source then fails too, the scan's error is
raised with the close failure attached as a note. A cancellation or interrupt
that arrives during that close outranks an ordinary scan error and
propagates, with the scan error as its context. If the scan succeeded, a
close failure is raised as before.

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
