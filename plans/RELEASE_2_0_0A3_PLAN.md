# aiogzip 2.0.0a3 Beta-Readiness Release Plan

> **Status:** Codex-ready implementation plan
> **Target release:** `2.0.0a3`
> **Repository destination:** `plans/RELEASE_2_0_0A3_PLAN.md`
> **Primary objective:** remove the file reader's duplicate gzip-header parser, restore correct live `mtime` behavior across concatenated members and rewinds, make a deliberate evidence-backed disposition on the remaining small-write regression, and validate the provisional 2.0 codec in realistic integrations without reopening the successful `2.0.0a2` decoder architecture.

This document is the living implementation checklist for aiogzip `2.0.0a3`. It is intentionally prescriptive. Codex must treat the locked commits, fixed design decisions, regression gates, scope boundaries, and work-package order as authoritative unless the maintainer edits this plan in a reviewed plan-only commit.

The release is a **beta-readiness alpha**, not a feature release. The central decoder scaling and scheduler work from `2.0.0a2` is considered successful and must be preserved. The remaining release work is concentrated in one high-level correctness/performance defect, one known diagnostic write regression, realistic integration evidence, and contract hardening before beta.

---

## 0. Locked starting points and mandatory preflight

### 0.1 Verify the exact repository base

This plan was written against the following immutable commits:

| Purpose | Commit |
| --- | --- |
| Expected `main` base | `a31f78ea8751a2fe6bb8a61ad1957bdf9108d851` |
| Published `v2.0.0a2` release | `9534eb31da15417126233eda225d8f897908e3bb` |
| Published `v2.0.0a1` release | `920004672bbb5e76fb2088358d1cb7051290576d` |
| Published `v1.11.0` comparison baseline | `3f23eadb524c8dba840c4fd855ad5acf84486048` |

Before editing any repository file, run:

```bash
git status --short
git rev-parse HEAD
git rev-parse v2.0.0a2^{commit}
git rev-parse v2.0.0a1^{commit}
git rev-parse v1.11.0^{commit}
git cat-file -e a31f78ea8751a2fe6bb8a61ad1957bdf9108d851^{commit}
git cat-file -e 9534eb31da15417126233eda225d8f897908e3bb^{commit}
git cat-file -e 920004672bbb5e76fb2088358d1cb7051290576d^{commit}
git cat-file -e 3f23eadb524c8dba840c4fd855ad5acf84486048^{commit}
```

Preflight requirements:

- [ ] The working tree is clean.
- [x] `HEAD` is exactly `a31f78ea8751a2fe6bb8a61ad1957bdf9108d851`.
- [x] `v2.0.0a2^{commit}` is exactly `9534eb31da15417126233eda225d8f897908e3bb`.
- [x] `v2.0.0a1^{commit}` is exactly `920004672bbb5e76fb2088358d1cb7051290576d`.
- [x] `v1.11.0^{commit}` is exactly `3f23eadb524c8dba840c4fd855ad5acf84486048`.
- [x] `src/aiogzip/__init__.py` reports `2.0.0a3.dev0`.
- [x] `CHANGELOG.md` has an empty `[Unreleased]` section before implementation entries are added.
- [x] `pyproject.toml` still declares Python `>=3.11` and the Alpha classifier.
- [x] `AGENTS.md` still requires `uv run prek run --all-files` before commits.

If `main` has advanced:

1. Stop before changing production code.
2. List every new commit and affected file.
3. Determine whether any change touches the codec, binary/text file layers, benchmarks, tests, packaging, or release records.
4. Do not silently replace the locked SHA.
5. Ask the maintainer to update this plan in a standalone reviewed plan-only commit.

Codex must not create, push, delete, or rename remote branches. Remote issues, labels, milestones, pull requests, tags, releases, documentation deployments, PyPI publication, repository settings, and branch protection are maintainer-only actions.

### 0.2 Verify the current release posture

The preflight report must record:

- [x] current version: `2.0.0a3.dev0`;
- [x] current open performance issue: #86, small-write overhead;
- [x] deferred architecture issues: #71, AnyIO substrate; #72, indexed random access;
- [x] current public codec status: provisional during the alpha series;
- [x] current maintained interpreter matrix: Python 3.11 through 3.14;
- [x] current engine matrix: stdlib zlib, zlib-ng active, and stdlib forced while zlib-ng is installed;
- [x] current coverage floor: 85%;
- [x] current release mechanism: tag-triggered Trusted Publishing.

Do not fold dependency updates, workflow modernization, broad style cleanup, or unrelated documentation changes into this release merely because they are nearby.

### 0.3 Add the `a3` regression harness before production changes

The existing `2.0.0a2` records preserve the repaired direct-decoder, streaming, scheduler, header-parser, memory, and historical high-level measurements. They do not measure the **high-level file reader's duplicate header probe**, and the existing tiny-write evidence is deliberately centered on the extreme 10-byte diagnostic rather than a useful write-size curve.

Before changing `src/aiogzip/`, add a benchmark-only commit containing the `a3` harness and its deterministic fixtures. Use that exact committed harness against detached worktrees for:

- exact `v2.0.0a2`;
- exact `v1.11.0` where the API supports the case;
- exact pre-change `main` at the locked `a3` base.

Create detached worktrees:

```bash
git worktree add --detach /tmp/aiogzip-v2.0.0a2-a3 v2.0.0a2
git worktree add --detach /tmp/aiogzip-v1.11.0-a3 v1.11.0
git worktree add --detach /tmp/aiogzip-main-pre-a3 a31f78ea8751a2fe6bb8a61ad1957bdf9108d851
```

The harness must support source-root injection or another documented mechanism so the identical benchmark code runs against each worktree without copying modified benchmark logic into the baselines.

Required new files:

```text
benchmarks/bench_a3_regressions.py
benchmarks/profile_small_writes.py
plans/benchmarks/v2.0.0a3-preflight.md
plans/benchmarks/data/v2.0.0a2-a3-baseline-stdlib.json
plans/benchmarks/data/v2.0.0a2-a3-baseline-zlib-ng.json
plans/benchmarks/data/v1.11.0-a3-comparable-stdlib.json
plans/benchmarks/data/v1.11.0-a3-comparable-zlib-ng.json
plans/benchmarks/data/main-pre-a3-stdlib.json
plans/benchmarks/data/main-pre-a3-zlib-ng.json
```

Use an equivalent existing benchmark module rather than creating a new one only when that module can express every required case without changing established result semantics. Document the choice.

The Markdown preflight record must include:

- [ ] exact source commits and clean-worktree status;
- [ ] benchmark-harness commit and SHA-256;
- [ ] fixture generator version and SHA-256 of each generated fixture;
- [ ] Python implementation, full version, executable, and build flags where available;
- [ ] OS, kernel, architecture, libc, CPU, logical/physical core count, and RAM;
- [ ] filesystem and temporary-directory location;
- [ ] stdlib zlib compile-time and runtime versions;
- [ ] zlib-ng package version and selected engine;
- [ ] `uv` version and `uv.lock` SHA-256;
- [ ] CPU governor, boost state, affinity, system load, power source, and other material conditions;
- [ ] exact commands;
- [ ] warm-up policy, repeat counts, garbage-collection policy, and ordering/randomization policy;
- [ ] every individual timing sample;
- [ ] medians, median absolute deviation, minima, maxima, and sample counts;
- [ ] peak-allocation method and values;
- [ ] sink/source call counts where relevant;
- [ ] output byte counts and SHA-256 values proving correctness;
- [ ] all interrupted, invalid, discarded, or excluded runs and why they were excluded.

Do not manufacture old-version measurements from prior prose. Run the exact harness or mark the gate unavailable.

### 0.4 Baseline immutability

After the first production-code change:

- [ ] Never overwrite committed exact-tag baseline JSON.
- [ ] Never rerun only the candidate after correcting a benchmark bug.
- [ ] If the harness is wrong, fix it in a standalone benchmark commit, preserve the superseded files, and recapture baseline and candidate with the corrected identical harness.
- [ ] Never change fixture sizes, fragmentation, write counts, thresholds, repeat counts, or formulas after seeing candidate results without explaining the change and recapturing all comparisons.
- [ ] Never average a named regression away with unrelated wins.
- [ ] Never describe a target as passed when the reference-machine baseline was not captured.
- [ ] Keep correctness checks outside timed regions where practical, but always retain output-size and digest verification.

---

## 1. Instructions to Codex

### 1.1 Execution model

Implement one work package at a time, in order.

For each package:

1. Read the complete package, its dependencies, fixed decisions, and exit criteria.
2. Inspect the current implementation and tests; do not assume line numbers or private names remain unchanged.
3. Add or revise tests before changing the behavior they protect, but do not commit a red package boundary.
4. Make the smallest coherent implementation change.
5. Update this plan's checklist in the same commit as the implementation, test, documentation, or evidence it describes.
6. Run package-specific checks plus the affected regression suite.
7. Run `uv run prek run --all-files` before every commit and treat `ruff format --check` as blocking.
8. Keep the repository green at every committed package boundary.
9. Report commands actually run, results, unresolved risks, and intentional non-changes.

A checkbox means the implementation, tests, documentation, and required evidence are present—not that code was drafted.

### 1.2 Forward-dependency rule

If keeping a package green requires work assigned to a later package:

- stop;
- identify the exact dependency and files;
- explain why a temporary compatibility seam is insufficient;
- propose a minimal package-boundary change or reorder;
- wait for a maintainer-edited plan.

Do not quietly pull later work forward. Do not combine the work packages into one giant refactor.

### 1.3 Regression and benchmark rules

- [ ] Profile before optimizing when the cause is not structurally proven.
- [ ] Preserve the `2.0.0a2` immutable-span input queue, bounded inflate windows, output cursor, progress events, and async cancellation ordering.
- [ ] Do not reintroduce whole-pending-buffer copies, front deletion, optional-header rescans, or wrapper-only rechunking.
- [ ] Do not weaken CRC, ISIZE, FHCRC, reserved-flag, member-boundary, padding, trailing-data, or decompression-limit validation.
- [ ] Do not change public output bounds to make a benchmark pass.
- [ ] Do not add a producer task, background writer, unbounded queue, or full-result materialization.
- [ ] Do not offload every small operation merely to hide Python overhead.
- [ ] Do not tune only for one compression engine.
- [ ] Do not special-case benchmark fixture sizes, hashes, compressibility, or source names.
- [ ] Do not edit a threshold after a miss. Stop, profile, and report.
- [ ] Do not claim a regression is fixed solely because one noisy run improved.

### 1.4 Small-write-specific rules

The established `write()` contract is frozen for this release:

- one `await write(data)` owns one accepted immutable input snapshot;
- all compressed bytes emitted by that call's codec operation reach the sink before the call returns;
- the file position advances only after those sink writes succeed;
- a sink failure is reported by the call that triggered it;
- a failed or cancelled call poisons the member;
- later writes are rejected;
- `close()` must not append a misleading valid trailer to a broken member.

Therefore:

- [ ] Do not buffer data across separate `write()` calls by default.
- [ ] Do not move an earlier call's sink failure to a later `write()`, `flush()`, or `close()`.
- [ ] Do not change `write()` into an enqueue operation.
- [ ] Do not create a background compression or sink task.
- [ ] Do not duplicate compressor state outside `GzipEncoder`.
- [ ] Prefer `writelines()` and application-level batching for tiny records.
- [ ] A no-code-change disposition is acceptable when profiling shows that parity requires changing these semantics.

### 1.5 Remote and maintainer-only actions

Codex may prepare local files and commits. Codex must not:

- create or modify GitHub issues, labels, milestones, projects, pull requests, releases, or repository settings;
- push branches or tags;
- publish to PyPI;
- deploy documentation;
- close issue #86;
- claim independent review occurred;
- claim Windows, macOS, Python versions, or engines passed unless those exact jobs ran.

Record remote and publication tasks in the maintainer handoff checklist.

---

## 2. Executive release decision

The next release is **`2.0.0a3`**, not `2.0.0b1`.

`2.0.0a2` successfully repaired the central decoder defects from `a1`:

- large one-feed decoding is approximately linear;
- compressed input uses immutable spans and bounded windows;
- public output bounds are decoupled from engine batch size;
- optional headers are parsed incrementally;
- event-loop fairness is bounded;
- decompression limits retain their exact allowed-byte behavior;
- the shared codec remains the source of framing and integrity truth.

The remaining beta-readiness gap is narrower:

