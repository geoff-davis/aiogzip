# ADR: One synchronous sans-I/O gzip codec

**Status:** Decided for the 2.0 alpha series (2026-07-22); bounded buffering
amendment accepted for `2.0.0a2` (2026-07-26)

## Context

aiogzip 1.x has separate gzip state machines in its binary-file, async
streaming, and inspection implementations. Keeping framing, trailer validation,
member traversal, limits, and engine bookkeeping aligned across those paths is
difficult. It also prevents users from applying aiogzip's gzip behavior to
transports other than files and asynchronous iterables.

The 2.0 alpha needs one reusable core without taking ownership of I/O or an
event loop. The public API is provisional during the alpha series; the existing
high-level asyncio APIs retain their normal compatibility expectations.

## Decision

Add synchronous `GzipEncoder` and `GzipDecoder` classes in `aiogzip.codec` and
re-export them from the package root. They handle complete RFC 1952 streams:
gzip headers, raw DEFLATE engine state, trailers, CRC and ISIZE validation,
concatenated members, permitted NUL padding, limits, and optional member
metadata.

The codec performs no file, socket, or asynchronous I/O. It does not import
`asyncio` or `aiofiles`, schedule executor work, or create background tasks.
Async wrappers retain responsibility for sources and sinks, executor policy,
cancellation, buffering, seeking, and text handling. Raw DEFLATE, AnyIO/Trio,
ISA-L, and indexed seeking are outside this alpha.

## Lazy operations and ownership

Every state-changing method returns a lazy, single-use `CodecOperation` of
non-empty `bytes` chunks bounded by `output_chunk_size`. The protocol extends
`Iterator[bytes]` with `close()`, making deterministic abandonment available
to type checkers without exposing the concrete operation class. A successful
call reserves its codec before it returns; only exhausting the operation
commits it and releases that reservation.

The reservation is codec-owned and independent of reachability of the returned
iterator. Dropping an iterator does not release, commit, close, or poison the
operation through garbage-collector side effects. A later state-changing call
therefore raises `RuntimeError` deterministically on both reference-counted and
tracing garbage collectors. If the operation is still reachable, explicitly
closing it makes the codec unusable. If the caller no longer retains it,
`discard()` is the codec-owned cleanup and makes the codec unusable.

`discard()` is idempotent and immediately invalidates a retained operation.
Advancing that operation afterward raises `RuntimeError` without yielding
buffered data or touching engine state; closing it is harmless. In `a2`,
invalidation also closes and drops the operation's underlying generator before
the reservation token is removed, promptly releasing captured feed input even
when the public operation object remains reachable. Exceptions after engine
state changes also make the codec unusable. Async wrappers must always exhaust
or explicitly close operations and must not depend on finalizer timing.

This ownership rule supplies bounded, pull-driven output without a producer
task or unbounded result list. It is a misuse guard, not synchronization.
Codec instances and operation iterators are not thread-safe. Use one instance
from one thread at a time, or externally lock the complete operation lifecycle.

## Immutable input snapshots

Public codec `feed()` methods accept `bytes`, including subclasses, but reject
`bytearray`, `memoryview`, and other buffer objects. Exact `bytes` use the
zero-copy path. A subclass is copied at call time from its immutable raw buffer
into an exact built-in `bytes`, without invoking overridable `__bytes__`,
`__len__`, iteration, indexing, or slicing behavior. Snapshot validation occurs
before the codec reserves an operation, so failure leaves an otherwise usable
codec untouched.

Mutable buffers are incompatible with lazy operations: mutation after `feed()`
returns could otherwise make output depend on when the iterator advances. A
`bytes` subclass has immutable storage and remains source-compatible, but the
normalization copy prevents its Python overrides from changing compression or
accounting. Thus ordinary exact bytes remain free of a copy, while uncommon
subclasses pay one deliberate copy.

High-level APIs preserve their established input boundaries. Async iterable
sources still require bytes instances. File `write()` still accepts its broader
buffer-protocol inputs. Before codec or executor work, wrappers normalize every
accepted non-exact input—including subclasses and mutable buffers—to an exact
bytes snapshot. This is the second intentional copy boundary for transports
that supply mutable storage.

## Validation and errors

Codec constructors share the file API's validators rather than duplicating
policy:

- `output_chunk_size` is an integer from 1 through 128 MiB; booleans and floats
  are rejected.
- `compresslevel` is an integer from -1 through 9.
- `mtime` is `None` or a non-negative integer/float whose integer truncation
  fits gzip's uint32 field. `None` samples the time when `start()` builds the
  header.
