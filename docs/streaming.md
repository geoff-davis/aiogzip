# Async-iterable streaming

Use `decompress_chunks()` when compressed gzip bytes arrive as an
`AsyncIterable[bytes]` rather than through a file object's `read()` method.
Paths and file objects belong with `open()`, `read()`, `inspect()`, or
`verify()`; this API is deliberately limited to asynchronous iterables.

```python
import aiogzip


async def compressed_source():
    async for chunk in receive_compressed_bytes():
        yield chunk


async for data in aiogzip.decompress_chunks(compressed_source()):
    await consume(data)
```

The source must yield `bytes`. Empty byte chunks are ignored. Synchronous
iterables and other item types are rejected rather than being converted
implicitly.

## Chunking and backpressure

Input and output boundaries are independent. A gzip header, deflate block, or
trailer may span any number of input items, and one input item may produce many
output chunks. Every yielded chunk is non-empty and no larger than
`output_chunk_size` (256 KiB by default).

The iterator is pull-driven: it requests compressed input only when the
consumer requests more decompressed output. It creates no producer task or
queue and holds only the current source item, incomplete gzip structure, codec
state, and bounded output. Concatenated gzip members are decoded transparently.

```python
async for data in aiogzip.decompress_chunks(
    compressed_source(),
    output_chunk_size=64 * 1024,
):
    await consume(data)
```

A zero-byte compressed source produces no output, matching a zero-byte file.
This differs intentionally from streaming compression, where an empty payload
must still produce a valid empty gzip member.

## Integrity validation

The iterator validates gzip headers, optional header CRCs, deflate data,
per-member CRC-32 values, trailer `ISIZE` values, concatenated members, and
final stream completeness. Complete validation requires consuming the iterator
to normal completion.

Payload bytes can be yielded before the corresponding member trailer is
available. A later corrupt trailer or truncated source therefore raises after
the consumer has already processed earlier output. This is inherent to
streaming validation; use `verify()` first when output must not be acted on
until the entire stream is known to be valid.

For untrusted input, set an application-specific cumulative output limit:

```python
async for data in aiogzip.decompress_chunks(
    compressed_source(),
    max_decompressed_size=100 * 1024 * 1024,
):
    await consume(data)
```

The codec is limited to the remaining allowance plus one byte on each inflate
call, so overflow is detected without first materializing an arbitrarily large
expansion. Exceeding the limit raises `OSError`.

## Early exit and cancellation

Stopping iteration stops source consumption immediately. The unconsumed gzip
tail is not drained or validated. For deterministic cleanup when breaking
early, explicitly close the returned async generator:

```python
import aiogzip


stream = aiogzip.decompress_chunks(compressed_source())
try:
    async for data in stream:
        if await consume_until_done(data):
            break
finally:
    await stream.aclose()
```

Finalization discards decoder buffers and calls `aclose()` on the source
iterator when it provides that async-generator lifecycle method. It does not
promise to close an unrelated transport or resource owned by the source.

Cancellation while waiting for input or codec work propagates
`asyncio.CancelledError`, stops pulling the source, and discards decoder state.
Unlike a reusable file reader, a one-shot streaming iterator has no recovery
state: discard it and start a new stream if needed.

Each returned iterator is single-consumer. Do not issue overlapping `anext()`
calls from multiple tasks; normal async-generator concurrency protection raises
`RuntimeError` instead of allowing codec-state corruption.

Argument validation for `source`, `output_chunk_size`, and
`max_decompressed_size` happens when `decompress_chunks()` is called. Source
item errors, corruption, I/O-like source failures, and cancellation occur while
the iterator is consumed.