1. `AsyncGzipBinaryFile` still maintains a separate `_header_probe_buffer` and `_try_parse_gzip_header_mtime()` compatibility parser.
2. That probe repeatedly copies and rescans fragmented optional headers, partially reintroducing the resource amplification fixed in the shared decoder.
3. The probe stops once `_mtime` becomes non-`None`, so the file object does not follow `gzip.GzipFile`'s “most recently read header” semantics across concatenated members.
4. Rewind constructs a fresh decoder without rearming the probe, so reread headers do not update the live property correctly.
5. The extreme 10-byte write diagnostic remains materially slower than `v1.11.0`, and the project needs an explicit profile-backed disposition rather than an indefinite vague deferral.
6. The provisional codec still needs realistic public-only integration evidence before beta.

`a3` is therefore a **compatibility, regression-disposition, and integration alpha**. It must not reopen the successful `a2` decoder design or absorb post-2.0 features.

---

## 3. Release outcomes

At release completion:

1. The high-level file reader obtains `mtime` from the shared incremental decoder; no second gzip-header parser remains.
2. `AsyncGzipBinaryFile.mtime` starts as `None` and updates to the timestamp in the most recently parsed valid header.
3. `mtime=0` is distinguishable from “no header parsed.”
4. Concatenated-member reads update `mtime` for every member, including when several headers are parsed during one decoder operation.
5. A backward seek preserves the previously observed value until a header is reread, then updates as reread headers are encountered.
6. Text mode exposes identical semantics through the binary layer.
7. A complete valid header commits `mtime` even if the later body or trailer is corrupt; an incomplete or invalid header does not.
8. Fragmented large FNAME/FCOMMENT fields through `aiogzip.open()` scale approximately linearly and do not allocate a duplicate header-sized probe buffer.
9. The helper `_try_parse_gzip_header_mtime()` and `_header_probe_buffer` are removed.
10. Every `2.0.0a2` decoder, memory, scheduler, integrity, and cross-engine gate remains passing.
11. Small writes have a committed write-size profile and a documented accepted or improved disposition.
12. No small-write optimization changes write visibility, position timing, sink-error timing, poisoning, or close behavior.
13. The documentation gives users an efficient path for tiny records through `writelines()` or explicit application batching.
14. One direct-codec custom-transport integration runs entirely through public APIs.
15. One concurrent striped-JSONL/safe-upload integration runs through public APIs and demonstrates bounded staging, full validation, failure atomicity, and ordered reconstruction.
16. Public examples are type-checked and executed from a built wheel.
17. Public boolean option behavior is deliberately settled before beta.
18. The release has complete raw benchmark evidence, independent review, clean artifacts, and accurate release notes.

---

## 4. Scope

### 4.1 In scope

- Package-private decoder header-notification state.
- File-layer synchronization of live header metadata.
- Removal of the compatibility-only header probe and helper.
- Binary and text `mtime` parity tests.
- Concatenated-member and rewind/reread tests.
- High-level fragmented-header scaling and memory benchmarks.
- Preservation of `a2` decoder and scheduler gates.
- A write-size benchmark and profile matrix.
- Semantics-preserving small-write optimizations, if profile evidence supports them.
- A deliberate non-blocking disposition when safe parity is unavailable.
- Small-write documentation and batching guidance.
- A public-codec fragmented-transport integration.
- A concurrent striped JSONL/safe-upload integration.
- Public constructor validation audit for boolean flags.
- Lifecycle/error contract consolidation.
- Full correctness, engine, interpreter, platform, typing, docs, and packaging validation.
- Release-candidate evidence and maintainer handoff.

### 4.2 Explicitly out of scope

Do not implement or begin:

- AnyIO or Trio high-level APIs;
- zran/indexed random access;
- raw DEFLATE or configurable `wbits`;
- the pull-style codec fallback;
- ISA-L or another compression engine;
- a default cross-call buffered writer;
- a background compression/sink pipeline;
- a codec-only distribution split;
- package-root lazy-import redesign;
- broad text-I/O redesign;
- arbitrary gzip-member indexing as a public format;
- cloud-specific production upload adapters;
- a stable/beta classifier change in the `a3` release commit;
- unrelated dependency, CI, formatting, or repository cleanup.

Issue #71 and issue #72 remain deferred. Issue #86 is addressed only to the extent defined in this plan.

---

## 5. Fixed design decisions

These decisions are not open for Codex to relitigate during implementation.

### D1. Release identity

- Development version remains `2.0.0a3.dev0` until release preparation.
- Release version is `2.0.0a3`.
- Package classifier remains Alpha.
- Python floor remains 3.11.
- The codec remains documented as provisional throughout the alpha series.

### D2. Historical comparisons

- Exact `v2.0.0a2` is the primary no-regression baseline for code paths changed in `a3`.
- Exact `v1.11.0` remains the historical comparison for high-level file and write APIs that existed in that release.
- Exact pre-change `main` is captured so dependency/housekeeping drift is distinguishable from production changes.
- Codec-only and `a2`-specific cases are not falsely compared with `v1.11.0` when no equivalent exists.

### D3. One gzip-header parser

`_GzipHeaderParser` in the shared decoder is the only gzip-header parser used by codec, streaming, file, inspect, and verify paths.

Delete rather than optimize:

```text
AsyncGzipBinaryFile._header_probe_buffer
_common._try_parse_gzip_header_mtime()
all imports, exports, comments, and tests that exist only for that helper
```

Do not introduce a replacement parser in `_binary.py` or `_text.py`.

### D4. Decoder header notification

`GzipDecoder` gains package-private read-only notification state:

```python
_header_generation: int
_last_header_mtime: int | None
```

Contract:

- `_header_generation` starts at `0` for a new decoder.
- `_last_header_mtime` starts at `None`.
- After `_GzipHeaderParser.advance()` returns a complete validated `_ParsedHeader`, and before body processing begins, the decoder:

  ```python
  self._header_generation += 1
  self._last_header_mtime = parsed.mtime
  ```

- The generation increments for every complete valid member header even when the timestamp repeats.
- `mtime=0` is stored as `0`.
- Notification does not depend on `collect_member_info`.
- A fragmented header not yet complete does not notify.
- A bad magic, unsupported method, reserved flag, malformed optional field, or bad FHCRC does not notify.
- Later body, CRC, ISIZE, truncation, limit, or trailing-data failures do not roll back a completed header notification.
- Notification state is private and is not added to `__all__`, public docs, or compatibility promises.
- `discard()` may clear active engine/parser state but must not retroactively decrement a generation that already represented a completed valid header. The two scalar notification values may remain until object disposal.

### D5. File-layer observation

`AsyncGzipBinaryFile` replaces `_header_probe_buffer` with:

```python
_decoder_header_generation: int
```

Add a narrow helper, named equivalently to:

```python
def _sync_decoder_mtime(self, decoder: GzipDecoder) -> None:
    if decoder._header_generation != self._decoder_header_generation:
        self._decoder_header_generation = decoder._header_generation
        self._mtime = decoder._last_header_mtime
```

Requirements:

- Opening in read mode sets public `_mtime = None` and observed generation `0`.
- Every decoder `feed()` and `finish()` drain synchronizes in a `finally` path so a header parsed before a later operation failure is still observed.
- Synchronization occurs before a cancellation/error handler discards the decoder, even though notification scalars are retained.
- A single operation that parses multiple headers leaves the file property at the last header parsed by that operation.
- A new decoder created for rewind sets observed generation to `0`.
- Rewind does **not** set public `_mtime` to `None`; the previously observed timestamp remains until the first header is reread.
- Once a reread header completes, its timestamp replaces the retained value.
- Text mode continues to delegate to the binary file property.
- No public callback, event object, or new file API is added.

### D6. Exact live-`mtime` semantics

Pin these behaviors:

- Before any complete header is encountered, `mtime is None`.
- After the first valid header, `mtime` equals that header's uint32 timestamp.
- A zero timestamp yields `0`, not `None`.
- Entering a later concatenated member updates to that member's header timestamp.
- If internal read-ahead parses several headers, the property reflects the most recently parsed header even if some decompressed output remains buffered.
- A valid header followed by corrupt DEFLATE data or a bad trailer still updates the property.
- An incomplete or invalid header does not commit a new property value.
- NUL padding between members does not create a notification.
- `seek(0)` or backward seek preserves the current property until a header is encountered again.
- After the first header is reread, the property updates to that first member's timestamp.
- Binary and text readers agree.

### D7. Preserve `a2` decoder architecture

Do not replace or materially redesign:

- `_InputQueue` immutable spans;
- bounded inflate-input windows;
- `_OutputCursor`;
- private progress events;
- remaining-limit-aware output requests;
- retained-input engine normalization;
- cooperative async checkpoints;
- wait-for-worker-before-discard cancellation ordering;
- deterministic codec operation ownership.

Changes necessary only to expose header notification are permitted.

### D8. Frozen write semantics

The small-write investigation must preserve the contract in section 1.4. Cross-call buffering is not an implementation option for `a3`.

`writelines()` remains the supported batching path for a collection of small bytes-like inputs. Documentation may recommend larger application batches, but must not claim that individual `write()` calls are buffered when they are not.

### D9. Profile before small-write code changes

WP4 begins with a full profile on exact `a2` and current candidate. A production optimization may be implemented only when:

- the profile identifies a concrete dominant cost;
- the optimization preserves the frozen semantics;
- it keeps `GzipEncoder` as the compressor-state owner;
- it does not create a second framing/accounting path;
- deterministic functional tests cover failure and cancellation;
- representative writes do not regress;
- both engine configurations remain correct.

If those conditions cannot be met, commit the profile and accepted disposition without speculative code churn.

### D10. No eager private bypass by default

Do not add a private “fast feed” path that bypasses operation reservation, poisoning, or shared codec accounting merely to reduce object overhead. Such a change requires an explicit plan amendment after profiling demonstrates that it is necessary and can preserve every ownership invariant.

Local implementation improvements to `_Operation`, `_reserve()`, or hot iterator code are allowed only when they retain the public lifecycle exactly and improve or preserve all affected codec benchmarks.

### D11. Direct-codec integration

Add a maintained, deterministic integration demonstrating:

- `GzipEncoder` and `GzipDecoder` over a custom fragmented transport;
- arbitrary 1–97 byte transport frames;
- low-latency `flush()` in one continuous member;
- independently valid member-per-batch mode;
- complete operation exhaustion;
- explicit `close()` on early abandonment;
- codec `discard()` on terminal failure;
- payload availability before final trailer validation;
- truncation and corruption failure paths;
- standard-library gzip interoperability.

The integration uses only public aiogzip imports.

### D12. Striped safe-upload integration

Add a local, credential-free integration that:

- creates configurable `N` independent `.jsonl.gz` shards;
- supports row-round-robin striping, with `N=3` as the documented example:

  ```text
  row 1 -> shard 0
  row 2 -> shard 1
  row 3 -> shard 2
  row 4 -> shard 0
  ```

- may additionally support block-cyclic striping for throughput;
- uploads or streams shards concurrently through bounded async iterables;
- decompresses each shard with an explicit per-shard size limit;
- writes each result to a temporary staging path;
- consumes each decompression iterator to normal completion before promotion;
- verifies manifest row counts and hashes;
- publishes the dataset manifest last only when every shard is valid;
- removes staged outputs after corruption, truncation, limit overflow, or cancellation;
- reconstructs one ordered async row iterator by interleaving the shard readers;
- proves the reconstructed stream's SHA-256 equals the source stream;
- demonstrates that a slow shard does not block unrelated shard ingestion while dataset publication remains atomic.

The example must use bounded queues or bounded prefetch. No unbounded task result accumulation is allowed.

### D13. Integrations are release evidence, not new library APIs

- Place integrations under `examples/v2/` or an equivalent documented examples directory.
- Do not add public library helpers solely for the demos.
- Use public APIs only.
- Run from the built wheel in clean environments.
- Type-check with mypy and `ty`.
- Include deterministic success and failure tests.
- Keep cloud SDKs and credentials out of dependencies.

### D14. Boolean validation is strict before beta

Public options annotated as boolean accept exact booleans only. Add shared validators and apply them consistently to:

```text
fast_compress
strict_size
collect_member_info
closefd (bool or None)
```

Also audit the public surface for any other boolean-annotated option and apply the same rule unless a documented standard-library compatibility reason requires otherwise.

Contract:

- `True` and `False` are accepted.
- `None` is accepted only where the annotation explicitly permits it.
- integers `0` and `1`, strings, arbitrary truthy objects, and NumPy-like boolean scalars are rejected with `TypeError`.
- validation occurs at construction/call time before warnings, files, engines, or operations are created.
- wrappers and direct codec APIs use the same validator and error category.

This is an intentional alpha contract correction. Record it in the changelog. Do not silently preserve `bool(value)` coercion.

### D15. Numeric and metadata validation remains shared

Continue using the existing shared validators for:

- `chunk_size` / `output_chunk_size`;
- `compresslevel`;
- optional positive byte limits;
- `mtime` normalization and uint32 range;
- `original_filename`.

Do not duplicate validation in examples or wrappers. Add parity tests when two public surfaces expose the same option.

### D16. No benchmark result fabrication

Release notes and the candidate record may contain only measurements actually captured from the identified source and environment. Use explicit placeholders in a local draft only; remove them or replace them with “not captured” before commit. Do not convert targets into claimed results.

### D17. Independent review is a release gate

At least one reviewer who did not author the implementation must review:

- header notification timing;
- file-layer synchronization under errors and cancellation;
- rewind and concatenated-member behavior;
- removal of duplicate parsing;
- small-write semantic preservation;
- benchmark methodology.

A second review should focus on the public integrations and beta-contract audit. One person may cover both areas when the review comments address both explicitly. Codex must not mark this gate complete itself.

### D18. Post-release development version is a maintainer decision

After publishing `2.0.0a3`, the maintainer chooses:

- `2.0.0b1.dev0` only if section 17's beta-entry conditions are accepted; or
- `2.0.0a4.dev0` if another material alpha change remains.

Codex must not predeclare beta merely because `a3` shipped.

---

## 6. Observable contracts

### 6.1 Decoder header notification lifecycle

For a new decoder:

```python
decoder._header_generation == 0
decoder._last_header_mtime is None
```

After a complete valid header with `mtime=100`:

```python
decoder._header_generation == 1
decoder._last_header_mtime == 100
```

After a second complete valid header with the same timestamp:

```python
decoder._header_generation == 2
decoder._last_header_mtime == 100
```

The generation represents header events, not distinct timestamp values.

The notification is committed at header completion, not at:

- `feed()` call time;
- first payload output;
- DEFLATE EOF;
- trailer validation;
- member-count increment;
- decoder `finish()`.

### 6.2 File `mtime` behavior

The high-level property mirrors the last notification observed from the active decoder.

A representative sequence is:

```text
open reader                          -> None
read enough to parse member 0       -> mtime 100
read into member 1                  -> mtime 200
seek(0)                              -> remains 200
read enough to reparse member 0      -> mtime 100
read into member 1 again            -> mtime 200
```

The property is allowed to move ahead of caller-visible output when the file reader has already read and parsed a later header internally. This matches “most recently read header,” not “header associated with the last byte returned to the caller.” Document this nuance.

### 6.3 Header error behavior

- Invalid magic or method before a complete valid header: no update.
- Reserved flag or bad FHCRC: no update for that header.
- Truncated optional field: no update for that header.
- Complete valid header followed by malformed DEFLATE data: update remains.
- Complete valid header followed by bad CRC or ISIZE: update remains.
- Complete valid member followed by malformed next header: retain the previous valid timestamp.

Preserve existing exception types and established stable message prefixes. Do not expose header-notification internals in errors.

### 6.4 Write call completion

For a successful call:

```python
written = await writer.write(payload)
```

on return:

- `written == len(payload)`;
- the exact immutable payload snapshot was accepted by the encoder;
- every compressed byte emitted by that operation was accepted by the sink;
- `tell()` reflects the accepted uncompressed position;
- no output from that call is intentionally held for a later API call, except state naturally retained inside the DEFLATE compressor that emitted no bytes yet.

The final caveat is important: DEFLATE itself may retain compression state, but aiogzip must not add a separate cross-call application buffer.

### 6.5 Failed write behavior

When an underlying write makes no progress, returns an invalid count, raises, or the task is cancelled:

- the triggering `write()` raises;
- the writer becomes broken;
- later writes fail;
- the encoder is discarded;
- `close()` does not emit a trailer that presents the torn member as valid;
- public position does not advance beyond data whose emitted compressed bytes reached the sink.

### 6.6 Integration integrity timing

The safe-upload integration must teach the actual gzip contract:

- decompressed payload may be available before trailer validation;
- a stream is fully trusted only after normal iterator completion;
- provisional output must be staged when publication requires complete validation;
- early consumer exit means validation did not complete;
- a decompression limit failure is not a valid upload;
- dataset publication is separate from per-shard byte production.

### 6.7 Thread/task safety

No change:

- one codec instance is not thread-safe;
- one open file handle is not safe for simultaneous operations from several tasks;
- operation-ownership errors are misuse guards, not synchronization;
- independent codec/file instances may run concurrently.

---

## 7. Target architecture and file map

Expected production changes:

```text
src/aiogzip/codec.py
    add private header-generation and last-mtime state
    commit notification when a valid header completes
    add direct private-state tests

src/aiogzip/_binary.py
    remove _header_probe_buffer
    add observed decoder generation
    synchronize mtime after feed/finish drains
    reset observed generation on new decoder/rewind
    preserve public mtime across rewind until reread

src/aiogzip/_common.py
    delete _try_parse_gzip_header_mtime
    remove unused constants/imports/exports created only for it
    add strict shared bool validators

src/aiogzip/_text.py
    ordinarily no production change beyond validation plumbing
    retain delegation of mtime

src/aiogzip/_streaming.py and public factories
    apply strict shared bool validation where relevant

examples/v2/codec_transport/
    deterministic fragmented-transport integration

examples/v2/striped_safe_upload/
    deterministic concurrent shard integration
```

Expected test and evidence changes:

```text
tests/test_codec.py or focused codec-header tests
tests/test_binary_io.py
tests/test_text_io.py
tests/test_seek.py
tests/test_streaming.py
tests/test_validation.py
tests/test_property_cross_surface.py

tests/examples/test_codec_transport.py
tests/examples/test_striped_safe_upload.py

benchmarks/bench_a3_regressions.py
benchmarks/profile_small_writes.py
plans/benchmarks/v2.0.0a3-preflight.md
plans/benchmarks/v2.0.0a3-small-write-disposition.md
plans/benchmarks/v2.0.0a3-candidate.md
plans/benchmarks/data/*.json
```

Use the repository's actual test organization when equivalent focused files already exist. Do not create duplicate test modules merely to match this suggested map.

---

## 8. Benchmark design and release thresholds

### 8.1 General methodology

Every timed category must:

- use deterministic fixtures;
- verify byte counts and SHA-256 outside the timed region;
- include warm-ups;
- retain individual samples;
- use odd repeat counts of at least five for primary comparisons;
- rerun material or noisy deltas with at least nine repeats;
- report median and MAD;
- record engine selection explicitly;
- compare baseline and candidate in the same session when practical;
- avoid mixing tracemalloc timings with ordinary wall-time claims;
- identify whether files are on disk, tmpfs, or memory-backed sources;
- distinguish target thresholds from hard blockers.

### 8.2 High-level fragmented-header fixtures

Build valid or deliberately incomplete gzip streams manually so optional fields can be large without allocating decompressed payloads.

Required fields:

- FNAME;
- FCOMMENT;
- FEXTRA at representative legal sizes;
- FHCRC on and off;
- combinations of FEXTRA + FNAME + FCOMMENT + FHCRC;
- zero `mtime` and nonzero `mtime`.

Required sizes:

```text
16 MiB
32 MiB
64 MiB
128 MiB release-only boundary
```

Required fragmentation modes:

```text
single complete compressed source item
1 MiB source chunks
64 KiB source chunks for smaller fixtures
adversarial boundary splits around fixed header, XLEN, NUL terminator, and FHCRC
```

Required surfaces:

- direct `GzipDecoder` control;
- `AsyncGzipBinaryFile` over a **seekable** asynchronous memory source so the rewind cache does not confound parser-memory measurements;
- a separate non-seekable control whose expected compressed rewind cache is reported but excluded from the parser-memory gate;
- path-backed `aiogzip.open()` representative run;
- text reader smoke parity.

For incomplete-field timing, create the fixture outside the tracemalloc/timed region, open the reader, and consume until the expected truncation failure. For complete fields, include a minimal valid body/trailer and verify the payload.

### 8.3 High-level header gates

Hard structural gates:

- [ ] `_header_probe_buffer` no longer exists.
- [ ] `_try_parse_gzip_header_mtime` no longer exists.
- [ ] `_binary.py` does not parse gzip magic, flags, optional fields, FHCRC, or NUL terminators.
- [ ] Only `_GzipHeaderParser` owns header parsing.

Hard functional gates:

- [ ] all live-`mtime` cases pass;
- [ ] 128 MiB safety-limit test passes under both engines;
- [ ] malformed headers retain existing exception behavior;
- [ ] complete header plus corrupt body/trailer retains the header timestamp;
- [ ] concatenated members and rewind behave exactly as section 6 specifies.

Hard performance gates on the locked reference machine:

- [ ] 16→32 MiB and 32→64 MiB wall-time ratios are each `<= 2.5x` for FNAME and FCOMMENT through the high-level file reader.
- [ ] With metadata collection absent, a seekable source, and 1 MiB source chunks, incremental Python peak allocation for the 32 MiB incomplete FNAME and FCOMMENT cases is `< 8 MiB`.
- [ ] Target peak for those cases is `< 4 MiB`.
- [ ] The high-level 64 MiB case does not retain a header-sized compatibility copy after failure.
- [ ] No candidate high-level header case is slower than the repaired direct decoder by more than a documented fixed wrapper cost plus transport I/O.

Comparisons against exact `a2`:

- target: at least `4x` lower peak allocation for the 32 MiB high-level optional-header cases;
- target: at least `4x` faster for the 64 MiB high-level fragmented case;
- these improvement factors are diagnostic targets, not substitutes for the structural and absolute hard gates.

### 8.4 Live-`mtime` benchmark/correctness probe

Add a low-overhead functional probe that creates many small concatenated members with alternating timestamps. Measure final read throughput only to ensure notification does not recreate a many-member regression.

Required member counts:

```text
1
2
1,001
10,000 diagnostic
```

For 1,001 ordinary members:

- target: `<= 5%` slower than exact `a2`;
- hard gate: `<= 10%` slower than exact `a2`;
- every timestamp transition is checked in a focused functional test, not inside the timed loop.

### 8.5 Small-write matrix

Use a fixed total uncompressed payload per case so smaller records imply more calls:

```text
write size: 10 B, 100 B, 1 KiB, 4 KiB, 16 KiB, 64 KiB, 256 KiB
total payload: at least 8 MiB per case
```

Run against:

- a minimal asynchronous counting memory sink;
- a short-write-capable sink in correctness tests;
- `aiofiles` on a local temporary file;
- one writer;
- 4 and 10 independent concurrent writers;
- stdlib compression;
- opt-in zlib-ng compression where installed.

Record:

- wall time;
- write calls;
- codec operation allocations;
- compressor calls;
- emitted compressed chunks;
- underlying sink calls;
- coroutine suspensions where instrumentable;
- peak Python allocation;
- compressed size and SHA-256;
- decompressed output digest;
- profile stacks or cumulative tables for the 10 B, 1 KiB, and 64 KiB cases.

Also benchmark:

- repeated `write()`;
- `writelines()` over the same logical records;
- explicit application batches of 64 KiB and 256 KiB.

Do not present `writelines()` as a same-semantics replacement for callers who require one failure boundary per individual record. Present it as the batching API.

### 8.6 Small-write gates

For every write-size case:

- [ ] candidate no more than `5%` slower than exact `a2` without investigation;
- [ ] candidate no more than `10%` slower than exact `a2` as a hard blocker;
- [ ] output bytes remain valid and equivalent;
- [ ] sink-error, position, cancellation, and poisoning tests pass.

For representative `1 KiB` through `64 KiB` writes:

- target: within `5%` of exact `v1.11.0`;
- hard gate: within `10%` of exact `v1.11.0`, unless the maintainer records a specific independently reviewed exception with profile evidence;
- no average across sizes may hide a miss.

For the 10-byte diagnostic:

- target: at least `20%` faster than exact `a2`;
- hard anti-regression gate: no more than `10%` slower than exact `a2`;
- parity with `v1.11.0` is not a release blocker when it requires changing the frozen write contract;
- a miss must produce `plans/benchmarks/v2.0.0a3-small-write-disposition.md` explaining the cost center, attempted safe optimizations, measured batching alternatives, rejected semantic changes, and recommended future API direction.

### 8.7 Preserve `a2` decoder and scheduler gates

Rerun the complete `a2` regression category. At minimum retain:

- one-feed decode scaling from 8 through 64 MiB;
- one-feed versus transport-feed ratios;
- public output sizes 1 B, 1 KiB, 64 KiB, and 256 KiB;
- compressible and incompressible inputs;
- direct decoder memory peaks;
- 32 MiB one-item async scheduler gap;
- no-output DEFLATE progress case;
- 512/256 KiB and 64/64 KiB `decompress_chunks()` cases;
- many-member inspect and verify;
- full-read memory sentinel;
- both real engines and fake-engine accounting tests.

General gate:

- any primary delta over `5%` versus exact `a2` requires investigation;
- any representative delta over `10%` is a release blocker unless this plan explicitly permits an exception;
- central decoder scaling, memory, decompression-limit, and scheduler gates have no waiver.

Scheduler hard gate remains:

```text
32 MiB one-item async source maximum ticker gap <= 50 ms
```

Target remains:

```text
maximum ticker gap <= 20 ms
```

### 8.8 Integration evidence

The integrations are correctness evidence, not headline performance claims.

Record:

- source and output byte counts;
- SHA-256 values;
- maximum configured queue/prefetch depth;
- maximum observed in-memory staged block count;
- time to first record/output;
- completion/validation status;
- behavior under corruption, truncation, limit overflow, slow source, slow sink, and cancellation;
- clean-wheel version used.

Do not claim “bounded memory” solely from code inspection. Include deterministic queue-depth assertions and at least one peak-allocation or RSS observation for the safe-upload example.

---

## 9. Work packages

### WP0 — Lock baselines and add the `a3` harness

#### Objective

Create auditable same-harness baselines before production changes and prove the plan is being executed from the intended repository state.

#### Dependencies

None beyond section 0.

#### Tasks

- [x] Copy this plan into `plans/RELEASE_2_0_0A3_PLAN.md` without changing its fixed decisions.
- [x] Run every commit/SHA preflight command from section 0.1.
- [x] Record the clean-tree result and current tool versions.
- [x] Verify `2.0.0a3.dev0`, Python `>=3.11`, and Alpha classifier.
- [x] Verify issue #86 is the active small-write deferral and #71/#72 remain out of scope.
- [x] Inspect the existing benchmark modules before adding new files.
- [x] Add deterministic large optional-header fixture generation.
- [x] Add high-level binary-reader timing and tracemalloc cases.
- [x] Add many-member live-metadata overhead control.
- [x] Add the write-size matrix and counting sink.
- [x] Add engine, source-root, fixture-size, repeat-count, and JSON-output CLI options.
- [x] Keep benchmark imports isolated from the source tree under test.
- [x] Verify output digests outside timed regions.
- [x] Add a schema/version field to machine-readable results.
- [x] Capture exact `v2.0.0a2` stdlib and zlib-ng records.
- [x] Capture exact `v1.11.0` comparable records.
- [x] Capture locked pre-change `main` records.
- [x] Commit individual samples, environment metadata, commands, fixture hashes, and disposition of unavailable cases.
- [x] Confirm no production file under `src/aiogzip/` changed in WP0.
- [x] Update this checklist in the same benchmark commit.

#### Required tests and checks

```bash
uv run python benchmarks/bench_a3_regressions.py --help
uv run python benchmarks/profile_small_writes.py --help
uv run prek run --all-files
```

Run a reduced smoke benchmark in ordinary CI time. Mark large timing and 128 MiB cases release-only rather than putting unstable wall-time gates in normal CI.

#### Exit criteria

- [x] Baseline JSON exists for every available engine/source pair.
- [x] Exact commits and environments are recorded.
- [x] Individual samples are preserved.
- [x] Fixtures and results have hashes.
- [x] The harness detects incorrect output.
- [x] No production code changed.
- [x] Repository is green.

#### Suggested commit

```text
bench: add 2.0.0a3 regression baselines
```

---

### WP1 — Add decoder header notifications

#### Objective

Expose the shared parser's completed-header events to package-internal consumers without adding a public API or changing parsing, framing, body, trailer, or operation semantics.

#### Dependencies

WP0 complete and baselines committed.

#### Test-first sequence

Before implementation, add focused tests that fail for the absence of notification state. Confirm the intended failure locally, then implement and commit the complete green package.

#### Implementation tasks

- [ ] Inspect `GzipDecoder.__init__`, `_process()`, `_release_state()`, and discard behavior.
- [ ] Add `_header_generation = 0` during decoder construction.
- [ ] Add `_last_header_mtime = None` during decoder construction.
- [ ] Commit notification exactly after a complete `_ParsedHeader` is returned and before engine/body setup.
- [ ] Increment generation for every complete valid header, including repeated timestamps.
- [ ] Preserve integer zero exactly.
- [ ] Keep notification independent of `collect_member_info`.
- [ ] Do not retain original filename, comment, extra data, or full header solely for notification.
- [ ] Ensure invalid/truncated headers do not commit.
- [ ] Ensure later body/trailer failure does not roll the notification back.
- [ ] Ensure member completion does not reset generation or last timestamp.
- [ ] Ensure parser reset for the next member does not reset notification.
- [ ] Ensure `discard()` releases heavyweight state but does not decrement or falsify an already committed notification.
- [ ] Keep fields package-private and absent from public exports/docs.
- [ ] Add a concise internal comment explaining why generation is needed even when timestamps repeat or equal zero.

#### Required direct tests

- [ ] fresh decoder: generation 0, timestamp `None`;
- [ ] fixed ten-byte header split at every byte boundary;
- [ ] `mtime=0`;
- [ ] maximum uint32 `mtime`;
- [ ] two members with distinct timestamps;
- [ ] two members with identical timestamps still increment twice;
- [ ] several members accepted in one `feed()`;
- [ ] FEXTRA, FNAME, FCOMMENT, and FHCRC combinations;
- [ ] header split before and after every optional-field terminator;
- [ ] bad magic;
- [ ] unsupported method;
- [ ] reserved flags;
- [ ] bad FHCRC;
- [ ] truncated fixed header;
- [ ] truncated optional field;
- [ ] valid header then malformed DEFLATE body;
- [ ] valid header then bad CRC;
- [ ] valid header then bad ISIZE;
- [ ] valid member followed by malformed next header;
- [ ] NUL padding between members;
- [ ] `collect_member_info=False` and `True` parity;
- [ ] discard after a completed header;
- [ ] operation close/poison behavior unchanged.

#### Package checks

```bash
uv run pytest -q tests -k "header and decoder"
AIOGZIP_ENGINE=stdlib uv run pytest -q tests -k "header and decoder"
uv run prek run --all-files
```

Use the repository's actual focused test selectors rather than relying blindly on this example expression.

#### Exit criteria

- [ ] Header notifications satisfy D4.
- [ ] No public API changed.
- [ ] No gzip parsing logic is duplicated.
- [ ] All existing codec/property tests pass.
- [ ] `a2` direct decoder smoke benchmarks remain inside the no-regression guard.
- [ ] Repository is green.

#### Suggested commit

```text
feat: expose private decoder header notifications
```

---

### WP2 — Migrate live file `mtime` to the shared parser

#### Objective

Remove the compatibility parser and make binary/text file `mtime` follow the most recently parsed valid gzip header across members, errors, and rewinds.

#### Dependencies

WP1 complete.

#### Implementation tasks

- [ ] Replace `_header_probe_buffer` in `AsyncGzipBinaryFile.__slots__` with `_decoder_header_generation`.
- [ ] Initialize observed generation in `__init__`.
- [ ] Set `_mtime = None` and observed generation `0` when a read-mode file is opened.
- [ ] Add a narrow `_sync_decoder_mtime()` helper.
- [ ] Synchronize after every decoder `feed()` drain.
- [ ] Synchronize after every decoder `finish()` drain.
- [ ] Use an inner `try/finally` so notification is observed when a later part of the same operation raises.
- [ ] Preserve cancellation ordering: active worker finishes, operation cleanup completes, header state synchronizes, decoder is discarded, cancellation propagates.
- [ ] Do not expose a half-parsed header on cancellation.
- [ ] When rewind creates a new decoder, reset observed generation to `0`.
- [ ] Preserve public `_mtime` across rewind until a reread header completes.
- [ ] Update `_decompress_next()` documentation to describe shared metadata notification, not a compatibility probe.
- [ ] Remove the `_try_parse_gzip_header_mtime` import.
- [ ] Delete `_try_parse_gzip_header_mtime()` from `_common.py`.
- [ ] Remove it from `__all__`.
- [ ] Remove imports/constants made unused only by that helper.
- [ ] Run `rg` to prove no probe symbol or helper remains.
- [ ] Keep `AsyncGzipTextFile.mtime` as delegation rather than adding another cache.

#### Exact synchronization shape

Use nested cleanup equivalent to:

```python
operation = decoder.feed(compressed_chunk)
try:
    try:
        pieces = [
            piece
            async for piece in _drive_operation(...)
        ]
    finally:
        self._sync_decoder_mtime(decoder)
except asyncio.CancelledError:
    self._read_broken = True
    decoder.discard()
    raise
```

Adapt syntax to the implementation, but preserve the order. Apply the same principle to finalization.

#### Required binary-file tests

- [ ] `mtime is None` immediately after open.
- [ ] first valid header updates before trailer completion.
- [ ] zero timestamp remains zero.
- [ ] two concatenated members update from first to second.
- [ ] three members with repeated timestamps still follow header order.
- [ ] one compressed read chunk containing several members leaves the last parsed timestamp.
- [ ] valid header then corrupt body leaves new timestamp visible with the raised error.
- [ ] valid header then corrupt trailer leaves new timestamp visible with the raised error.
- [ ] invalid next header leaves prior timestamp visible.
- [ ] incomplete next header leaves prior timestamp visible.
- [ ] NUL padding does not change timestamp.
- [ ] seek to zero preserves old timestamp immediately.
- [ ] rereading first header changes back to first timestamp.
- [ ] rereading later member changes again.
- [ ] non-seekable cached rewind follows the same behavior.
- [ ] `read()`, `read1()`, `readline()`, `peek()`, `readinto()`, `seek()`, and read-all paths observe the same underlying behavior.
- [ ] cancellation after header completion but during body work synchronizes completed metadata and marks the reader broken.
- [ ] cancellation before header completion does not update.

#### Required text-file tests

- [ ] initial `mtime` is `None`;
- [ ] concatenated-member transition delegates correctly;
- [ ] zero timestamp;
- [ ] backward seek/reread when supported by current text semantics;
- [ ] corrupt body/trailer behavior matches binary layer;
- [ ] no independent text metadata state is introduced.

#### Differential tests with stdlib

Use Python's `gzip.GzipFile` as an oracle for:

- initial value;
- final value after reading concatenated members;
- update after backward seek and reread;
- valid-header/later-corruption behavior where stdlib behavior is stable.

Do not require aiogzip's internal read-ahead boundary to match stdlib byte-for-byte. Assert the documented header-read semantics at controlled source boundaries.

#### Package checks

```bash
uv run pytest -q tests/test_binary_io.py tests/test_text_io.py tests/test_seek.py
AIOGZIP_ENGINE=stdlib uv run pytest -q tests/test_binary_io.py tests/test_text_io.py tests/test_seek.py
uv run ruff check src tests
uv run ruff format --check src tests
uv run prek run --all-files
rg "_header_probe_buffer|_try_parse_gzip_header_mtime" src tests
```

The final `rg` should return no production or test references except a deliberate architecture assertion or changelog prose.

#### Exit criteria

- [ ] D5 and D6 are implemented.
- [ ] One header parser remains.
- [ ] Binary/text parity tests pass.
- [ ] Seek and non-seekable replay tests pass.
- [ ] Cancellation and corruption timing tests pass.
- [ ] No public signature changed.
- [ ] Repository is green.

#### Suggested commit

```text
fix: drive file mtime from the shared gzip parser
```

---

### WP3 — Prove high-level optional-header scaling is repaired

#### Objective

Demonstrate that removing the file-level probe closes the high-level memory/time hole without regressing normal-member throughput or the `a2` shared decoder.

