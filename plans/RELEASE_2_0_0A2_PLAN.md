# aiogzip 2.0.0a2 Regression-Repair Release Plan

> **Status:** Codex-ready implementation plan
> **Target release:** `2.0.0a2`
> **Repository destination:** `plans/RELEASE_2_0_0A2_PLAN.md`
> **Primary objective:** remove the decoder performance and scheduler-latency regressions exposed by `2.0.0a1` without weakening gzip correctness, bounded output, lifecycle ownership, cancellation safety, or engine portability.

This document is the living implementation checklist for the next aiogzip alpha. It is intentionally prescriptive. Codex must treat the fixed decisions, regression gates, scope boundaries, and package ordering below as authoritative unless the maintainer edits this plan in a reviewed commit.

---

## 0. Locked starting points and mandatory preflight

### 0.1 Verify the exact repository base before changing anything

The plan was written against these immutable commits:

| Purpose | Commit |
| --- | --- |
| Expected `main` base | `072ea60e309ac0fda64f12897455deac0557bfc5` |
| Published `v2.0.0a1` tag | `920004672bbb5e76fb2088358d1cb7051290576d` |
| Published `v1.11.0` baseline | `3f23eadb524c8dba840c4fd855ad5acf84486048` |

Before implementation, run:

```bash
git status --short
git rev-parse HEAD
git rev-parse v2.0.0a1^{commit}
git rev-parse v1.11.0^{commit}
git cat-file -e 072ea60e309ac0fda64f12897455deac0557bfc5^{commit}
git cat-file -e 920004672bbb5e76fb2088358d1cb7051290576d^{commit}
git cat-file -e 3f23eadb524c8dba840c4fd855ad5acf84486048^{commit}
```

Preflight rules:

- [x] The working tree is clean before the first implementation commit.
- [x] `v2.0.0a1^{commit}` resolves to `920004672bbb5e76fb2088358d1cb7051290576d`.
- [x] `v1.11.0^{commit}` resolves to `3f23eadb524c8dba840c4fd855ad5acf84486048`.
- [x] `HEAD` resolves to `072ea60e309ac0fda64f12897455deac0557bfc5`.
- [ ] If `main` has advanced, stop and report the new commits and affected files. Do not silently rebase this plan, guess that the new commits are harmless, or change the locked SHA in an implementation commit.
- [ ] If the maintainer intentionally updates the base, update this section in a standalone reviewed plan commit before implementation resumes.

Codex must not create, push, delete, or rename remote branches. Branch creation, branch protection, issue creation, milestones, tags, releases, PyPI publication, and documentation deployment are maintainer-only actions.

Tooling verification: at the locked base, `AGENTS.md` and `.codexrc` already agree on `uv run prek run --all-files`, the obsolete Python 3.8 compatibility hook is absent from `.pre-commit-config.yaml`, and `scripts/check_py38_compat.py` is no longer present. Verify that state during preflight and do not recreate, rename, or churn those files merely to manufacture a setup commit. If the locked base changes and the tooling state no longer matches, stop and report the drift rather than silently folding unrelated cleanup into this release.

### 0.2 Capture a dedicated `2.0.0a1` regression baseline before production changes

The existing records preserve the `v1.11.0` high-level baseline and the `2.0.0a1` release-candidate measurements, including the known `decompress_chunks` regression. They do **not** contain the scaling, event-loop-gap, fragmented-header, and tiny-output cases required for this repair.

Before modifying `src/aiogzip/`, create a benchmark-only commit that adds the regression harness described in WP0. Then use that exact harness against detached worktrees for both the alpha tag and the current starting commit.

Create worktrees:

```bash
git worktree add --detach /tmp/aiogzip-v2.0.0a1-regression v2.0.0a1
git worktree add --detach /tmp/aiogzip-v1.11.0-regression v1.11.0
```

The `v1.11.0` worktree is used only for benchmark cases supported by its public API. The public codec and codec-specific scaling cases use `v2.0.0a1` as their historical comparison.

Required committed records:

```text
plans/benchmarks/v2.0.0a1-regression-baseline.md
plans/benchmarks/data/v1.11.0-a2-comparable-stdlib.json
plans/benchmarks/data/v1.11.0-a2-comparable-zlib-ng.json
plans/benchmarks/data/v2.0.0a1-regression-stdlib.json
plans/benchmarks/data/v2.0.0a1-regression-zlib-ng.json
plans/benchmarks/data/main-pre-a2-regression-stdlib.json
plans/benchmarks/data/main-pre-a2-regression-zlib-ng.json
```

The machine-readable JSON files must retain individual samples, not just medians. Remove machine-specific absolute paths where necessary, but preserve all information needed to reproduce and audit the comparison.

The Markdown record must include:

- [x] exact source commits and worktree paths;
- [x] benchmark harness SHA-256;
- [x] fixture sizes and SHA-256 hashes;
- [x] Python implementation, complete version, and executable;
- [x] OS, kernel, architecture, libc, CPU, core count, RAM, and filesystem used for temporary files;
- [x] stdlib zlib compile-time and runtime versions;
- [x] zlib-ng package version and active engine selection;
- [x] `uv` version and `uv.lock` SHA-256;
- [x] CPU governor, boost state, affinity, system load, and other material machine conditions;
- [x] exact commands;
- [x] warm-up policy, repeat counts, garbage-collection policy, and fixture-generation policy;
- [x] all individual timing samples, medians, median absolute deviation, minimum, and maximum;
- [x] peak-memory method and values;
- [x] event-loop ticker method, baseline ticker gap, p50, p95, p99, and maximum gap;
- [x] output hashes and byte counts proving complete correct consumption;
- [x] any interrupted, discarded, or invalid runs.

Do not manufacture baseline values from the earlier review or transpose measurements from another machine. If the intended release reference machine is unavailable, implementation may continue, but the release gate remains incomplete.

### 0.3 Baseline immutability rule

After the first production-code change:

- [ ] Never overwrite the committed `v2.0.0a1` raw baseline files.
- [ ] Never rerun only the candidate with a corrected harness.
- [ ] If a benchmark bug is found, fix the harness in its own commit, recapture **both** baseline and candidate with the identical harness, preserve the superseded files, and explain the correction in the record.
- [ ] Never tune fixtures, repeat counts, chunk sizes, or comparison formulas after seeing a candidate result without recording the change and recapturing the baseline.
- [ ] Never use benchmark wins in unrelated cases to average away a regression in a named gate.

---

## 1. Instructions to Codex

### 1.1 Execution model

Implement one work package at a time in the order written.

For every package:

1. Read the complete package, its dependencies, and its exit criteria before editing.
2. Inspect the current implementation and tests rather than assuming filenames or internals remain unchanged.
3. Make the smallest coherent change that satisfies the package.
4. Add or update tests in the same commit as the behavior they protect.
5. Update this plan's checklist in that same commit.
6. Run the package-specific checks and the relevant existing regression suite.
7. Keep the repository green at the package boundary.
8. Report measured results, unresolved risks, and deliberate non-changes in the commit or PR notes.

Do not mark a checkbox complete because code was drafted. Mark it only when the implementation, tests, documentation, and specified validation for that item are present in the same commit.

### 1.2 Forward-dependency rule

If keeping a package green requires implementing work assigned to a later package:

- stop;
- identify the exact dependency and affected files;
- explain why a temporary compatibility seam is insufficient;
- propose either a package-boundary edit or a minimal reorder;
- wait for the maintainer to update this plan.

Do not quietly pull later work forward. That produces nominally small commits whose review surface is actually the full refactor.

### 1.3 Regression-specific rules

- [ ] Profile before optimizing when the cause is not already structurally proven.
- [ ] Preserve correctness checks outside timed regions where possible.
- [ ] Do not weaken CRC, ISIZE, header CRC, reserved-flag, member-boundary, trailing-data, or decompression-limit validation.
- [ ] Do not increase the public `output_chunk_size` supplied by a caller to make a benchmark pass.
- [ ] Do not materialize the full decompressed result.
- [ ] Do not add a producer task, background queue, or unbounded result queue.
- [ ] Do not fix only `decompress_chunks()` by rechunking its source; the public synchronous decoder must scale correctly on one large `feed()`.
- [ ] Do not offload every `next()` call merely to hide event-loop stalls. The synchronous step itself must be bounded.
- [ ] Do not remove deterministic operation ownership, explicit abandonment, or poisoning on partial close.
- [ ] Do not special-case benchmark sizes, fixture hashes, compressibility, or engine names.
- [ ] Do not loosen a threshold after a miss. Stop, profile, and report.
- [ ] Do not substitute an unrecorded same-session rerun for a locked historical baseline.

### 1.4 Remote and maintainer-only actions

Codex may prepare local files and commits. Codex must not:

- create or modify GitHub issues, milestones, projects, releases, tags, branch protection, repository settings, or documentation aliases;
- push branches or tags;
- publish to PyPI;
- close or relabel issues;
- claim independent review occurred;
- claim a platform or engine passed unless its commands actually ran.

Record these as maintainer handoff items instead.

---

## 2. Executive release decision

The next release is **`2.0.0a2`**, not `2.0.0b1`.

`2.0.0a1` successfully validated the shared sans-I/O architecture, but alpha review exposed a concentrated internal-buffering defect:

- accepted compressed bytes are accumulated in one `bytearray`;
- each bounded body step converts the complete remaining buffer to `bytes`;
- each consumption step deletes from the front of that buffer;
- the public output bound is also used as the engine's inflate batch size;
- a large one-item feed therefore performs repeated suffix copies and can scale superlinearly;
- the same representation makes incomplete-header parsing copy and rescan more data than its safety limit is meant to protect;
- async wrappers can execute later bounded-output iterations inline, making those copies visible as event-loop stalls.

The official `2.0.0a1` benchmark record also preserves a repeatable **39.2%** stdlib-zlib regression in `decompress_chunks()` at 512 KiB compressed-input / 256 KiB output boundaries relative to `v1.11.0`. The 512/256 KiB compression case was **7.6%** slower, and the diagnostic 10-byte write stress case was **39.0%** slower.

The purpose of `a2` is to repair and lock down these regressions while preserving the successful `a1` contracts. It remains an alpha because:

- the decoder's private data model changes materially;
- internal inflation batching is decoupled from public output chunking for the first time;
- the public operation return type is made explicit for typing;
- real downstream integrations have not yet validated the provisional codec API broadly enough for beta.

A successful `a2` may become the basis for a beta decision. This plan does not predeclare `2.0.0b1`.

---

## 3. Release outcome

At release completion:

1. `GzipDecoder.feed()` accepts a complete large gzip archive as one `bytes` object without repeatedly copying the entire unconsumed suffix.
2. Direct decoder runtime scales approximately linearly over the locked 8–64 MiB regression matrix.
3. One-large-feed performance is within a small constant factor of transport-sized feeds.
4. Public emitted chunks remain no larger than `output_chunk_size`.
5. Internal inflate batches are bounded independently of the public emitted chunk size.
6. Tiny emitted chunks no longer cause one engine-decompression call per emitted byte or per tiny chunk.
7. The 512/256 KiB `decompress_chunks()` case is back inside the historical high-level release gate.
8. A one-item async source no longer produces the alpha's long scheduler gaps on the release reference machine.
9. Incomplete FNAME/FCOMMENT headers are parsed incrementally without whole-pending-buffer copies or rescanning from byte zero.
10. The 128 MiB header limit is checked before an operation allocates or copies a header-sized temporary.
11. Gzip correctness, member metadata, limits, operation ownership, cancellation, seeking, and cross-engine behavior remain compatible.
12. The documented operation cleanup method is visible in the public type system through `CodecOperation`.
13. `main` identifies itself as `2.0.0a2.dev0` during development.
14. Raw regression samples are committed and auditable.
15. The release candidate contains no undocumented performance exception for the central decoder gates.

---

## 4. Scope

### 4.1 In scope

- A private immutable-span input queue for codec parsing and inflation.
- Engine-normalized retained-input bytes in addition to consumed counts.
- Bounded compressed-input windows for the decoder body.
- A separate bounded internal inflate-output batch.
- A bounded output-block cursor that splits internal output into public chunks without front deletion.
- Incremental gzip header parsing, including FEXTRA, FNAME, FCOMMENT, and FHCRC.
- Incremental NUL-padding consumption and exact trailer reads.
- Async cooperative scheduling after bounded inline work.
- Revalidation of executor cancellation and operation cleanup.
- A public typed `CodecOperation` interface exposing `close()`.
- Release-version housekeeping and lifecycle-document clarification.
- A dedicated regression benchmark category and committed raw samples.
- Investigation of the 512/256 KiB compression regression.
- Profiling and documented disposition of the tiny-write diagnostic regression.
- Full stdlib-zlib and zlib-ng correctness/performance validation.

### 4.2 Explicit non-goals

Do not implement any of the following in this release:

- AnyIO or Trio support;
- indexed or zran-style random access;
- raw DEFLATE or configurable public `wbits`;
- ISA-L/python-isal support;
- a public source-chunk-size or internal-window constructor option;
- a switch from the iterator API to the predeclared pull-style fallback;
- a context-manager API for codec operations;
- a buffered asynchronous writer that defers sink errors across `write()` calls;
- parallel decompression;
- a separate codec-only distribution;
- broad package-root lazy-import redesign;
- unrelated dependency upgrades or formatting churn;
- stable `2.0.0` compatibility guarantees;
- performance comparisons that replace correctness or memory gates.

If a non-goal becomes necessary to satisfy a release blocker, stop and report rather than expanding scope.

---

## 5. Fixed design decisions

### D1. Release identity

- Development version: `2.0.0a2.dev0`.
- Candidate version: `2.0.0a2` only in the final release-preparation commit.
- Development status remains Alpha.
- Python floor remains 3.11.
- The established high-level asyncio API remains source-compatible.

### D2. Dual historical baselines

Use two baselines because the public codec did not exist in `v1.11.0`:

- `v1.11.0` is the baseline for high-level file, streaming, memory, compression, and concurrency cases that existed in 1.x.
- exact `v2.0.0a1` is the baseline for direct codec scaling, one-large-feed behavior, scheduler gaps caused by the codec path, header amplification, and public operation behavior.

A candidate does not pass merely because it improves on `a1`; it must also avoid regressing established 1.x high-level paths.

### D3. The core codec owns the fix

The primary performance correction must live in `GzipDecoder` and its private helpers.

Wrappers may preserve or improve their transport boundaries, but these are insufficient fixes:

- splitting one source item inside `decompress_chunks()` while the public decoder remains superlinear;
- increasing wrapper chunk sizes;
- adding a special whole-buffer fast path that bypasses shared validation;
- routing direct-codec calls through asyncio or an executor;
- buffering the complete decoded result and slicing afterward.

### D4. Immutable span queue

Add `src/aiogzip/_codec_buffer.py` with a private queue backed by immutable `bytes` spans and logical offsets, not a monolithic front-deleted `bytearray`.

The intended internal shape is equivalent to:

```python
@dataclass(slots=True)
class _Span:
    data: bytes
    start: int
    end: int

class _InputQueue:
    _spans: deque[_Span]
    _size: int
```

Required properties:

- appending an exact `bytes` feed stores a reference without copying it;
- a `bytes` subclass has already been snapshotted by the public boundary;
- partial consumption advances an offset rather than deleting or rebuilding the suffix;
- fully consumed spans are released promptly;
- total queued size is O(1) to query;
- reads across spans copy only the requested bounded amount;
- the queue can prepend normalized engine-retained bytes at EOF without reordering later input;
- clearing releases all span references;
- no queue operation converts all pending bytes merely to inspect a prefix.

Private method names may be adjusted for clarity, but the module must provide the logical operations needed for:

- `append(data)`;
- `prepend(data)`;
- `take(max_bytes)`;
- `take_exact(size)`;
- `pop_window(max_bytes)`;
- leading-byte inspection/consumption;
- `clear()`;
- `len(queue)`.

Any temporary `to_bytes()` compatibility helper used during migration must accept an explicit maximum and must be removed by WP4.

### D5. Bounded compressed-input windows

The body inflater never receives the complete remaining accepted input merely because it is available.

Start with a private constant:

```python
_INFLATE_INPUT_WINDOW = 256 * 1024
```

This is a private implementation value, not a public compatibility promise. It may be changed only after recording benchmark evidence for at least 64 KiB, 256 KiB, and 512 KiB candidates on both engines.

The decoder owns at most one active contiguous body-input window. It removes that bounded window from `_InputQueue`, passes it to the engine, and retains the engine-normalized unconsumed suffix for the next step. It must not reconstruct that window from the entire queue on every advancement.

### D6. Engine normalization returns retained bytes

Extend `_engine._InflateStep` from:

```python
output: bytes
consumed: int
eof: bool
```

to the logical contract:

```python
output: bytes
consumed: int
eof: bool
retained: bytes
```

`retained` is the exact normalized suffix of the supplied bounded input span that the decoder must process again or reinterpret as post-DEFLATE bytes.

Normalization must continue to support engines that:

- duplicate the same post-EOF bytes in `unused_data` and `unconsumed_tail`;
- populate only one field;
- split a suffix across both fields;
- expose overlapping fields;
- return equal bytes in distinct objects;
- use the non-aliasing fake-engine patterns already required by `a1`.

Requirements:

- `consumed == len(data) - len(retained)`;
- `retained` must represent a suffix of the supplied window;
- non-EOF retained bytes remain the active inflate input;
- EOF-retained bytes are prepended to the parse queue for trailer/member processing;
- irreconcilable engine reports fail loudly;
- no engine-specific alias assumption may escape `_engine.py`.

### D7. Separate internal inflate output from public emitted chunks

The public `output_chunk_size` remains an upper bound on each yielded `bytes`. It is no longer the only bound passed to `decompressobj.decompress()`.

Start with:

```python
_INFLATE_OUTPUT_BATCH = 256 * 1024
```

The engine output bound is the private `_INFLATE_OUTPUT_BATCH`, independent of the caller's public `output_chunk_size`. A public output bound larger than the private batch may therefore receive smaller chunks; the public contract promises a maximum, not a minimum or exact chunk size. Do not coalesce several engine blocks merely to fill a larger public bound.

For a decoder with `max_decompressed_size`, do not combine allowed output and the overflow probe in one engine block:

- while the remaining allowance is positive, request at most `min(_INFLATE_OUTPUT_BATCH, remaining)` bytes;
- after the exact limit is reached, request at most one additional byte on the next engine step only when EOF has not already been established;
- if that probe produces a byte, raise the existing limit error before storing, accounting, or yielding it;
- if the probe produces no output but consumes input or reaches EOF, continue normal framing validation;
- no byte beyond the limit is yielded or included in CRC/member-size counters;
- the codec does not materialize an arbitrarily large over-limit batch.

Store one engine output block plus an offset. Split it into public chunks using an offset; do not delete from the front of a `bytearray` or repeatedly copy the un-emitted suffix. When the public bound exceeds the internal block, yield the internal block directly rather than copying or waiting to coalesce more output.

Treat 256 KiB as the initial value, not an unmeasured conclusion. Record comparative evidence for at least 64 KiB, 256 KiB, 512 KiB, and 1 MiB private output batches on both engines before freezing the release value.

The decoder may account CRC and member size for the bounded internal block before every slice has been returned, because an abandoned partial operation is unusable by contract. Document that counters can be ahead of the last chunk observed by at most one bounded internal batch while an operation is active. Full integrity is still established only after trailer validation.

### D8. Engine-call count must not scale with tiny public chunks

For a fixed compressed stream, reducing `output_chunk_size` from 256 KiB to 1 byte necessarily increases Python iterator yields. It must not cause one inflate-engine call per emitted byte.

Add deterministic counting-engine tests. For a one-member stream whose output fits in one internal batch, `output_chunk_size=1` must still require only O(1) inflate calls plus framing calls. Do not rely only on wall-clock timing for this invariant.

### D9. Incremental header parser

Move header parsing into `src/aiogzip/_gzip_header.py` with a private stateful parser. Move `_ParsedHeader` there as well.

The parser consumes from `_InputQueue` and retains only the state necessary for the current header:

- fixed ten-byte header;
- flags and mtime;
- FEXTRA length and remaining bytes;
- current FNAME/FCOMMENT field;
- running FHCRC value;
- total header bytes seen;
- optional metadata buffers only when collection is enabled.

Required behavior:

- validate magic, method, and reserved flags as soon as enough bytes exist;
- process FEXTRA without waiting for the body;
- scan FNAME and FCOMMENT from the previous scan point, never from byte zero;
- include terminators in header CRC accounting;
- preserve Latin-1 metadata decoding;
- validate FHCRC over exactly the bytes preceding the CRC field;
- enforce the 128 MiB safety limit before copying or accumulating the byte that would exceed it;
- avoid a 128 MiB temporary merely to reject a 128 MiB header;
- retain metadata only when `collect_member_info=True`;
- distinguish an untouched empty stream from a partially started truncated header;
- preserve existing error classes and tested message prefixes.

### D10. Padding and trailers use queue cursors

- Skip allowed NUL padding by consuming leading zero spans or span prefixes.
- Do not call `lstrip()` on the complete pending input.
- Read exactly eight trailer bytes through `take_exact(8)`.
- Preserve member compressed offsets and compressed sizes, excluding inter-member padding exactly as in `a1`.
- Keep non-zero trailing material invalid.

### D11. Public operation model remains iterator-based

Do not switch to the pull-style fallback in `a2`.

Preserve:

- one active state-changing operation;
- deterministic reservation independent of garbage collection;
- single-use lazy iteration;
- `RuntimeError` for overlapping operations;
- poisoning on partial `close()`;
- `discard()` as irreversible codec cleanup;
- invalidated retained operations raising `RuntimeError` when advanced;
- no finalizer-driven state mutation.

The buffering repair is not evidence that iterator ownership itself failed.

### D12. Publish `CodecOperation`

