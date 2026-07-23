# aiogzip 2.0.0a1 Release Plan

> **Revision 3 — final contract polish (2026-07-22).**
> This revision retains all Revision 2 decisions and additionally accepts `bytes` subclasses through a call-time exact-`bytes` snapshot, defines advancement of a `discard()`-invalidated operation as `RuntimeError`, and makes clear that benchmark thresholds apply only to baseline-backed comparable operations—not new codec-only microbenchmarks.

**Release theme:** public sans-I/O gzip codec and a single shared codec core
**Target version:** `2.0.0a1`
**Development version while work is in progress:** `2.0.0a1.dev0`
**Primary issue:** GitHub issue #70, “2.0: extract a sans-IO codec layer”
**Explicitly deferred:** issue #71 (AnyIO/Trio substrate) and issue #72 (indexed random access)
**Intended location in the repository:** `plans/RELEASE_2_0_0A1_PLAN.md`
**Audience:** maintainer, reviewers, and Codex
**Locked 1.x branch point:** `v1.11.0` / `3f23eadb524c8dba840c4fd855ad5acf84486048`

---

## 0. Locked preflight decisions

### 0.1 The 1.x maintenance branch starts at the published release

Create the remote `1.x` branch from exactly:

```text
v1.11.0
3f23eadb524c8dba840c4fd855ad5acf84486048
```

This is the reviewed merge commit from which `v1.11.0` was published. Do not
branch `1.x` from the later documentation-only merge
`d5c9c6b19c7abfdaff9da665505a4894ccabc340`.

If the upstream-link improvement to `docs/adr-isal.md` belongs on the maintenance
line, cherry-pick the underlying documentation commit
`b91da9acbd0031ba117e4f72dd071ab6231be256` after creating `1.x`. Keeping that
optional documentation change separate preserves an unambiguous, reproducible
branch point at the released and tested artifact.

- [ ] Maintainer creates and pushes `1.x` at the exact release commit above.
- [ ] Codex verifies the branch point before WP0 and reports a mismatch; Codex
      must not move or create the remote branch itself.

### 0.2 Capture the performance baseline before changing the environment

Before editing the Python floor, `uv.lock`, engine dependencies, benchmark code,
or production code, create a separate worktree at the exact `v1.11.0` commit
above and capture the benchmark categories listed in WP8. This is the first
executable task for the release and blocks WP0.

Record a concise, reviewable baseline in:

```text
plans/benchmarks/v1.11.0-baseline.md
```

The record must include:

- the full baseline commit SHA and capture date;
- OS, CPU, architecture, power/governor state, and relevant storage details;
- Python executable path, implementation, full version/build, and uv version;
- stdlib zlib version, zlib-ng package/version, and selected engine mode;
- `uv.lock` hash, relevant environment variables, fixture hashes, and exact
  benchmark commands;
- medians, sample counts, dispersion where the harness reports it, and peak
  memory for the release-gating cases;
- any warm-up, affinity, load-control, or background-process precautions.

Keep raw machine-specific output as a local or pull-request artifact unless the
repository already has a convention for committing it. Commit the concise
baseline record and its checklist update immediately as the preflight commit
(or as the first commit in the WP0 pull request), before any WP0 environment or
production change. Do not reconstruct the baseline later from a changed
interpreter, codec build, lockfile, or machine configuration.

- [x] `plans/benchmarks/v1.11.0-baseline.md` exists before WP0 is declared
      complete.
- [x] The baseline uses `AIOGZIP_ENGINE=stdlib` for the primary gate and records
      a representative zlib-ng run separately.

---

## 1. Instructions to Codex

Treat this document as the implementation specification for the release.

Before editing code:

1. Read `AGENTS.md`, `CLAUDE.md`, `CHANGELOG.md`, `README.md`, `SECURITY.md`, `pyproject.toml`, and `.codexrc`.
2. Read issue #70 and `docs/adr-isal.md`.
3. Read the existing implementations in:
   - `src/aiogzip/_binary.py`
   - `src/aiogzip/_streaming.py`
   - `src/aiogzip/_inspection.py`
   - `src/aiogzip/_engine.py`
   - `src/aiogzip/_common.py`
4. Read the streaming, encoder, inspection, binary I/O, lifecycle, cancellation, seeking, engine, and public-export tests before refactoring.
5. Verify the locked branch point and benchmark-baseline artifact in section 0.
6. Record the starting test count, coverage percentage, and current public exports.

Execution rules:

- Work through the work packages in order.
- Keep the repository green at the end of every work package.
- Prefer one reviewable pull request or commit series per work package.
- Do not combine the complete refactor into a single unreviewable change.
- If keeping a work package green requires changing code assigned to a later
  package, stop and report the dependency. Do not silently pull later work
  forward, broaden the current package, or reorder the plan merely to make an
  intermediate commit pass.
- Add characterization tests before changing behavior that is not already pinned down.
- Do not weaken, delete, or broadly rewrite an existing test merely to make the refactor pass.
- Do not change existing high-level public signatures unless this plan explicitly calls for it.
- Do not implement AnyIO, Trio, raw DEFLATE, permessage-deflate, ISA-L, or indexed seeking in this release.
- Do not create a tag, publish to PyPI, change branch protection, close issues, or create a GitHub release. Those are maintainer actions.
- When repository behavior conflicts with this plan, preserve documented 1.11 behavior and report the conflict in the pull request rather than silently choosing a new behavior.
- Update the checklist in this file in the same commit as the work it
  describes. Mark only behavior, tests, or documentation present in that commit;
  do not pre-check future work or use a later bookkeeping-only commit to make the
  plan appear current.

Required checks before every commit:

```bash
uv run prek run --all-files
uv run pytest
```

Required checks before declaring a work package complete:

```bash
uv run prek run --all-files
AIOGZIP_ENGINE=stdlib uv run pytest \
  --cov --cov-report=term-missing --cov-fail-under=85
uv run pytest --cov --cov-report=term-missing --cov-fail-under=85
uv run mypy src
uv run ty check src
```

Run targeted tests during development; do not wait until the end to run the full suite.

---

## 2. Executive decision

The next release should be **`2.0.0a1`**, not `1.12.0` and not a stable `2.0.0`.

The release should do one architectural job completely:

> Expose a synchronous, pure sans-I/O gzip encoder and decoder, then make the existing asyncio file, async-iterable, and inspection APIs use that shared codec implementation.

An alpha is the correct release level because this introduces a new public API and replaces the central compression/decompression machinery under mature high-level APIs. The alpha gives downstream users a real artifact to exercise while preserving room to refine the new codec API before beta.

The Python floor moves to 3.11 as already announced for the 2.0 line. The high-level asyncio API remains source-compatible apart from that interpreter requirement.

---

## 3. Release outcome

The release is successful when all of the following are true:

1. Users can import `GzipEncoder` and `GzipDecoder` from `aiogzip.codec` and from the package root.
2. The codec works synchronously with no event loop, file object, `aiofiles`, executor, or background task.
3. The codec owns gzip framing, header parsing, trailer validation, concatenated-member handling, NUL padding, CRC/ISIZE validation, size limits, and optional member metadata.
4. Async wrappers own only source/sink I/O, executor offload, cancellation handling, buffering, seeking, and async iteration.
5. `_streaming.py`, `_inspection.py`, and `_binary.py` no longer maintain separate gzip state machines.
6. Existing asyncio APIs retain their documented behavior, error classes, bounded-memory guarantees, cancellation rules, and interoperability.
7. Decompression consumption accounting is isolated behind an engine adapter and does not depend on zlib’s post-EOF aliasing behavior.
8. The full test suite passes on Python 3.11 through 3.14, on the existing representative Windows and macOS jobs, with both stdlib zlib and zlib-ng paths exercised.
9. The package builds, documentation builds strictly, and the release artifact reports `2.0.0a1`.
10. Benchmark regressions are within the gates in this plan or are explicitly approved and documented.

---

## 4. Scope

### 4.1 In scope

- Public `aiogzip.codec` module.
- Public `GzipEncoder` and `GzipDecoder`.
- Pure synchronous incremental codec operations.
- Bounded lazy output.
- One gzip member for an encoder instance.
- Zero or more gzip members for a decoder instance.
- Concatenated members.
- Gzip header metadata currently supported by inspection.
- Trailer CRC and ISIZE validation.
- Optional cumulative decompressed-size limit.
- Existing strict 4 GiB ISIZE guard for encoding.
- Non-finalizing `Z_SYNC_FLUSH` support for the encoder.
- Engine-neutral decompressor-step accounting.
- Async bridge for running codec operations inline or in an executor.
- Migration of async iterable compression/decompression.
- Migration of inspection and verification.
- Migration of binary writer and reader.
- Preservation of text behavior through the binary layer.
- Python 3.11 minimum.
- Documentation, API reference, migration guide, changelog, and release notes.
- Benchmark and memory regression validation.

### 4.2 Explicit non-goals

Do not add any of the following to `2.0.0a1`:

- AnyIO or Trio support.
- A replacement for `aiofiles`.
- Raw DEFLATE mode or configurable `wbits`.
- WebSocket permessage-deflate support.
- ISA-L/python-isal support.
- Indexed or checkpoint-based random access.
- A persistent gzip index format.
- A separate `aiogzip-codec` distribution.
- Background producer tasks or queues in streaming APIs.
- New compression formats.
- A text-layer redesign.
- A general cleanup or modernization of unrelated modules.
- A stable `2.0.0` compatibility promise for the alpha codec API.

---

## 5. Fixed design decisions