#### Dependencies

WP2 complete.

#### Tasks

- [ ] Run the full high-level header category against exact `a2` and candidate.
- [ ] Run FNAME and FCOMMENT at 16, 32, and 64 MiB.
- [ ] Run complete and incomplete forms.
- [ ] Run 1 MiB and representative smaller source chunks.
- [ ] Run fixed-header/terminator/FHCRC adversarial splits.
- [ ] Run metadata-disabled direct-decoder control.
- [ ] Run a seekable high-level binary memory source for parser-memory gates.
- [ ] Run a separate non-seekable control and report the intentional rewind-cache allocation outside those gates.
- [ ] Run one path-backed representative case.
- [ ] Capture wall-time samples separately from tracemalloc peaks.
- [ ] Capture peak allocation after fixture creation.
- [ ] Verify no retained header-sized object remains after expected failure and garbage collection.
- [ ] Run the real 128 MiB boundary test under both engines outside normal CI.
- [ ] Run the 1,001-member throughput control.
- [ ] Investigate every candidate delta over 5% versus exact `a2`.
- [ ] Do not optimize `_GzipHeaderParser` unless the candidate itself misses a gate.
- [ ] If a gate misses because another high-level layer retains input, stop and document the actual owner before changing architecture.
- [ ] Commit raw candidate samples only after the implementation is stable.

#### Deterministic functional sentinels

Timing gates must be backed by non-timing tests:

- [ ] seekable memory source never returns more than requested and does not activate the compressed rewind cache;
- [ ] fixture generator produces expected flag layout;
- [ ] FHCRC fixture is valid before corruption variants;
- [ ] incomplete field fails only at finalization/EOF;
- [ ] over-limit field rejects before accepting the first byte beyond the limit;
- [ ] public `mtime` is not committed for the over-limit header;
- [ ] source read-count growth is linear in field size;
- [ ] no whole-header compatibility buffer exists in the file object.

#### Exit criteria

- [ ] Every hard header gate in section 8.3 passes.
- [ ] Many-member control stays inside the gate.
- [ ] All `a2` decoder controls remain passing.
- [ ] Raw data and investigation notes are committed.
- [ ] No waiver is used for duplicate parsing or header-sized allocation.
- [ ] Repository is green.

#### Suggested commit

```text
bench: verify bounded file-header processing
```

---

### WP4 — Investigate and disposition small-write overhead

#### Objective

Determine exactly where the 2.0 per-call overhead comes from, implement only semantics-preserving improvements, and leave the release with an explicit measured contract-aware disposition.

#### Dependencies

WP0 baseline captured; WP2–WP3 complete so benchmark noise from concurrent production edits is minimized.

#### Phase A — Characterize the contract

Before optimization, add or consolidate tests proving:

- [ ] exact bytes and bytes-like inputs are snapshotted before asynchronous work;
- [ ] bytes subclasses use raw-buffer snapshot semantics;
- [ ] each successful call returns its input length;
- [ ] position updates only after all emitted bytes reach the sink;
- [ ] a sink exception is raised by the triggering call;
- [ ] short writes are retried to completion;
- [ ] zero progress fails;
- [ ] invalid negative/oversized counts fail;
- [ ] cancellation poisons the writer;
- [ ] later writes fail after a failed call;
- [ ] close does not finish a broken member;
- [ ] `flush()` semantics remain distinct from ordinary `write()`;
- [ ] `writelines()` batches boundedly and preserves iterator/coercion failure behavior.

#### Phase B — Profile

- [ ] Run every size in section 8.5 against exact `v1.11.0`, exact `a2`, and candidate.
- [ ] Capture profiles for 10 B, 1 KiB, and 64 KiB.
- [ ] Count `_Operation` construction and `__next__` calls.
- [ ] Count compressor calls and output yields.
- [ ] Count `_write_all()` calls and underlying sink calls.
- [ ] Separate payload coercion, reservation, generator advancement, CRC/accounting, compression, and await/sink costs.
- [ ] Compare repeated `write()` with `writelines()` and explicit batching.
- [ ] Run one and multiple independent streams.
- [ ] Run with stdlib and zlib-ng configurations.
- [ ] Record whether zlib emits no bytes for most tiny calls.
- [ ] Record whether file I/O or protocol overhead dominates at each size.

#### Phase C — Safe optimization candidates

Evaluate in order and stop when evidence says further change is not justified:

1. Remove redundant high-level validation or normalization already guaranteed by the exact snapshot path.
2. Reduce allocation or attribute-lookup overhead in the private operation hot path while retaining reservation and poisoning.
3. Avoid temporary containers where iteration can remain direct and exception-safe.
4. Avoid unnecessary async-driver setup for work already proven safely bounded; preserve current cancellation behavior.
5. Coalesce only compressed fragments emitted by **one** codec operation before one sink call when this preserves partial-write/error behavior and has a strict bound. Do not coalesce across public calls.
6. Improve `writelines()` internals if profiling identifies avoidable overhead without changing its documented iterator-failure semantics.

For every attempted optimization:

- [ ] add a focused benchmark result;
- [ ] add or retain functional tests;
- [ ] rerun all write sizes;
- [ ] rerun direct codec operation lifecycle tests;
- [ ] rerun file close/flush/failure tests;
- [ ] revert the change when it does not produce a repeatable useful result.

#### Forbidden “optimizations”

- cross-call buffering;
- delayed sink errors;
- background tasks;
- new public buffering defaults;
- bypassing the codec's compressor/CRC/size state;
- an unreserved private generator path;
- holding the entire file before writing;
- changing gzip output metadata or compression level;
- making `write()` return before operation output reaches the sink;
- special-casing the 10-byte fixture.

#### Required disposition document

Create:

```text
plans/benchmarks/v2.0.0a3-small-write-disposition.md
```

It must include:

- exact baseline/candidate commits;
- environment and engine versions;
- write-size table with raw-record links/hashes;
- profile tables;
- cost-center explanation;
- safe changes attempted and retained/reverted;
- semantics that were intentionally preserved;
- `writelines()` and batching comparison;
- whether the 10-byte target was met;
- why a remaining miss is blocking or non-blocking;
- recommendation for any future explicit buffered-writer API;
- no claim that the regression is fixed unless the data demonstrates it.

#### Exit criteria

- [ ] Every hard small-write gate passes.
- [ ] No write semantic changed.
- [ ] Realistic write sizes have a recorded comparison.
- [ ] The 10-byte case is improved or explicitly accepted with evidence.
- [ ] Documentation gives a practical batching recommendation.
- [ ] Issue #86 handoff notes are prepared for the maintainer.
- [ ] Repository is green.

#### Suggested commits

```text
perf: reduce safe small-write overhead
bench: document small-write performance disposition
```

Use only the second commit when no production optimization survives review.

---

### WP5 — Add a public-codec fragmented-transport integration

#### Objective

Exercise the provisional codec exactly as a non-file user would and collect evidence about ownership, cleanup, flush, and integrity ergonomics before beta.

#### Dependencies

WP1–WP4 complete so the example targets the intended `a3` contract.

#### Directory

Preferred structure:

```text
examples/v2/codec_transport/
    README.md
    demo.py
    transport.py
```

Equivalent compact organization is acceptable when it remains readable and testable.

#### Functional design

Implement a deterministic in-memory duplex transport with configurable frame fragmentation and optional delays. It must not import test-only or private aiogzip helpers.

Modes:

1. **Continuous member**
   - one encoder;
   - `start()` once;
   - `feed(record)` for each JSONL event;
   - `flush()` after each event or configured batch;
   - `finish()` once.

2. **Member per batch**
   - new encoder for each batch;
   - each member fully finished before transmission is considered committed;
   - concatenate completed members;
   - decoder treats them as one logical payload.

Required behavior:

- [ ] deterministic JSONL events;
- [ ] transport frames of random 1–97 byte lengths from a fixed seed;
- [ ] headers, DEFLATE data, trailers, and records split arbitrarily;
- [ ] receiver feeds exact immutable `bytes` frames;
- [ ] every operation is exhausted before the next call;
- [ ] early break closes the active operation in `finally`;
- [ ] terminal transport failure discards the codec;
- [ ] receiver labels payload as provisional until `finish()` completes;
- [ ] standard-library `gzip.decompress()` verifies the complete wire output;
- [ ] aiogzip decoder output digest matches the source;
- [ ] continuous and member-per-batch tradeoffs are explained without fabricated throughput claims.

#### Failure modes

- [ ] truncate before trailer;
- [ ] flip CRC byte;
- [ ] flip ISIZE byte;
- [ ] corrupt a later member only;
- [ ] abandon a reachable operation and explicitly close it;
- [ ] call next operation while one is active and show deterministic `RuntimeError`;
- [ ] discard and prove retained invalidated operation cannot advance;
- [ ] enforce a decompressed-size limit below the payload;
- [ ] demonstrate that already-emitted payload does not imply final integrity.

#### Packaging and typing

- [ ] README contains one-command run instructions.
- [ ] Demo has no cloud/network dependency.
- [ ] Example runs from an installed wheel in a clean environment.
- [ ] Mypy checks public types without `type: ignore` around operation cleanup.
- [ ] `ty` checks the same example.
- [ ] A fast deterministic test exercises success and representative failure paths.
- [ ] The example does not depend on source checkout layout.

#### Ergonomics record

Create a short section in the release candidate record listing:

- ownership mistakes encountered during implementation;
- whether `CodecOperation.close()` was sufficient;
- whether private internals were needed;
- whether bounded transport behavior was expressible;
- any recurring lifecycle issue that would justify another alpha.

Do not redesign the codec because an alternative API feels more familiar. Record concrete failures.

#### Exit criteria

- [ ] Both transport modes run from the wheel.
- [ ] Success and failure tests pass.
- [ ] No private aiogzip import exists.
- [ ] The standard library verifies complete output.
- [ ] Ownership and integrity timing are demonstrated accurately.
- [ ] Repository is green.

#### Suggested commit

```text
examples: demonstrate gzip over a fragmented transport
```

---

### WP6 — Add the concurrent striped JSONL safe-upload integration

#### Objective

Demonstrate the high-level concurrency, validation, resource-bounding, and atomic-publication value of aiogzip with several independent gzip streams.

#### Dependencies

WP5 complete; public contracts stable for the release.

#### Directory

Preferred structure:

```text
examples/v2/striped_safe_upload/
    README.md
    demo.py
    manifest.py
```

Keep it local and dependency-light.

#### Producer requirements

- [ ] Generate a deterministic source JSONL file.
- [ ] Give every row an explicit monotonic sequence number.
- [ ] Support configurable shard count; document `N=3`.
- [ ] Support row-round-robin striping exactly as described in D12.
- [ ] Use one independent gzip handle per shard.
- [ ] Let each writer task own exactly one handle.
- [ ] Use bounded per-shard queues.
- [ ] Batch lines before `writelines()` rather than one `write()` per row in the throughput path.
- [ ] Record per-shard row count, uncompressed bytes, uncompressed SHA-256, and compressed SHA-256.
- [ ] Set deterministic `mtime=0` and explicit original filenames.
- [ ] Write a manifest containing format version, distribution, shard count, total rows, source digest, and per-shard metadata.

#### Upload/ingest simulation requirements

For each shard, concurrently:

- [ ] expose compressed bytes through a bounded asynchronous iterable;
- [ ] optionally inject deterministic latency;
- [ ] run `decompress_chunks()` with a per-shard limit;
- [ ] stage output to a `.partial` path;
- [ ] compute row count and digest while staging;
- [ ] consume to normal completion;
- [ ] verify manifest metadata;
- [ ] promote only that staged shard after complete validation;
- [ ] delete the partial path on any failure;
- [ ] close the async iterator in `finally`.

At dataset level:

- [ ] apply a global decompressed-byte budget in addition to per-shard limits;
- [ ] bound active ingestion with a semaphore when shard count exceeds configured concurrency;
- [ ] cancel remaining tasks on terminal dataset failure;
- [ ] wait for task cleanup;
- [ ] remove every staged/promoted shard from the unpublished transaction on failure;
- [ ] publish/copy/rename the manifest last as the dataset commit point;
- [ ] never expose a committed dataset containing only a subset of shards.

#### Reader/reconstruction requirements