Add a public structural type in `aiogzip.codec`:

```python
class CodecOperation(Iterator[bytes], Protocol):
    def close(self) -> None: ...
```

The exact spelling may use equivalent `Protocol` methods if required by mypy and `ty`, but it must remain structural and must expose iteration plus `close()`.

- Export it from `aiogzip.codec` and package-root `aiogzip`.
- Annotate all state-changing codec methods with `CodecOperation`.
- Annotate `_CodecBase._reserve()` as returning `CodecOperation`. Keep the async driver's extra raw-advance method on a private protocol that extends `CodecOperation`; `_drive_operation()` accepts that private protocol rather than adding the raw method to the public type.
- Keep assignment to `Iterator[bytes]` valid.
- Do not add context-manager semantics in this release.

Also add private operation invalidation so `discard()` releases an outstanding generator's captured input promptly. A retained invalidated operation must still raise `RuntimeError` when advanced and have idempotent `close()`.

### D13. Async scheduling is cooperative and bounded

Preserve the existing cancellation rule: cleanup must not race a worker thread still advancing mutable codec state.

A bounded engine call is necessary but is not, by itself, a bound on one public `next()`: a valid DEFLATE stream can consume several bounded input windows without producing output. The async driver therefore needs a private progress path that never changes the public byte iterator:

- add a private immutable progress event carrying the compressed-input bytes consumed by one no-output inflate step;
- allow the decoder's private generator to produce that event after a body-engine step consumes input but has no byte block to expose;
- keep the concrete operation's public `__next__()` byte-only by swallowing private progress events and continuing synchronously;
- add a private concrete-operation advancement method, not part of public `CodecOperation`, that returns one raw byte/progress/completion event to `_codec_async`;
- never represent progress as `b""`, never expose the private event to public callers, and never add it to `__all__`.

The async driver counts private no-output progress as well as visible output. Initial private policy:

- checkpoint after 1 MiB of inline yielded output, or
- after 4,096 inline yielded chunks, or
- after 1 MiB of compressed input is consumed without output, or
- after eight consecutive no-output inflate steps,
- whichever occurs first.

Use `await asyncio.sleep(0)` or a small private equivalent. Visible output resets only the consecutive no-output counters. A worker-thread hop or cooperative checkpoint resets all fairness counters. A raw async advancement performs at most one inflate-engine call; public synchronous `next()` may continue across private progress events because synchronous callers did not request scheduler cooperation.

These thresholds are private and may be tuned only with the scheduler-gap, adversarial no-output, and throughput benchmarks. The final values and evidence must be recorded.

Do not:

- checkpoint after every chunk or every ordinary engine call;
- yield empty public chunks as scheduling signals;
- expose the private progress type in the public protocol;
- offload pure output slicing;
- offload every bounded inflate step;
- suppress cancellation until the complete stream finishes;
- discard state while an executor call is running.

### D14. Async offload policy moves out of the engine module

Move `run_zlib_in_thread` and asyncio imports out of `_engine.py` and into `_codec_async.py` or another async-only private module.

After this change:

- `_engine.py` contains synchronous engine selection, normalization, CRC, and constructors;
- the codec's dependency closure contains no asyncio scheduling policy;
- `_codec_async.py` owns executor and cooperative scheduling policy.

This is a dependency-boundary cleanup, not a separate package split.

### D15. High-level wrapper behavior is preserved

The binary file, text file, streaming, inspection, verification, seek, rewind, append, and CLI paths continue to use the shared codec.

Do not reintroduce a second gzip state machine.

Preserve:

- accepted high-level bytes-like writer inputs;
- call-time snapshot behavior;
- partial-write handling;
- sink error precedence;
- write-broken/read-broken states;
- rewind caching and seek semantics;
- member metadata and mtime behavior;
- strict-size behavior;
- the limit exception type and no-over-limit guarantee, while applying the explicit `a2` clarification that every allowed byte through the exact limit is emitted before an overflow error;
- concatenated members;
- deterministic gzip output guarantees already documented.

### D16. Compression regressions are investigated without weakening ownership

The 512/256 KiB compression case is a representative gate. The tiny-write stress case is diagnostic.

For both:

- profile operation creation, engine calls, CRC, chunk slicing, async-driver overhead, and sink calls separately;
- retain deterministic operation ownership;
- do not add cross-call writer buffering in `a2`;
- do not delay sink failures from one `write()` into a later `flush()` or `close()`;
- apply only optimizations supported by profile evidence and correctness tests.

It is acceptable for the tiny-write diagnostic to remain slower than `v1.11.0` if the result is understood, does not worsen from `a1`, and no safe local optimization exists. It is not acceptable to ignore or omit it from the candidate report.

### D17. No new public tuning knobs

The input window, internal output batch, queue compaction policy, and cooperative checkpoint policy remain private.

Alpha users should provide feedback on semantics, not be forced to select internal buffering parameters that are not yet stable.

### D18. Error and metadata compatibility

Unless this plan explicitly says otherwise:

- preserve exception types;
- preserve tested stable message prefixes;
- preserve zero-member finish behavior;
- preserve strict reserved-flag rejection;
- preserve validated-member timing;
- preserve member indexing and offsets;
- preserve `compressed_size` accounting at `feed()` call time.

One deliberate alpha clarification is permitted: when an input exceeds `max_decompressed_size`, `a2` emits every byte through the exact configured limit before a later advancement raises the existing `OSError`. `a1` could raise before returning all allowed bytes when its engine call crossed the limit. The probe byte is never yielded, counted, or included in CRC/ISIZE accounting. Document this as a correctness normalization, not a compatibility-neutral implementation detail.

Clarify in docs that `compressed_size` includes accepted bytes from an active, not-yet-advanced operation, while decoded counters can be ahead of observed yielded chunks by at most one internal batch during an active operation.

### D19. Benchmark data is a release artifact

The final candidate must commit:

```text
plans/benchmarks/v2.0.0a2-candidate.md
plans/benchmarks/data/v2.0.0a2-candidate-stdlib.json
plans/benchmarks/data/v2.0.0a2-candidate-zlib-ng.json
```

The raw JSON must include individual samples and dispersion. Hash-only references to unavailable local files are insufficient.

---

## 6. Observable contracts that must not regress

### 6.1 Decoder behavior

- `feed()` accepts exact `bytes` and snapshots `bytes` subclasses as in `a1`.
- Mutable and general buffer objects remain invalid at the public codec boundary.
- `feed(b"")` remains a real state-changing operation with normal ownership rules.
- `feed()` after successful `finish()` raises `ValueError`.
- repeated `finish()` raises `ValueError`.
- `finish()` on no accepted input validates a zero-member stream.
- payload bytes may precede trailer validation.
- completion validates CRC and ISIZE for every member.
- concatenated members and permitted NUL padding remain supported.
- trailing non-padding bytes remain invalid.
- no yielded chunk exceeds `output_chunk_size`.
- every output byte through the exact `max_decompressed_size` limit is yielded before overflow is reported;
- no output byte beyond `max_decompressed_size` is yielded or counted.
- decoder failure makes the instance unusable.

### 6.2 Operation ownership

- creating an operation reserves the codec before iteration;
- a dropped but not collected operation keeps the reservation;
- garbage collection never releases it;
- `gc.disable()` does not alter observable ownership;
- closing a partially advanced operation poisons the codec;
- `discard()` invalidates and releases state;
- advancing a retained invalidated operation raises `RuntimeError` without output or engine access;
- closing an invalidated operation is idempotent;
- reentrant advancement raises `RuntimeError`;
- codec instances and operations remain not thread-safe.

### 6.3 File and streaming surfaces

- the async iterable APIs remain pull-driven;
- no background producer or queue is introduced;
- source-item boundaries do not affect correctness;
- cancellation waits for active executor work before state disposal;
- file reads, readinto, readline, line iteration, seek, rewind, inspect, and verify agree on valid and invalid streams;
- stdlib-created files remain readable;
- aiogzip-created files remain readable by stdlib gzip.

---

## 7. Target architecture

### 7.1 File map

Expected additions and changes:

```text
src/aiogzip/
├── __init__.py                 # version and CodecOperation export
├── codec.py                    # public encoder/decoder orchestration
├── _codec_buffer.py            # immutable span queue and output-block cursor
├── _gzip_header.py             # incremental header parser and _ParsedHeader
├── _engine.py                  # synchronous engine selection/normalization
├── _codec_async.py             # executor and cooperative scheduling policy
├── _streaming.py               # shared codec integration, no state machine
├── _binary.py                  # integration/regression adjustments only
└── _inspection.py              # integration/regression adjustments only

tests/
├── test_codec.py
├── test_codec_buffer.py
├── test_gzip_header_parser.py
├── test_codec_decoder_regressions.py
├── test_codec_operation_typing.py
├── test_codec_async_fairness.py
├── test_streaming.py
├── test_binary*.py
└── test_cross_surface_properties.py

benchmarks/
├── bench_codec_regressions.py
├── bench_streaming.py
├── run_benchmarks.py
├── bench_compare.py
└── README.md

plans/benchmarks/
├── v2.0.0a1-regression-baseline.md
├── v2.0.0a2-candidate.md
└── data/
    ├── v1.11.0-a2-comparable-stdlib.json
    ├── v1.11.0-a2-comparable-zlib-ng.json
    ├── v2.0.0a1-regression-stdlib.json
    ├── v2.0.0a1-regression-zlib-ng.json
    ├── main-pre-a2-regression-stdlib.json
    ├── main-pre-a2-regression-zlib-ng.json
    ├── v2.0.0a2-candidate-stdlib.json
    └── v2.0.0a2-candidate-zlib-ng.json
```

Use the repository's actual split test filenames when they differ. Do not create duplicate broad test modules merely to match this sketch.

### 7.2 Dependency direction

Required direction:

```text
_common / _metadata
        ↓
     _engine        _codec_buffer        _gzip_header
        \               |                    /
         \              |                   /
                     codec
                       ↓
                 _codec_async
                  ↙    ↓    ↘
          _streaming  _binary  _inspection
                       ↓
                     _text
```

Forbidden directions:

- `_engine` importing `asyncio` or `_codec_async`;
- `codec` importing file, streaming, inspection, or asyncio modules;
- `_gzip_header` performing I/O;
- wrappers reimplementing gzip framing or integrity checks;
- benchmark helpers imported by production code.

### 7.3 Body data flow

For each feed operation:

1. The public boundary validates/snapshots the input before reservation.
2. The lazy operation appends the exact snapshot as a queue span when first advanced.
3. Header/padding/trailer states consume only the needed queue prefix.
4. Body state obtains at most `_INFLATE_INPUT_WINDOW` contiguous bytes.
5. `_engine.inflate_step()` returns bounded output plus normalized retained input.
6. Consumed compressed accounting advances by `step.consumed`.
7. Non-EOF retained input remains the active body window.
8. EOF retained input is prepended for trailer/member parsing.
9. A bounded internal output block is split into public chunks by offset.
10. The next engine call occurs only after that block is drained.

### 7.4 Complexity target