These decisions resolve the open questions in issue #70 for this alpha. Do not reopen them during implementation unless a correctness problem makes the design impossible.

### D1. Package placement

The codec lives in:

```text
src/aiogzip/codec.py
```

It is part of the existing `aiogzip` distribution.

### D2. Public names

Expose:

```python
from aiogzip.codec import GzipDecoder, GzipEncoder
```

Also re-export both names from `aiogzip.__init__` and include them in `aiogzip.__all__`.

### D3. Gzip-only surface

The alpha supports complete RFC 1952 gzip streams only. It does not expose raw DEFLATE or a public `wbits` option.

### D4. Member ownership

The codec owns:

- gzip header construction and parsing;
- optional filename, comment, extra field, and header CRC handling;
- raw DEFLATE engine state;
- gzip trailer construction and validation;
- CRC32 and ISIZE accounting;
- concatenated members;
- permitted NUL padding between or after members;
- compressed and uncompressed byte counts;
- optional completed-member metadata;
- malformed/truncated stream detection.

Wrappers own:

- files, paths, sockets, or asynchronous iterables;
- reads and writes;
- async iteration and backpressure;
- executor scheduling;
- cancellation policy;
- file buffering;
- seeking and rewind caches;
- text encoding/newline handling.

### D5. Purity boundary

`aiogzip.codec` must not import or call:

- `asyncio`;
- `aiofiles`;
- any file-opening function;
- any executor API;
- any background-task or queue API.

The codec may use the package’s synchronous engine selection and gzip helper functions.

### D6. Input types and immutable snapshot semantics

Public codec `feed()` accepts `bytes` instances, including subclasses. Before
reserving the codec, normalize the accepted input to an exact built-in `bytes`
snapshot:

- exact `bytes` may be retained without copying;
- a `bytes` subclass is copied from its underlying buffer into exact `bytes` at
  call time;
- the subclass snapshot must use raw buffer contents and must not consult
  overridable Python behavior such as `__bytes__`, `__len__`, iteration, or
  slicing;
- `bytearray`, `memoryview`, and arbitrary non-`bytes` buffer objects raise
  `TypeError` at the public codec boundary.

Implement this behavior once in a shared private helper, recommended name
`_snapshot_bytes_input`, rather than duplicating exact-type and subclass logic
in the encoder and decoder. Snapshotting is part of call-time validation and
must complete before the operation token is reserved; a snapshot failure leaves
the codec untouched and available for a later legal call.

The distinction is intentional:

- Lazy operations make caller-mutable storage unsound. A caller could change a
  `bytearray` after `feed()` returns but before its iterator is advanced, making
  output depend on timing and violating snapshot semantics.
- A `bytes` subclass has immutable underlying storage, so rejecting it is not
  justified by mutation risk. It is nevertheless normalized because subclasses
  may override Python-level methods used by accounting or conversion. The codec
  must consume the immutable raw byte buffer, not subclass-defined behavior.
- Exact `bytes` therefore remains the zero-copy fast path. Transport
  integrations receiving mutable frames pay an explicit copy before calling
  the codec; uncommon `bytes` subclasses pay a call-time normalization copy.

High-level file and streaming APIs preserve their established public input-type
acceptance. Before they call the codec or schedule executor work, every accepted
input must be an exact built-in `bytes` snapshot. In particular, accepted
`bytes` subclasses must be normalized from raw buffer contents rather than
passed through unchanged, while file `write()` continues accepting its existing
mutable and general buffer inputs.

Record this rationale, the subtype-compatibility decision, and both copy
boundaries in `docs/adr-sans-io-codec.md` so alpha feedback does not treat the
behavior as accidental.

### D7. Output model

Every state-changing codec method returns a lazy, single-use `Iterator[bytes]`.

All yielded chunks must be:

- non-empty;
- no larger than `output_chunk_size`;
- produced incrementally rather than accumulated into an unbounded list.

An operation may yield no chunks.

### D8. Operation ownership, abandonment, and garbage collection

Only one operation may be active on a codec at a time.

Calling `start()`, `feed()`, `flush()`, or `finish()` performs call-time
validation and then reserves the codec synchronously, before returning the
operation iterator. The reservation is represented by codec-owned state whose
lifetime does not depend on whether the returned Python object remains
reachable.

- Advancing an operation reentrantly or starting another state-changing
  operation while one is active raises `RuntimeError`.
- Exhausting an operation commits it and releases the codec for the next legal
  operation.
- Explicitly closing an operation before exhaustion marks the codec unusable.
- Merely dropping an iterator does **not** commit, release, close, or poison the
  operation through `__del__`, a weakref callback, or generator-finalizer side
  effects. The codec remains reserved. A later state-changing method therefore
  raises `RuntimeError` deterministically even if the abandoned iterator has
  already been collected by CPython, PyPy, or another implementation.
- When an iterator has been dropped and can no longer be exhausted or closed,
  `discard()` is the only legal cleanup action. It invalidates any outstanding
  operation, releases pending buffers and engine state, and makes future codec
  operations fail.
- An exception while advancing an operation marks the codec unusable unless it
  is a call-time validation error raised before engine state changes.
- `discard()` is idempotent and may be called while an operation is active.
- After `discard()` returns, advancing any retained operation invalidated by that
  call raises `RuntimeError` deterministically. It must not yield buffered
  output, touch engine state, or change the codec's terminal status. Closing an
  already-invalidated operation is idempotent and has no state-changing effect.
- Async wrappers must explicitly exhaust or close every operation. Their
  correctness, poisoning behavior, and cleanup must not depend on garbage
  collection timing.

Implement this with a private operation object and an independent codec-owned
operation token. Do not rely on generator finalizers to mutate codec state.

### D9. Error taxonomy

Preserve these categories:

- `TypeError` for invalid input types or incompatible protocol objects.
- `ValueError` for invalid options and ordinary state misuse such as finalizing twice.
- `RuntimeError` for concurrent/reentrant operation advancement and for
  advancing an operation invalidated by `discard()`.
- `gzip.BadGzipFile` for malformed gzip headers, invalid DEFLATE payloads, CRC/ISIZE failures, truncated members, and invalid trailing data.
- `OSError` for resource-limit failures, strict-size failures, wrapped engine failures on encoding, and a codec made unusable by a prior partial operation.

Preserve useful existing message fragments that tests or documentation rely on. Exact punctuation need not be frozen unless an existing test requires it.

### D10. Metadata

Move result dataclasses to a neutral private module, recommended:

```text
src/aiogzip/_metadata.py
```

Move:

- `GzipMemberInfo`
- `GzipInfo`
- `VerificationResult`

Keep aliases imported in `_inspection.py` so old private-module lookups do not fail unnecessarily. Preserve package-root exports and class behavior.

`GzipDecoder.members` contains only completed and trailer-validated members. Metadata collection remains opt-in to avoid unnecessary retention.

### D11. Python floor

Set:

```toml
requires-python = ">=3.11"
```

Test Python 3.11, 3.12, 3.13, and 3.14.

Do not perform a repository-wide syntax modernization solely because older interpreters are dropped. Modernize touched code when it materially improves clarity.

### D12. Version progression

During implementation:

```python
__version__ = "2.0.0a1.dev0"
```

In the release commit:

```python
__version__ = "2.0.0a1"
```

After publishing, use a separate follow-up commit for the next development version, expected to be `2.0.0a2.dev0`.

### D13. Alpha stability statement

Document that the new codec API is provisional during the 2.0 alpha series. Existing high-level asyncio APIs retain their normal compatibility expectations.

### D14. Thread safety

`GzipEncoder`, `GzipDecoder`, and their operation iterators are not thread-safe.
Use one codec instance from one thread at a time. Callers that share an instance
across threads must serialize the complete lifecycle of each operation with
external locking; the operation-ownership `RuntimeError` is a misuse guard, not
a synchronization mechanism or a data-race guarantee.

The same restriction applies to advancing one returned operation from several
threads. Prefer one codec instance per thread or transport session.

### D15. Constructor validation parity

The codec must reuse the same shared validators as the established file API.
Do not copy or reinterpret validation rules in `codec.py`.

- `output_chunk_size` uses `_validate_chunk_size`: it must be an integer, `bool`
  and non-integers such as `float` are rejected, and the legal range is
  `1..134217728` bytes inclusive (128 MiB).
- `compresslevel` uses `_validate_compresslevel` and preserves the current
  `-1..9` range and integer-only behavior.
- `mtime` uses `_normalize_mtime`. `None` means sample the current Unix time
  when `start()` constructs the header. Non-negative `int` and `float` values
  are accepted; floats are converted with `int()` and therefore truncate toward
  zero. The normalized value must fit the gzip uint32 field
  (`0..0xFFFFFFFF`); negative values are rejected before conversion and values
  whose normalized integer exceeds the field raise `ValueError`.
- `original_filename` uses `_validate_original_filename` and preserves its NUL
  and type behavior.
- `max_decompressed_size` uses `_validate_optional_positive_int` and preserves
  integer-only, positive-or-`None` behavior.

Add parity tests that construct both the codec and the corresponding high-level
API with the same boundary and invalid values. A future validator change should
move both surfaces together.

---

## 6. Proposed public API contract

The implementation may use private helper classes, but the public shape for `2.0.0a1` is:

```python
from collections.abc import Iterator

class GzipEncoder:
    def __init__(
        self,
        *,
        compresslevel: int = 6,
        mtime: int | float | None = None,
        original_filename: str | bytes | None = None,
        fast_compress: bool = False,
        strict_size: bool = False,
        output_chunk_size: int = 256 * 1024,
    ) -> None: ...

    @property
    def input_size(self) -> int: ...

    @property
    def crc32(self) -> int: ...

    @property
    def started(self) -> bool: ...

    @property
    def finished(self) -> bool: ...

    def start(self) -> Iterator[bytes]: ...

    def feed(self, data: bytes) -> Iterator[bytes]: ...

    def flush(self) -> Iterator[bytes]: ...

    def finish(self) -> Iterator[bytes]: ...

    def discard(self) -> None: ...


class GzipDecoder:
    def __init__(
        self,
        *,
        output_chunk_size: int = 256 * 1024,
        max_decompressed_size: int | None = None,
        collect_member_info: bool = False,
    ) -> None: ...

    @property
    def members(self) -> tuple[GzipMemberInfo, ...]: ...

    @property
    def member_count(self) -> int: ...

    @property
    def compressed_size(self) -> int: ...

    @property
    def uncompressed_size(self) -> int: ...

    @property
    def finished(self) -> bool: ...

    def feed(self, data: bytes) -> Iterator[bytes]: ...

    def finish(self) -> Iterator[bytes]: ...

    def discard(self) -> None: ...
```

### 6.1 Shared operation semantics

Every state-changing method validates arguments before reserving the codec. Once
validation succeeds, the call reserves the codec before returning its operation
object. The operation is single-use.

The following misuse must behave identically with cyclic GC enabled or disabled,
and on reference-counted and tracing garbage collectors:

```python
encoder.feed(b"payload")  # returned operation is ignored
encoder.finish()           # raises RuntimeError: prior operation is active
```

The second call raises `RuntimeError` even if the first operation object is no
longer reachable or has already been collected. Garbage collection must not
release, commit, close, or poison the reserved operation. The caller must do one
of the following:

- exhaust the operation completely;
- retain it and explicitly close it, accepting that the codec becomes unusable;
- call `codec.discard()` to abandon the entire codec.

If the caller retains an operation and then calls `codec.discard()`, the
operation is invalidated immediately. Any later advancement of that retained
operation raises `RuntimeError`; it cannot emit bytes or mutate codec state.
Calling its `close()` method afterward is idempotent and has no state-changing
effect.

Add a direct lifecycle test that disables cyclic GC, drops an unadvanced
operation, and verifies the same `RuntimeError` before and after an explicit
collection attempt. Add the equivalent case after partial advancement. Also
test retained unadvanced and partially advanced operations after `discard()`:
advancement must raise `RuntimeError` and emit nothing. Do not use a finalizer whose timing
changes this observable behavior.

An exhausted operation releases ownership. An explicitly closed, partially
advanced operation or an operation that raises after mutating engine state makes
the codec unusable. Call-time argument and state validation errors occur before
reservation and do not poison untouched state unless this contract explicitly
states that the prior state is already terminal.

### 6.2 Encoder semantics

- One encoder instance produces exactly one gzip member.
- `start()` is required before `feed()`, `flush()`, or `finish()`.
- `start()` emits the gzip header and succeeds exactly once.
- `feed()` may be called zero or more times.
- `feed(b"")` is legal and may yield nothing.
- `flush()` performs a non-finalizing `Z_SYNC_FLUSH`.
- Multiple completed `flush()` calls are legal.
- `finish()` finalizes DEFLATE and emits the gzip trailer exactly once.
- `finish()` after one or more `flush()` calls is legal.
- `strict_size=True` rejects input that would make the member exceed the 32-bit ISIZE range.
- `input_size` and `crc32` remain queryable after successful finalization.
- Default compression remains stdlib zlib; `fast_compress=True` retains existing zlib-ng opt-in behavior and warning behavior.
- Default output remains interoperable with Python’s `gzip` module.
- The alpha does not promise compressed-byte identity across different zlib versions or engines beyond existing documented guarantees.

Example:

```python
from aiogzip.codec import GzipEncoder

encoder = GzipEncoder(mtime=0)
compressed = bytearray()
compressed.extend(encoder.start())
compressed.extend(encoder.feed(b"hello "))
compressed.extend(encoder.feed(b"world"))
compressed.extend(encoder.finish())
wire_bytes = bytes(compressed)
```

### 6.3 Decoder semantics

- A decoder accepts a complete gzip stream containing zero or more members.
- Empty input is accepted to preserve existing aiogzip empty-file behavior.
- `feed()` may receive arbitrary compressed chunk boundaries.
- `finish()` is required to prove that the final member/header/trailer is complete.
- CRC and ISIZE are validated before a member is counted as complete.
- Concatenated members are exposed as one decompressed byte stream.
- Existing allowed NUL padding behavior is preserved.
- Non-NUL trailing junk is rejected.
- `max_decompressed_size` is cumulative across all members for the decoder lifetime.
- The decoder must not emit the first byte beyond `max_decompressed_size`.
- `compressed_size` counts bytes accepted by `feed()`.
- `uncompressed_size` counts emitted/accounted output bytes; a successful `finish()` proves that the complete stream was validated.
- `members` is populated only when `collect_member_info=True`.
- `finish()` after successful completion raises `ValueError`; use a new decoder for another stream.
- `feed()` after successful completion also raises `ValueError`, including
  `feed(b"")`; terminal completion is not a reusable empty-input state.

Example:

```python
from aiogzip.codec import GzipDecoder

decoder = GzipDecoder(max_decompressed_size=64 * 1024 * 1024)
parts: list[bytes] = []

for network_chunk in compressed_chunks:
    parts.extend(decoder.feed(network_chunk))
parts.extend(decoder.finish())

payload = b"".join(parts)
```

Documentation must warn that the example list is appropriate only when the caller intends to retain the complete result; transport integrations should consume each yielded chunk immediately.

---

## 7. Target architecture

### 7.1 File map

Recommended final shape:

```text
src/aiogzip/
    __init__.py
    codec.py                 # public synchronous codec
    _codec_async.py          # private asyncio operation driver
    _metadata.py             # public result dataclass definitions
    _engine.py               # engine selection plus normalized step adapter
    _common.py               # validations and gzip framing helpers
    _binary.py               # async file wrapper using codec
    _streaming.py            # AsyncIterable wrappers using codec
    _inspection.py           # inspect/verify wrappers using codec
    _text.py                 # unchanged except indirect effects
    py.typed
```

Names of private helper files may change if a clearer layout emerges, but keep the public `codec.py` path fixed.

### 7.2 Dependency direction

Enforce this dependency direction:

```text
_common ─┐
_engine ─┼──> codec ───> _codec_async ───> _streaming
_metadata┘                    │             _inspection
                             └────────────> _binary ───> _text
```

Avoid these cycles:

- `codec` importing `_binary`, `_streaming`, or `_inspection`;
- `_metadata` importing `_inspection`;
- `_engine` importing the public codec;
- `_common` importing async wrappers.

### 7.3 Engine-normalization boundary

Add a private normalized inflate-step API. The exact names may differ, but the contract should resemble:

```python
@dataclass(frozen=True, slots=True)
class _InflateStep:
    output: bytes
    consumed: int
    eof: bool
```

Only the engine adapter may inspect engine-specific `unused_data` or `unconsumed_tail` behavior.

The codec must reason in terms of:

- bytes offered;
- bytes consumed;
- bytes retained by the codec;
- output emitted;
- end-of-deflate state.

Required invariants:

1. `0 <= consumed <= len(input_span)`.
2. Every processing step either consumes input, emits output, changes state, reaches EOF, or reports that more input is required.
3. A step that does none of those is a no-progress error.
4. Bytes after the raw DEFLATE EOF remain available to the gzip trailer/member parser exactly once.
5. No code outside the adapter assumes that `unused_data` and `unconsumed_tail` alias, overlap, or have identical semantics.
6. Stdlib zlib and zlib-ng pass the same adapter conformance tests.
7. A fake non-aliasing engine passes tests in which post-EOF bytes appear:
   - only as unused data;
   - only as unconsumed input;
   - split between engine fields without duplication.

Do not add ISA-L in this release; the fake adapter is sufficient to prove that the codec no longer embeds the zlib-specific assumption.

### 7.4 Async operation driver

The private async bridge must:

- consume a synchronous codec operation;
- yield its output asynchronously;
- run cheap steps inline;
- offload sufficiently large codec work using the existing threshold and executor mechanism;
- preserve the strict output chunk bound;
- avoid precomputing `list(operation)` in a worker;
- avoid eager source consumption;
- preserve cancellation poisoning behavior;
- never reuse codec state after cancellation may have allowed an executor call to continue;
- avoid racing `discard()` against a still-running worker call;
- preserve the original exception when iterator cleanup also fails.

Because `StopIteration` cannot safely escape an executor future, use a sentinel-returning helper around `next()`.

A cancellation test must prove that:

1. the awaiting task receives `CancelledError`;
2. the relevant reader/writer/stream operation becomes unusable;
3. no later operation touches a codec that may still be advancing in a worker;
4. resources are eventually released;
5. source/sink cleanup does not replace the cancellation.

---

## 8. Work packages

Each package below should end in a green repository.

---

### WP0 — Release branch, tooling, and 2.0 development baseline

#### Objective

Create a safe 2.0 development line and remove tooling contradictions before the codec refactor.

#### Maintainer prerequisites

Before merging the Python-floor change:

1. Create and push `1.x` at exactly
   `3f23eadb524c8dba840c4fd855ad5acf84486048`, as locked in section 0.
2. Capture and commit the concise `v1.11.0` benchmark baseline record required
   by section 0 before changing the interpreter, lockfile, engine versions, or
   benchmark implementation.

