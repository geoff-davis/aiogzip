# Maintained examples

Maintained examples are credential-free, deterministic, bounded, exercised by
the test and platform matrix, and restricted to aiogzip's public API. They are
complete application workflows rather than copy-only snippets: success,
integrity failure, cancellation, and cleanup behavior are part of their
contract.

Both examples require Python 3.11 or newer. `fragmented_transport.py` needs
only aiogzip and the standard library. `concurrent_jsonl_ingest.py` also uses
`aiofiles`, which is an aiogzip runtime dependency and is installed with the
wheel. Neither requires credentials, services, zlib-ng, HTTPX, or a
development-only runtime package.

Functions and classes whose names start with `_`, the frame format,
`DatasetBudget`, staging layout, manifest schema, and status labels are
example-owned application code. They are not aiogzip API. Only names imported
from the top-level `aiogzip` package are library contracts.

## Run from a clean checkout

From the repository root:

```bash
uv sync --all-extras
uv run python examples/fragmented_transport.py --self-test
uv run python examples/concurrent_jsonl_ingest.py \
  --generate-fixtures ./demo-input \
  --output ./demo-published
```

The ingest command requires new `demo-input` and `demo-published` paths. Remove
or rename an earlier demo run before repeating it.

## Run against the built wheel

Build from the repository root, create an isolated environment, and invoke the
repository-owned example files with that environment's interpreter. Because
the scripts live under `examples/`, the checkout's `src/` directory is not on
their import path; `aiogzip` resolves from the installed wheel.

```bash
uv build
python -m venv .venv-example
.venv-example/bin/python -m pip install \
  dist/aiogzip-2.0.0a4.dev0-py3-none-any.whl
.venv-example/bin/python examples/fragmented_transport.py --self-test
.venv-example/bin/python examples/concurrent_jsonl_ingest.py \
  --generate-fixtures ./wheel-demo-input \
  --output ./wheel-demo-published
```

On Windows, replace `.venv-example/bin/python` with
`.venv-example\\Scripts\\python.exe`.

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

Inputs must use nonempty `<partition>.jsonl.gz` names, and their derived
`.jsonl` output names must remain distinct under cross-platform case folding.
Publication uses the operating system's atomic no-replace rename operation, so
a destination created by another publisher is preserved and the ingest fails.

The per-shard limit bounds one gzip expansion. The locked dataset budget counts
exact bytes written across all staged outputs, holding its lock only for
arithmetic. Invalid JSON is a separate application failure even when the gzip
framing is valid. Any corruption, limit, write failure, cancellation, or JSON
error cancels sibling work and removes staging without creating the final
destination. Cleanup is awaited to completion even when cancellation is
requested repeatedly; no cleanup task is left running after the ingest returns.

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
