# Synchronous sans-I/O codec

`GzipEncoder` and `GzipDecoder` expose aiogzip's RFC 1952 implementation
without taking ownership of files, sockets, an event loop, or any other
transport. They are synchronous state machines: callers provide immutable
`bytes`, consume bounded output chunks, and decide where those chunks go.

The public codec API is beta-frozen for the 2.0 line as of `2.0.0b1`.
Ordinary `asyncio` callers can continue using `open()`, `read()`, `write()`,
`compress_chunks()`, and `decompress_chunks()` without changing their code.
See the [stability policy](stability.md) for guarantees and non-guarantees.

## Encoding one member

One encoder creates exactly one complete gzip member. Each state-changing call
returns a lazy `CodecOperation` that must be exhausted before the next call:

```python
from aiogzip import GzipEncoder

encoder = GzipEncoder(mtime=0, output_chunk_size=64 * 1024)
wire = bytearray()
wire.extend(b"".join(encoder.start()))
wire.extend(b"".join(encoder.feed(b"hello ")))
wire.extend(b"".join(encoder.feed(b"world")))
wire.extend(b"".join(encoder.finish()))

assert encoder.finished
assert encoder.input_size == 11
```

`start()` emits the header, `feed()` accepts uncompressed input, `flush()`
performs a non-finalizing `Z_SYNC_FLUSH`, and `finish()` emits the final DEFLATE
bytes and trailer. Output chunks are non-empty and no larger than
`output_chunk_size`.

The constructor accepts the same compression, metadata, and safety options as
the file writer:

- `compresslevel` is an integer from `-1` through `9`;
- `mtime` is `None` or a non-negative integer or float; floats are truncated,
  and the resulting value must fit gzip's unsigned 32-bit field;
- `original_filename` follows the file API's type, basename, `.gz` suffix, and
  embedded-NUL rules;
- `fast_compress=True` opts into zlib-ng when it is installed;
- `strict_size=True` rejects input beyond gzip's 4 GiB `ISIZE` range; and
- `output_chunk_size` is an integer from 1 through 128 MiB.

`fast_compress` and `strict_size` require the exact built-in values `True` or
`False`. Integer stand-ins such as `0` and `1`, strings, and custom truthy or
falsy objects raise `TypeError`; aiogzip does not call their `__bool__` or
`__len__` methods. Validation happens before the compression engine is
constructed or an unavailable-zlib-ng warning can be emitted.

## Decoding complete streams

A decoder accepts zero or more concatenated gzip members plus permitted NUL
padding. Feed it arbitrary compressed boundaries and then exhaust `finish()`
to prove that the complete stream, final trailer, and any trailing bytes are
valid:

```python
from aiogzip import GzipDecoder

decoder = GzipDecoder(
    output_chunk_size=64 * 1024,
    max_decompressed_size=100 * 1024 * 1024,
)
plain = bytearray()
plain.extend(b"".join(decoder.feed(first_network_chunk)))
plain.extend(b"".join(decoder.feed(second_network_chunk)))
plain.extend(b"".join(decoder.finish()))

assert decoder.finished
```

Input boundaries are arbitrary for correctness, but they are not
performance-neutral. For predictable memory and copy costs, pass
transport-sized compressed chunks as they arrive instead of one complete
large archive to a single `feed()` call. The span queue prevents a large source
item from causing superlinear whole-suffix copies, but transport-sized items
still bound snapshot lifetime and executor workload. `AsyncGzipBinaryFile`
reads according to its configured `chunk_size`; callers of
`decompress_chunks()` control the size of each source item.

> **Warning — integrity is established only at normal completion.** `feed()`
> may emit payload before the corresponding CRC-32 and `ISIZE` trailer arrives.
> Decompression integrity is not established until the iterator returned by
> `finish()` has been exhausted. Likewise, `decompress_chunks()` is not fully
> validated until its async iterator is exhausted. If output must not be acted
> on before complete validation, use `verify()` first or stage the output until
> validation succeeds.

`max_decompressed_size` is a cumulative positive-integer limit. Every inflate
step is bounded to the remaining allowance plus one probe byte. Every allowed
byte is emitted before a later advancement raises `OSError` for the first byte
over the limit. That probe byte is not yielded and is not included in
`uncompressed_size`, CRC-32, or ISIZE accounting. Corrupt, truncated, or
malformed gzip data raises `gzip.BadGzipFile`.

Pass `collect_member_info=True` when member metadata is needed. After each
member's trailer is validated, `members` gains a `GzipMemberInfo` entry and
`member_count` advances. Metadata for an incomplete or corrupt member is never
committed.

`collect_member_info` likewise requires exact `True` or `False`; `0`, `1`, and
other truthy or falsy substitutes are rejected before decoder state is built.

Completed records survive a later member failure, an abandoned operation, or
an explicit `discard()`. They describe only members whose CRC and ISIZE
trailers validated; they do not mean the complete concatenated stream is
valid, and no record is created for the failed member. Check `finished` to
distinguish successful whole-stream completion. Collection remains opt-in
because retained records consume memory proportional to the member count.