- `original_filename` preserves the shared type and NUL checks.
- `max_decompressed_size` is `None` or a positive integer.

Invalid types use `TypeError`; invalid options and ordinary terminal-state
misuse use `ValueError`; concurrent or invalidated operation advancement uses
`RuntimeError`. Malformed gzip data uses `gzip.BadGzipFile`. Resource limits,
strict encoding size, wrapped encoder-engine failures, and a codec poisoned by
a prior partial operation use `OSError`.

## Engine boundary

Only the private engine adapter may interpret `unused_data` and
`unconsumed_tail`. It reports explicit output, consumed-input count, and EOF to
the codec. The codec retains its own pending input, detects no-progress steps,
and never assumes that engine-owned leftover fields alias or overlap. This
keeps stdlib zlib and zlib-ng behavior aligned and permits future engines with
different post-EOF semantics without exposing an engine-specific public API.

## Bounded decoder buffering

`2.0.0a1` retained accepted compressed input in one `bytearray`. Each body step
converted the complete remaining suffix to `bytes`, and consumption deleted
from the front. Large one-item feeds therefore repeated work over progressively
smaller suffixes and scaled superlinearly.

`2.0.0a2` uses a deque of immutable byte spans with a cursor into the first
span. Consuming a partial span advances its offset; consuming a complete span
releases that reference. Body inflation pops at most a 256 KiB compressed
window. Engine-retained bytes are normalized by the engine adapter and
prepended once, so the queue never depends on aliasing behavior of
`unused_data` or `unconsumed_tail`.

Inflate output has its own adaptive 64–256 KiB private batch limit. One output
cursor holds
that block and yields slices bounded by the caller's independent
`output_chunk_size`, releasing the block when drained. Tiny public chunks
therefore do not multiply engine calls. During an active operation,
`compressed_size` already includes the complete call-time snapshot while
engine read-ahead is bounded by one private input window;
`uncompressed_size` can include the current private output block before all of
its public slices have been pulled.

Header parsing uses the same span queue but maintains explicit state for fixed
fields, FEXTRA, FNAME, FCOMMENT, and FHCRC. It consumes bytes once, updates
header CRC incrementally, and retains optional metadata only when requested.
NUL padding advances queue cursors and trailers use exact eight-byte reads.
The header safety check runs before accepting the first byte beyond its limit.

The decompression limit permits internal production of one probe byte after
the remaining allowance. All allowed bytes are accounted and drained first;
the next advancement raises `OSError` without yielding, CRC-accounting, or
size-accounting the probe byte.

Wrapper-only source rechunking was rejected because direct `GzipDecoder.feed()`
would retain the same defect and callers may legitimately supply complete
archives. Retaining one shifting buffer was rejected because it cannot avoid
whole-suffix conversion and front deletion. A segmented queue plus bounded
engine windows fixes the shared codec and therefore every transport.

## Async bridge and cancellation

A private async driver pulls one codec event at a time. Cheap steps run inline;
the first raw advancement of work at or above 256 KiB uses the executor.
Private no-output progress events let the driver account for bounded inflate
work without exposing empty public chunks. It checkpoints after 1 MiB or 4,096
inline output chunks, or after 1 MiB or eight consecutive no-output steps.
It does not call `list(operation)` and does not read another source item until
all output for the current item is consumed.

Offloading every `next()` call was rejected because most later advances only
slice an already-produced block, making a thread hop more expensive than the
work and obscuring whether the synchronous step is bounded. The chosen
thresholds keep large engine work off the loop while cooperative checkpoints
bound long inline drains. The M3 tuning evidence is recorded in the WP3-WP5
benchmark reports; final release claims require the Framework Desktop rerun.

If cancellation happens while a worker may still be advancing an operation,
the wrapper waits for that worker to finish before discarding the codec and
re-raising `CancelledError`. No replacement operation may race the old worker,
and cleanup failures must not replace the original cancellation or source
exception.

## Fallback if alpha feedback rejects iterator ownership

The bounded alternative is a pull-style operation object with an explicit
`next_chunk()` method and mandatory `close()`/context-manager lifecycle. It
would keep codec-owned reservation tokens, snapshot semantics, output bounds,
and deterministic abandonment behavior while making ownership more visible.
It would not be replaced with eager lists, background queues, or unbounded
accumulation. Such an API change is eligible for a later alpha, before the
codec surface becomes stable.

## Consequences

There is one production gzip state machine and transport wrappers become
independently reviewable. Users can drive gzip over memory or custom transports
without an event loop. The tradeoffs are an explicit iterator lifecycle, an
intentional copy for non-exact inputs, and a documented single-threaded usage
model.
