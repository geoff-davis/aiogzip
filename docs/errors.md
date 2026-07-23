# Error Handling

aiogzip normalizes errors into a small, stable taxonomy. The engine backing
decompression (stdlib zlib or zlib-ng from the `[fast]` extra) never changes
which exception type you see: engine-specific errors are caught internally and
re-raised uniformly, so `except` clauses written against stdlib behavior keep
working when the fast engine is installed.

## Taxonomy

| Situation | Raises | Notes |
|---|---|---|
| Corrupt or malformed gzip data | `gzip.BadGzipFile` | Bad magic/header, CRC mismatch, wrong ISIZE, truncated or garbled deflate stream. Identical across engines. |
| Underlying I/O failure | `OSError` | Missing file, permission denied, disk errors — whatever the OS raised. |
| `max_decompressed_size` exceeded | `OSError` (not `BadGzipFile`) | Message starts with `"decompressed output exceeded max_decompressed_size"`. |
| Wrong argument types / values | `TypeError` / `ValueError` | Raised eagerly at the call with a corrective message. |
| Codec operation still active | `RuntimeError` | Exhaust the returned iterator before starting another operation. |
| Codec abandoned or partially closed | `OSError` on later use | The instance is unusable; call `discard()` and create a new codec. |
| Codec used after successful decoder finalization | `ValueError` | `feed()` and repeated `finish()` are terminal-state misuse. |
| Operations on a closed file | `ValueError` | Matches `io` module conventions. |
| Reading a write-mode file (or vice versa) | `OSError` | e.g. `"File not open for reading"`. |

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

## Codec finalization and operation abandonment

Every state-changing `GzipEncoder` or `GzipDecoder` call reserves the codec and
returns a lazy operation iterator. Engine errors, integrity failures, or
closing an operation before it is exhausted make that codec unusable. This is
intentional: the engine may already have consumed input, so silently reusing
the instance could skip bytes or emit a valid-looking trailer for incomplete
output.

Dropping an operation does not invoke state-changing finalizer behavior. The
codec remains reserved and another operation raises `RuntimeError` regardless
of garbage-collector timing. If the operation is reachable, exhaust it to
continue or close it to abandon the stream. If it is unreachable, call the
codec's idempotent `discard()` method; this releases retained state but does
not reset the instance. Start again with a new codec.

`GzipDecoder.finish()` checks that the current deflate stream and trailer are
complete, that no partial next header remains, and that all CRC and `ISIZE`
values match. An incomplete or corrupt stream raises `gzip.BadGzipFile` and
poisons the decoder. After `finish()` succeeds, both another `feed()` and
another `finish()` raise `ValueError`.

The async wrappers follow the same rule internally. If cancellation occurs
while a worker thread is advancing an operation, they wait until that worker
has stopped before discarding state and re-raising cancellation. Source and
cleanup failures do not replace the primary operation error.
