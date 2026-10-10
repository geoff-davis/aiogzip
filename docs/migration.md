# Migrating from `gzip.open`

`aiogzip.open()` accepts the same paths, modes, and keyword arguments as the
stdlib's `gzip.open()`, and it reads and writes the same `.gz` format. Exactly
three things change:

aiogzip 2.0 requires Python 3.11 or newer. On Python 3.8 through 3.10, normal
dependency resolution continues selecting the newest compatible 1.x release;
pin `aiogzip<2` when an explicit upper bound is preferred. Upgrade the
interpreter before moving to 2.0.

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

Most asyncio callers do not need to change their code. The high-level
`open()`, `AsyncGzipFile()`, `read()`, `write()`, `inspect()`, `verify()`,
`compress_chunks()`, and `decompress_chunks()` APIs keep their names,
signatures and asynchronous lifecycle, and files remain interoperable. The
main compatibility change is the Python 3.11 floor.

The 1.x line receives security fixes only, until 2027-04-30. Python 3.10, the
last interpreter that only 1.x supports, reached end of life on 2026-10-01.

### Behavior changes since 1.11

2.0 makes several behaviors stricter or more precisely defined. Code that
relied on the 1.11 behavior below should be checked. This list covers the
key changes; each item links to the detailed rule, and the changelog has the
rest.

- **Overlapping calls on one handle** raise the public
  `ConcurrentOperationError`, an `OSError` subtype, instead of interleaving.
  The call already in flight is unaffected. Give each task its own handle or
  hold an application lock across the whole logical operation. See
  [Same-handle concurrency](errors.md#same-handle-concurrency).
- **`mtime` in read mode** reports the most recently completed member header.
  On a concatenated stream, read-ahead can move it past the member whose bytes
  the current read returned. See
  [Live member timestamps](api.md#live-member-timestamps).
- **A failed or cancelled read of a custom source** leaves the reader usable
  only if the failure is proven to have consumed no input. Otherwise the
  reader is terminal until a `seek(0)` completes, or until the source is
  reopened. An `OSError` alone no longer means that a retry is safe. A native
  aiofiles read is different: once started, it finishes before the
  cancellation propagates, and the reader keeps its bytes for the next read.
  See
  [Source failures and cancellation](recipes.md#source-failures-and-cancellation).
- **A custom source's synchronous `tell()`**, if it has one, provides that
  proof. It is now called before each physical read and seek, and after a
  failure, so it must be cheap and free of side effects. Async `tell()`
  methods do not count. A source without a synchronous `tell()` still works,
  but a failed read on it leaves the reader terminal until `seek(0)`.
- **After an integrity failure** (a CRC-32 or `ISIZE` mismatch), output
  already decoded stays readable as unvalidated recovery data, and later
  reads raise the terminal `OSError` instead of returning a clean EOF. The
  recovery data is not proof that its member is valid. See
  [Recovery data after an integrity failure](errors.md#recovery-data-after-an-integrity-failure).
- **A text read that raises `UnicodeDecodeError`** does not make the reader
  terminal, but it has already consumed the chunk it was decoding. Do not
  retry it: call `seek(0)`, or reopen the file with another `encoding` or an
  `errors` handler such as `"replace"`. See
  [Recovery data after an integrity failure](errors.md#recovery-data-after-an-integrity-failure),
  which ends with this rule.
- **Text recovery after a failure** goes through `seek(0)`. A `tell()` cookie
  saved before the failure may be refused with the terminal `OSError`; once
  `seek(0)` has recovered the reader, the cookie is an ordinary position
  again. Text cookies are valid only on the handle that produced them. See
  [`seek()` and `tell()` in text mode](api.md#seek-and-tell-in-text-mode).
- **Cancellation waits for native I/O** already running in a worker thread:
  cancellation cannot abandon a native open, read, write, flush or seek, or a
  submitted close, so no part of the stream is skipped. A cancellation can
  therefore take as long as the blocked call. If a submitted close fails,
  the failure becomes the cancellation's cause, and an aborted handle stays
  reportably open so that `close()` can be retried. See
  [Cancellation](recipes.md#cancellation) and
  [Same-handle concurrency](errors.md#same-handle-concurrency).
- **Boolean options are exact**, as described below.

### Exact Boolean options

Pass the exact built-in values `True` or `False` for `fast_compress`,
`strict_size`, and the direct decoder's `collect_member_info`. Integer
stand-ins (`0`, `1`), strings such as `"false"`, and custom truthy or falsy
objects raise `TypeError`:

```python
aiogzip.GzipEncoder(fast_compress=False)  # valid
aiogzip.GzipEncoder(fast_compress=0)      # TypeError
```

`closefd` accepts exact `True`, exact `False`, or `None`. `None` preserves the
ownership default: a resource opened from a path is closed by aiogzip, while a
caller-supplied `fileobj` remains open. Use an explicit Boolean only when
overriding that default.

### The synchronous codec

aiogzip 2.0 also adds synchronous `GzipEncoder` and `GzipDecoder` classes for
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

`GzipEncoder`, `GzipDecoder`, and `CodecOperation` are public and have been
frozen for the 2.0 line since `2.0.0b1`. See the
[stability policy](stability.md) for the exact compatibility boundary.

Next steps: [Examples](examples.md) for common tasks,
[Recipes](recipes.md) for streaming patterns, and the
[Performance Guide](performance.md) for tuning.