- [ ] Open all validated gzip shards independently.
- [ ] Use one task or controlled read per shard; never operate one handle concurrently.
- [ ] Reconstruct original row order from sequence numbers and shard order.
- [ ] Provide a simple row-round-robin interleaver for the documented `N=3` case.
- [ ] Detect inconsistent shard lengths rather than silently shifting order.
- [ ] Bound prefetch to a documented number of rows or blocks per shard.
- [ ] Yield one ordered async iterator.
- [ ] Verify total row count and source SHA-256.
- [ ] Demonstrate that standard gzip can read each shard independently.

#### Failure scenarios

- [ ] valid concurrent upload;
- [ ] corrupt CRC in one shard;
- [ ] corrupt ISIZE in one shard;
- [ ] truncated shard;
- [ ] decompression limit overflow;
- [ ] manifest row-count mismatch;
- [ ] manifest digest mismatch;
- [ ] one intentionally slow source;
- [ ] one intentionally slow staging sink;
- [ ] cancellation during one shard;
- [ ] inconsistent shard lengths during reconstruction.

For every failed dataset:

- no published manifest;
- no stale `.partial` files;
- no background tasks left running;
- clear error identifies the failed shard and reason.

#### Backpressure evidence

Add a deterministic controlled source/sink test proving:

- when a shard's sink is paused, its source is not drained without bound;
- unrelated shard tasks continue within the concurrency limit;
- queue/prefetch depth never exceeds the configured bound;
- publication still waits for every shard.

#### Example UX

README must provide commands equivalent to:

```bash
python -m examples.v2.striped_safe_upload.demo --rows 100000 --shards 3
python -m examples.v2.striped_safe_upload.demo --rows 100000 --shards 3 --corrupt-shard 1
python -m examples.v2.striped_safe_upload.demo --rows 100000 --shards 3 --slow-shard 2
```

Adapt module invocation to packaging layout. The normal success run should finish quickly on a developer machine.

#### Exit criteria

- [ ] Success reconstructs the exact source digest.
- [ ] Every failure leaves the dataset unpublished.
- [ ] Backpressure assertions pass.
- [ ] No private imports or cloud credentials.
- [ ] Wheel-installed example passes mypy and `ty`.
- [ ] Integration notes record any API friction.
- [ ] Repository is green.

#### Suggested commit

```text
examples: add concurrent striped gzip ingestion demo
```

---

### WP7 — Freeze the intended beta contract

#### Objective

Resolve remaining validation ambiguity, consolidate lifecycle behavior, and ensure public examples and annotations describe the contract that may be frozen in `2.0.0b1`.

#### Dependencies

WP1–WP6 complete.

#### Boolean validation tasks

- [ ] Add `_validate_bool(value, name) -> bool` to the shared validation module.
- [ ] Add `_validate_optional_bool(value, name) -> bool | None` if useful for `closefd`.
- [ ] Reject non-exact booleans with `TypeError`.
- [ ] Apply the validator to direct codec constructors.
- [ ] Apply it to binary and text file constructors/factories.
- [ ] Apply it to async iterable helpers.
- [ ] Apply it to inspect/verify options when applicable.
- [ ] Validate before engine warnings, file opening, header generation, or operation reservation.
- [ ] Ensure error messages name the option.
- [ ] Add cross-surface parity tests.
- [ ] Add changelog entry under Changed/Compatibility.
- [ ] Update docs to state exact bool behavior only where users need it; do not clutter every signature description.

#### Full public-option audit

Create a table in the PR/review notes covering:

```text
compresslevel
mtime
original_filename
output_chunk_size
chunk_size
max_decompressed_size
max_rewind_cache_size
strict_size
fast_compress
collect_member_info
closefd
encoding
errors
newline
mode
filename/fileobj exclusivity
```

For each option record:

- accepted Python types;
- bool acceptance/rejection;
- range/normalization;
- error type;
- validation timing;
- public surfaces exposing it;
- shared validator used.

Do not change non-boolean semantics without a separate concrete inconsistency and tests.

#### Lifecycle contract matrix

Add or consolidate a readable parameterized suite covering:

| Surface | Required cases |
| --- | --- |
| `GzipEncoder` | start/feed/flush/finish ordering, repeated calls, abandonment, discard |
| `GzipDecoder` | feed/finish ordering, malformed input, terminal state, counters |
| `CodecOperation` | exhaustion, close, repeated close, invalidation, dropped reachable iterator |
| Binary writer | write/flush/close failure and cancellation |
| Binary reader | EOF validation, cancellation poisoning, seek/rewind |
| Streaming | normal completion, early exit, source failure, `aclose()` |
| Inspect/verify | metadata, integrity, limits, no payload materialization |

The suite may reference existing focused tests instead of duplicating every assertion. Its purpose is to make the beta contract discoverable and prevent surface drift.

#### Public examples and type checks

- [ ] Run every README/docs codec example as a smoke test.
- [ ] Run both new integration examples.
- [ ] Type-check examples with mypy.
- [ ] Type-check examples with `ty`.
- [ ] Install and import from a built wheel, not an editable source tree.
- [ ] Confirm no example relies on private symbols.
- [ ] Confirm cleanup is explicit where operations may not be exhausted.
- [ ] Confirm integrity completion is stated accurately.
- [ ] Confirm no example feeds huge whole buffers contrary to current guidance unless the code intentionally demonstrates supported linear behavior.

#### Exit criteria

- [ ] Boolean validation is deliberate and consistent.
- [ ] Numeric/metadata validation parity remains intact.
- [ ] Lifecycle matrix passes.
- [ ] Public examples execute and type-check from the wheel.
- [ ] No material API redesign is identified.
- [ ] Repository is green.

#### Suggested commit

```text
refactor: settle 2.0 constructor validation contracts
```

---

### WP8 — Cross-surface hardening and independent review

#### Objective

Prove the changes do not disturb gzip correctness, engine portability, async cancellation, seeking, or the successful `a2` architecture; prepare a reviewable evidence package.

#### Dependencies

All production and example work complete. Production code should be feature-frozen before final benchmarking.

#### Randomized and property-based tests

Extend the existing cross-surface properties to include live file metadata:

- [ ] zero through several concatenated members;
- [ ] empty and non-empty members;
- [ ] random timestamps including zero and uint32 maximum;
- [ ] repeated timestamps;
- [ ] random optional metadata;
- [ ] random compressed-input fragmentation;
- [ ] padding between members;
- [ ] direct codec output;
- [ ] async iterable output;
- [ ] binary file output and live/final `mtime`;
- [ ] text file smoke behavior;
- [ ] inspect/verify metadata;
- [ ] standard-library decompressed bytes;
- [ ] backward seek and reread on representative cases.

For corrupt corpora include:

- fixed-header mutations;
- optional-field truncation;
- FHCRC corruption;
- body corruption;
- trailer CRC/ISIZE corruption;
- malformed later members;
- trailing junk;
- limit overflow.

Assert both output/error parity and the expected last valid live timestamp.

#### Cancellation and executor tests

- [ ] cancellation before header completion;
- [ ] cancellation after header completion while a worker advances body state;
- [ ] cancellation after output but before trailer;
- [ ] sync metadata before decoder discard;
- [ ] no cleanup races with active worker;
- [ ] reader remains poisoned after unsafe cancellation;
- [ ] independent handles continue unaffected;
- [ ] integration cancellation leaves no tasks/files.

Use controlled events/barriers, not timing sleeps alone.

#### Engine matrix

Run:

1. zlib-ng absent, stdlib active;
2. zlib-ng active;
3. zlib-ng installed with `AIOGZIP_ENGINE=stdlib`;
4. fake retained-input engines;
5. counting/slow engines for deterministic internal assertions.

Header notification should be engine-independent because it precedes raw-DEFLATE creation, but run both configurations to catch surrounding path differences.

#### Interpreter/platform matrix

Match CI:

- Linux: Python 3.11, 3.12, 3.13, 3.14;
- Windows: Python 3.12;
- macOS: Python 3.12.

Performance gates run only on the locked reference machine. Platform jobs are correctness gates.

#### Review packet

Create:

```text
plans/reviews/v2.0.0a3-review.md
```

Include:

- locked commits;
- work packages and commits;
- fixed decisions;
- files changed;
- one-parser proof;
- live-`mtime` contract table;
- cancellation ordering;
- header performance table;
- small-write disposition;
- integration evidence;
- validation changes;
- tests/engines/platforms run;
- unresolved risks and deferrals;
- explicit review questions.

Review questions must include:

1. Is notification committed at the correct header-validity point?
2. Can an error/cancellation lose or invent a completed header event?
3. Does rewind preserve and then correctly replace live `mtime`?
4. Did any duplicate parser survive?
5. Did any small-write change alter sink-error or position timing?
6. Do the integrations reveal recurring operation-ownership misuse?
7. Is the public contract ready to freeze in beta?

#### Exit criteria

- [ ] Randomized cross-surface tests pass.
- [ ] Malformed corpus passes under both engines.
- [ ] Cancellation tests are deterministic.
- [ ] Full CI matrix passes.
- [ ] Review packet is complete.
- [ ] At least one independent reviewer approves the core repair and regression disposition.
- [ ] A public-integration review is recorded.
- [ ] Every finding is fixed or explicitly recorded as a release blocker/deferral.
- [ ] Repository is green.

#### Suggested commits

```text
test: harden live header metadata across surfaces
docs: prepare the 2.0.0a3 review packet
```

---

### WP9 — Final evidence, documentation, packaging, and release preparation

#### Objective

Produce reproducible release evidence, accurate user-facing documentation, clean artifacts, and a maintainer-ready release commit.

#### Dependencies

WP8 approved; production code frozen.

#### Documentation tasks

- [ ] Update `CHANGELOG.md` incrementally as behavior lands.
- [ ] Document correct live `mtime` semantics for concatenated members and read-ahead.
- [ ] Document that the file layer now uses the shared parser.
- [ ] Update performance guidance with high-level optional-header evidence.
- [ ] Add tiny-write guidance recommending `writelines()` or explicit batching.
- [ ] State clearly whether the 10-byte diagnostic remains slower than `v1.11.0`.
- [ ] Link the direct-codec transport example.
- [ ] Link the striped safe-upload example.
- [ ] Explain staging and validation-at-completion.
- [ ] Document strict boolean validation as an alpha compatibility correction.
- [ ] Keep the codec labeled provisional until beta.
- [ ] Do not claim AnyIO, indexed access, parallel single-stream DEFLATE, or arbitrary random access.
- [ ] Update any ADR/reference that still implies the file reader has a compatibility header probe.

#### Final benchmark tasks

- [ ] Freeze source before final capture.
- [ ] Run exact `a2` and candidate with the identical final harness.
- [ ] Run exact `v1.11.0` comparable write/high-level cases.
- [ ] Run forced stdlib with at least five repeats.
- [ ] Run zlib-ng active with at least five repeats for new gates.
- [ ] Rerun noisy/material cases with nine or more repeats.
- [ ] Run the real 128 MiB header boundary under both engines.
- [ ] Run the complete `a2` regression category.
- [ ] Run the full small-write matrix.
- [ ] Run many-member metadata control.
- [ ] Run integration resource observations.
- [ ] Commit raw JSON samples with individual measurements.
- [ ] Create `plans/benchmarks/v2.0.0a3-candidate.md`.
- [ ] Compare exact `a2`, exact `v1.11.0` where valid, and candidate.
- [ ] List every primary delta over 5% and its investigation.
- [ ] State every hard gate and pass/fail result.
- [ ] Include fixture, source, and artifact hashes.
- [ ] Include the small-write disposition without overstating it.
- [ ] Include integration ergonomics findings.

#### Quality commands