For incompressible or ordinarily compressed data supplied in one large feed:

- queue append is O(1);
- queue consumption is O(number of spans/windows), not O(total remaining bytes) per output;
- every aiogzip-created contiguous body-input materialization is bounded by `_INFLATE_INPUT_WINDOW`;
- every internal output block is bounded;
- no front deletion moves the complete remaining compressed suffix;
- no body step calls `bytes()` on all accepted pending input;
- total Python-side buffering work scales approximately linearly with input plus output.

This is an algorithmic requirement, not merely a benchmark aspiration.

---

## 8. Regression benchmark design

### 8.1 Harness requirements

Add a `regressions` benchmark category. The harness must:

- generate fixtures and pre-split every source-item sequence outside timed and `tracemalloc` regions;
- retain the pre-split exact `bytes` items for the complete run so source slicing/allocation is not charged to one boundary mode but not another;
- record source item count, minimum/maximum item size, and total bytes;
- use deterministic SHAKE-256 or an equivalently stable seeded byte generator for incompressible fixtures;
- use deterministic patterned fixtures for highly compressible data;
- create gzip bytes with fixed level and `mtime=0`;
- stream decoded output into a digest rather than joining it;
- assert exact byte count and digest after every timed run;
- add `--regression-profile {quick,release}` for this category; preserve the existing global `--quick` category-selection behavior;
- retain individual samples in JSON;
- report medians and median absolute deviation;
- add an explicit `--source-root PATH` (or equivalently strict target option) that imports aiogzip from `PATH/src`, records `aiogzip.__file__`, and refuses a mismatch before timing;
- record the resolved source root, package version, and exact target commit in every JSON result;
- support forced stdlib and active zlib-ng runs;
- separate timing and `tracemalloc` runs;
- avoid collecting event-loop gap samples in the same run used for pure throughput.

### 8.2 Direct decoder scaling matrix

Release matrix for incompressible payloads:

| Uncompressed size | Source boundary | Output bound |
| ---: | --- | ---: |
| 8 MiB | one `feed()` | 256 KiB |
| 16 MiB | one `feed()` | 256 KiB |
| 32 MiB | one `feed()` | 256 KiB |
| 64 MiB | one `feed()` | 256 KiB |
| 8 MiB | 256 KiB compressed items | 256 KiB |
| 16 MiB | 256 KiB compressed items | 256 KiB |
| 32 MiB | 256 KiB compressed items | 256 KiB |
| 64 MiB | 256 KiB compressed items | 256 KiB |

Also run 8 and 32 MiB highly compressible fixtures under both source-boundary modes.

Report:

- median wall time and dispersion;
- throughput;
- one-feed/chunked ratio;
- doubling ratios;
- time per MiB;
- peak Python allocation excluding fixture creation;
- output digest and byte count;
- engine name.

### 8.3 Public output-bound matrix

On a deterministic 128 KiB decoded fixture, run:

```text
output_chunk_size = 1
output_chunk_size = 1 KiB
output_chunk_size = 64 KiB
output_chunk_size = 256 KiB
```

Report:

- total iterator yields;
- engine `decompress()` call count through an instrumented wrapper;
- wall time;
- maximum yielded chunk;
- peak memory.

The call-count result, not the one-byte wall time, is the primary invariant.

### 8.4 Async scheduler matrix

Use an async source that yields the complete compressed fixture as one item. Test 8, 16, 32, and 64 MiB incompressible decoded sizes with 256 KiB public output.

Run a cooperative ticker in a sibling task. Prime it before decompression and record:

- ticker baseline with no codec workload;
- total decompression time;
- ticker count;
- p50, p95, p99, and maximum scheduling gap;
- first-output latency;
- output digest and byte count.

Run a second source with 256 KiB compressed items to separate source-boundary effects.

Add a separate adversarial no-output case. Use a deterministic fake engine in ordinary tests and a modest valid RFC 1951 fixture containing an output-producing prefix followed by many empty blocks in the release benchmark. Cross-check the real fixture with stdlib gzip before timing. Report private progress-event count, engine-call count, consumed compressed bytes, ticker gaps, and whether any empty public byte chunk escaped. Fixture construction is outside the timed region; do not make this synthetic case part of the representative throughput aggregate.

### 8.5 Header matrix

Construct valid or intentionally incomplete members containing:

- FEXTRA split across boundaries;
- FNAME with lengths 1, 4, 16, 32, and 64 MiB;
- FCOMMENT with the same lengths;
- both FNAME and FCOMMENT;
- FHCRC with all optional fields;
- missing terminators;
- a terminator at the exact safety boundary;
- a terminator one byte beyond the safety boundary;
- long trailing NUL padding;
- non-zero data after allowed padding.

Feed using:

- one item;
- 64 KiB items;
- 1 KiB items for quick fragmented cases.

Run metadata collection both disabled and enabled where memory permits.

### 8.6 Existing high-level cases

Retain the exact historical cases in the existing benchmark suite, especially:

- binary bulk single write/read;
- binary 64 KiB chunked write/read;
- binary 10-byte write stress;
- binary reader 64 KiB output;
- binary writer 64 KiB input;
- read-all highly compressible;
- `compress_chunks` 64/64 and 512/256;
- `decompress_chunks` 64/64 and 512/256;
- simulated-latency concurrency;
- mixed operations;
- streaming and full-read memory sentinels.

Do not replace them with only new codec microbenchmarks.

---

## 9. Performance gates

Absolute millisecond values below are meaningful only on the same locked reference environment as the existing records. On another machine or materially different interpreter/engine environment, compute the same percentage thresholds from the same-harness exact-`v1.11.0` captures produced in WP0; do not compare candidate milliseconds to the table across environments. The percentage rules remain authoritative, and any material divergence between the new same-harness `v1.11.0` samples and the locked historical record must be explained rather than silently substituted.

### 9.1 Historical high-level gates

| Operation | `v1.11.0` | `2.0.0a1` | `a2` target | `a2` blocker |
| --- | ---: | ---: | ---: | ---: |
| `decompress_chunks`, 512/256 KiB | 6.62 ms | 9.22 ms | ≤ 6.95 ms (+5%) | > 7.28 ms (+10%) |
| `decompress_chunks`, 64/64 KiB | 2.18 ms | 2.27 ms | ≤ 2.29 ms (+5%) | > 2.40 ms (+10%) |
| `compress_chunks`, 512/256 KiB | 124.55 ms | 134.06 ms | ≤ 130.78 ms (+5%) | > 137.01 ms (+10%) |
| `compress_chunks`, 64/64 KiB | 117.89 ms | 117.10 ms | ≤ 123.78 ms (+5%) | > 129.68 ms (+10%) |

Rules:

- The 512/256 decoder case has **no correctness-tradeoff waiver in `a2`**. Repairing it is a release objective.
- A result between +5% and +10% requires profiling, rerun with at least nine repeats if dispersion is material, and a written explanation.
- A result above +10% blocks the release.
- Every other comparable representative high-level case uses the same +5% investigation and +10% blocking policy unless a stricter gate is listed.
- Wins in other cases do not offset a named miss.

### 9.2 Direct large-feed gates

Using the newly locked `v2.0.0a1` regression baseline:

- [ ] At 32 MiB, the candidate one-feed median is at least 4× faster than `a1`.
- [ ] At 64 MiB, the candidate one-feed median is at least 4× faster than `a1`.
- [ ] Candidate one-feed/chunked ratio is ≤ 1.5× target and ≤ 3.0× hard maximum at both 32 and 64 MiB.
- [ ] Candidate 16/8, 32/16, and 64/32 one-feed doubling ratios are ≤ 2.25× target and ≤ 2.5× hard maximum.
- [ ] Candidate time per MiB at 64 MiB is ≤ 1.25× target and ≤ 1.5× hard maximum relative to 8 MiB.
- [ ] Both stdlib zlib and zlib-ng show non-superlinear growth; zlib-ng may have different absolute throughput.

If the `a1` reference machine differs from the candidate machine, rerun the exact `a1` tag and candidate in the same session; do not compare absolute numbers across machines.

### 9.3 Tiny-output deterministic gate

- [ ] For output fitting within one internal batch, `output_chunk_size=1` does not cause engine calls proportional to output bytes.
- [ ] A counting-engine test establishes the bound without timing.
- [ ] Maximum public yield length is exactly within the configured bound for every matrix value.
- [ ] Memory remains bounded by the private internal batch plus ordinary codec state; it does not grow with the number of emitted chunks.

### 9.4 Scheduler-latency gate

On the locked release reference environment, for a one-item 32 MiB incompressible source and 256 KiB public output:

- target maximum ticker gap: ≤ 20 ms;
- hard maximum ticker gap: ≤ 50 ms;
- candidate must improve the exact-tag `a1` maximum gap by at least 4× unless `a1` was already below 20 ms on that machine;
- throughput must remain within the high-level gates.

Timing-sensitive scheduler gates run in the release benchmark, not as brittle ordinary CI assertions. CI must contain deterministic cooperative-checkpoint tests and a functional ticker-progress test.

The adversarial no-output path has a separate hard functional gate:

- [ ] the deterministic fake engine gives a sibling task progress no later than the first configured no-output byte or step threshold;
- [ ] one private raw advancement performs at most one inflate-engine call;
- [ ] the valid empty-block fixture gives the ticker progress before decode completion and emits no empty public chunks;
- [ ] failure of any of these conditions blocks the release even when ordinary one-item throughput and maximum-gap timing pass.

The synthetic fixture's absolute throughput is informational; its bounded-progress behavior is not.

### 9.5 Header and memory gates

- [ ] With metadata collection disabled, parsing a 32 MiB incomplete FNAME or FCOMMENT has incremental Python peak allocation below 4 MiB when fixture creation is excluded.
- [ ] With metadata enabled, peak incremental allocation is no more than field size × 2.25 plus 4 MiB; this allows the encoded field and decoded Latin-1 string to coexist briefly but forbids duplicate whole-header retention.
- [ ] Fragmented-header doubling ratios are ≤ 2.5×.
- [ ] A reduced-limit unit test proves rejection occurs before consuming or copying the first byte beyond the configured header limit.
- [ ] A release-only real-limit test validates the 128 MiB boundary.
- [ ] No body input following a legal near-limit header is misclassified as header bytes.

### 9.6 Existing memory sentinels

- `decompress_chunks`, compressible 8 MiB: target no worse than `a1` +10%; hard ceiling `v1.11.0` +25%.
- full read, compressible 8 MiB: target no worse than `a1` +10%; hard ceiling no worse than the `v1.11.0` peak.
- no new unbounded queue or retained complete result.
- a large one-feed benchmark must consume output into a digest, not retain it, so the measured peak reflects codec buffering.

### 9.7 Tiny-write diagnostic

The 10-byte write stress result is not a representative release blocker, but it is not ignored.

- target: reduce the delta to ≤ +25% versus `v1.11.0`;
- hard anti-regression guard: no more than +10% slower than `2.0.0a1`;
- if target is not met, commit profile evidence and a written decision explaining why ownership-preserving local optimizations were insufficient;
- do not introduce cross-call buffering or weaken deterministic operation ownership merely to hit the target.

