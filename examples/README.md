# Maintained examples

The examples are credential-free, generate their own deterministic fixtures,
and use only aiogzip's public API.

## Fragmented transport

Run the public sans-I/O codec over a bounded local bidirectional asyncio byte
transport with an explicit two-byte-length frame protocol:

```bash
python examples/fragmented_transport.py
python examples/fragmented_transport.py --self-test
```

The self-test covers a successful stream, one-byte and varied frame sizes,
optional-header and trailer splits, concatenated members, truncated and corrupt
trailers, clean protocol termination versus transport EOF, early operation
abandonment, and retained-operation invalidation.

A sans-I/O codec is useful when an application already owns its transport and
needs gzip framing without giving a compression library control of sockets,
files, or scheduling. Codec operations are pull-driven reservations: exhaust
each operation before starting another, or call `operation.close()` when
abandoning it. Call codec-wide `discard()` for idempotent terminal cleanup.

Decoded payload may become visible before its gzip CRC and ISIZE trailer is
available. The example therefore labels records `receiving-provisional` until
`GzipDecoder.finish()` succeeds, then changes the stream to `verified`.
Previously displayed records remain provisional when a trailer is truncated or
corrupt.

The sender calls `flush()` after every JSON record to demonstrate low-latency
visibility. Frequent flushes cost compression efficiency. One long-lived gzip
member gives the best continuity but validates only at the final trailer;
member-per-batch designs add independently validated boundaries at the cost of
more headers, trailers, and compression resets.

This is a compact lifecycle and framing demonstration, not an official
transport abstraction or a promise that TCP reads correspond to writes. The
application-level length prefix makes fragmentation observable and testable.

### Implementation feedback

The public ownership model required one small `send_operation()` helper and a
matching receiver-side driver to pair exhaustion with `operation.close()`.
After those helpers were in place, no recurring ownership mistake, private
aiogzip hook, lifecycle workaround, or unbounded queue was needed. Explicit
provisional/verified state was the main application-level obligation exposed
by the integration.

## Concurrent staged JSONL ingest

Generate three deterministic standard-library gzip shards, ingest them with
bounded concurrency, and atomically publish a validated dataset:

```bash
python examples/concurrent_jsonl_ingest.py \
  --generate-fixtures ./demo-input \
  --output ./demo-published
```

Each input is an ordinary independent `.jsonl.gz` file owned by exactly one
task and one aiogzip handle. `iter_batches()` amortizes async line overhead
without retaining all records. Decoded bytes are parsed and written to a unique
sibling staging directory, but remain provisional until normal gzip exhaustion.
Only after every shard validates does the example write `manifest.json` and
rename the complete staging directory once.

The per-shard limit bounds one gzip expansion. The locked dataset budget counts
exact bytes written across all staged outputs, holding its lock only for
arithmetic. Invalid JSON is a separate application failure even when the gzip
framing is valid. Any corruption, limit, write failure, cancellation, or JSON
error cancels sibling work and removes staging without creating the final
destination.

Multiple independent files demonstrate useful async overlap; this is not a
custom striped format. Creating one lightweight task per known shard keeps the
example compact. Applications with very large input lists can use a fixed
worker pool while retaining the same one-handle-per-task rule.

### Ingest implementation feedback

The high-level API needed no private hook: `iter_batches()`, normal context
exit, decompression limits, `TaskGroup`, and application-owned staging were
sufficient. The main integration obligation was recognizing that batch output
is provisional until the iterator reaches normal EOF; atomic dataset
publication belongs to application code, not aiogzip.
