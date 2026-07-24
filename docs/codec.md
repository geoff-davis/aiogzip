# Synchronous sans-I/O codec

`GzipEncoder` and `GzipDecoder` expose aiogzip's RFC 1952 implementation
without taking ownership of files, sockets, an event loop, or any other
transport. They are synchronous state machines: callers provide immutable
`bytes`, consume bounded output chunks, and decide where those chunks go.

The codec API is provisional throughout the 2.0 alpha series. Ordinary
`asyncio` callers can continue using `open()`, `read()`, `write()`,
`compress_chunks()`, and `decompress_chunks()` without changing their code.

## Encoding one member

One encoder creates exactly one complete gzip member. Each state-changing call
returns a lazy iterator that must be exhausted before the next call:

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
large archive to a single `feed()` call. `AsyncGzipBinaryFile` reads according
to its configured `chunk_size`; callers of `decompress_chunks()` control the
size of each source item.

> **Warning — integrity is established only at normal completion.** `feed()`
> may emit payload before the corresponding CRC-32 and `ISIZE` trailer arrives.
> Decompression integrity is not established until the iterator returned by
> `finish()` has been exhausted. Likewise, `decompress_chunks()` is not fully
> validated until its async iterator is exhausted. If output must not be acted
> on before complete validation, use `verify()` first or stage the output until
> validation succeeds.

`max_decompressed_size` is a cumulative positive-integer limit. Every inflate
step is bounded to the remaining allowance plus one byte, and no byte beyond
the configured limit is emitted. Limit failures raise `OSError`; corrupt,
truncated, or malformed gzip data raises `gzip.BadGzipFile`.

Pass `collect_member_info=True` when member metadata is needed. After each
member's trailer is validated, `members` gains a `GzipMemberInfo` entry and
`member_count` advances. Metadata for an incomplete or corrupt member is never
committed.

After successful completion, another decoder `feed()` or `finish()` raises
`ValueError`. Repeated encoder finalization and invalid method ordering also
raise `ValueError`; create a new codec for another stream.

## Lazy operations and ownership

Calls reserve the codec immediately, but engine work occurs as the returned
operation iterator advances. Exhaust one operation before requesting another.
This keeps output pull-driven and bounded without a producer task, background
queue, or eager `list()` allocation.

Abandonment is deliberately deterministic:

- ignoring an unadvanced or partially advanced operation leaves the codec
  reserved;
- the next state-changing method raises `RuntimeError`, regardless of whether
  garbage collection has run;
- explicitly closing a partially consumed operation makes the codec unusable;
- no iterator finalizer releases ownership or mutates codec state; and
- if an abandoned operation is unreachable, `discard()` is the only cleanup.
  It permanently invalidates the codec and releases its retained state.

When an operation is still reachable, exhaust it if the stream should remain
usable. Otherwise close the operation and discard the codec. `discard()` is
idempotent, but it is not a reset; construct a new instance to continue.

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

This alpha handles complete gzip streams only. A public raw-DEFLATE mode,
AnyIO/Trio abstraction, indexed seeking, and new engine APIs are out of scope.
See the [architecture decision](adr-sans-io-codec.md) for the ownership and
engine-boundary rationale.