---

## 10. Work packages

### WP0 — Lock the regression harness, baselines, and `a2` development line

#### Objective

Create auditable measurements before production changes and establish the new development version.

#### Tasks

- [x] Add this plan at `plans/RELEASE_2_0_0A2_PLAN.md`.
- [x] Verify all SHAs in section 0.
- [x] Verify that `.codexrc`, `AGENTS.md`, and `.pre-commit-config.yaml` remain aligned on `uv run prek run --all-files`, and that `scripts/check_py38_compat.py` remains absent; make no tooling edit when the locked-base state is already correct.
- [x] Add `benchmarks/bench_codec_regressions.py`.
- [x] Register the `regressions` category in `benchmarks/run_benchmarks.py`.
- [x] Add `--regression-profile {quick,release}` without changing the existing meaning of the global `--quick` option. Reject the profile flag when the regressions category is not selected.
- [x] Extend benchmark JSON output to retain individual samples and median absolute deviation without breaking existing consumers.
- [x] Add `--source-root PATH` and source-root verification so benchmark runs cannot accidentally import the current checkout instead of the requested worktree.
- [x] Run target imports in a clean subprocess when necessary so an already imported editable checkout cannot contaminate a historical run.
- [x] Record the resolved source root, `aiogzip.__file__`, package version, and target commit in JSON.
- [x] Add deterministic fixture hashing and output-digest validation.
- [x] Add async ticker-gap collection as a separate benchmark mode.
- [x] Add header and output-bound matrices.
- [x] Document the category and commands in `benchmarks/README.md`.
- [x] Run the comparable historical high-level cases against exact `v1.11.0` with forced stdlib.
- [x] Run those supported cases against exact `v1.11.0` with zlib-ng active; record unsupported codec-only cases as explicit skips rather than synthetic zeros.
- [x] Run the full regression harness against exact `v2.0.0a1` with forced stdlib.
- [x] Run it against exact `v2.0.0a1` with zlib-ng active.
- [x] Run it against the expected `main` base before production changes under both engine selections.
- [x] Commit raw JSON and `v2.0.0a1-regression-baseline.md`.
- [x] Set `aiogzip.__version__` to `2.0.0a2.dev0` only after baseline capture.
- [x] Add an Unreleased changelog skeleton describing regression repair without claiming results.
- [x] Reconcile demonstrably completed `a1` post-release checklist items; do not mark unverifiable maintainer actions complete.

#### Validation

```bash
uv run ruff check benchmarks plans src/aiogzip/__init__.py
uv run ruff format --check benchmarks src/aiogzip/__init__.py
uv run python benchmarks/run_benchmarks.py --category regressions \
  --regression-profile quick --source-root . --repeat 3
```

Also execute the exact detached-worktree commands recorded in the baseline document.

#### Exit criteria

- [x] No `src/aiogzip/` production behavior changed before the baseline files were committed.
- [x] Exact `v1.11.0`, exact-tag `v2.0.0a1`, and starting-main raw samples are inspectable in Git.
- [x] Every benchmark verifies correctness.
- [x] The harness identifies the imported aiogzip source.
- [x] `main` reports `2.0.0a2.dev0` after the housekeeping commit.
- [x] The repository is green.

#### Suggested commits

```text
test: add decoder regression benchmark harness
chore: lock the 2.0.0a1 regression baseline
chore: begin the 2.0.0a2 development line
```

Do not combine baseline capture with production-code changes.

---

### WP1 — Pin decoder behavior before changing its data model

#### Objective

Add focused characterization around state transitions and edge cases most likely to be disturbed by the buffering rewrite.

#### Tasks

- [x] Inventory existing codec, streaming, binary, inspection, verification, and property tests covering decoder behavior.
- [x] Add missing cases without changing production code.
- [x] Pin zero-member finish.
- [x] Pin empty feeds at header, body, trailer, and post-member padding boundaries.
- [x] Pin concatenated empty and non-empty members.
- [x] Pin FEXTRA, FNAME, FCOMMENT, FHCRC, combinations, and split boundaries.
- [x] Pin reserved flags and unknown compression method failures.
- [x] Pin exactly seven trailer bytes followed by finish.
- [x] Pin CRC and ISIZE failures after payload emission.
- [x] Pin permitted trailing NUL padding and invalid non-zero trailing data.
- [x] Pin member compressed offsets with and without padding.
- [x] Pin `collect_member_info=False` not retaining optional metadata.
- [x] Pin `max_decompressed_size` at limit-1, exact limit, and limit+1 for tiny and large output bounds.
- [x] Pin `compressed_size` call-time accounting for an unadvanced operation.
- [x] Pin operation drop, partial close, discard, retained invalidated iterator, reentrancy, and `gc.disable()` behavior.
- [x] Pin cancellation while the first operation advancement is running in an executor.
- [x] Pin cross-surface results for randomized source boundaries.

#### Required test technique

Use small deterministic fixtures for ordinary CI. Do not add multi-second timing assertions in WP1.

Where error messages are already asserted, preserve exact text. Otherwise assert type and stable context rather than freezing incidental formatting.

#### Exit criteria

- [x] Tests pass unchanged against the pre-refactor production code.
- [x] The characterization suite fails under deliberate local mutations to CRC, trailer, member transition, and ownership behavior.
- [x] No performance fix has begun.
- [x] Checklist changes are in the same commit.

#### Suggested commit

```text
test: pin decoder contracts before buffering repair
```

---

### WP2 — Add immutable span buffering and retained-input normalization

#### Objective

Introduce and test the private primitives needed by the body rewrite without yet changing public decoder behavior.

#### Tasks: `_codec_buffer.py`

- [x] Add `_Span` and `_InputQueue`.
- [x] Use `deque` or an equivalently O(1) head-removal structure.
- [x] Track total queued length explicitly.
- [x] Retain exact `bytes` spans without copying on append.
- [x] Implement partial head consumption by offset.
- [x] Release fully consumed spans promptly.
- [x] Implement bounded `take()`.
- [x] Implement exact-length `take_exact()` that returns `None` or an equivalent need-more signal without consuming partial data.
- [x] Implement bounded `pop_window()`.
- [x] Implement `prepend()` for normalized EOF-retained bytes.
- [x] Implement leading-byte inspection/consumption needed for padding.
- [x] Implement idempotent `clear()`.
- [x] Reject non-exact bytes at this internal boundary with an assertion or clear internal error.
- [x] Add an output-block cursor or equivalent offset helper; no front deletion.

#### Tasks: `_engine.py`

- [x] Extend `_InflateStep` with normalized retained bytes.
- [x] Replace or extend `_merged_retained_size()` with a helper returning the normalized suffix.
- [x] Reuse an engine-provided exact retained object when valid rather than copying automatically.
- [x] Construct a merged bounded suffix only for split/overlap cases.
- [x] Preserve no-progress detection.
- [x] Preserve engine error normalization.
- [x] Keep consumed-count validation.
- [x] Do not change engine selection.

#### Required tests

`test_codec_buffer.py`:

- [x] append and length;
- [x] exact-span zero-copy identity where observable internally;
- [x] partial consumption;
- [x] cross-span bounded take;
- [x] exact read success/failure without partial consumption;
- [x] prepend ordering;
- [x] repeated small spans;
- [x] clearing releases references;
- [x] no negative or over-consumption;
- [x] output cursor emits bounded slices and releases drained blocks.

Engine tests:

- [x] duplicated leftovers;
- [x] only `unused_data`;
- [x] only `unconsumed_tail`;
- [x] split suffix;
- [x] overlapping suffix;
- [x] equal non-identical objects;
- [x] irreconcilable fields;
- [x] too-long field ending in supplied data;
- [x] non-suffix tail;
- [x] consumed/output/no-progress combinations;
- [x] stdlib and zlib-ng real-engine smoke tests.

#### Exit criteria

- [x] New primitives are fully tested but not yet required by public code.
- [x] `_engine.inflate_step()` callers are updated compatibly or a temporary adapter keeps the repository green.
- [x] Fake non-aliasing engine coverage remains stronger than `a1`.
- [x] No asyncio dependency is moved yet unless needed solely to keep typing green; D14 belongs to WP5.

#### Suggested commit

```text
refactor: add bounded codec input spans
```

---

### WP3 — Rewrite decoder body inflation and output batching

#### Objective

Remove the superlinear body-copy path and decouple engine batches from public emitted chunks.

#### Tasks

- [x] Replace `GzipDecoder._pending: bytearray` with `_InputQueue`.
- [x] Add a bounded active inflate-input field.
- [x] Add a bounded internal output-block field and offset.
- [x] Add an EOF-after-output marker so trailer transition waits until the output block is drained.
- [x] Append accepted snapshots as immutable spans on first operation advancement.
- [x] Immediately clear the generator-local feed snapshot after queue ownership is established; the active operation must not keep a second stale reference to a large feed solely through its frame locals.
- [x] Pull at most `_INFLATE_INPUT_WINDOW` for one engine input window.
- [x] Pass only that bounded window to `_engine.inflate_step()`.
- [x] Increment compressed-consumption accounting by `step.consumed`, not by popped-window size.
- [x] Retain non-EOF `step.retained` as the next body input.
- [x] Prepend EOF `step.retained` for trailer parsing.
- [x] Store `step.output` as one internal block.
- [x] Split it into chunks no larger than `output_chunk_size` by offset.
- [x] Do not front-delete output bytes.
- [x] Avoid another engine call until the current output block is drained.
- [x] Implement exact-limit and one-byte overflow probing as a separate post-limit engine step; never place allowed bytes and the probe byte in the same stored output block.
- [x] Preserve CRC, ISIZE, member size, and total uncompressed accounting.
- [x] Preserve body error context including member index and compressed offset.
- [x] Clear active input/output references on failure and discard.
- [x] Keep a temporary bounded header adapter only if required; it must be removed in WP4.

#### Forbidden implementation shortcuts

- `bytes(all_pending_input)` in the body path;
- `del pending[:consumed]` on a monolithic buffer;
- decompressing without `max_length`;
- yielding a public chunk larger than the configured public bound;
- collecting yielded chunks to split later;
- bypassing `_engine.inflate_step()` normalization;
- changing wrapper source boundaries as the primary fix.

#### Required deterministic tests

- [x] one large feed equals 1-byte, 1 KiB, 64 KiB, and 256 KiB feed boundaries;
- [x] maximum yielded chunk for all public output bounds;
- [x] counting engine proves tiny public chunks do not multiply inflate calls;
- [x] retained non-EOF input is replayed exactly once in order;
- [x] EOF retained trailer bytes are parsed before later queued spans;
- [x] one window containing end of member 1 and all of member 2 works;
- [x] output block with EOF drains before trailer validation;
- [x] close/discard while output remains poisons/releases correctly;
- [x] exact decompression limit emits every allowed byte, then rejects the first extra byte on a later advancement without accounting or yielding it;
- [x] a fake engine returning output with zero consumed input can make bounded progress;
- [x] a fake engine returning neither output nor consumption raises no-progress error;
- [x] engine call input length never exceeds the selected private window;
- [x] internal output length never exceeds the selected private batch bound.