Codex may prepare code without performing the remote branch action, but it must
not guess a different branch point and must call the missing branch out as a
merge prerequisite. Codex must perform or verify the local baseline capture
before WP0 environment changes.

#### Tasks

- [x] Add this plan to `plans/RELEASE_2_0_0A1_PLAN.md`.
- [x] Verify the local `v1.11.0` worktree resolves to
      `3f23eadb524c8dba840c4fd855ad5acf84486048`.
- [x] Capture the release-gating baseline before any environment change and add
      `plans/benchmarks/v1.11.0-baseline.md` with the fields in section 0.
- [x] Change `.codexrc` from the retired `pre-commit` command to:

  ```json
  ["uv", "run", "prek", "run", "--all-files"]
  ```

- [x] Keep the test command in `.codexrc`; optionally add the existing coverage floor if command latency remains acceptable.
- [x] Set `__version__` to `2.0.0a1.dev0`.
- [x] Set `requires-python = ">=3.11"`.
- [x] Change the development-status classifier to `3 - Alpha`.
- [x] Remove Python 3.8, 3.9, and 3.10 classifiers.
- [x] Set Ruff’s target to `py311`.
- [x] Set mypy’s configured Python version to 3.11 or later.
- [x] Remove the `tomli` dependency branch for Python below 3.11.
- [x] Audit `typing_extensions`; retain it only where tests or supported typing behavior still require it.
- [x] Set the uv development environment floor to 3.11.
- [x] Remove the Python 3.8 compatibility CI step and the corresponding pre-commit hook.
- [x] Delete `scripts/check_py38_compat.py` if nothing else uses it.
- [x] Change the Linux CI matrix to Python 3.11–3.14.
- [x] Keep representative Windows and macOS coverage; use an actively supported matrix version already available in CI.
- [x] Update comments in `pyproject.toml`, CI, `CLAUDE.md`, contributing docs, and README that describe the 1.x floor.
- [x] Update `SECURITY.md` so the supported-version table distinguishes the latest stable 1.x line from the 2.0 alpha series and does not leave the stale 1.8.x-only entry in place.
- [x] Regenerate `uv.lock`.
- [x] Add an Unreleased changelog entry for the Python 3.11 floor and alpha development line.
- [ ] Update the changelog comparison-link definitions for `2.0.0a1` and the new `[Unreleased]` range when the version is finalized.
- [x] Verify package metadata rejects installation on Python 3.10.

#### Tests

- [x] Existing suite passes on Python 3.11.
- [x] CI configuration contains no 3.8–3.10 legs.
- [x] `python -m pip install .` under Python 3.10 fails because of package metadata, not a syntax crash.
- [x] Version-sync tests pass with `2.0.0a1.dev0`.
- [x] `uv run prek run --all-files` works from a clean checkout.

#### Exit criteria

- [x] Tooling instructions and `.codexrc` agree.
- [x] The benchmark baseline is locked to the exact published release and was
      captured before the environment changed.
- [x] Main is clearly a 2.0 development line.
- [x] The support policy accurately describes which 1.x and 2.0 prerelease lines receive fixes.
- [x] No functional gzip behavior has changed.
- [x] Maintainer has a documented branch-protection update to perform if required-check contexts changed.

Suggested commit title:

```text
chore: establish the 2.0 alpha development line
```

---

### WP1 — Characterize behavior and extract shared metadata types

#### Objective

Pin down the behavior the refactor must preserve and eliminate the impending import cycle around inspection result types.

#### Tasks

- [x] Add missing characterization tests before moving codec code.
- [x] Move `GzipMemberInfo`, `GzipInfo`, and `VerificationResult` to `_metadata.py`.
- [x] Import those names back into `_inspection.py`.
- [x] Preserve package-root exports and identity.
- [x] Add tests that old private lookup paths still resolve as module attributes.
- [x] Add the next repository ADR, recommended filename `docs/adr-sans-io-codec.md`.
- [x] Record the fixed decisions from sections 5–7 in the ADR, including:
  - the lazy-iterator ownership model and deterministic dropped-iterator rule;
  - the immutable-input `feed()` rule, `bytes`-subclass normalization,
    snapshot-semantics rationale, and copy tradeoffs;
  - constructor validation parity with the file API;
  - the explicit non-thread-safe contract; and
  - the bounded pull-style fallback described in section 15 if alpha feedback
    rejects iterator ownership.
- [x] Do not add the public codec implementation in this package unless it is a behavior-neutral skeleton.

#### Characterization coverage to add or confirm

Encoder/file writer:

- [x] header is written before payload;
- [x] append creates a new member;
- [x] bytes-like file writes remain accepted;
- [x] simple `bytes` subclasses remain accepted anywhere the current API
      accepts `bytes`; characterize acceptance separately from the hardened
      raw-buffer snapshot semantics introduced in WP3;
- [x] `flush()` is non-finalizing and writing can continue afterward;
- [x] failed or cancelled writes poison the writer;
- [x] a broken writer does not emit a misleading trailer;
- [x] strict-size failure occurs before the engine advances;
- [x] default and fast-engine selection behavior is preserved.

Decoder/file reader:

- [x] zero-byte source behavior;
- [x] arbitrary compressed chunk boundaries;
- [x] concatenated members;
- [x] NUL padding;
- [x] trailing junk rejection;
- [x] truncated header/body/trailer;
- [x] CRC and ISIZE failures;
- [x] `mtime` availability timing;
- [x] bounded output and cumulative size limit;
- [x] rewind and backward seek reset the read-pass limit;
- [x] cancellation poisons executor-backed reads;
- [x] external file-object close ownership.

Streaming and inspection:

- [x] no source read-ahead;
- [x] early consumer exit closes the source iterator;
- [x] source exceptions remain primary;
- [x] complete validation occurs only at iterator exhaustion;
- [x] output chunks obey the strict bound;
- [x] completed-member offsets and sizes remain correct.

#### Exit criteria

- [x] Moving result types causes no public behavior change.
- [x] The contract tests fail if the later codec refactor drops an existing safety or lifecycle behavior.
- [x] The ADR is reviewed before the public API is exposed.

Suggested commit title:

```text
refactor: extract gzip metadata types and pin codec behavior
```

---

### WP2 — Implement engine-neutral consumption accounting

#### Objective

Create the internal engine adapter that makes a portable synchronous decoder possible.

#### Tasks

- [x] Add a private normalized raw-inflate step abstraction in `_engine.py` or a focused private module.
- [x] Centralize every read of engine-specific post-call attributes.
- [x] Return explicit `consumed`, `output`, and `eof` information to callers.
- [x] Track pending input in the caller rather than handing engine-owned tail objects around the package.
- [x] Add no-progress detection.
- [x] Preserve engine-error wrapping.
- [x] Preserve stdlib/zlib-ng selection behavior.
- [x] Do not expose the adapter publicly.
- [x] Do not add a new runtime dependency.

#### Required tests

- [x] stdlib adapter conformance;
- [x] zlib-ng adapter conformance when installed;
- [x] forced-stdlib behavior while zlib-ng is installed;
- [x] member EOF with trailer bytes in the same input span;
- [x] member EOF followed immediately by another member;
- [x] bounded output requiring repeated steps over one input span;
- [x] fake non-aliasing engine variants;
- [x] malformed payload error normalization;
- [x] no-progress guard;
- [x] property test over payload sizes and input splits.

#### Exit criteria

- [x] Search confirms no decoder outside the adapter reads both `unused_data` and `unconsumed_tail` to infer consumption.
- [x] All adapter variants identify the exact same member/trailer boundary.
- [x] Existing high-level behavior is unchanged at this stage.

Suggested commit title:

```text
refactor: normalize incremental inflate accounting
```

---

### WP3 — Add the public synchronous codec

#### Objective

Create `aiogzip.codec` by extracting and hardening the existing incremental encoder and decoder.

#### Tasks

- [x] Add `src/aiogzip/codec.py`.
- [x] Implement the public API in section 6.
- [x] Reuse shared validation and gzip framing helpers.
- [x] Add the shared `_snapshot_bytes_input` helper specified in D6 and use it
      for both encoder and decoder `feed()` calls before operation reservation.
- [x] Preserve exact `bytes` as the no-copy path; normalize `bytes` subclasses
      from raw buffer contents into exact `bytes`; reject mutable and non-`bytes`
      buffers at the codec boundary.
- [x] Do not invoke subclass overrides such as `__bytes__`, `__len__`,
      `__iter__`, or `__getitem__` while snapshotting or accounting input.
- [x] Route `output_chunk_size`, `compresslevel`, `mtime`,
      `original_filename`, and `max_decompressed_size` through the exact shared
      validators named in D15.
- [x] Keep all methods synchronous.
- [x] Implement the explicit operation-ownership model with a codec-owned token
      independent of the operation object's reachability.
- [x] Ensure operation finalization or garbage collection has no observable
      state-changing side effects.
- [x] Add `GzipEncoder.flush()` using `Z_SYNC_FLUSH`.
- [x] Ensure output is lazily sliced to `output_chunk_size`.
- [x] Ensure decoder output is bounded during expansion, not after materialization.
- [x] Enforce the cumulative decompressed-size limit before emitting an over-limit byte.
- [x] Preserve gzip header safety limits.
- [x] Parse and validate optional metadata fields and FHCRC.
- [x] Validate CRC and ISIZE.
- [x] Handle concatenated members and NUL padding.
- [x] Preserve empty-stream behavior.
- [x] Preserve statistics after successful `finish()`.
- [x] Make `discard()` idempotent.
- [x] Add `GzipEncoder` and `GzipDecoder` to package-root exports and `__all__`.
- [x] Add module and class docstrings suitable for mkdocstrings.
- [x] Do not migrate async wrappers in this work package unless needed for an isolated integration test.