Run at minimum:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run ty check src
uv run prek run --all-files
AIOGZIP_ENGINE=stdlib uv run pytest --cov --cov-report=term-missing --cov-report=xml --cov-fail-under=85
uv run pytest --cov --cov-report=term-missing --cov-fail-under=85
uv run mkdocs build --strict
```

Also run the zlib-ng-active suite and stdlib-forced suite while zlib-ng remains installed, matching CI.

#### Packaging tasks

- [ ] Build wheel and sdist from a clean tree.
- [ ] Run metadata checks equivalent to `twine check dist/*`.
- [ ] Inspect sdist contents.
- [ ] Confirm Python floor and Alpha classifier.
- [ ] Confirm `py.typed` is included.
- [ ] Confirm only the intended runtime dependency is required by the base install.
- [ ] Confirm examples/tests/benchmarks are included or excluded according to project packaging policy.
- [ ] Confirm no giant generated fixtures or raw temporary files entered artifacts.
- [ ] Install wheel in clean Python 3.11 and 3.14 environments.
- [ ] Smoke file, streaming, inspect, verify, CLI, direct codec, and both new integrations.
- [ ] Smoke optional zlib-ng from the wheel.
- [ ] Confirm source and wheel report `2.0.0a3.dev0` before release preparation.

#### Release preparation

Only after every hard gate and review gate passes:

- [ ] Change version from `2.0.0a3.dev0` to `2.0.0a3`.
- [ ] Add the actual release date to `CHANGELOG.md`.
- [ ] Move finalized entries under `## [2.0.0a3] - YYYY-MM-DD`.
- [ ] Update changelog comparison links.
- [ ] Update any version-sync fixture/reference.
- [ ] Rebuild wheel and sdist from the exact release-preparation commit.
- [ ] Rerun metadata and clean-install smoke tests.
- [ ] Record final artifact SHA-256 hashes.
- [ ] Confirm tag/version workflow will accept `v2.0.0a3`.
- [ ] Leave tagging, publishing, documentation deployment, and post-release development version to the maintainer.

#### Exit criteria

- [ ] Every correctness gate passes.
- [ ] Every architecture gate passes.
- [ ] Every non-waivable performance gate passes.
- [ ] Small-write result has an explicit reviewed disposition.
- [ ] Two public-only integrations pass from the wheel.
- [ ] Full CI-equivalent matrix passes.
- [ ] Strict docs build passes.
- [ ] Wheel and sdist pass clean-install smoke tests.
- [ ] Raw evidence and review packet are committed.
- [ ] Release notes contain no fabricated result.
- [ ] Independent review is recorded.

#### Suggested commits

```text
docs: document 2.0.0a3 compatibility and examples
bench: record the 2.0.0a3 release candidate
chore: prepare release 2.0.0a3
```

---

## 10. Required test matrix

### 10.1 Header notification dimensions

Cross representative combinations of:

- one and multiple members;
- distinct and repeated timestamps;
- timestamp zero and uint32 maximum;
- fixed header only;
- FEXTRA;
- FNAME;
- FCOMMENT;
- FHCRC;
- all optional fields together;
- every important split boundary;
- complete and incomplete headers;
- valid and invalid flags/method/FHCRC;
- normal body, corrupt body, corrupt CRC, corrupt ISIZE;
- no padding and NUL padding;
- one member per source chunk and many members per chunk;
- metadata collection on and off;
- direct decoder, binary file, text file, inspect, verify;
- forward read, read-ahead, backward seek, non-seekable cached rewind;
- stdlib and zlib-ng configurations.

### 10.2 Write dimensions

Cross:

- exact bytes;
- bytes subclass;
- bytearray;
- contiguous and non-contiguous memoryview;
- 0, 10, 100, 1 KiB, 4 KiB, 16 KiB, 64 KiB, 256 KiB inputs;
- single and repeated writes;
- `writelines()`;
- normal sink;
- partial sink;
- zero-progress sink;
- invalid-count sink;
- exception sink;
- cancellation;
- flush and close;
- stdlib compression and opt-in zlib-ng;
- one and multiple independent writers.

### 10.3 Integration dimensions

Direct transport:

- continuous member;
- member per batch;
- arbitrary fragmentation;
- early close;
- discard;
- corruption/truncation;
- decompression limit;
- stdlib interoperability.

Striped upload:

- 1, 3, and more shards;
- row-round-robin;
- optional block-cyclic mode;
- valid upload;
- one slow source;
- one slow sink;
- corrupt/truncated/over-limit shard;
- cancellation;
- inconsistent manifest/shard lengths;
- ordered reconstruction;
- bounded prefetch;
- atomic publication.

### 10.4 Interpreter/platform/engine

- Linux Python 3.11, 3.12, 3.13, 3.14;
- Windows Python 3.12;
- macOS Python 3.12;
- stdlib zlib with zlib-ng absent;
- zlib-ng active;
- stdlib forced while zlib-ng installed;
- fake retained-input engine tests;
- controlled slow/counted operations.

### 10.5 Coverage

- Keep coverage at or above the 85% CI floor.
- New notification branches require direct tests.
- Error and cancellation synchronization paths require branch coverage.
- Examples require deterministic smoke tests but may be excluded from library coverage when repository policy does so consistently.
- Do not exclude difficult paths merely to preserve the percentage.

---

## 11. Release gates

### 11.1 Correctness — hard blockers

- [ ] All existing tests pass.
- [ ] Decoder notification tests pass.
- [ ] Binary and text live-`mtime` tests pass.
- [ ] Concatenated-member and rewind/reread behavior passes.
- [ ] Valid-header/later-corruption timing passes.
- [ ] CRC, ISIZE, FHCRC, flags, padding, trailing data, and limits remain correct.
- [ ] Seeking and non-seekable replay remain correct.
- [ ] Write failure/cancellation/position semantics remain correct.
- [ ] Both integrations pass all required failure modes.
- [ ] Cross-surface randomized tests pass.

### 11.2 Architecture — hard blockers

- [ ] One gzip-header parser remains.
- [ ] `_header_probe_buffer` is absent.
- [ ] `_try_parse_gzip_header_mtime` is absent.
- [ ] Header notification is package-private.
- [ ] No public callback/event API was added.
- [ ] `a2` input queue, batching, limits, and scheduler design remain intact.
- [ ] No duplicate compressor or decoder state machine was introduced.
- [ ] No cross-call writer buffer or background task was introduced.
- [ ] Examples use public APIs only.

### 11.3 Performance — hard blockers

- [ ] High-level fragmented-header doubling ratios are `<= 2.5x`.
- [ ] 32 MiB metadata-off high-level peak is `< 8 MiB` under the locked method.
- [ ] Real 128 MiB header-limit case passes without duplicate compatibility allocation.
- [ ] 1,001-member metadata control is within 10% of exact `a2`.
- [ ] Every `a2` central decoder scaling/memory/limit gate passes.
- [ ] 32 MiB one-item scheduler gap remains `<= 50 ms`.
- [ ] No write-size case is more than 10% slower than exact `a2`.
- [ ] Representative write sizes satisfy their historical gate or have a specific independently reviewed exception.
- [ ] The 10-byte result is accurately classified and retains the `a2` anti-regression guard.
- [ ] Every primary delta over 5% is investigated.

### 11.4 API and validation — hard blockers

- [ ] Exact boolean validation is consistent across public surfaces.
- [ ] Shared numeric/metadata validators remain consistent.
- [ ] Lifecycle contract matrix passes.
- [ ] Public examples type-check with mypy and `ty`.
- [ ] No known recurring operation-ownership failure remains unexplained.
- [ ] Codec remains labeled provisional in alpha.

### 11.5 Quality and packaging — hard blockers

- [ ] Ruff check passes.
- [ ] Ruff format check passes.
- [ ] Mypy passes.
- [ ] `ty` passes.
- [ ] `prek` passes.
- [ ] Coverage gate passes.
- [ ] Strict docs build passes.
- [ ] Full Python/OS matrix passes.
- [ ] All engine configurations pass.
- [ ] Wheel and sdist build.
- [ ] Metadata checks pass.
- [ ] Clean Python 3.11 and 3.14 wheel smokes pass.
- [ ] Integration examples run from the wheel.
- [ ] Version/changelog/artifacts agree.
- [ ] Raw evidence is committed.

### 11.6 Review — hard blockers

- [ ] Core repair reviewed by a non-author.
- [ ] Cancellation/error synchronization reviewed explicitly.
- [ ] Small-write semantics and disposition reviewed explicitly.
- [ ] Public integrations reviewed.
- [ ] All findings are closed or recorded as blockers/deferrals.

### 11.7 Maintainer-only gates

Codex records but does not execute:

- [ ] create/update the `2.0.0a3` milestone or issue labels;
- [ ] update issue #86 with the measured disposition;
- [ ] decide whether issue #86 remains open for a future opt-in buffered writer;
- [ ] confirm #71 and #72 remain post-2.0 or later work;
- [ ] merge approved release PR;
- [ ] verify release commit signature according to project practice;
- [ ] create tag `v2.0.0a3` at the exact release commit;
- [ ] create GitHub prerelease;
- [ ] let tag workflow run tests and Trusted Publishing;
- [ ] verify wheel/sdist attestations;
- [ ] deploy versioned documentation under the prerelease/dev alias;
- [ ] verify stable/latest aliases remain correct;
- [ ] choose `2.0.0b1.dev0` or `2.0.0a4.dev0` for `main`;
- [ ] reconcile this living checklist after remote actions.

---

## 12. Documentation and release-note requirements

### 12.1 User-facing `mtime` documentation

State plainly:

- the property is `None` before a header is read;
- it is the timestamp in the most recently read valid header;
- concatenated members update it;
- internal read-ahead may update it before all prior decompressed bytes are returned;
- backward seek preserves the old value until a header is reread;
- zero is a valid timestamp;
- header metadata is not a statement that body/trailer integrity has passed.

Do not expose private generation mechanics.

### 12.2 Small-write guidance

Include a practical comparison:

```python
# Correct but expensive for very many tiny records:
for row in rows:
    await stream.write(row)

# Preferred when one failure boundary for the batch is acceptable:
await stream.writelines(rows)
```

Also show explicit bounded application batches for asynchronous producers. Explain the tradeoff in failure granularity rather than promising universal speedups.

### 12.3 Integration guidance

Direct codec documentation must emphasize:

- exhaust each operation;
- call `close()` on explicit abandonment;
- call codec `discard()` after terminal failure;
- `flush()` is non-finalizing;
- output before trailer validation is provisional;
- one codec instance is not thread-safe.

Safe-upload documentation must emphasize:

- stage, validate, then publish;
- consume decompression to completion;
- per-stream and global limits;
- bounded concurrency;
- one handle per task;
- dataset manifest last;
- row-round-robin reconstruction requirements.

### 12.4 Proposed changelog outline

Use measured, accurate wording equivalent to:

```markdown
## [2.0.0a3] - YYYY-MM-DD

### Fixed

- Drove live file `mtime` from the shared incremental gzip-header parser. The
  property now follows the most recently parsed valid header across
  concatenated members and rereads.
- Removed the file reader's duplicate growing header probe, avoiding repeated
  copies and rescans of large fragmented FNAME/FCOMMENT fields.

### Changed

- Boolean public options now require actual `bool` values (or `None` where
  explicitly allowed) instead of coercing arbitrary truthy values.

### Performance

- Insert only captured high-level fragmented-header results.
- Describe the measured small-write disposition accurately; do not claim full
  `v1.11.0` parity unless achieved.

### Documentation

- Added public-codec fragmented-transport and concurrent striped safe-upload
  examples.

### Compatibility

- High-level asyncio APIs remain source-compatible for correctly typed calls.
- The synchronous codec remains provisional during the 2.0 alpha series.
```

Do not insert target numbers as release results.

---

## 13. Risk register

### R1. Header notification commits too early

**Failure mode:** `mtime` updates for a header whose optional field or FHCRC later fails.

**Mitigation:** notify only after `_GzipHeaderParser.advance()` returns a complete validated `_ParsedHeader`.

**Gate:** invalid/truncated optional-field and bad-FHCRC tests.

### R2. Header notification commits too late

**Failure mode:** a valid header followed by corrupt body/trailer never updates `mtime`, violating header-read semantics.

**Mitigation:** notify before engine/body setup, independently of trailer completion.

**Gate:** valid-header/corrupt-body and corrupt-trailer tests.

### R3. Timestamp equality hides a new member

**Failure mode:** observing only timestamp value misses a second header with the same value.

**Mitigation:** monotonic generation counter independent of timestamp.

**Gate:** repeated-timestamp concatenated members.

### R4. `mtime=0` is confused with no header

**Failure mode:** truthiness or `None` checks suppress a valid epoch timestamp.

**Mitigation:** generation counter plus exact optional integer state.

**Gate:** zero-timestamp tests across codec, binary, and text.

### R5. Cancellation loses a completed notification

**Failure mode:** a worker parses a header, cancellation cleanup discards state, and the file property never observes it.

**Mitigation:** wait for worker, synchronize in `finally`, then discard and propagate.

**Gate:** controlled cancellation after header completion.

### R6. Cancellation exposes a partial header

**Failure mode:** wrapper updates from raw bytes before shared parser validation.

**Mitigation:** wrapper reads only completed decoder notification; no raw probe.

**Gate:** cancellation at every optional-field boundary.

### R7. Rewind resets or freezes `mtime` incorrectly

**Failure mode:** property becomes `None` immediately, or remains on the later member after first header is reread.

**Mitigation:** preserve public value; reset only observed generation for the new decoder.

**Gate:** seek/reread sequence tests on seekable and cached non-seekable sources.

### R8. Read-ahead expectations are over-specified

**Failure mode:** tests demand update at the exact caller byte boundary rather than the most recently internally parsed header.

**Mitigation:** control source chunk boundaries for focused tests and document read-ahead nuance.

**Gate:** semantic tests avoid reliance on undocumented buffering granularity.

### R9. Removing the probe changes unrelated error messages

**Failure mode:** duplicate helper previously returned quietly for invalid magic, while shared parser raises at a different point/message.

**Mitigation:** characterize public error type and stable prefixes before migration; preserve intentional shared-parser behavior.

**Gate:** malformed-input differential tests.

### R10. Metadata notification regresses many-member performance

**Failure mode:** generation/property synchronization adds material per-member overhead.

**Mitigation:** two scalar assignments on header completion and one generation comparison per driven operation; benchmark 1,001 members.

**Gate:** <=10% exact-`a2` hard limit.

### R11. Header benchmark includes fixture allocation

**Failure mode:** peak memory falsely measures the prebuilt 64 MiB fixture rather than parser behavior.

**Mitigation:** construct fixtures before tracemalloc/timed region and record method.

**Gate:** benchmark self-test and methodology review.

### R12. Small-write optimization changes failure timing

**Failure mode:** earlier input is buffered and fails during a later call.

**Mitigation:** frozen write contract and sink-failure tests; no cross-call buffering.

**Gate:** trigger-call error assertions and position checks.

### R13. Small-write optimization bypasses ownership

**Failure mode:** a private eager path diverges from codec reservation, poisoning, or accounting.

**Mitigation:** no bypass without plan amendment; prefer local operation hot-path improvements.

**Gate:** operation lifecycle suite and architecture review.

### R14. Microbenchmark overfitting harms real writes

**Failure mode:** 10-byte case improves while 1–64 KiB or concurrent streams regress.

**Mitigation:** complete size/concurrency matrix; every size retains a no-regression gate.

**Gate:** section 8.6.

### R15. Strict bool validation causes accidental broad churn

**Failure mode:** implementation changes unrelated truthiness conversions or standard protocol results.

**Mitigation:** shared validator applied only at public option boundaries; audit table; focused compatibility note.

**Gate:** validation parity tests and diff review.

### R16. Direct transport example hides cleanup complexity

**Failure mode:** happy-path `b"".join()` examples avoid real early-exit ownership.

**Mitigation:** mandatory abandonment, corruption, and discard scenarios.

**Gate:** public-only integration tests and ergonomics record.

### R17. Striped upload publishes partial data

**Failure mode:** valid shards are promoted before another shard fails, leaving a visible incomplete dataset.

**Mitigation:** transaction directory and manifest-last commit; cleanup on dataset failure.

**Gate:** every injected failure leaves no published manifest or partials.

### R18. Striped reconstruction silently misorders rows

**Failure mode:** a missing row causes implicit round-robin positions to shift.

**Mitigation:** explicit sequence numbers, manifest row counts, and inconsistency detection.

**Gate:** removed-row and unequal-length tests.

### R19. Example concurrency becomes unbounded

**Failure mode:** producer tasks or `gather()` retain all rows/blocks/results.

**Mitigation:** bounded queues/prefetch, staging to disk, semaphore, deterministic depth assertions.

**Gate:** backpressure test and resource observation.

### R20. Scope expands into AnyIO/indexed access

**Failure mode:** examples become justification for new framework or index APIs before beta.

**Mitigation:** public current APIs only; explicit out-of-scope list.

**Gate:** no such public API in diff.

### R21. Benchmark noise drives false regression conclusions

**Failure mode:** short cases move with governor/load.

**Mitigation:** raw samples, MAD, same-session pairs, nine-repeat reruns, fixed environment.

**Gate:** methodology review and complete >5% audit.

### R22. Release is called beta-ready without real evidence

**Failure mode:** examples run only from source or no non-author reviews lifecycle behavior.

**Mitigation:** wheel-installed integrations, review packet, independent approval, separate post-release beta decision.

**Gate:** sections 11.6 and 17.

---

## 14. Review strategy

### Review 1 — Baseline and methodology

Review before production changes:

- source isolation;
- fixture construction;
- raw schema;
- sample retention;
- correctness checks;
- memory methodology;
- gate formulas.

### Review 2 — Header notification

Review:

- exact commit point;
- repeated timestamps and zero;
- invalid-header behavior;
- discard lifetime;
- no public API leakage.

### Review 3 — File synchronization

Review:

- feed and finish `finally` paths;
- cancellation ordering;
- exception translation;
- rewind state;
- read-ahead semantics;
- binary/text delegation;
- complete removal of duplicate parsing.

### Review 4 — Small-write disposition

Review:

- profile attribution;
- semantic tests;
- retained/reverted optimizations;
- size matrix;
- batching guidance;
- issue #86 handoff.

### Review 5 — Integrations and contract

Review:

- public-only imports;
- operation cleanup;
- integrity timing;
- bounded queues/prefetch;
- atomic publication;
- ordered reconstruction;
- validation changes;
- beta-freeze implications.

### Review 6 — Release evidence

Review:

- complete >5% audit;
- exact baselines;
- both engines;
- CI/platform status;
- wheel smokes;
- release notes;
- remaining alpha caveats.

At least one independent reviewer must cover reviews 2–4. At least one independent review must cover review 5. A single qualified reviewer may cover both, but the record must address the questions explicitly.

---

## 15. Suggested pull-request sequence

Preferred sequence:

1. **PR A — Plan, harness, and baselines**
   WP0 only. No production changes.

2. **PR B — Shared live-header metadata**
   WP1–WP3. Decoder notification, file migration, duplicate parser removal, high-level header evidence.

3. **PR C — Write regression disposition**
   WP4. Profile, safe optimization if justified, documentation, issue handoff.

4. **PR D — Public integrations and contract audit**
   WP5–WP7. Examples, validation, lifecycle/type checks.

5. **PR E — Hardening and release candidate**
   WP8–WP9. Full matrix, review, benchmarks, docs, artifacts, release preparation.

A maintainer may split these further. Do not combine them into one giant PR.

Every PR description must include:

- work packages covered;
- checklist items completed;
- exact commits/baselines used;
- behavior intentionally unchanged;
- tests and benchmark commands run;
- measured results;
- risks remaining;
- whether later-package files were touched;
- exact next package;
- remote actions still pending.

---

## 16. Maintainer handoff

Codex must leave a concise handoff containing:

### Repository state

- release-preparation commit SHA;
- clean-tree status;
- version and changelog status;
- artifact paths and SHA-256 hashes;
- raw evidence and review-record paths.

### Gate summary

- live-`mtime` correctness;
- one-parser proof;
- header timing/memory;
- many-member control;
- preserved `a2` gates;
- small-write size matrix and disposition;
- integration results;
- validation audit;
- CI/platform/engine status;
- independent review status.

### Remote actions

- milestone/issue updates;
- release PR merge;
- tag;
- GitHub prerelease;
- Trusted Publishing run;
- attestation verification;
- docs deployment;
- post-release version decision.

### Honest limitations

List any command or environment not run. Do not replace absent evidence with an expectation that CI will pass.

---

## 17. Decision after `2.0.0a3`

Move toward `2.0.0b1` only when all of the following are true:

- the shared-parser live-`mtime` repair has shipped and no follow-up correctness issue is open;
- high-level optional-header processing is demonstrably linear and bounded;
- the `a2` decoder/scheduler gates remain stable;
- the small-write result has a deliberate accepted disposition;
- at least two realistic public-only integrations have exercised the codec/high-level stack;
- integration authors did not encounter a recurring ownership or cleanup problem requiring API redesign;
- boolean and constructor validation is settled;
- no material lifecycle, buffering, or exception-timing change is expected;
- independent review has occurred;
- no critical correctness/security issue is open.

Then a maintainer may advance to `2.0.0b1.dev0`, change the classifier in the beta release, remove “provisional throughout alpha” language, and freeze the codec lifecycle.

Use `2.0.0a4.dev0` instead when:

- notification/rewind semantics require another material change;
- small-write work reveals a necessary public buffering API before 2.0;
- integrations repeatedly misuse the iterator ownership model despite documentation and typing;
- a pull-style fallback becomes justified by concrete evidence;
- engine or cancellation behavior requires another architectural correction.

Do not move to the pull-style fallback merely because it is familiar. Record actual recurring failures from more than one integration.

Later work remains separate:

- AnyIO/Trio substrate;
- indexed random access;
- explicit opt-in buffered writer;
- codec-only package/import boundary;
- additional engines;
- broader segmented-archive tooling.

---

## 18. Codex kickoff prompt

Copy the following prompt to Codex after committing this plan:

```text
Implement aiogzip 2.0.0a3 according to
plans/RELEASE_2_0_0A3_PLAN.md.

Treat the plan's locked SHAs, scope, fixed design decisions, regression gates,
and work-package ordering as authoritative.

Begin with section 0 and WP0. Before changing production code:
1. verify the exact main, v2.0.0a2, v2.0.0a1, and v1.11.0 commits;
2. verify the working tree is clean and the version is 2.0.0a3.dev0;
3. add the benchmark-only a3 regression harness;
4. capture and commit exact-tag raw baselines with individual samples;
5. keep the repository green.

The non-waivable implementation objective is to remove the binary file
reader's duplicate gzip-header probe and drive live mtime from the shared
incremental decoder. Implement the package-private header generation and last
mtime contract exactly as specified. Update the file property after each feed
and finish drain, including error and cancellation paths. Preserve the public
mtime across rewind until a header is reread. Delete _header_probe_buffer and
_try_parse_gzip_header_mtime; do not replace them with another parser.

Profile the remaining small-write regression across the complete size matrix
before optimizing. Preserve same-call sink errors, output visibility, position
timing, poisoning, and close behavior. Do not buffer across write() calls, add
a background task, bypass codec ownership, or change thresholds after seeing
results. A documented no-code-change disposition is acceptable when safe
parity is unavailable.

Add the two public-only integrations: fragmented custom transport using the
codec, and concurrent striped JSONL safe upload with bounded staging,
validation-at-completion, manifest-last publication, and ordered
reconstruction. Run them from the built wheel and type-check them.

Preserve every successful 2.0.0a2 decoder, memory, integrity, scheduler,
cancellation, and engine invariant. Do not implement AnyIO/Trio, indexed
access, raw DEFLATE, ISA-L, the pull-style fallback, a default buffered writer,
or unrelated cleanup.

Work package by work package. Update checklist items in the same commit as the
work or evidence they describe. If keeping a package green requires later
package work, stop and report the dependency instead of pulling it forward. If
a hard performance gate misses, stop, profile, and report; do not edit the
gate or baseline.

Run uv run prek run --all-files before each commit. Do not tag, publish, push,
create remote branches/issues/milestones, change repository settings, deploy
docs, close issue #86, or claim independent review. Record maintainer-only
handoff actions in the plan.
```

---

## 19. Compact definition of done

The release is ready for maintainer publication only when all statements below are true:

- [ ] exact base and baselines are verified;
- [ ] one shared gzip-header parser remains;
- [ ] live binary/text `mtime` follows the most recently parsed valid header;
- [ ] concatenated members, corruption, cancellation, and rewind are covered;
- [ ] high-level large optional headers are linear and bounded;
- [ ] all `a2` decoder/scheduler gates remain passing;
- [ ] small writes have a measured semantics-preserving disposition;
- [ ] no write size regressed more than the allowed threshold;
- [ ] strict boolean validation is consistent;
- [ ] direct transport example passes from the wheel;
- [ ] striped safe-upload example passes success and failure scenarios from the wheel;
- [ ] public examples type-check;
- [ ] complete Python/platform/engine matrix passes;
- [ ] review packet and independent approvals exist;
- [ ] candidate benchmarks and raw samples are committed;
- [ ] wheel/sdist and clean-install smokes pass;
- [ ] version, changelog, release notes, and artifact hashes agree;
- [ ] no result was fabricated and every unavailable check is disclosed;
- [ ] remote publication remains in maintainer hands.