#### Interim benchmark gate

Before WP4:

- [x] Compare private input-window candidates of 64 KiB, 256 KiB, and 512 KiB on the direct scaling and 512/256 KiB streaming cases under both engines.
- [x] Compare private output-batch candidates of 64 KiB, 256 KiB, 512 KiB, and 1 MiB under both engines, including tiny public output and decompression-limit cases.
- [x] Record the tuning table in the PR notes or a committed benchmark analysis; do not leave an undocumented temporary benchmark switch in production.
- [x] Run the direct large-feed and existing streaming benchmarks on stdlib.
- [x] The 32 and 64 MiB one-feed cases meet the hard scaling ratios.
- [x] The 512/256 KiB `decompress_chunks()` result is within +10% of `v1.11.0`.
- [x] Tiny-output engine-call count is fixed.
- [x] If these miss, stop and profile before header work. Do not hope WP4 will repair a body-path miss.

The WP3 interim measurements are provisional Apple M3 MacBook Air results.
The Framework Desktop rerun remains an incomplete release gate; see
`plans/benchmarks/v2.0.0a2-wp3-buffer-tuning.md`.

#### Exit criteria

- [x] The monolithic body suffix is never copied or shifted per yielded output.
- [x] All characterization and cross-surface tests pass.
- [x] Both engines pass focused codec tests.
- [x] Interim hard performance gates pass.
- [x] No public API changed.

#### Suggested commit

```text
perf: bound decoder input and inflate batches
```

---

### WP4 — Replace whole-buffer header, padding, and trailer parsing

#### Objective

Close the oversized-header allocation gap and make header processing linear across fragmented feeds.

#### Tasks

- [x] Add `_GzipHeaderParser` and `_ParsedHeader` in `_gzip_header.py`.
- [x] Move all fixed-header validation into the parser.
- [x] Maintain running header CRC incrementally.
- [x] Parse FEXTRA length and bytes incrementally.
- [x] Parse FNAME incrementally from the prior scan point.
- [x] Parse FCOMMENT incrementally from the prior scan point.
- [x] Validate FHCRC without reconstructing the complete header.
- [x] Allocate optional metadata buffers only when collection is enabled.
- [x] Count every header byte toward the safety limit.
- [x] Reject before accepting/copying the first byte beyond the limit.
- [x] Preserve Latin-1 decoding and optional `None` values.
- [x] Track whether a header has started for finish-time truncation errors.
- [x] Replace whole-buffer padding `lstrip` with cursor consumption.
- [x] Replace trailer slicing with exact queue reads.
- [x] Remove `_parse_header()` from `codec.py`.
- [x] Remove temporary whole-queue conversion helpers.
- [x] Keep member offsets and padding accounting compatible.

#### Required tests

- [x] every split point through the fixed ten-byte header;
- [x] every split point around FEXTRA length and payload;
- [x] every split point around FNAME/FCOMMENT terminators;
- [x] metadata enabled and disabled;
- [x] hostile near-limit names/comments;
- [x] exact-limit terminator accepted;
- [x] one-byte-over-limit rejected before body consumption;
- [x] valid body immediately after near-limit header;
- [x] FHCRC valid/invalid across all optional fields;
- [x] multiple members with large metadata;
- [x] padding split over many spans;
- [x] real 128 MiB boundary marked slow/release-only;
- [x] reduced injected limit in ordinary CI;
- [x] fragmented-header runtime grows approximately linearly in benchmark mode;
- [x] peak allocation gates.

#### Exit criteria

- [x] No header state calls `bytes()` or `lstrip()` on all pending data.
- [x] No parser rescan begins at byte zero after a partial feed.
- [x] The safety check precedes oversized temporary allocation.
- [x] Header and body data in the same span remain correctly separated.
- [x] All malformed-header behavior remains correctly typed.

WP4 validation on the Apple M3 MacBook Air is recorded in
`plans/benchmarks/v2.0.0a2-wp4-header-parser.md`. The implementation package is
complete; the Framework Desktop rerun remains mandatory for the final release
gate.

#### Suggested commit

```text
perf: parse gzip headers incrementally
```

---

### WP5 — Bound async scheduling latency and isolate async policy

#### Objective

Make the bounded synchronous work visible as responsive asyncio behavior while preserving cancellation safety.

#### Tasks

- [x] Move executor helper code and `asyncio` imports out of `_engine.py`.
- [x] Keep `_engine.py` importable without async scheduling policy.
- [x] Add a private `_AsyncDrivableOperation` protocol or equivalent covering byte iteration, `close()`, and the raw-advance capability; do not export it and do not publish `CodecOperation` before WP7.
- [x] Update `_drive_operation()` to accept that private protocol.
- [x] Add a private progress event for a no-output inflate step; keep it out of the future public `CodecOperation`, `__all__`, documentation, and public iteration.
- [x] Make ordinary `_Operation.__next__()` swallow private progress events while a private async-only advancement returns at most one raw byte/progress/completion event.
- [x] Preserve first-step offload based on accepted workload size.
- [x] Track inline output bytes, inline yielded-chunk count, no-output compressed bytes, and consecutive no-output steps.
- [x] Add cooperative checkpoints at the private thresholds.
- [x] Reset the relevant counters after visible output, executor hops, and checkpoints.
- [x] Do not checkpoint after each chunk or each ordinary engine call.
- [x] Do not offload output-only block slicing.
- [x] Preserve wait-for-worker-before-close/discard on cancellation.
- [x] Preserve exception precedence when cancellation and codec failure coincide.
- [x] Verify binary writer and decoder driver call sites.
- [x] Verify streaming, inspection, and verification call sites.

#### Required tests

- [x] a controlled synchronous operation yielding many immediately ready chunks gives a sibling ticker progress;
- [x] checkpoint happens by byte threshold;
- [x] checkpoint happens by chunk-count threshold;
- [x] a fake engine consuming repeated bounded windows without output produces private progress and gives a sibling ticker progress by the no-output byte or step threshold;
- [x] public synchronous iteration over that operation exposes only `bytes`, never the private progress event or an empty scheduling chunk;
- [x] one private async advancement performs at most one inflate call;
- [x] a modest valid empty-block DEFLATE fixture agrees with stdlib gzip and completes without scheduler starvation;
- [x] no checkpoint occurs before any applicable threshold;
- [x] visible output resets the consecutive no-output counters;
- [x] executor hop resets checkpoint accounting;
- [x] cancellation after a private progress event preserves normal close/discard poisoning semantics;
- [x] cancellation during worker advancement waits for worker completion;
- [x] operation is closed/discarded exactly once;
- [x] codec state is not mutated concurrently from event loop and worker;
- [x] output ordering and chunk bounds are unchanged;
- [x] no empty chunks are introduced;
- [x] async generator early close preserves cleanup semantics.

#### Benchmark validation

- [x] Run scheduler-gap matrix on exact `a1` and candidate in the same session.
- [x] Run the adversarial no-output scheduler case and record progress-event/engine-call counts separately from representative throughput.
- [x] Meet the 32 MiB maximum-gap hard gate.
- [x] Confirm the no-output case makes bounded cooperative progress and emits no empty public chunks.
- [x] Run high-level throughput benchmarks after adding checkpoints.
- [x] If fairness thresholds cause a >5% throughput regression, tune them using recorded evidence; do not remove checkpoints.
- [x] Record final private thresholds.

#### Exit criteria

- [x] Scheduler gap and throughput gates both pass.
- [x] Cancellation tests pass repeatedly under forced stdlib and active zlib-ng.
- [x] `_engine.py` has no asyncio import or executor helper.
- [x] No background task or queue exists.

#### Suggested commit

```text
perf: bound async codec scheduling latency
```

---

### WP6 — Investigate compression and tiny-write regressions

#### Objective

Recover safe compression-side overhead where evidence supports it and document what remains.

#### Measurement tasks

- [x] Re-run 64/64 and 512/256 compression cases with at least nine repeats if the initial delta exceeds 5%.
- [x] Re-run the 10-byte write diagnostic under identical conditions.
- [x] Profile separately with stdlib and zlib-ng compression where applicable.
- [x] Attribute time to input normalization, operation allocation, `__next__`, engine compression, CRC, output slicing, async driver, sink writes, and event-loop overhead.
- [x] Record profile commands and summaries in `plans/benchmarks/v2.0.0a2-compression-analysis.md`.

#### Permitted optimization areas

- avoid redundant exact-bytes checks already guaranteed by an internal caller;
- avoid redundant output-slice allocation when the complete engine result already fits the public bound;
- reduce private driver indirection without bypassing operation ownership;
- remove repeated calculations from hot paths;
- improve benchmark harness noise handling.

#### Forbidden optimization areas

- bypassing public codec lifecycle from file writers;
- adding a second eager encoder state machine;
- reusing an operation object across public operations;
- deferring accepted uncompressed input across separate `write()` calls;
- changing sink error timing;
- weakening CRC or strict-size accounting;
- selecting zlib-ng compression unless explicitly requested;
- suppressing an unfavorable diagnostic.

#### Acceptance

- [x] 512/256 compression meets the +10% hard gate and targets +5%.
- [x] 64/64 compression remains within gate.
- [x] Tiny-write stress is no worse than `a1` by more than 10%.
- [x] Any code optimization has focused tests and before/after profile evidence.
- [x] If no safe tiny-write improvement exists, the retained overhead and deferred buffered-writer option are documented without claiming the regression is fixed.

#### Exit criteria

- [x] Representative compression is within the release gate.
- [x] Diagnostic tiny-write behavior has an evidence-based disposition.
- [x] Ownership and error timing remain unchanged.

#### Suggested commit

Use one of:

```text
perf: reduce codec operation overhead
```

or, when no safe code change is justified:

```text
docs: record 2.0 alpha compression regression analysis
```

Do not create an empty code optimization merely to fit the suggested title.

---

### WP7 — Publish typed operations and tighten lifecycle cleanup

#### Objective

Make the documented `close()` contract type-correct and release captured resources promptly on explicit discard.

#### Tasks

- [ ] Add public `CodecOperation` protocol.
- [ ] Export it from `aiogzip.codec`.
- [ ] Export it from package root and `__all__`.
- [ ] Update `start()`, `feed()`, `flush()`, and `finish()` annotations.
- [ ] Update private reservation annotations and make the private async-driver protocol extend public `CodecOperation` while retaining its private raw-advance member.
- [ ] Remove cleanup `getattr()` where direct typed invocation is valid.
- [ ] Add private `_Operation._invalidate()` or equivalent.
- [ ] Make `discard()` invalidate the active operation before dropping its token.
- [ ] Release the underlying generator/iterator reference during invalidation.
- [ ] Preserve retained invalidated iterator `RuntimeError` behavior.
- [ ] Preserve idempotent close.
- [ ] Preserve no-finalizer rule.
- [ ] Update API docs and examples.
- [ ] Clarify compressed and uncompressed counter timing.