#### New test modules

Recommended:

```text
tests/test_codec_encoder.py
tests/test_codec_decoder.py
tests/test_codec_lifecycle.py
tests/test_codec_engine_accounting.py
tests/test_codec_typing.py
```

#### Encoder tests

- [x] default constructor and validation;
- [x] `output_chunk_size` parity: reject `bool` and `float`, reject zero and
      negatives, accept 128 MiB, and reject values above 128 MiB;
- [x] `mtime` parity: `None`, integer boundaries, positive float truncation,
      negative fractions, and normalized uint32 overflow;
- [x] exact header fields for deterministic metadata;
- [x] filename encoding and rejection rules;
- [x] one-member round trip through `gzip.decompress`;
- [x] empty member;
- [x] arbitrary payload and feed boundaries;
- [x] exact `bytes` input uses the no-copy snapshot path;
- [x] a simple `bytes` subclass is accepted and normalized to exact `bytes`;
- [x] a hostile `bytes` subclass overriding `__bytes__`, `__len__`, iteration,
      and indexing is consumed according to its raw underlying buffer only;
- [x] `bytearray`, `memoryview`, and other non-`bytes` buffers raise `TypeError`;
- [x] output bound for header, body, flush output, final bytes, and trailer;
- [x] `Z_SYNC_FLUSH` output remains resumable;
- [x] multiple flushes;
- [x] strict ISIZE boundary without allocating 4 GiB;
- [x] stdlib and fast-compression selection;
- [x] engine errors become `OSError`;
- [x] start/feed/flush/finish state transitions;
- [x] concurrent operation rejection;
- [x] an unadvanced dropped operation keeps the codec reserved under
      `gc.disable()` and after an explicit collection attempt;
- [x] a partially advanced dropped operation has the same deterministic result;
- [x] early operation close poisons the codec;
- [x] call-time validation does not poison untouched state;
- [x] after `discard()`, advancing a retained unadvanced or partially advanced
      operation raises `RuntimeError`, emits nothing, and changes no state;
- [x] closing an already-invalidated retained operation is idempotent;
- [x] stats after finish;
- [x] discard idempotence.

#### Decoder tests

- [x] stdlib-generated input;
- [x] exact `bytes`, simple `bytes` subclass, hostile `bytes` subclass, and
      mutable/non-`bytes` rejection cases matching the encoder contract;
- [x] constructor validation parity for `output_chunk_size` and
      `max_decompressed_size`;
- [x] encoder-generated input;
- [x] every-byte and randomized input splits;
- [x] highly compressible input with a strict output bound;
- [x] multiple concatenated members;
- [x] empty members;
- [x] NUL padding between and after members;
- [x] metadata-heavy headers;
- [x] FHCRC;
- [x] CRC mismatch;
- [x] ISIZE mismatch;
- [x] malformed magic, method, flags, extra fields, and unterminated strings;
- [x] truncated header/body/trailer;
- [x] trailing non-NUL junk;
- [x] zero-byte input;
- [x] cumulative limit exactly at, one below, and one above the boundary;
- [x] no over-limit output escapes;
- [x] metadata collection on and off;
- [x] offsets and compressed sizes;
- [x] state transitions, repeated `finish()`, and `feed()` after successful
      `finish()` raising `ValueError` even for `b""`;
- [x] concurrent operation rejection;
- [x] dropped-operation behavior under `gc.disable()`;
- [x] early operation close poisons the codec;
- [x] after `discard()`, advancing a retained unadvanced or partially advanced
      operation raises `RuntimeError`, emits nothing, and changes no state;
- [x] closing an already-invalidated retained operation is idempotent;
- [x] stats after finish;
- [x] discard idempotence.

#### Purity tests

- [x] `aiogzip.codec` imports and operates in synchronous code with no running event loop.
- [x] An AST/import test prevents `asyncio` and `aiofiles` imports in `codec.py`.
- [x] No public codec method is a coroutine function or async generator function.
- [x] Public type-check examples pass.
- [x] A thread-safety documentation test or doc-example assertion makes clear
      that operation ownership is not a synchronization guarantee.

#### Exit criteria

- [x] The public codec is complete and documented at the API-docstring level.
- [x] It is not yet used by every wrapper, but its behavior matches the pinned contract.
- [x] New codec code has meaningful branch coverage; do not rely only on the repository-wide 85% floor.

Suggested commit title:

```text
feat: add a public synchronous gzip codec
```

---

### WP4 — Add the async codec driver and migrate streaming/inspection

#### Objective

Move the least stateful async consumers onto the new codec and validate the async bridge.

#### Tasks

- [x] Add `_codec_async.py` or an equivalent private module.
- [x] Implement safe inline/executor iteration of codec operations.
- [x] Use the existing offload threshold.
- [x] Use a sentinel helper around `next()` for executor calls.
- [x] Handle cancellation without racing codec cleanup against a worker.
- [x] Migrate `compress_chunks()` to `GzipEncoder`.
- [x] Migrate `decompress_chunks()` to `GzipDecoder`.
- [x] Preserve `bytes`-subclass acceptance in async iterable sources, but
      normalize each accepted subclass to an exact raw-buffer snapshot before
      starting the codec operation.
- [x] Migrate `_scan_gzip()`, `inspect()`, and `verify()` to `GzipDecoder`.
- [x] Remove `_IncrementalGzipEncoder`.
- [x] Remove `_IncrementalGzipDecoder`.
- [x] Preserve source iterator validation and close semantics.
- [x] Preserve pull-driven behavior: do not request another source item until current output is consumed.
- [x] Preserve error precedence when source cleanup fails.
- [x] Inspection must discard decompressed payload immediately rather than retaining it.

#### Required tests

- [x] existing streaming and encoder suites;
- [x] existing inspection and CLI suites;
- [x] large feed/decode operations use the executor;
- [x] small operations remain inline;
- [x] cancellation during executor work poisons the stream operation;
- [x] an abandoned async iterator poisons its codec;
- [x] concurrent async advancement produces the documented error;
- [x] no eager source consumption;
- [x] simple and hostile `bytes` subclasses in compression and decompression
      sources preserve acceptance while using raw-buffer snapshot semantics;
- [x] source `aclose()` on success, error, and early exit;
- [x] source exception remains primary over cleanup exception;
- [x] memory regression test for highly compressible input;
- [x] member metadata and offsets remain identical.

#### Exit criteria

- [x] `_streaming.py` and `_inspection.py` contain no independent gzip codec state machine.
- [x] Streaming output and source-pull behavior match 1.11.
- [x] Inspection and verification use the same decoder users can import.
- [x] Cancellation tests demonstrate no codec reuse after a worker race.

Suggested commit title:

```text
refactor: drive streaming and inspection through the sans-IO codec
```

---

### WP5 — Migrate the binary writer

#### Objective

Make `AsyncGzipBinaryFile` write mode use `GzipEncoder` without changing file semantics.

#### Tasks

- [x] Replace direct compressor construction with `GzipEncoder`.
- [x] On `open()`, exhaust `encoder.start()` and write the complete header.
- [x] Preserve filename derivation from a path versus explicit metadata override.
- [x] Preserve `mtime`, compression level, strict-size, and fast-compression behavior.
- [x] Continue accepting `bytes`, `bytes` subclasses, `bytearray`,
      `memoryview`, and other valid buffer objects at the file API.
- [x] Normalize every accepted non-exact input—including `bytes` subclasses and
      mutable buffers—to an exact built-in `bytes` snapshot before codec or
      executor work. For subclasses, snapshot raw buffer contents without
      invoking overridden conversion or sequence methods.
- [x] For `write()`, exhaust the codec operation and `_write_all()` every emitted chunk.
- [x] Credit `_position` only after the entire operation’s output reaches the sink.
- [x] If the codec advances but the sink fails, mark the writer broken.
- [x] If an executor-backed operation is cancelled, mark the writer broken.
- [x] Implement file `flush()` by exhausting `encoder.flush()` and then flushing the underlying sink.
- [x] Implement close finalization by exhausting `encoder.finish()`.
- [x] Do not emit a trailer after an earlier broken write/flush.
- [x] Preserve primary finalization errors when underlying `close()` also fails.
- [x] Preserve append behavior: every opened append writer creates one new member.
- [x] Remove duplicate `_crc`, `_input_size`, header, trailer, and compressor-state code where no longer needed. Retain wrapper-level committed-position accounting.

#### Required tests

- [x] entire binary writer suite;
- [x] external sink partial writes;
- [x] invalid write counts and no-progress writes;
- [x] sink failure after one emitted compressed chunk;
- [x] cancellation during compression;
- [x] cancellation or failure during flush;
- [x] write after flush;
- [x] multiple flushes;
- [x] close after flush;
- [x] close after broken write emits no trailer;
- [x] empty file/member;
- [x] append creates readable concatenated members;
- [x] bytes-like compatibility, including simple and hostile `bytes`
      subclasses and mutable buffers;
- [x] strict-size preflight;
- [x] fast-compression warning and engine selection;
- [x] stdlib `gzip` reads all output.

#### Exit criteria

- [x] No direct write-mode `compressobj`, gzip-header, gzip-trailer, CRC, or ISIZE state machine remains in `_binary.py`.
- [x] File-level failure semantics are unchanged.
- [x] Writer benchmarks meet the release gate.

