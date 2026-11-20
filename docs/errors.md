# Error Handling

aiogzip normalizes errors into a small, stable taxonomy. The engine backing
decompression (stdlib zlib or zlib-ng from the `[fast]` extra) never changes
which exception type you see: engine-specific errors are caught internally and
re-raised uniformly, so `except` clauses written against stdlib behavior keep
working when the fast engine is installed.

The exception types and the explicitly documented decompression-limit message
prefix are part of the [2.0 stability contract](stability.md). Complete dynamic
messages are not: offsets, sizes, member numbers, engine names, and operating
system text may vary.

## Taxonomy

| Situation | Raises | Notes |
|---|---|---|
| Corrupt or malformed gzip data | `gzip.BadGzipFile` | Bad magic/header, CRC mismatch, wrong ISIZE, truncated or garbled deflate stream. Identical across engines. |
| Underlying I/O failure | `OSError` | Missing file, permission denied, disk errors — whatever the OS raised. |
| `max_decompressed_size` exceeded | `OSError` (not `BadGzipFile`) | Message starts with `"decompressed output exceeded max_decompressed_size"`. |
| Wrong argument types / values | `TypeError` / `ValueError` | Raised eagerly at the call with a corrective message. |
| Undecodable bytes in a text read | `UnicodeDecodeError` | A `ValueError` subtype, not an `OSError`. The reader stays open, but the failed read has consumed data. See [Text decoding and encoding errors](#text-decoding-and-encoding-errors). |
| Unencodable character in a text write | `UnicodeEncodeError` | A `ValueError` subtype. Nothing from the failed `write()` is written and the writer stays usable; `writelines()` keeps every line before the failing one. See [Text decoding and encoding errors](#text-decoding-and-encoding-errors). |
| Unknown `encoding` for a text handle | `LookupError` | Raised when the handle is constructed, before a file is opened. See [Unknown encodings and error handlers](#unknown-encodings-and-error-handlers). |
| Unknown `errors` handler for a text handle | `LookupError` | Not raised at construction: raised by the first read or write that needs the handler. See [Unknown encodings and error handlers](#unknown-encodings-and-error-handlers). |
| Overlapping operations on one async file | `aiogzip.ConcurrentOperationError` | An `OSError` subtype reporting a shared-handle ownership bug before state corruption. |
| Codec operation still active | `RuntimeError` | Exhaust the returned iterator before starting another operation. |
| Codec abandoned or partially closed | `OSError` on later use | The instance is unusable; call `discard()` and create a new codec. |
| Codec used after successful decoder finalization | `ValueError` | `feed()` and repeated `finish()` are terminal-state misuse. |
| Operations on a closed file | `ValueError` | Matches `io` module conventions, except that `async for` over a closed handle ends without raising (see below). |
| Reading a write-mode file (or vice versa) | `OSError` | e.g. `"File not open for reading"`. |
| `fast_compress=True` without zlib-ng | `UserWarning` (not an exception) | Compression falls back to stdlib zlib. See [Warnings](#warnings). |
| Unrecognized `AIOGZIP_ENGINE` value | `RuntimeWarning` (not an exception) | Issued when `aiogzip` is imported; the value is ignored. See [Warnings](#warnings). |

`gzip.BadGzipFile` subclasses `OSError`, so order your handlers from specific
to general:

```python
import gzip

import aiogzip

try:
    data = await aiogzip.read("untrusted.gz", max_decompressed_size=100 * 2**20)
except gzip.BadGzipFile:
    ...  # corrupt or hostile input: reject the file
except OSError as exc:
    ...  # I/O failure, or the decompression cap tripped (see below)
```

A `BadGzipFile` raised by a file handle, `aiogzip.read()`, `inspect()` or
`verify()` names the file in an exception note when a name is known: a path,
or the `name` of a file object. Python prints the note under the traceback and
exposes it as `__notes__`; the message itself is not rewritten:

```text
gzip.BadGzipFile: Error decompressing gzip data: Not a gzipped file (b'(\xb5'): looks like Zstandard
while reading 'data.zst'
```

Text decoding and encoding errors carry no such note.

## Closed and unopened handles

Reads, writes and seeks on a closed handle raise `ValueError`. Iteration is
the exception: `async for` over a closed binary or text handle yields nothing
and ends, as if at end of file, instead of raising. Check `closed` first if a
loop must distinguish a closed handle from an empty stream.

`flush()` on a write handle that has not been opened yet (constructed but not
entered with `async with`) returns without error: no gzip member has started,
so there is nothing to flush.

## Text decoding and encoding errors

A text handle (`AsyncGzipTextFile`, or `aiogzip.open()` in a text mode)
decodes and encodes with Python's codecs, using the handle's `encoding`
(default `"utf-8"`) and `errors` (default `"strict"`). The codec's exceptions
propagate unchanged. `UnicodeDecodeError` and `UnicodeEncodeError` subclass
`ValueError`, not `OSError`, so an `except OSError` clause that covers corrupt
gzip data does not cover them. Their messages are Python's, for example:

```text
UnicodeDecodeError: 'utf-8' codec can't decode byte 0xff in position 37: invalid start byte
UnicodeEncodeError: 'ascii' codec can't encode character '\xe9' in position 3: ordinal not in range(128)
```

### Reading: `UnicodeDecodeError`

`read()`, `readline()`, `readlines()` and iteration raise
`UnicodeDecodeError` when the decompressed bytes are not valid in the handle's
encoding. After the error:

- The handle is still open and is not terminal. The error is about the text
  encoding and says nothing about the file's integrity: it can be raised
  before the member's checksum has been checked.
- The failed read has consumed the whole chunk of decompressed bytes it was
  decoding. The next read resumes after that chunk and skips text without an
  error, possibly far more than the undecodable bytes themselves. If the
  chunk was the last one, the next read returns `''`, which looks like a
  clean end of file. Do not retry the read.
- Text decoded before the failing chunk and not yet returned stays buffered,
  and a later read returns it.
- The `position` in the message counts from the start of the chunk being
  decoded, not from the start of the file.
- `seek(0)` starts again from the beginning. It does not change the result:
  reading forward meets the same bytes and raises again.

A file that ends inside a multibyte character raises `UnicodeDecodeError`
(`unexpected end of data`) when a read reaches the end. Reading again raises
the same error instead of returning `''`; `seek(0)` rewinds as above.

To read such a file, reopen it with the correct `encoding`, or with an
`errors` handler such as `"replace"`, which substitutes U+FFFD for each
invalid byte sequence and does not raise.

### Writing: `UnicodeEncodeError`

`write()` raises `UnicodeEncodeError` when the string contains a character
the encoding cannot represent. Nothing from that call is written, including
the characters before the offending one, and the encoder is restored to the
state it had before the call. The writer stays usable: `tell()` is unchanged,
later writes and `flush()` work normally, and a byte-order mark is still
written only once.

`writelines()` writes every line before the one that fails to encode, and the
exception describes that line, as separate `write()` calls would. The failing
line and the lines after it are not written. The writer stays usable here
too. Before 2.0.1 the lines that shared a batch with the failing line were
also lost.

The exception is a `UnicodeEncodeError` raised by a custom `fileobj`'s own
`write()`. That is a sink failure: the writer is broken, as described under
[Custom sink errors](#custom-sink-errors-in-write-and-flush), and
`writelines()` does not retry line by line.

### Unknown encodings and error handlers

The two parameters are checked at different times:

- An unknown `encoding` raises `LookupError` (`unknown encoding: ...`) from
  the `AsyncGzipTextFile` constructor or from `aiogzip.open()`, before a file
  is opened or created. An empty `encoding` raises `ValueError`.
- An `errors` value that is neither a `str` nor `None` raises `TypeError`
  (`errors must be str or None, not int`) from the same place.
- An unknown `errors` handler name is not detected at construction. The handle
  opens, and reads and writes succeed for as long as the data needs no error
  handling. The first read that meets undecodable bytes, or the first write
  that meets an unencodable character, raises `LookupError` (`unknown error
  handler name '...'`) in place of the Unicode error. After a read, or a
  `write()`, the handle is in the state described above for the
  corresponding Unicode error. `writelines()` differs: the batch of lines
  that contains the failing line is not written at all, including the
  lines before it in that batch, because the line-by-line recovery runs
  only for `UnicodeEncodeError`. Batches completed earlier in the same
  call stay written.

`LookupError` is neither a `ValueError` nor an `OSError`.

## Warnings

aiogzip issues two warnings through Python's `warnings` module. Neither stops
the operation.

| Warning | Category | Issued when | How often |
|---|---|---|---|
| `fast_compress=True requested but zlib-ng is not available; falling back to stdlib zlib. ...` | `UserWarning` | A writer asks for `fast_compress=True` and zlib-ng is not installed, or `AIOGZIP_ENGINE=stdlib` has disabled it. Compression proceeds with stdlib zlib. | See below. |
| `Ignoring unrecognized AIOGZIP_ENGINE value '...'; expected 'stdlib' or 'zlib-ng'.` | `RuntimeWarning` | `aiogzip` is first imported with `AIOGZIP_ENGINE` set to a value other than `stdlib` or `zlib-ng` (compared after stripping whitespace and lowercasing). An empty or whitespace-only value is treated as unset and does not warn. The value is ignored, as if the variable were unset. | Once per process. |

The fallback warning is issued when the object is created, before any file
is opened:

- `AsyncGzipBinaryFile`, `AsyncGzipTextFile` and `aiogzip.open()` in a write
  mode: when the handle is constructed.
- `aiogzip.write()`: when the call is awaited.
- `GzipEncoder`: when the encoder is constructed.
- `compress_chunks()`: at the call, before the first chunk is requested.

Read-mode handles ignore `fast_compress` and do not warn.

The warning is attributed to your code: its location is the nearest caller
outside the `aiogzip` package, such as the line that calls `aiogzip.open()`.
Python's default filter therefore shows it once for each such line, however
many files that line opens. Under an `always` filter it is shown once for
each handle, encoder or `compress_chunks()` call.

To turn the warnings into errors in tests, use a `-W` option or the
`PYTHONWARNINGS` environment variable. Both take the
`action:message:category` form:

```bash
# Fail when fast compression silently falls back to stdlib zlib
python -m pytest -W "error:fast_compress=True requested:UserWarning"

# Fail on a mistyped AIOGZIP_ENGINE. The warning fires during import, so set
# the filter for the interpreter.
python -W error::RuntimeWarning -c "import aiogzip"
PYTHONWARNINGS=error::RuntimeWarning python -m pytest
```

With the fallback filter set to `error`, the `UserWarning` is raised as an
exception from the point listed above.

## Custom sink errors in `write()` and `flush()`

When a custom `fileobj`'s `write()` raises, the two calls report it
differently:

- `write()` lets the sink's exception propagate unchanged, whatever its type.
- `flush()` wraps any `Exception` that is not an `OSError` as
  `OSError("Unexpected error during flush: ...")`, with the original as
  `__cause__`. A sink's `OSError` normally propagates as raised (aiogzip
  rewrites only one whose message begins with its own internal
  `Unexpected error during compression flush:` prefix). Cancellation and
  interrupts such as `KeyboardInterrupt` propagate unwrapped.

Either way the writer is broken afterwards: discard the incomplete output and
create a new writer. Code that catches a sink's own exception type around
`flush()` should inspect `__cause__`. Unifying the two is a candidate for a
later release because it changes an exception type.

## Same-handle concurrency

One `AsyncGzipBinaryFile` or `AsyncGzipTextFile` handle is intentionally owned
by one task at a time. If a read, seek, write, flush, or close overlaps an
operation already in flight on that handle, the rejected call raises the
public `ConcurrentOperationError`. The active call is left intact. Treat the
exception as a programming error: it is not a lock, and catching it in a retry
loop is not supported synchronization. Separate handles may progress
concurrently because they do not share gzip or buffer state.

Handles are asyncio objects bound to the event loop that uses them; they are
not thread-safe. Do not call one handle from several threads or event loops.

When several tasks intentionally share a handle, use an application lock that
covers the complete logical operation, not only the first low-level call:

```python
import asyncio

lock = asyncio.Lock()

async with lock:
    batch = await stream.readlines(1024 * 1024)
```

The reservation covers text already decoded into the wrapper's buffer as well
as binary codec work. Composite `readlines()`, `writelines()`, and write-mode
`seek()` calls retain ownership across all of their internal reads or writes;
another task cannot consume a buffered prefix or splice data between batches.
If a text refill fails before the call can publish a result, characters decoded
before that failure remain buffered for the documented retry.

On a clean `async with` exit, aiogzip waits until all calls from a looping
producer finish and then closes normally. Concurrent close calls wait for the
same binary or text finalization. If the context body is already raising, exit
preserves that primary exception and attempts abortive owned-resource cleanup.
An active read, write, or flush that resumes after this abort raises `OSError`;
it never returns a truncated prefix or reports success for a gzip member that
can no longer receive its trailer. Cancellation delivered during cleanup still
propagates, and a failed abortive underlying close leaves the handle reportably
open so `close()` can be retried.

Once a handle has submitted the native close of an aiofiles file it owns (a
path, or a file object passed with `closefd=True`), cancellation cannot
abandon that close: it runs to completion before the cancellation propagates,
and a close failure becomes the cancellation's `__cause__`. During an
abortive exit, the handle is closed only if that close returned normally;
otherwise it stays reportably open and `close()` retries. A cancellation that
arrives while the exit is still waiting for an active call to settle no longer
skips the close: once that call has settled, the exit closes the file in the
same way and then propagates the cancellation. When the context body raised,
that cancellation keeps the body's exception in its chain: as its
`__context__`, or, when the close failed, as the context of the close failure
that is the cancellation's `__cause__`. Custom file objects' async `close()`
methods are cancelled cooperatively, as before.

Cancellation while a clean context exit is waiting for an active call also
attempts abortive owned-resource cleanup before the cancellation propagates.

If that abortive cleanup fails, for example because a custom source's
`close()` raises, the failure is recorded as a note beginning
`Context-exit cleanup also failed:` instead of being dropped. Exception types
and precedence are unchanged:

- When the context body raised, an ordinary exception from the cleanup is
  noted on the body's exception. A cancellation or interrupt delivered during
  the cleanup propagates instead, as before.
- When a cancellation interrupted a clean exit, the cancellation propagates
  and any cleanup failure is noted on it, including a failure carried as the
  cause of a repeated cancellation. A repeated cancellation on its own adds no
  note.

To abort an active read or write on a custom file object, the exit cancels
the task running that call once, and consumes that request however the call
ends, even if the custom object swallows the cancellation. An enclosing
`asyncio.timeout()` in that task therefore still reports its own expiry as
`TimeoutError`, and a separate outside cancellation of the task is kept.

The maintained examples avoid same-handle overlap entirely: each shard task
owns a separate file handle, and each transport codec operation is exhausted
before the next begins.

## Telling the decompression cap apart from corruption

A stream that exceeds `max_decompressed_size` (a decompression bomb, or just a
bigger file than expected) raises a plain `OSError`, **not** `BadGzipFile` —
the data may be perfectly valid gzip; it is the output budget that was
exceeded. Because the cap error is not a `BadGzipFile`, the handler split
above distinguishes the two cases by exception type alone. If you need to
single the cap out from real I/O errors within the `OSError` branch, match on
its stable message prefix:

```python
try:
    data = await aiogzip.read("untrusted.gz", max_decompressed_size=100 * 2**20)
except gzip.BadGzipFile:
    raise  # corrupt input: not the cap
except OSError as exc:
    if str(exc).startswith("decompressed output exceeded max_decompressed_size"):
        ...  # over budget: maybe retry with a larger cap
    else:
        raise
```

## Where errors surface

Decompressed bytes reach the caller in one of three states:

- **Provisional output:** bytes from a member whose trailer has not been
  checked yet. Normal reads deliver these as they decode; a later CRC,
  `ISIZE`, truncation or trailing-data error can still invalidate them.
- **Validated output:** every member has passed its trailer check once a
  file read reaches the end of the stream (`read()` or `read(n)` with
  `n > 0` returns empty without an error), once the operation returned by
  `GzipDecoder.finish()` is exhausted without an error, or once
  `decompress_chunks()` is exhausted without an error. An empty `read(0)`
  and an exhausted `feed()` operation validate nothing.
- **Recovery data:** bytes still readable after an integrity failure has
  been raised (see below). They are not validated and must not be trusted
  as that member's content.

> **Warning — successful output is not yet proof of integrity.**
> `GzipDecoder.feed()` and `decompress_chunks()` can produce payload before the
> member trailer arrives. CRC, `ISIZE`, truncation, and trailing-data errors may
> surface later. Exhaust `GzipDecoder.finish()` or the complete async iterator
> before treating the stream as valid.

Streaming helpers validate lazily where the work happens: the iterator
returned by `decompress_chunks()` raises `BadGzipFile` only as the corrupt
region is consumed, and complete trailer validation happens when the iterator
is exhausted. `verify()` and `inspect()` scan the whole stream eagerly and
raise before returning a result. See
[Processing untrusted gzip input](recipes.md#processing-untrusted-gzip-input)
for a full defensive-reading recipe.

## Recovery data after an integrity failure

High-level binary and text readers distinguish clean EOF from a poisoned
terminal state. Their integrity-failure lifecycle is:

```text
healthy
  -> integrity failure raised
  -> previously decoded recovery data may remain readable
  -> recovery data is drained
  -> stable terminal OSError

rewindable source:
  absolute seek(0) may construct a fresh decoder and recover

non-rewindable source:
  close and reopen/recreate the source
```

Recovery data is not proof that its gzip member is valid. Deflate output can
be emitted before a later CRC-32 or `ISIZE` trailer check fails, so applications
must not publish or trust that member's bytes merely because they were
readable. When codec metadata collection is enabled, trailer-validated prior
members remain in `GzipDecoder.members`; the failing member is absent. Those
records validate only the completed prefix, not the full concatenated stream.

After the recovery buffer is empty, later reads raise the same terminal
`OSError` instead of returning clean EOF. An absolute `seek(0)` can rebuild the
decoder only when the source can rewind (directly or through its replay cache).
Close and recreate a non-rewindable source. Decompression-limit failures,
cancellation, and unexpected internal failures poison the reader without
automatically enabling the integrity-failure salvage path.

For text readers, the only guaranteed recovery is calling `seek(0)` directly.
A cookie saved with `tell()` before the failure is not a recovery point:
`seek(cookie)` may raise the same terminal `OSError` instead of rewinding. Call
`seek(0)` first; once the reader has recovered, a saved cookie is an ordinary
position again.

An absolute text `seek()`, to a position or a `tell()` cookie, that fails or
is cancelled after it has moved the underlying binary reader makes the
reader terminal: later reads raise the same terminal `OSError` until
`seek(0)` recovers it. A seek that fails before moving the binary reader
leaves the text position where it was. If the binary reader is
still healthy, the text reader is unchanged and the seek can be retried.
Otherwise the binary reader's failure rules above apply: a gzip integrity
failure leaves the recovery state, so later reads return the recovered text
from the original position, and any other failure makes the reader terminal.
Either way, a failed absolute seek is never followed by text from the wrong
position. `seek(0, SEEK_END)` reads to the end, so its failures follow the
`read()` rules above, including the `UnicodeDecodeError` caution below.

Do not retry a text read that raised `UnicodeDecodeError`. The reader does
not become terminal, but the failed read has already consumed the whole chunk
of decompressed bytes it was decoding, so the next read resumes after that
chunk and silently skips text, possibly far more than the undecodable bytes
themselves. Call `seek(0)` to
start again from the beginning, or reopen the file with a different `encoding`
or an `errors` handler such as `"replace"`. See
[Text decoding and encoding errors](#text-decoding-and-encoding-errors) for
the handle's state after each Unicode error.

## Codec finalization and operation abandonment

Every state-changing `GzipEncoder` or `GzipDecoder` call reserves the codec and
returns a lazy `CodecOperation`. Engine errors, integrity failures, or closing
an operation before it is exhausted make that codec unusable. This is
intentional: the engine may already have consumed input, so silently reusing
the instance could skip bytes or emit a valid-looking trailer for incomplete
output.

Dropping an operation does not invoke state-changing finalizer behavior. The
codec remains reserved and another operation raises `RuntimeError` regardless
of garbage-collector timing. If the operation is reachable, exhaust it to
continue or call its idempotent `close()` method to abandon the stream. If the
caller no longer retains it, call the codec's idempotent `discard()` method;
this invalidates the operation and promptly releases its captured input and
codec state. Neither method resets the instance. Start again with a new codec.

`GzipDecoder.finish()` checks that the current deflate stream and trailer are
complete, that no partial next header remains, and that all CRC and `ISIZE`
values match. An incomplete or corrupt stream raises `gzip.BadGzipFile` and
poisons the decoder. After `finish()` succeeds, both another `feed()` and
another `finish()` raise `ValueError`.

The async wrappers follow the same rule internally. If cancellation occurs
while a worker thread is advancing an operation, they wait until that worker
has stopped before discarding state and re-raising cancellation. Source and
cleanup failures do not replace the primary operation error.