#### Type tests

Add strict mypy and `ty` snippets proving:

```python
operation: aiogzip.CodecOperation = decoder.feed(data)
operation.close()
iterator: Iterator[bytes] = operation
```

Also prove that an ordinary `Iterator[bytes]` is not incorrectly promised to have `close()`.

#### Runtime tests

- [ ] `discard()` releases a large unadvanced feed snapshot even while the operation object remains reachable;
- [ ] advancing that operation raises `RuntimeError`;
- [ ] closing it is idempotent;
- [ ] no engine method runs after invalidation;
- [ ] operation ownership tests still pass with `gc.disable()`;
- [ ] public import and `__all__` tests pass;
- [ ] generated docs show `close()`.

#### Exit criteria

- [ ] Official lifecycle examples type-check without ignores.
- [ ] No return annotation remains merely `Iterator[bytes]` where cleanup is supported.
- [ ] Explicit discard promptly drops captured input.
- [ ] Runtime semantics remain compatible.

#### Suggested commit

```text
feat: expose typed codec operations
```

---

### WP8 — Cross-surface hardening and randomized verification

#### Objective

Prove that the optimized decoder remains the one shared source of gzip truth across every interface.

#### Tasks

- [ ] Run and extend cross-surface property tests.
- [ ] Generate randomized zero-to-five-member archives.
- [ ] Include empty members, random metadata, padding, arbitrary source splits, and output bounds.
- [ ] Compare direct codec, async iterable, binary file, inspect, verify, and stdlib behavior.
- [ ] Corrupt fixed headers, optional fields, bodies, trailers, and inter-member boundaries.
- [ ] Exercise exact and one-over decompression limits.
- [ ] Exercise backward seek and rewind after the data-model change.
- [ ] Exercise non-seekable rewind caching.
- [ ] Exercise append members and deterministic output.
- [ ] Exercise cancellation at header, body, output-block, trailer, and sink-write points.
- [ ] Exercise partial operation close with queued spans and pending output.
- [ ] Run with stdlib forced while zlib-ng is installed.
- [ ] Run with zlib-ng active.
- [ ] Run a repeated stress loop to detect retained spans or output blocks after completion.

#### Exit criteria

- [ ] No surface has a private gzip parser or integrity implementation.
- [ ] Randomized valid archives agree across surfaces.
- [ ] Randomized corrupt archives fail with compatible classes and context.
- [ ] Seeking and rewind behavior is unchanged.
- [ ] No persistent memory growth is observed across repeated decoder instances.

#### Suggested commit

```text
test: harden optimized codec across public surfaces
```

---

### WP9 — Documentation, final benchmarks, packaging, and release candidate

#### Objective

Produce an auditable `2.0.0a2` candidate only after all hard gates pass.

#### Documentation tasks

- [ ] Update `CHANGELOG.md` with measured, non-promotional wording.
- [ ] Explain that `a2` replaces monolithic pending-input copying with bounded spans/windows.
- [ ] Explain separate internal inflate batching and public output bounds.
- [ ] Document the normalized limit behavior: all allowed bytes are emitted before the overflow error, and the probe byte is not counted.
- [ ] State that source boundaries should no longer cause superlinear copying, while transport-sized items remain sensible.
- [ ] Document bounded internal read-ahead/accounting during an active operation.
- [ ] Document `CodecOperation` and `close()`.
- [ ] Add safe lifecycle examples using `try/finally`.
- [ ] Clarify `compressed_size` call-time semantics.
- [ ] Update the codec ADR with the buffering decision and alternatives considered.
- [ ] Record why wrapper-only rechunking and offload-every-step were rejected.
- [ ] Record the chosen private window, batch, and checkpoint values with benchmark evidence.
- [ ] Update performance guidance with one-item and transport-item results.
- [ ] Do not claim a tiny-write regression was fixed unless the gate data supports it.

#### Final benchmark tasks

- [ ] Freeze production code before final benchmark capture.
- [ ] Run the complete historical suite under forced stdlib with five or more repeats.
- [ ] Run the complete historical suite with zlib-ng active with three or more repeats.
- [ ] Run the complete regression category with release matrix and five or more repeats.
- [ ] Rerun noisy cases with nine repeats.
- [ ] Commit raw JSON samples.
- [ ] Create `plans/benchmarks/v2.0.0a2-candidate.md`.
- [ ] Include direct comparisons to both locked baselines.
- [ ] List every >5% delta and its investigation.
- [ ] State explicitly that the central decoder gates have no waiver.
- [ ] Include event-loop gap distributions.
- [ ] Include memory peaks.
- [ ] Include engine-call counts.
- [ ] Include fixture and source hashes.
- [ ] Include any accepted non-blocking tiny-write disposition.

#### Quality and packaging tasks

- [ ] Run `ruff check .`.
- [ ] Run `ruff format --check .`.
- [ ] Run `mypy src`.
- [ ] Run `ty check src`.
- [ ] Run `uv run prek run --all-files`.
- [ ] Run forced-stdlib pytest with branch coverage and `--cov-fail-under=85`.
- [ ] Run zlib-ng-active pytest with branch coverage and `--cov-fail-under=85`.
- [ ] Run forced stdlib while zlib-ng remains installed.
- [ ] Run the slow release tests, including real header limit and scaling checks.
- [ ] Run strict documentation build.
- [ ] Build wheel and sdist.
- [ ] Inspect metadata: version, Python floor, Alpha classifier, typed marker, dependencies.
- [ ] Install wheel into clean Python 3.11 and 3.14 environments.
- [ ] Smoke direct codec, streaming, file I/O, inspect, verify, CLI, and optional zlib-ng from the wheel.
- [ ] Confirm source tree and built wheel report the intended version.
- [ ] Confirm no benchmark fixtures or oversized raw files accidentally entered the distribution.
- [ ] Confirm package import contains no benchmark dependency.

#### Release-preparation tasks

Only after all gates pass:

- [ ] Set version from `2.0.0a2.dev0` to `2.0.0a2`.
- [ ] Add the actual release date to the changelog.
- [ ] Update changelog comparison links.
- [ ] Rebuild artifacts from the exact release-preparation commit.
- [ ] Record artifact hashes.
- [ ] Leave tagging, GitHub release creation, PyPI publication, documentation deployment, and post-release version bump to the maintainer.

#### Exit criteria

- [ ] Every hard regression gate passes.
- [ ] No central decoder exception remains.
- [ ] Every >5% high-level delta is explained.
- [ ] Raw data is committed.
- [ ] All CI-equivalent checks pass.
- [ ] Wheel smoke tests pass.
- [ ] Release notes are accurate and reproducible.
- [ ] At least one independent reviewer has approved the buffering and async-cancellation changes before maintainer publication.

#### Suggested commits

```text
docs: document the bounded decoder architecture
bench: record the 2.0.0a2 release candidate
chore: prepare release 2.0.0a2
```

---

## 11. Required test matrix

### 11.1 Interpreter and platform

Match the maintained CI policy:

- Linux: Python 3.11, 3.12, 3.13, 3.14;
- Windows: representative Python 3.12;
- macOS: representative Python 3.12.

Performance release gates run on the locked Linux reference machine. Platform jobs are correctness gates, not cross-machine timing comparisons.

### 11.2 Engine

- stdlib zlib with zlib-ng absent where available;
- zlib-ng active;
- stdlib forced through `AIOGZIP_ENGINE=stdlib` while zlib-ng is installed;
- fake engine with non-aliasing and split retained data;
- counting engine for call-bound assertions;
- controlled slow operation for cancellation/fairness tests.

### 11.3 Functional dimensions

Cross at least representative combinations of:

- zero, one, and multiple members;
- empty and non-empty members;
- compressible and incompressible data;
- one large feed and fragmented feeds;
- output bounds 1, 1 KiB, 64 KiB, 256 KiB, and a larger valid value;
- metadata disabled/enabled;
- no limit, exact limit, one-over limit;
- valid and invalid FHCRC;
- optional fields absent/present;
- padding absent/present;
- normal completion, partial close, discard, cancellation, and engine failure;
- direct codec, async streaming, binary file, inspection, and verification.

### 11.4 Coverage

- Keep branch coverage above the repository's 85% CI gate.
- New private parser and buffer modules require direct branch-focused tests; do not rely only on integration coverage.
- Performance-only branches must still have deterministic functional tests.
- Do not exclude difficult error paths from coverage merely because they are private.

---

## 12. Release gates

### Correctness — hard blockers

- [ ] All existing tests pass.
- [ ] All new buffer, parser, ownership, and fairness tests pass.
- [ ] stdlib and zlib-ng produce equivalent decoded bytes and member validation.
- [ ] CRC, ISIZE, FHCRC, reserved flags, and trailing-data behavior remain correct.
- [ ] concatenated members and padding remain correct.
- [ ] output bounds and decompression limits remain strict.
- [ ] cross-surface properties pass.
- [ ] seeking, rewind, append, and deterministic output pass.

### Architecture — hard blockers

- [ ] No monolithic front-deleted compressed pending buffer remains in `GzipDecoder`.
- [ ] No body step converts all pending compressed input to `bytes`.
- [ ] No header step converts all pending input or calls whole-buffer `lstrip()`.
- [ ] Engine retained data is normalized centrally.
- [ ] Public output and internal output batch are separate.
- [ ] Async policy is absent from `_engine.py`.
- [ ] No duplicate gzip state machine is introduced.
- [ ] No background producer or unbounded queue is introduced.

### Lifecycle and cancellation — hard blockers

- [ ] deterministic reservation remains GC-independent;
- [ ] partial close poisons;
- [ ] discard invalidates and promptly releases captured input;
- [ ] retained invalidated operation raises `RuntimeError`;
- [ ] worker completion precedes cleanup after cancellation;
- [ ] no concurrent codec advancement is possible;
- [ ] official examples type-check through `CodecOperation`.

### Performance — hard blockers

- [ ] 512/256 KiB decoder historical gate passes without waiver.
- [ ] direct large-feed scaling hard gates pass.
- [ ] tiny-output engine-call invariant passes.
- [ ] scheduler maximum-gap hard gate passes.
- [ ] header allocation and scaling gates pass.
- [ ] existing memory hard ceilings pass.
- [ ] no new representative high-level case exceeds +10% without an explicitly permitted, reviewed exception; the central decoder cases do not permit one.

### Quality and packaging — hard blockers

- [ ] Ruff, mypy, `ty`, `prek`, coverage, and docs pass.
- [ ] Python/OS matrix passes.
- [ ] both engine modes pass.
- [ ] wheel and sdist build.
- [ ] clean-wheel smoke tests pass.
- [ ] package metadata is correct.
- [ ] raw benchmark samples and candidate report are committed.
- [ ] version and changelog are consistent.

### Maintainer-only gates

- [ ] independent review obtained;
- [ ] remote issue/milestone updated or created for any deferred regression;
- [ ] release commit signed according to project practice;
- [ ] tag created from exact release commit;
- [ ] GitHub prerelease created;
- [ ] artifacts published through Trusted Publishing;
- [ ] attestations verified;
- [ ] versioned docs deployed under the prerelease alias;
- [ ] `main` advanced to the next development version after release.