WP5 benchmark note (2026-07-22): locked-baseline representative writer
operations passed (bulk -4.1%, 64 KiB chunks -7.0%, text bulk -2.6%, and
flush faster). The deliberately pathological 838,860-call 10-byte stress case
was investigated and improved from +122% to +39.6%; its remaining per-call
cost is the codec's deterministic lazy operation ownership, so it is recorded
for WP8 but is not a representative-operation blocker under the gate above.

Suggested commit title:

```text
refactor: use the sans-IO encoder for binary writes
```

---

### WP6 — Migrate the binary reader and seeking paths

#### Objective

Make all binary read modes use `GzipDecoder`. This is the highest-risk package.

#### Tasks

- [x] Replace direct `decompressobj(GZIP_WBITS)` state with `GzipDecoder`.
- [x] Feed compressed source chunks through the async codec driver.
- [x] On underlying EOF, exhaust `decoder.finish()` exactly once.
- [x] Preserve the zero-byte-file behavior.
- [x] Preserve `_decompress_next()`’s list-of-pieces optimization for `read(-1)` if it remains beneficial.
- [x] Preserve bounded buffering for partial reads.
- [x] Preserve `read`, `read1`, `readinto`, `readinto1`, `peek`, `readline`, `readlines`, iteration, and tarfile-style access behavior.
- [x] Preserve cumulative `max_decompressed_size` behavior for a read pass.
- [x] Preserve multi-member and NUL-padding behavior through the codec.
- [x] Preserve error mapping and useful context.
- [x] Preserve `.mtime` availability. It is acceptable to retain the small existing header-mtime probe in the file wrapper solely for early property compatibility; it must not become a second decompression state machine.
- [x] On rewind/backward seek, instantiate a fresh decoder and reset the per-pass counters and buffered output.
- [x] Preserve non-seekable replay-cache semantics and limits.
- [x] Preserve broken-reader behavior after executor cancellation.
- [x] Ensure a worker still running after cancellation cannot race with a newly created decoder.
- [x] Remove duplicate member-loop, `unused_data`, `unconsumed_tail`, and finalization logic from `_binary.py`.
- [x] Keep forward seek implemented by consuming decompressed bytes; do not add indexing.

#### Required tests

Run the complete suite, with special attention to:

- [x] binary partial-read tests;
- [x] read-all fast path;
- [x] read buffer compaction;
- [x] read1/readinto1 limits;
- [x] peek non-advancement;
- [x] line boundary handling;
- [x] tarfile integration;
- [x] concatenated members;
- [x] zero padding;
- [x] corruption and truncation;
- [x] decompression bomb guard;
- [x] exact-limit behavior;
- [x] seek from start/current/end;
- [x] backward seek replay;
- [x] rewind;
- [x] non-seekable sources and cache cap;
- [x] `.mtime`;
- [x] external async sources;
- [x] cancellation and reopen guidance;
- [x] text-mode suite, because it depends on binary reads;
- [x] aiocsv integration.

Add parity/property tests:

- [x] generate payloads and member groupings with Hypothesis;
- [x] compare full output with `gzip.decompress`;
- [x] compare a sequence of reads/seeks with `gzip.GzipFile` where semantics overlap;
- [x] run the same fixture through `GzipDecoder`, `decompress_chunks`, `inspect`, `verify`, and `AsyncGzipBinaryFile`.

#### Exit criteria

- [x] `_binary.py` no longer performs direct gzip decompression or member traversal.
- [x] All high-level and text tests pass unchanged except deliberate Python-floor adjustments.
- [x] Reader memory and throughput meet the release gate.
- [x] The only remaining header parser duplication is a documented, read-only mtime compatibility probe if still required.

WP6 benchmark note (2026-07-22): the bounded-work hint restored the binary file
reader to the locked 3.99 ms baseline (4 ms candidate), and full-read peak
Python memory improved from 21.397 MiB to 16.01 MiB. The representative
512/256 KiB `decompress_chunks` case remained 10 ms versus the locked 6.62 ms
baseline after improving from 20 ms. The maintainer explicitly accepted this
CRC/ISIZE-validation and bounded-output correctness/memory tradeoff on
2026-07-22, as permitted by the release gate.

Suggested commit title:

```text
refactor: use the sans-IO decoder for binary reads
```

---

### WP7 — Remove duplication and harden the unified implementation

#### Objective

Audit the result as one architecture rather than three migrated call sites.

#### Tasks

- [ ] Search for duplicate gzip framing, trailer, CRC/ISIZE, member-loop, and raw engine code.
- [ ] Remove dead private classes, helpers, imports, slots, and tests.
- [ ] Confirm all decoder paths use normalized engine accounting.
- [ ] Confirm all encoder paths use `GzipEncoder`.
- [ ] Confirm every async codec operation is exhausted or explicitly closed.
- [ ] Confirm no wrapper calls `list(operation)` before yielding/writing.
- [ ] Confirm no wrapper reads the next async source item while output from the current item remains unconsumed.
- [ ] Audit cancellation paths for BaseException handling and resource ownership.
- [ ] Audit close paths for preservation of primary errors.
- [ ] Audit type annotations and public `__all__`.
- [ ] Add a source-level architecture test or focused assertions only where they protect an important boundary without becoming brittle.
- [ ] Run mutation-like manual checks by temporarily breaking CRC, size limits, source cleanup, and output bounds to ensure tests fail.

#### Exit criteria

- [ ] There is one production gzip state machine.
- [ ] Async wrappers are thin enough to review independently from codec correctness.
- [ ] No known dead compatibility code remains.
- [ ] Coverage does not fall materially from the baseline; new core branches are tested directly.

Suggested commit title:

```text
refactor: consolidate gzip state on the shared codec
```

---

### WP8 — Documentation, benchmarks, packaging, and release candidate

#### Objective

Make the alpha understandable, measurable, and publishable.

#### Documentation tasks

- [ ] Add `docs/codec.md`.
- [ ] Add the page to `mkdocs.yml`.
- [ ] Add the codec classes to `docs/api.md`.
- [ ] Update `docs/streaming.md` to distinguish the sync codec from async iterable wrappers.
- [ ] Update `docs/errors.md` with operation-abandonment, finalization, corruption, and size-limit behavior.
- [ ] Update `docs/migration.md` with:
  - Python 3.11 requirement;
  - installation behavior for users remaining on 1.x;
  - the new codec API;
  - the provisional alpha compatibility statement;
  - no change required for ordinary asyncio callers.
- [ ] Update README with a concise synchronous codec example.
- [ ] Update `CLAUDE.md` and contributing guidance for the new architecture and Python floor.
- [ ] Complete the ADR.
- [ ] Add a prominent warning that decompression integrity is not established until `finish()` or full iterator exhaustion.
- [ ] Explain operation ownership and why returned iterators must be exhausted.
- [ ] Document the deterministic dropped-iterator contract: ignoring an operation
      leaves the codec reserved, the next operation raises `RuntimeError`
      regardless of GC timing, and `discard()` is the only cleanup once the
      iterator is unreachable.
- [ ] Explain that codec `feed()` accepts `bytes` subclasses but snapshots them
      to exact built-in `bytes`, while mutable/non-`bytes` buffers are rejected;
      include the raw-buffer rationale and both copy costs.
- [ ] State that codec instances and their operation iterators are not
      thread-safe: use one thread at a time or external locking around the full
      operation lifecycle.
- [ ] Document constructor validation parity, including float `mtime`
      truncation, uint32 bounds, and the 128 MiB `output_chunk_size` ceiling.
- [ ] Document that decoder `feed()` and repeated `finish()` after successful
      completion raise `ValueError`.
- [ ] Explain that the codec performs no I/O and no executor offload.
- [ ] Explain that async wrappers may offload large codec steps.
- [ ] State that raw DEFLATE and AnyIO are not part of this alpha.

#### Benchmark tasks

Use the locked `v1.11.0` baseline captured before WP0 and recorded in
`plans/benchmarks/v1.11.0-baseline.md`. Do not substitute a baseline recreated
weeks later under a changed interpreter, lockfile, codec build, or machine
configuration. Re-run the old worktree only as a diagnostic when the recorded
environment can be reproduced closely enough to make the comparison meaningful.

Run at least:

1. synchronous codec encode/decode of representative 8 MiB data, compared with
   an equivalent stdlib or v1.11 internal codec path where one exists; treat a
   genuinely new microbenchmark as informational rather than inventing a
   nonexistent v1.11 public-codec number;
2. async `compress_chunks` and `decompress_chunks`;
3. binary `read(-1)` and bounded `read(size)`;
4. binary write and flush;
5. JSONL text iteration/readlines as a regression sentinel;
6. multi-file simulated-latency concurrency;
7. highly compressible input peak memory;
8. stdlib and representative zlib-ng paths.

Rules:

- Run the established repository benchmark categories and follow its
  same-machine/same-fixture comparison protocol.
- Use `AIOGZIP_ENGINE=stdlib` for the primary comparison.
- Compare against the exact medians, fixture hashes, and environment metadata in
  the locked baseline record; report any unavoidable environment drift before
  interpreting a percentage.
- Record medians and environment metadata for the candidate using the same
  schema as the baseline.
- Investigate any regression greater than approximately 5%.
- The 5% investigation threshold and 10% blocking threshold apply only to
  comparable operations that have a valid locked `v1.11.0` baseline. New
  codec-only microbenchmarks with no predecessor are informational, not release
  gates; report their absolute results and methodology without inventing a
  percentage comparison.