```python
import gzip

import aiogzip

decoder = aiogzip.GzipDecoder(collect_member_info=True)
try:
    # Feed transport chunks and exhaust decoder.finish().
    ...
except gzip.BadGzipFile:
    for member in decoder.members:
        report_already_validated_member(member)
```

Payload emitted from the failed member is recovery data, not validated output.
The decoder remains unusable after the failure or discard even though earlier
metadata remains available.

After successful completion, another decoder `feed()` or `finish()` raises
`ValueError`. Repeated encoder finalization and invalid method ordering also
raise `ValueError`; create a new codec for another stream.

## Counter timing

The counters reflect different commitment boundaries:

- `GzipEncoder.input_size` and `crc32` change when a `feed()` operation
  advances far enough to pass its complete snapshot through the compression
  engine. Calling `feed()` without advancing its operation does not change
  them.
- `GzipDecoder.compressed_size` changes when `feed()` returns, after its input
  has been validated and snapshotted but before the operation advances.
- `GzipDecoder.uncompressed_size` changes as inflate steps complete. Internal
  output is accounted before its bounded public chunks are yielded, so the
  counter can temporarily lead the bytes already consumed by the caller.
- `member_count` and `members` change only after a complete member trailer has
  been validated.

## Lazy operations and ownership

Calls reserve the codec immediately, but engine work occurs as the returned
operation iterator advances. Exhaust one operation before requesting another.
This keeps output pull-driven and bounded without a producer task, background
queue, or eager `list()` allocation.

A decoder `feed()` snapshots and counts its complete argument at call time,
but advancing the operation reads compressed input through bounded 256 KiB
windows. Inflate output is produced in separate internal batches that adapt
between 64 KiB and 256 KiB, then sliced to the caller's `output_chunk_size`.
Consequently
`compressed_size` can lead engine consumption during an active operation, and
`uncompressed_size` can lead public delivery by at most the pending internal
batch. These are accounting boundaries, not evidence that the complete input
or output has been copied into a second contiguous buffer.

Abandonment is deliberately deterministic:

- ignoring an unadvanced or partially advanced operation leaves the codec
  reserved;
- the next state-changing method raises `RuntimeError`, regardless of whether
  garbage collection has run;
- explicitly closing a partially consumed operation makes the codec unusable;
- no iterator finalizer releases ownership or mutates codec state; and
- `discard()` permanently invalidates the codec and any retained operation,
  immediately releasing the operation's captured input and the codec's mutable
  and incomplete state while preserving validated member records.

When an operation is still reachable, exhaust it if the stream should remain
usable. Otherwise call its idempotent `close()` method. A `try`/`finally`
ensures an exception or early return cannot leave the codec reserved:

```python
import aiogzip


def decode_chunk(decoder: aiogzip.GzipDecoder, chunk: bytes) -> bytes:
    operation: aiogzip.CodecOperation = decoder.feed(chunk)
    try:
        return b"".join(operation)
    finally:
        operation.close()
```

Calling `close()` after exhaustion has no effect. Calling it earlier releases
the operation and makes the codec unusable. If the caller no longer retains
the operation, use the codec's idempotent `discard()` method; it invalidates
active work and promptly releases both the captured operation input and the
codec's mutable and incomplete state. Already trailer-validated member records
remain available. Neither method resets the codec, so construct a new instance
to continue.

Codec instances and their operation iterators are **not thread-safe**. Use an
instance from one thread at a time, or hold an external lock around the entire
call-and-exhaust operation lifecycle. The same rule excludes overlapping
advancement from multiple tasks.

## Immutable input boundary

Codec `feed()` accepts exact `bytes` and `bytes` subclasses. Exact `bytes`
takes the zero-copy path. A subclass is copied at call time from its immutable
raw buffer into an exact built-in `bytes`, without invoking its overridable
Python methods. Mutable and general buffer objects such as `bytearray` and
`memoryview` are rejected.

This boundary prevents lazy output from changing when input storage is mutated
and prevents subclass overrides from altering compression or accounting.
High-level file `write()` retains its broader buffer-protocol API: its wrapper
first snapshots a non-exact buffer, then passes exact `bytes` to the codec.
Consequently an uncommon `bytes` subclass pays one codec normalization copy,
while a mutable high-level write pays one wrapper snapshot copy. Ordinary
exact `bytes` pays neither.

## Relationship to the async APIs

The codec module performs no I/O and imports neither `asyncio` nor `aiofiles`.
It does not use an executor or start background tasks. The high-level async
wrappers own sources, sinks, backpressure, cancellation, and executor policy;
they may offload sufficiently large codec steps so other tasks can progress.

The 2.0 codec handles complete gzip streams only. A public raw-DEFLATE mode,
AnyIO/Trio abstraction, indexed seeking, and new engine APIs are out of scope.
See the [architecture decision](adr-sans-io-codec.md) for the ownership and
engine-boundary rationale.