Codex records these items but does not execute them.

---

## 13. Risk register

### R1. Retained-input normalization corrupts member boundaries

**Failure mode:** trailer or next-member bytes are consumed as DEFLATE input, duplicated, or reordered.

**Mitigation:** retain exact normalized suffix bytes; prepend EOF leftovers; fake split/overlap engines; one-window multi-member tests; member-offset assertions.

**Gate:** randomized cross-surface members and both real engines.

### R2. Internal output batching weakens the decompression limit

**Failure mode:** a batch emits bytes beyond the configured limit or allocates far beyond it.

**Mitigation:** remaining-limit-aware engine requests; a separate one-byte post-limit probe; exact-limit tests proving every allowed byte is emitted and the probe is neither counted nor yielded.

**Gate:** no byte beyond limit yielded; bounded over-read.

### R3. Internal counters get ahead of visible output unexpectedly

**Failure mode:** callers infer emitted bytes from `uncompressed_size` during an active operation.

**Mitigation:** bound the lead to one internal batch; document it; preserve full consistency after operation exhaustion; poison partial operations.

**Gate:** counter-timing tests and docs.

### R4. Incremental header parser changes accepted syntax or error behavior

**Failure mode:** valid optional fields fail, invalid flags pass, FHCRC covers the wrong bytes, or truncation messages drift.

**Mitigation:** exhaustive split tests, stdlib fixtures, current characterization, running CRC tests, exact boundary tests.

**Gate:** header matrix and cross-surface verification.

### R5. Header metadata retains excessive memory

**Failure mode:** parser copies large names/comments even when metadata is disabled, or stores duplicate full-header bytes.

**Mitigation:** metadata buffers conditional; incremental CRC; no whole-header retention; tracemalloc gates.

**Gate:** 32 MiB metadata-off and metadata-on peaks.

### R6. Cooperative checkpoints repair fairness but regress throughput

**Failure mode:** too many `sleep(0)` calls dominate normal streaming.

**Mitigation:** byte and chunk thresholds, not per-yield checkpointing; separate timing and fairness benchmarks; tune privately with evidence.

**Gate:** scheduler and historical throughput gates together.

### R7. Cancellation races with a running worker

**Failure mode:** event-loop cleanup releases queue or engine state while a worker still advances it.

**Mitigation:** preserve shield/wait ordering; controlled blocked-worker tests; one owner at a time.

**Gate:** repeated cancellation tests under both engines.

### R8. Queue spans retain complete large inputs too long

**Failure mode:** consumed prefix objects remain referenced through stale spans, active windows, operations, or output blocks.

**Mitigation:** pop fully consumed spans, clear generator-local feed snapshots after queue handoff, clear active fields, invalidate operations on discard, and use allocation/frame-lifetime tests where practical.

**Gate:** repeated large-feed memory and discard-retention tests.

### R9. Benchmark optimization overfits one engine

**Failure mode:** stdlib improves while zlib-ng regresses or leftover assumptions return.

**Mitigation:** both-engine benchmarks and fake engine; no engine-specific fast path without explicit evidence.

**Gate:** zlib-ng scaling and correctness.

### R10. Benchmark noise causes false confidence

**Failure mode:** short medians move because of governor, boost, load, or tmpfs state.

**Mitigation:** environment record, odd repeat counts, raw samples, MAD, same-session reruns, longer scaling cases.

**Gate:** rerun material/noisy deltas with nine repeats.

### R11. Tiny-write optimization weakens error timing

**Failure mode:** buffering across calls makes an earlier successful write fail only at close.

**Mitigation:** prohibit cross-call buffering in `a2`; permit only local profile-backed reductions.

**Gate:** sink-failure and position tests.

### R12. Public operation type accidentally freezes implementation details

**Failure mode:** exposing the concrete `_Operation` class prevents later changes.

**Mitigation:** publish a structural protocol, keep concrete implementation private, no context-manager promise.

**Gate:** public API review and type tests.

### R13. Scope expands into the pull-style fallback

**Failure mode:** performance work becomes an API redesign.

**Mitigation:** preserve iterator API; private batching solves engine-call amplification; reassess only after `a2` downstream feedback.

**Gate:** no public pull methods in diff.

### R14. A no-output DEFLATE run defeats output-based fairness

**Failure mode:** bounded input windows still permit one public advancement to execute many no-output inflate calls before yielding a byte, so output-byte and output-chunk checkpoints never run.

**Mitigation:** private progress events observable only by the async driver; one raw async advancement per engine call; byte/step budgets for no-output work; a fake-engine deterministic test plus a valid empty-block fixture.

**Gate:** no private progress object or empty scheduling chunk reaches public iteration, cancellation semantics remain intact, and the adversarial ticker test shows bounded cooperative progress.

---

## 14. Review strategy

Require review in layers rather than one undifferentiated PR pass.

### Review 1 — Baseline and methodology

Review:

- benchmark import isolation;
- deterministic fixtures;
- correctness outside timed regions;
- raw sample schema;
- environment record;
- gate formulas.

Do this before production changes so a flawed baseline does not contaminate the release.

### Review 2 — Buffer and engine accounting

Review:

- span lifetime and offsets;
- bounded copies;
- retained suffix normalization;
- EOF/trailer ordering;
- no-progress behavior;
- fake-engine completeness.

### Review 3 — Decoder body and limits

Review:

- internal input/output bounds;
- limit off-by-one behavior;
- CRC/size timing;
- output block draining;
- one-feed complexity;
- memory release.

### Review 4 — Header parser

Review:

- RFC 1952 field order;
- FHCRC byte coverage;
- safety-boundary order;
- metadata-disabled memory;
- member offsets and padding.

### Review 5 — Async scheduling and cancellation

Review:

- executor ownership;
- cancellation ordering;
- checkpoint frequency;
- no background work;
- scheduler benchmark method.

### Review 6 — Public API and release evidence

Review:

- `CodecOperation` typing;
- docs and examples;
- benchmark gates;
- release artifacts;
- remaining alpha caveats.

At least one reviewer other than the implementation author should focus on decoder/engine correctness, and one should focus on asyncio cancellation/fairness. One person may fill both roles if qualified, but the review comments should address both explicitly.

---

## 15. Suggested pull-request sequence

Preferred sequence:

1. **PR A — Baseline and characterization**
   WP0–WP1. No production performance changes.
2. **PR B — Bounded decoder body**
   WP2–WP3. Core queue, engine normalization, body batching, interim gates.
3. **PR C — Header and async hardening**
   WP4–WP5. Incremental parser, fairness, dependency boundary.
4. **PR D — Compression analysis and typed operations**
   WP6–WP7.
5. **PR E — Release hardening**
   WP8–WP9, final benchmarks, docs, packaging.

A maintainer may split these further. Do not merge them into one giant refactor PR.

Every PR description should include:

- work packages covered;
- checklist items completed;
- behavior intentionally unchanged;
- tests run;
- benchmark commands and results where applicable;
- risks remaining;
- whether later packages were touched;
- exact next package.

---

## 16. Release notes outline

### aiogzip 2.0.0a2

#### Fixed: decoder scaling and responsiveness

- Replaced repeated whole-pending-buffer copies with bounded immutable input spans and inflate windows.
- Separated internal inflate batches from public emitted chunk bounds.
- Prevented tiny public output chunks from multiplying engine calls.
- Normalized decompression-limit behavior so all allowed bytes are emitted before overflow is reported.
- Added cooperative scheduling for long inline async drains.

#### Fixed: defensive header parsing

- Parse optional gzip header fields incrementally.
- Enforce the header safety limit before oversized temporary allocation.
- Avoid repeated rescans of fragmented FNAME and FCOMMENT fields.

#### Added: typed codec operations

- Public `CodecOperation` exposes iteration and explicit `close()` to type checkers.

#### Compatibility

- Public codec lifecycle and high-level asyncio APIs remain compatible with `2.0.0a1`.
- The codec API remains provisional during the alpha series.
- Python 3.11+ remains required for 2.x.

#### Performance evidence

Insert measured release-machine results only after final capture:

- 512/256 KiB streaming comparison against `v1.11.0` and `a1`;
- 8–64 MiB one-feed scaling;
- scheduler maximum-gap comparison;
- memory peaks;
- compression and tiny-write disposition.

Do not insert placeholders as if they were results.

---

## 17. Post-`a2` decision

After publication and a defined downstream evaluation period, decide among:

- `2.0.0b1` if no lifecycle/API changes are needed, performance gates remain stable, and at least two real integrations exercise the public codec;
- `2.0.0a3` if iterator ergonomics, engine behavior, or buffering semantics require another material change;
- the predeclared bounded pull-style fallback only if concrete alpha evidence shows that operation ownership remains a recurring misuse source despite documentation and typing.

Do not switch to the pull API merely because it is more familiar. Record actual failure signals, such as repeated dropped-operation bugs, cleanup mistakes in multiple integrations, or an inability to express efficient transports without violating ownership.

Potential later work remains separate:

- AnyIO/Trio substrate;
- indexed random access;
- codec-only installation/import boundary;
- buffered writer design for many tiny writes;
- additional native engines.

---

## 18. Codex kickoff prompt

Copy the following prompt to Codex after committing this plan:

```text
Implement aiogzip 2.0.0a2 according to
plans/RELEASE_2_0_0A2_PLAN.md.

Treat the plan's locked SHAs, scope, fixed design decisions, regression gates,
and work-package ordering as authoritative.

Begin with section 0 and WP0. Before changing production code:

1. verify the exact main, v2.0.0a1, and v1.11.0 commits;
2. verify the locked-base `prek` tooling alignment and leave it unchanged when already correct;
3. add the benchmark-only regression harness;
4. capture and commit the exact-tag raw baselines with individual samples;
5. keep the repository green.

Work package by work package. Update checklist items in the same commit as the
implementation, tests, documentation, or benchmark evidence they describe.

The primary release objective is to remove the decoder's repeated whole-suffix
copying, restore the 512/256 KiB streaming case to the historical gate, make
one-large-feed scaling approximately linear, bound event-loop gaps, and fix
the oversized-header allocation order. The fix must live in the shared public
codec, not only in an async wrapper.

Do not weaken CRC/ISIZE/FHCRC validation, output bounds, decompression limits,
operation ownership, cancellation safety, or engine normalization. Do not hide
the issue by rechunking wrappers, increasing public chunks, offloading every
step, materializing the full output, or adding a background queue.

Do not implement AnyIO/Trio, indexed access, raw DEFLATE, ISA-L, the pull-style
fallback, a buffered cross-call writer, or unrelated cleanup.

If keeping a package green requires work assigned to a later package, stop and
report the dependency instead of pulling that work forward. If a performance
gate misses, stop, profile, and report; do not edit the threshold or baseline.

Do not tag, publish, push, create remote branches or issues, change repository
settings, deploy docs, or claim independent review. Record maintainer-only
handoff actions in the plan.
```