- A repeatable regression over 10% in a representative baseline-backed
  high-level operation blocks the alpha unless the maintainer explicitly
  accepts a documented correctness/safety tradeoff.
- Do not violate output bounds or backpressure to win a benchmark.
- Preserve the existing highly-compressible streaming memory ceiling.
- Add a codec microbenchmark to `benchmarks/` if the current suite has no direct sans-I/O case.
- Commit benchmark scripts and methodology. The concise release-specific
  baseline record required by section 0 is intentionally committed; keep raw
  machine-specific output outside Git unless existing repository practice says
  otherwise.

#### Packaging tasks

- [ ] Update the package description/keywords if needed to mention the sans-I/O codec without overstating performance.
- [ ] Keep `aiofiles` as a core dependency for the existing high-level API.
- [ ] Verify `codec.py` and `_metadata.py` are included in wheel and sdist.
- [ ] Verify `py.typed` remains included.
- [ ] Set `__version__ = "2.0.0a1"` in the release commit.
- [ ] Move changelog entries from Unreleased into:

  ```markdown
  ## [2.0.0a1] - YYYY-MM-DD
  ```

- [ ] Keep the development-status classifier at Alpha.
- [ ] Build and inspect artifacts:

  ```bash
  rm -rf dist build
  python -m build
  twine check dist/*
  tar tzf dist/*.tar.gz
  ```

- [ ] Install the wheel into a clean Python 3.11 environment and run smoke tests.
- [ ] Confirm Python 3.10 installation is rejected by metadata.
- [ ] Run `mkdocs build --strict`.

#### Exit criteria

- [ ] Docs describe both happy paths and lifecycle hazards.
- [ ] Benchmark results satisfy the gate.
- [ ] Wheel and sdist contain all expected files.
- [ ] Version, tag candidate, changelog, and package metadata agree.
- [ ] All release checks in section 10 pass.

Suggested commit title:

```text
docs: prepare the 2.0.0a1 codec release
```

---

## 9. Required test matrix

### 9.1 Interpreter and platform

| Environment | Required |
|---|---:|
| Linux / Python 3.11 | Yes |
| Linux / Python 3.12 | Yes |
| Linux / Python 3.13 | Yes |
| Linux / Python 3.14 | Yes |
| Windows / representative supported Python | Yes |
| macOS / representative supported Python | Yes |

### 9.2 Engine

| Engine mode | Required |
|---|---:|
| stdlib zlib, zlib-ng absent or forced off | Yes |
| zlib-ng installed and active for decompression | Yes |
| zlib-ng opt-in compression | Yes |
| fake non-aliasing engine adapter | Unit tests only |

### 9.3 Functional layers

| Layer | Required coverage |
|---|---|
| `GzipEncoder` | direct unit, property, validation-parity, and GC-independent lifecycle tests |
| `GzipDecoder` | direct unit, corruption, limit, validation-parity, terminal-state, and property tests |
| async driver | inline, offload, cancellation, abandonment |
| async iterable API | backpressure, cleanup, bounds, errors |
| inspection/verification | metadata, offsets, corruption, CLI |
| binary writer | all modes, flush, partial sink writes, failures |
| binary reader | all read methods, members, limits, seeks, cancellation |
| text layer | full existing suite |
| integrations | tarfile-style and aiocsv tests |
| public typing | mypy/ty and runtime exports |
| packaging | wheel/sdist smoke test |

### 9.4 Coverage policy

- The repository’s hard floor remains 85%.
- Target at least the pre-refactor baseline, approximately the low 90s.
- A new core codec branch should not remain uncovered merely because unrelated modules keep aggregate coverage above the floor.
- Any coverage drop greater than one percentage point requires an explanation.

---

## 10. Release gates

Every item is mandatory unless explicitly marked as a maintainer-only action.

### Correctness

- [ ] All existing behavior tests pass.
- [ ] All new codec tests pass.
- [ ] Hypothesis tests pass under stdlib and representative fast-engine configurations.
- [ ] Stdlib `gzip` reads encoder and file-writer output.
- [ ] aiogzip reads stdlib-created gzip streams.
- [ ] Concatenated members, padding, metadata, CRC, and ISIZE behave consistently across all entry points.
- [ ] No byte beyond `max_decompressed_size` is emitted.
- [ ] `finish()` detects incomplete streams.
- [ ] Decoder `feed()` and repeated `finish()` after successful completion raise
      `ValueError`.
- [ ] Codec constructor validation matches the established file API for
      `mtime`, `output_chunk_size`, compression level, original filename, and
      decompression limits.

### Architecture

- [ ] `aiogzip.codec` has no async or I/O dependency.
- [ ] There is one gzip state machine.
- [ ] Async wrappers own offload and cancellation.
- [ ] Engine-specific tail semantics are isolated.
- [ ] No direct decompression-member loop remains in `_binary.py`, `_streaming.py`, or `_inspection.py`.
- [ ] No direct write-mode gzip framing remains in `_binary.py`.

### Lifecycle and cancellation

- [ ] Operation concurrency is rejected.
- [ ] Dropping an unadvanced or partially advanced operation leaves the codec
      reserved and makes the next state-changing call raise `RuntimeError`
      deterministically with GC enabled or disabled.
- [ ] No operation finalizer mutates codec state or releases ownership.
- [ ] Partial operation close makes codec state unusable.
- [ ] Async early exit closes source iterators.
- [ ] Cancellation during executor work does not permit state reuse.
- [ ] Broken writers do not emit a valid-looking trailer.
- [ ] Cleanup errors do not replace primary operation errors.

### Quality

- [ ] `uv run prek run --all-files`.
- [ ] Ruff lint and format checks.
- [ ] mypy.
- [ ] ty.
- [ ] Full coverage suite at or above 85%.
- [ ] Strict documentation build.
- [ ] Codec thread-safety, immutable-input and `bytes`-subclass snapshot
      rationale, dropped-iterator behavior, terminal decoder behavior, and
      constructor limits are documented.
- [ ] No unexpected warnings.
- [ ] Public export tests updated.
- [ ] Version-sync tests updated.

### Performance and memory

- [ ] `plans/benchmarks/v1.11.0-baseline.md` identifies the exact published
      commit and the pre-WP0 environment.
- [ ] Primary representative operations with valid locked `v1.11.0` baselines
      are within 5% or investigated.
- [ ] No unapproved repeatable regression over 10% in a comparable,
      baseline-backed high-level operation.
- [ ] New codec-only microbenchmarks without a `v1.11.0` equivalent are labeled
      informational and are excluded from the 5%/10% release gates.
- [ ] Strict output bounds remain intact.
- [ ] Highly compressible streaming input remains within the existing memory ceiling.
- [ ] No background task or unbounded queue has been introduced.

### Packaging

- [ ] `requires-python >=3.11`.
- [ ] Alpha classifier.
- [ ] `__version__ == 2.0.0a1`.
- [ ] Changelog release date and version.
- [ ] Wheel and sdist build.
- [ ] `twine check` passes.
- [ ] Clean-wheel smoke test passes.
- [ ] Docs and source files are present in sdist as intended.

### Maintainer-only repository checks

- [ ] `1.x` maintenance branch exists at exactly
      `3f23eadb524c8dba840c4fd855ad5acf84486048`.
- [ ] Required branch-protection checks reflect the new CI matrix.
- [ ] `2.0.0a1` milestone/issue tracking is updated.
- [ ] Final release commit is reviewed.
- [ ] Tag `v2.0.0a1` is created from the reviewed release commit.
- [ ] Publish workflow succeeds.
- [ ] PyPI metadata and files are inspected.
- [ ] GitHub prerelease notes are published.
- [ ] Issue #70 is closed with a link to the release.
- [ ] Issues #71 and #72 remain open and explicitly out of scope.

---

## 11. Risk register

### R1. Public API is frozen too early

**Risk:** An iterator-based codec API may reveal ergonomics or lifecycle issues only after real transport integrations use it.

**Mitigation:**

- release as `2.0.0a1`;
- label the codec API provisional through the alpha series;
- keep the surface deliberately small;
- require at least one feedback cycle before beta;
- avoid raw DEFLATE and framework abstractions in this alpha;
- predeclare the `2.0.0a2` fallback: replace lazy operation iterators with the
  bounded pull-style API in section 15 if real integrations show that ownership
  and abandonment are too error-prone. Alpha compatibility must not prevent
  making that correction.

### R2. Executor cancellation races with mutable codec state

**Risk:** Cancelling an await does not stop a running worker. Reusing or discarding the same codec immediately can race with the worker.

**Mitigation:**

- operation ownership;
- poison the wrapper on cancellation;
- never reuse the affected codec;
- defer final cleanup until the worker is known to be finished;
- add deterministic tests with a blocking fake engine and synchronization events.

### R3. Consumption accounting misidentifies trailer/member boundaries

**Risk:** Stdlib zlib’s aliasing can hide a portability bug that appears with another engine.

**Mitigation:**

- normalized step adapter;
- explicit consumed-byte contract;
- fake non-aliasing engine tests;
- concatenated-member fixtures with header/trailer boundaries inside one feed;
- property tests over chunk boundaries.

### R4. Binary reader performance regresses

**Risk:** Yielding bounded codec chunks and crossing the async driver more often may add overhead.

**Mitigation:**

- keep output chunks at the existing tuned default;
- preserve the `read(-1)` list/join fast path;
- benchmark after streaming migration and again after reader migration;
- permit private cost hints in the operation/driver if profiling proves thread hops dominate;
- do not weaken memory bounds.

### R5. Writer accounting diverges after sink failure

**Risk:** The codec consumes input before all emitted output reaches the sink.

**Mitigation:**

- wrapper position advances only after all output writes succeed;
- any sink failure after engine advancement poisons the writer;
- no trailer on a broken writer;
- partial-write tests.

### R6. Metadata extraction introduces import or pickle regressions

**Risk:** Moving public dataclasses changes module paths.

**Mitigation:**

- preserve `_inspection` aliases;
- preserve package-root identity;
- add import/pickle compatibility tests where practical;
- keep dataclass fields and frozen behavior unchanged.

### R7. The 2.0 floor strands 1.x fixes

**Risk:** Once main requires 3.11, a security or correctness fix for older Python needs a clean branch.

**Mitigation:**

- create `1.x` at the exact `v1.11.0` release commit before merging WP0;
- document backport policy;
- do not merge 2.0-only syntax into `1.x`.

### R8. Scope expands into AnyIO or indexed seeking

**Risk:** Adjacent open issues turn the alpha into an indefinite rewrite.

**Mitigation:**

- fixed non-goals;
- issue #71 depends on feedback after the codec exists;
- issue #72 remains a separate project;
- reject unrelated feature work from this release branch.

---

## 12. Review strategy

Use separate review lenses:

1. **Codec correctness review**
   - state transitions;
   - framing;
   - limits;
   - metadata;
   - corruption handling;
   - engine accounting.

2. **Async/cancellation review**
   - executor ownership;
   - cleanup;
   - source pull behavior;
   - exception precedence.

3. **File API compatibility review**
   - read/write methods;
   - seeking;
   - buffering;
   - external objects;
   - text-layer effects.

4. **Performance review**
   - profile differences rather than only wall-clock totals;
   - memory;
   - number of executor hops;
   - allocations and copies.

5. **Release review**
   - docs;
   - typing;
   - package metadata;
   - changelog;
   - artifact contents.

Do not ask a single reviewer to validate every dimension in one pass.

---

## 13. Suggested pull-request sequence

| PR | Work package | Merge requirement |
|---|---|---|
| 1 | WP0: 2.0 baseline/tooling | `1.x` points to exact `v1.11.0` SHA; locked benchmark record committed |
| 2 | WP1: characterization/metadata/ADR | no behavior change |
| 3 | WP2: engine-normalized accounting | adapter conformance green |
| 4 | WP3: public codec | direct codec suite green |
| 5 | WP4: streaming/inspection migration | cancellation and memory green |
| 6 | WP5: binary writer migration | writer parity and benchmarks green |
| 7 | WP6: binary reader migration | full suite and reader benchmarks green |
| 8 | WP7: consolidation audit | no duplicate state machine |
| 9 | WP8: docs/release preparation | all release gates green |

Small fixes discovered during a package should remain in that package when directly related. Unrelated cleanup should be filed separately.

---

## 14. Release notes outline

Use this structure for the GitHub/PyPI-facing release notes:

### aiogzip 2.0.0a1

This alpha begins the aiogzip 2.0 series.

#### New: synchronous sans-I/O codec

- `aiogzip.codec.GzipEncoder`
- `aiogzip.codec.GzipDecoder`
- bounded incremental output;
- concatenated members and metadata;
- CRC/ISIZE validation;
- optional decompression limit;
- no event loop or file object required.

#### Unified implementation

The existing file, async iterable, inspection, and verification APIs now use the same gzip codec core.

#### Python requirement

aiogzip 2.0 requires Python 3.11 or newer. Python 3.8–3.10 users should remain on the 1.x release line.

#### Alpha notice

The new codec API is provisional during the alpha series. State-changing codec
methods return single-use lazy operation iterators: callers must fully consume
an operation before starting another one. Dropping an operation does not release
its codec reservation; call `discard()` to abandon the codec. Advancing an
operation invalidated by `discard()` raises `RuntimeError`. Codec `feed()`
accepts `bytes` subclasses by snapshotting their raw buffer into exact built-in
`bytes`; mutable and other non-`bytes` buffers are rejected at the codec
boundary. Codec instances and their operation iterators are not thread-safe.
The established high-level asyncio APIs are intended to remain compatible apart
from the Python requirement.

#### Not included

AnyIO/Trio support, raw DEFLATE, and indexed random access are not part of this alpha.

#### Upgrade guidance

Ordinary `aiogzip.open`, `read`, `write`, `compress_chunks`, `decompress_chunks`, `inspect`, and `verify` callers should not require source changes on Python 3.11+.

---

## 15. Post-alpha plan

Do not proceed directly from `2.0.0a1` to stable `2.0.0`.

Collect feedback on:

- method naming;
- explicit `start()` ergonomics;
- whether callers accidentally ignore operation iterators;
- iterator ownership, abandonment, and close behavior;
- whether deterministic reservation after a dropped iterator is understandable in
  practice;
- need for member-boundary events;
- metadata retention;
- transport integration examples;
- performance in real async pipelines;
- demand for AnyIO versus direct codec embedding.

### 15.1 Predeclared `2.0.0a2` fallback: bounded pull-style codec

The lazy operation-iterator design is a deliberate alpha experiment. If alpha
usage shows that ignored return values, abandoned operations, or ownership rules
are a recurring source of integration mistakes, do not attempt to preserve the
model through increasingly implicit cleanup behavior. Use `2.0.0a2` to replace
it with a bounded pull-style API, modeled conceptually on incremental zlib and
zstandard interfaces.

The fallback design is:

- `start()`, `feed(data)`, `flush()`, and `finish()` register the next codec
  transition and return `None`; they do not use an executor or background task;
- `read(max_output: int | None = None) -> bytes` drives that transition and
  pulls at most the requested amount, with `output_chunk_size` as the default
  bound;
- callers must drain pending output before providing more input or starting a
  new state transition; violating that rule raises a deterministic state error;
- a read returns `b""` only when no output is presently available, with explicit
  state such as `needs_input`, `finishing`, and `finished` distinguishing why;
- the codec retains only bounded pending input/output and does not introduce a
  background task, queue, file object, or event-loop dependency;
- gzip framing, concatenated-member support, validation, decompression limits,
  engine normalization, metadata, thread-safety rules, and async-wrapper
  cancellation guarantees remain unchanged;
- the async bridge repeatedly calls `read()` and preserves source backpressure
  and the same executor threshold;
- because the public API is still alpha, source compatibility with `2.0.0a1`
  is not a release blocker, but migration guidance and deprecation-free release
  notes are required.

Signals that should trigger serious consideration of the fallback include:

- real callers repeatedly writing `codec.feed(data)` without consuming the
  returned iterator;
- integrations needing GC- or finalizer-related explanations to be correct;
- adapters accumulating boilerplate solely to track operation ownership;
- abandoned-iterator bugs that survive documentation and type-check examples;
- inability to make cancellation and executor ownership easy to audit without
  exposing internal operation objects.

Do not switch designs merely because a pull API is familiar. Compare both models
against the alpha's bounded-memory, copy-count, cancellation, usability, and
transport-integration evidence, and record the decision in the codec ADR.

### 15.2 Version progression

Choose the next version as follows:

- `2.0.0a2` for public codec API changes, including the fallback above, or for
  substantial cancellation/performance fixes;
- `2.0.0b1` only when the codec API is considered feature-complete and no known
  design question requires a breaking alpha change;
- stable `2.0.0` only after at least one beta and successful downstream
  validation.

Issue #71 should be reconsidered after alpha feedback. Issue #72 remains independent.

---

## 16. Codex kickoff prompt

Paste the following prompt into Codex with this plan present in the repository:

```text
Implement the aiogzip 2.0.0a1 release according to
plans/RELEASE_2_0_0A1_PLAN.md.

Start by reading AGENTS.md, CLAUDE.md, issue #70, docs/adr-isal.md,
the current codec-related modules, and the relevant tests. Treat the
scope and fixed design decisions in the plan as authoritative.

Before WP0, verify that the maintainer-created 1.x branch points to
3f23eadb524c8dba840c4fd855ad5acf84486048 exactly. Capture and commit
the locked v1.11.0 benchmark record required by section 0 before
changing the interpreter, lockfile, dependencies, benchmark harness, or
production code. Do not create or move the remote branch yourself.

Work package by work package. Keep the repository green after each
package, add characterization tests before changing behavior, and
update the checklist in the same commit as the work it describes. If a
package can remain green only by changing code assigned to a later
package, stop and report the dependency instead of pulling that work
forward or silently reordering the plan. Do not implement AnyIO/Trio,
raw DEFLATE, ISA-L, indexed random access, or unrelated cleanup.

Do not tag, publish, change branch protection, close issues, or perform
other remote maintainer actions. Report those as explicit handoff items.

Preserve existing high-level API signatures and behavior except for the
documented Python 3.11 minimum. Preserve strict output bounds,
decompression limits, concatenated-member behavior, source backpressure,
cancellation poisoning, partial-write handling, and error precedence.
Implement the deterministic abandoned-operation and post-discard invalidation
contracts, immutable-input snapshot boundary (including raw-buffer normalization
of `bytes` subclasses), shared constructor validation, decoder
feed-after-finish error, and codec thread-safety documentation exactly as
specified. Apply performance gates only to comparable operations with locked
v1.11.0 baselines; keep new codec-only microbenchmarks informational.

Before every commit run:
    uv run prek run --all-files
    uv run pytest

Before completing a work package run the full stdlib and fast-engine
test/coverage/type-check matrix specified in the plan. Include in each
handoff:
- files changed;
- tests added;
- commands run and results;
- behavior or performance differences;
- remaining checklist items;
- maintainer-only actions.
```
