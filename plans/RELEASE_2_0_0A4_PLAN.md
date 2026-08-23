# aiogzip 2.0.0a4 Integration and Beta-Readiness Release Plan

> **Status:** Follow-up review found four staged-ingest blockers at `f4a2fc8`;
> corrected in `c3f681e`, with corrected-head platform CI, renewed human
> approval, and release preparation pending
> **Target release:** `2.0.0a4`
> **Repository destination:** `plans/RELEASE_2_0_0A4_PLAN.md`
> **Plan date:** 2026-08-17
> **Primary objective:** finish the 2.0 alpha series by exercising the public codec and high-level async APIs in two practical integrations, deliberately settle the remaining public validation and completed-member metadata contracts, preserve the `2.0.0a3` correctness and performance gains, and produce reviewable evidence for a subsequent `2.0.0b1` decision.

This document is the living implementation checklist for aiogzip `2.0.0a4`. It is intentionally prescriptive. Codex must treat the locked commits, fixed design decisions, regression gates, scope boundaries, and work-package order as authoritative unless the maintainer changes them in a reviewed plan-only commit.

`2.0.0a4` is a **small integration and contract-finalization alpha**, not another architecture release. The shared codec, immutable compressed-input spans, incremental gzip-header parser, bounded inflate windows, cooperative async scheduling, operation ownership, high-level same-handle reservations, poisoning, recovery-data behavior, live `mtime`, and write visibility rules established by `a1` through `a3` are considered successful. Preserve them.

The expected path after this release is:

```text
2.0.0a3
    ↓
2.0.0a4: integrations + contract settlement + external review
    ↓
2.0.0b1, if no material lifecycle or API redesign remains
```

A further alpha is still preferable to a premature beta if either maintained integration exposes a recurring public-API problem.

---

## 0. Locked starting points and mandatory preflight

### 0.1 Immutable repository references

This plan was written against these commits:

| Purpose | Commit |
| --- | --- |
| Expected pre-plan `main` base | `924ae3659a6ba416f5391a083f27f0b387e6fe67` |
| Published `v2.0.0a3` release | `3e95073581be7cba437da45dacd9724f649e54d0` |
| Published `v2.0.0a2` release | `9534eb31da15417126233eda225d8f897908e3bb` |
| Published `v2.0.0a1` release | `920004672bbb5e76fb2088358d1cb7051290576d` |
| Published `v1.11.0` comparison baseline | `3f23eadb524c8dba840c4fd855ad5acf84486048` |

At the time this plan was prepared, the only commit after `v2.0.0a3` was the development-version advance to `2.0.0a4.dev0`.

Before editing any file other than this plan, run:

```bash
git status --short
git rev-parse HEAD
git rev-parse v2.0.0a3^{commit}
git rev-parse v2.0.0a2^{commit}
git rev-parse v2.0.0a1^{commit}
git rev-parse v1.11.0^{commit}
git cat-file -e 924ae3659a6ba416f5391a083f27f0b387e6fe67^{commit}
git cat-file -e 3e95073581be7cba437da45dacd9724f649e54d0^{commit}
git cat-file -e 9534eb31da15417126233eda225d8f897908e3bb^{commit}
git cat-file -e 920004672bbb5e76fb2088358d1cb7051290576d^{commit}
git cat-file -e 3f23eadb524c8dba840c4fd855ad5acf84486048^{commit}
```

Two starting states are permitted:

1. `HEAD` is exactly `924ae3659a6ba416f5391a083f27f0b387e6fe67`; or
2. `HEAD` is a descendant of that commit and every intervening commit changes only `plans/RELEASE_2_0_0A4_PLAN.md`.

For the second case, verify with:

```bash
git merge-base --is-ancestor \
  924ae3659a6ba416f5391a083f27f0b387e6fe67 HEAD
git diff --name-only \
  924ae3659a6ba416f5391a083f27f0b387e6fe67..HEAD
```

Preflight checklist:

- [x] The working tree is clean.
- [x] `v2.0.0a3^{commit}` is exactly `3e95073581be7cba437da45dacd9724f649e54d0`.
- [x] `v2.0.0a2^{commit}` is exactly `9534eb31da15417126233eda225d8f897908e3bb`.
- [x] `v2.0.0a1^{commit}` is exactly `920004672bbb5e76fb2088358d1cb7051290576d`.
- [x] `v1.11.0^{commit}` is exactly `3f23eadb524c8dba840c4fd855ad5acf84486048`.
- [x] `HEAD` satisfies one of the two allowed starting states.
- [x] `src/aiogzip/__init__.py` reports `2.0.0a4.dev0`.
- [x] `pyproject.toml` still declares Python `>=3.11`.
- [x] `pyproject.toml` still uses the Alpha development-status classifier.
- [x] `AGENTS.md` and repository-local instructions have been read in full.
- [x] The project-prescribed commit checks are known before implementation begins.
- [x] The actual implementation-base commit is recorded in the preflight report.

If `main` has advanced with any non-plan change:

1. stop before changing production code;
2. list every new commit and every changed file;
3. identify whether any change touches source, tests, examples, docs, benchmarks, packaging, CI, or release evidence;
4. do not silently replace the locked SHA;
5. prepare a short impact report;
6. require a maintainer-edited plan-only commit before continuing.

Codex must not create, push, delete, or rename remote branches. Remote issues, labels, milestones, pull requests, reviews, tags, releases, documentation deployments, PyPI publication, repository settings, and branch protection are maintainer-only actions.

### 0.2 Verify the current release posture

Record these facts in the preflight report after confirming them from the checkout:

- [x] Current development version is `2.0.0a4.dev0`.
- [x] Current published release is `v2.0.0a3`.
- [x] The public codec is still documented as provisional during the alpha series.
- [x] Open issue #86 covers small-write overhead.
- [x] Open issue #71 covers a possible AnyIO substrate.
- [x] Open issue #72 covers indexed random access.
- [x] Python 3.11 through 3.14 remain the intended 2.0 interpreter matrix.
- [x] The engine matrix remains stdlib zlib, zlib-ng active, and stdlib forced while zlib-ng is installed.
- [x] The configured coverage floor remains unchanged.
- [x] Release publication remains tag-triggered Trusted Publishing.
- [x] No top-level maintained integration examples already satisfy this plan's two integration gates.
- [x] The `2.0.0a3` release plan received an honest closeout without retroactive checkbox inflation.

Do not fold routine dependency updates, workflow modernization, style-only cleanup, or unrelated documentation changes into `a4` merely because they are nearby.

### 0.3 Preserve an exact `a3` comparison baseline

`v2.0.0a3` is the primary performance and behavior baseline for `a4`. `v1.11.0` remains useful only for historical small-write context and other genuinely comparable high-level operations. Do not treat `v1.11.0` as the lifecycle or exception-semantics reference for the 2.0 codec.

Before changing `src/aiogzip/`, extend the existing release benchmark harness or add the smallest coherent `a4` supplement. Prefer extending the existing `a3` harness when doing so does not alter existing result semantics.

The exact same committed harness must run against detached worktrees for:

- exact `v2.0.0a3`;
- exact pre-change `main` at the locked base or allowed plan-only descendant;
- exact `v1.11.0` only for rows that its API can represent faithfully.

Suggested worktrees:

```bash
git worktree add --detach /tmp/aiogzip-v2.0.0a3-a4 v2.0.0a3
git worktree add --detach /tmp/aiogzip-v1.11.0-a4 v1.11.0
git worktree add --detach /tmp/aiogzip-main-pre-a4 \
  924ae3659a6ba416f5391a083f27f0b387e6fe67
```

Required evidence files, adjusted only when the repository already has an equivalent naming convention:

```text
plans/benchmarks/v2.0.0a4-preflight.md
plans/benchmarks/data/v2.0.0a3-a4-baseline-stdlib.json
plans/benchmarks/data/v2.0.0a3-a4-baseline-zlib-ng.json
plans/benchmarks/data/main-pre-a4-stdlib.json
plans/benchmarks/data/main-pre-a4-zlib-ng.json
plans/benchmarks/data/v1.11.0-a4-comparable-stdlib.json
plans/benchmarks/data/v1.11.0-a4-comparable-zlib-ng.json
```

The baseline suite must retain at least these established cases:

- [x] representative `decompress_chunks()` 512 KiB input / 256 KiB output;
- [x] representative `decompress_chunks()` 64 KiB input / 64 KiB output;
- [x] representative `compress_chunks()` cases already pinned by `a3`;
- [x] direct one-large-feed decoding and transport-sized-feed decoding;
- [x] one-item async-source scheduler responsiveness;
- [x] fragmented optional-header time and peak allocation;
- [x] concurrent independent-file throughput;
- [x] JSONL bounded-batch reading;
- [x] full binary read peak allocation;
- [x] write-size curve at 10 B, 100 B, 1 KiB, 4 KiB, 16 KiB, 64 KiB, and 256 KiB;
- [x] the extreme one-call-per-10-byte-write diagnostic;
- [x] output lengths and digests for every timed correctness-bearing case.

The Markdown preflight record must include:

- [x] exact source commits and clean-worktree status;
- [x] benchmark harness commit and SHA-256;
- [x] fixture generator version and fixture hashes;
- [x] Python implementation, full version, executable, and build details;
- [x] operating system, kernel, architecture, libc, CPU, core count, and RAM;
- [x] filesystem and temporary-directory locations;
- [x] stdlib zlib compile-time and runtime versions;
- [x] zlib-ng package version and selected engine;
- [x] `uv` version and `uv.lock` SHA-256;
- [x] material machine conditions such as power state, CPU governor, affinity, and system load;
- [x] exact commands;
- [x] warm-up, repeat, ordering, and garbage-collection policies;
- [x] every timing sample, not only medians;
- [x] medians, median absolute deviation, minima, maxima, and sample counts;
- [x] peak-allocation method and values;
- [x] source-read, compressor, codec-operation, and sink-write counts where available;
- [x] output byte counts and SHA-256 digests;
- [x] every excluded, interrupted, or invalid run and the reason for exclusion.

Do not reconstruct exact-tag measurements from prose. Run the harness or mark the comparison unavailable.

### 0.4 Baseline immutability

After the first production-code change:

- [ ] Never overwrite committed exact-tag baseline JSON.
- [ ] Never rerun only the candidate after fixing a benchmark defect.
- [ ] If the harness is defective, fix it in a standalone benchmark commit, preserve superseded evidence, and recapture baseline and candidate with the corrected identical harness.
- [ ] Never change fixture sizes, fragmentation, sample counts, formulas, or thresholds after seeing candidate results without recapturing every comparison and documenting the reason.
- [ ] Never average a named regression away with unrelated wins.
- [ ] Never claim a gate passed when its required reference run was not captured.
- [ ] Keep correctness verification outside timed regions when practical, but always retain output-size and digest checks.

---

## 1. Instructions to Codex

### 1.1 Execution model

Implement one work package at a time, in order.

For each work package:

1. Read the complete package, its dependencies, fixed decisions, tests, gates, and exit criteria.
2. Inspect the current implementation and tests; do not trust historical line numbers.
3. Add or update characterization tests before changing protected behavior, but do not commit a red package boundary.
4. Make the smallest coherent implementation change.
5. Update this plan's checkboxes in the same commit as the implementation, test, documentation, or evidence they describe.
6. Run package-specific checks plus all affected regression suites.
7. Run the repository-prescribed hooks before every commit.
8. Keep the repository green at every committed package boundary.
9. Report commands actually run, results, unresolved risks, and intentional non-changes.

A checked box means the implementation, tests, docs, and required evidence exist. It does not mean code was drafted or a command was intended.

### 1.2 Forward-dependency rule

If keeping a work package green requires work assigned to a later package:

- stop;
- identify the exact dependency and files;
- explain why a temporary compatibility seam is insufficient;
- propose the smallest package-boundary correction;
- require a maintainer-edited plan-only commit before continuing.

Do not quietly pull later work forward. Do not collapse the release into one giant refactor.

### 1.3 Scope-control rules

- [ ] Do not reopen the immutable-span decoder architecture.
- [ ] Do not replace the incremental header parser.
- [ ] Do not change bounded inflate windows merely to chase a benchmark.
- [ ] Do not weaken operation ownership or deterministic abandonment.
- [ ] Do not weaken same-handle async reservations or `ConcurrentOperationError`.
- [ ] Do not weaken poisoning, recovery-data, seek-recovery, CRC, ISIZE, FHCRC, padding, trailing-data, or decompression-limit behavior.
- [ ] Do not introduce default cross-call write buffering.
- [ ] Do not add a producer task, background compressor, or unbounded queue.
- [ ] Do not materialize complete compressed or decompressed datasets in an integration whose purpose is bounded streaming.
- [ ] Do not add cloud credentials, Docker, a database, or a web framework to make an example look realistic.
- [ ] Do not add HTTPX, aiohttp, fsspec, or another integration library as a required runtime dependency.
- [ ] Do not create a public striped-archive format or API in this release.
- [ ] Do not implement AnyIO, Trio, indexed access, raw DEFLATE, ISA-L, the pull-style codec fallback, or a codec-only distribution.
- [ ] Do not perform broad internal cleanup from the `a3` review unless a required integration exposes a correctness defect that cannot be fixed otherwise.
- [ ] Do not combine unrelated dependency upgrades with behavior changes.

### 1.4 Reviewability rules

Prefer a sequence of small pull requests or reviewable commit groups:

| Review unit | Scope |
| --- | --- |
| A | Preflight evidence, `a3` closeout, and changelog-link repair |
| B | Boolean validation and completed-member metadata contract |
| C | Fragmented-transport integration |
| D | Concurrent staged-ingest integration |
| E | Documentation, benchmarks, packaging, and release evidence |

- [ ] Do not put all `a4` work in one pull request when repository workflow permits separate reviews.
- [ ] Keep generated fixtures out of behavioral diffs when possible.
- [ ] Separate benchmark-harness corrections from candidate optimizations.
- [ ] Make public contract changes visually obvious in their own commit or PR.
- [ ] Preserve an ordinary GitHub-reviewable diff; do not generate hundreds of incidental files.

### 1.5 Remote and maintainer-only actions

Codex may prepare local files and commits. Codex must not:

- create, edit, label, milestone, close, or reopen GitHub issues;
- create or merge pull requests;
- claim a human review occurred;
- push branches or tags;
- publish releases or packages;
- deploy documentation;
- alter branch protection, repository settings, permissions, or secrets;
- claim Windows, macOS, an interpreter, or an engine passed unless that exact job ran.

Record every remote or publication action in the maintainer handoff checklist.

---

## 2. Executive release decision

The next release is **`2.0.0a4`**, not `2.0.0b1`.

`2.0.0a3` successfully delivered the intended high-level correctness and lifecycle work:

- the binary reader no longer owns a duplicate gzip-header parser;
- live `mtime` comes from the shared incremental decoder;
- same-handle overlap is rejected deterministically;
- decompression and validation failures poison readers consistently;
- recovery-data behavior is explicit;
- seek-to-zero is the supported recovery path for rewindable readers;
- text and binary cancellation and rollback behavior were hardened;
- small writes improved without moving sink failures across calls.

The remaining beta-readiness gap is narrower:

1. the public codec still lacks a maintained, realistic direct-transport integration;
2. the high-level APIs still lack a maintained concurrent staged-ingest integration demonstrating validation-at-completion and bounded independent-stream concurrency;
3. boolean configuration values are still coerced by truthiness rather than deliberately validated;
4. `GzipDecoder.member_count` can remain positive while `members` is cleared after a later failure;
5. issue #86 needs an explicit 2.0 disposition rather than indefinite ambiguity;
6. user-facing concurrency and recovery guidance should be consolidated;
7. beta should follow an actual independent human review of the public contracts and integration code.

`a4` is therefore an **integration, public-contract settlement, and release-evidence alpha**. It must not become a feature grab bag.

The preferred next development version after publication is `2.0.0b1.dev0`, but only when the completed `a4` evidence shows that no material lifecycle or API redesign remains. Otherwise advance to `2.0.0a5.dev0` and explain the unresolved alpha finding.

---

## 3. Release objectives and scope

### 3.1 Required outcomes

`2.0.0a4` is complete only when all of these outcomes exist:

1. **Honest `a3` closeout.** The prior plan distinguishes shipped work, deferred work, superseded work, maintainer actions, and work not performed.
2. **Deliberate boolean contracts.** Public boolean options reject accidental truthy/falsy substitutes consistently and at the documented call boundary.
3. **Coherent completed-member metadata.** Already trailer-validated metadata remains consistent with `member_count` after a later failure or explicit discard.
4. **Direct-codec integration.** A compact fragmented-transport example uses only public codec interfaces and demonstrates success, provisional output, verification, corruption, truncation, and cleanup.
5. **High-level integration.** A compact concurrent JSONL ingest example uses independent aiogzip handles, bounded concurrency, limits, staging, complete validation, cancellation cleanup, and atomic publication semantics.
6. **Performance preservation.** No required `a3` regression gate is lost.
7. **Clear issue disposition.** Small per-call writes remain semantically strict and issue #86 has a documented 2.0 outcome.
8. **Independent review.** At least one human reviewer who did not author or generate the implementation reviews the public contract changes and at least one integration.
9. **Beta decision evidence.** The release record states whether `main` should advance to `2.0.0b1.dev0` or another alpha and why.

### 3.2 In scope

- `a3` release-plan closeout;
- changelog comparison-link repair;
- exact-boolean and optional-boolean validation;
- cross-surface constructor/function validation tests;
- retention semantics for completed `GzipMemberInfo` records;
- a fragmented custom-transport example;
- a concurrent staged JSONL ingest example;
- wheel-installed and sdist-installed example smoke tests;
- example type checking;
- concurrency and recovery-data documentation;
- small-write benchmark preservation and issue disposition;
- full supported interpreter, platform, engine, packaging, docs, lint, type, and coverage validation;
- external review evidence;
- release notes and maintainer handoff.

### 3.3 Explicitly out of scope

- AnyIO or Trio support (#71);
- indexed or zran-style random access (#72);
- an implicit/default buffered writer;
- a background write queue;
- a public striped JSONL or segmented-archive format;
- round-robin reconstruction as a release gate;
- HTTP range access;
- an HTTP client runtime dependency;
- raw DEFLATE;
- ISA-L;
- the bounded pull-style codec fallback;
- a codec-only package or import-graph redesign;
- a new compression engine;
- broad text-layer consolidation;
- broad reservation-helper consolidation;
- broad decoder-notification or hot/cold cleanup from the `a3` review;
- unrelated dependency, CI, style, or documentation modernization.

### 3.4 Optional non-gating follow-up

A small HTTPX safe-download example may be added only after all required work packages and gates pass, and only in a separate commit. It must remain an optional example/test dependency and use raw response bytes with HTTP content decoding disabled. It is not part of the `a4` definition of done.

---

## 4. Fixed design decisions

These decisions are authoritative for `a4`.

### D1. Release stage

The release is `2.0.0a4`. Keep the package Alpha classifier and keep the public codec's provisional-alpha language.

Do not change to beta during implementation merely because the work is going well. Beta is a maintainer decision after candidate evidence and external review.

### D2. Preserve the `a3` architecture and semantics

Do not redesign:

- codec operation ownership;
- iterator cleanup;
- mutable-state poisoning;
- async same-handle reservations;
- `ConcurrentOperationError` inheritance or principal role;
- recovery-data sequencing;
- read/write cancellation semantics;
- shared-header notifications;
- compressed-input span queues;
- inflate-window normalization;
- public output chunk bounds;
- high-level write visibility or same-call sink-error timing.

A required integration may reveal a correctness problem. In that case, stop and report it rather than folding a lifecycle redesign into the example package.

### D3. Exact boolean validation

Add one shared validator:

```python
def _validate_bool(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{name} must be a bool")
    return value
```

Use exact type identity, not `isinstance`, truthiness, equality, or coercion.

The following values are accepted:

```python
True
False
```

The following representative values are rejected:

```python
0
1
""
"false"
[]
object()
custom_truthy_object
custom_falsy_object
numpy_like_bool_scalar
```

Do not add NumPy as a test dependency. Use a small local bool-like test class.

### D4. Optional boolean validation for `closefd`

`closefd` accepts exactly:

```python
None
True
False
```

Add a shared helper or explicit conditional validation:

```python
def _validate_optional_bool(value: object, name: str) -> bool | None:
    if value is None:
        return None
    return _validate_bool(value, name)
```

`None` retains the current defaulting rule:

```text
file opened by aiogzip → aiogzip closes it
external fileobj       → caller retains it
```

An explicit `True` or `False` continues to override that default. This is an intentional alpha-stage tightening.

### D5. Public options covered by exact validation

Audit every public surface and apply the shared contract to:

- `fast_compress`;
- `strict_size`;
- `collect_member_info`;
- `closefd`.

At minimum, inspect and test:

- `GzipEncoder`;
- `GzipDecoder`;
- `AsyncGzipBinaryFile`;
- `AsyncGzipTextFile`;
- `AsyncGzipFile` and `open()` factory paths;
- whole-file write helpers;
- `compress_chunks()`;
- inspection and verification helpers where an affected option is exposed;
- any public aliases or compatibility factories.

Do not validate only the lowest layer if doing so changes where warnings, source iteration, file acquisition, or other side effects occur.

### D6. Validation timing

Invalid boolean arguments fail at the earliest boundary compatible with the existing public API shape:

- synchronous constructors, factories, and async-iterator factories fail before returning;
- coroutine functions fail on their first await, before opening a path or touching an external file object;
- validation occurs before warning about unavailable zlib-ng;
- validation occurs before creating a codec engine where practical;
- validation occurs before requesting the first item from an async iterable;
- do not change an existing `async def` API into a synchronous wrapper merely to move validation to coroutine creation time.

Exception type is `TypeError`. Every error message includes the parameter name. No invalid call may perform I/O or mutate codec/engine state.

### D7. Completed-member metadata survives later failure

When `collect_member_info=True`, a `GzipMemberInfo` record is appended only after that member's trailer CRC and ISIZE validate. Once appended, it is immutable, complete, and remains observable even if a later member fails.

After any later operation failure or explicit `discard()`:

- `member_count` retains the number of trailer-validated members;
- `members` retains exactly the corresponding completed records;
- no record is created for the active or failed member;
- mutable input, output, parser, inflate, and engine state is released;
- the decoder remains unusable as already specified;
- `finished` remains `False` unless normal finalization previously completed.

When `collect_member_info=False`:

- `members` remains `()`;
- `member_count` still reports the number of completed members;
- no metadata objects are retained.

The opt-in memory cost is deliberate. A caller that requested metadata may use already validated records for diagnostics after a later failure.

### D8. `discard()` remains the only codec-wide cleanup operation

Retaining immutable validated metadata does not make `discard()` reversible. It still:

- invalidates an outstanding operation;
- releases mutable/incomplete codec state;
- makes the codec unusable;
- leaves an invalidated retained operation raising `RuntimeError` when advanced;
- remains idempotent.

Update wording from “release all codec state” to “release mutable and incomplete codec state” where needed.

### D9. No new public integration API

The integrations are maintained examples and integration tests. They do not introduce:

- a transport adapter class in `src/aiogzip/`;
- a dataset-ingest framework;
- a manifest library;
- a sharding format;
- a global decompression-budget API;
- a new public exception solely for examples.

Example-local helpers and exception classes are acceptable.

### D10. Fragmented-transport example boundary

The direct-codec example uses public imports only:

```python
aiogzip.GzipEncoder
aiogzip.GzipDecoder
aiogzip.CodecOperation
```

It demonstrates a small application-level framed stream over an asyncio local connection. It is not a general networking framework.

The sender may use `flush()` to expose low-latency records. The receiver may expose decoded records before final validation, but it must label them provisional until `finish()` is exhausted.

### D11. Concurrent-ingest example boundary

The high-level example ingests independent `.jsonl.gz` files concurrently. It does **not** round-robin rows among shards and does not reconstruct a custom striped format.

Each active shard owns one aiogzip handle in one task. Concurrency is bounded. The example uses bounded line batches rather than per-line asynchronous iteration in the hot path.

### D12. Publication model

The concurrent-ingest example stages all outputs in a unique sibling directory on the same filesystem as the final destination. The final dataset directory must not already exist.

Publication occurs by one final directory rename after every shard has:

- reached normal gzip completion;
- passed CRC and ISIZE validation;
- remained within its decompression limit;
- remained within the dataset-wide budget;
- produced its expected row count and digest metadata;
- closed successfully.

On any failure or cancellation, the final destination must not exist and the staging directory must be removed.

### D13. Limits in the ingest example

The example demonstrates both:

- a per-shard `max_decompressed_size` enforced by aiogzip; and
- an example-level dataset-wide decoded-byte budget shared across tasks.

The global budget uses exact UTF-8 byte counts for the fixture format and a small async-safe accounting object. It does not claim to be a new aiogzip primitive.

### D14. Slow-source demonstration

A deliberately slow shard must not prevent healthy independent shards from progressing. Tests must prove this with events or recorded progress ordering, not a fragile wall-clock race.

Do not add arbitrary sleeps as the only assertion mechanism. A small controlled delay may be used to create the condition, but correctness must be event-driven.

### D15. Small-write contract remains frozen

One `await write(data)` continues to guarantee:

- an immutable snapshot of that call's input;
- completion of that call's codec operation;
- delivery of every compressed byte emitted by that operation to the sink before return;
- logical-position advancement only after successful sink writes;
- a sink failure reported by the call that triggered it;
- poisoning after failure or cancellation;
- no misleading valid trailer after a broken write.

Do not buffer across calls by default. The 10-byte benchmark is diagnostic, not authority to change this contract.

### D16. Issue #86 disposition

For 2.0, per-call tiny writes are accepted as a strict-semantics tradeoff. `writelines()` or application-level bounded batching is the recommended throughput path.

`a4` must preserve the `a3` anti-regression row and produce a written disposition. Whether issue #86 is closed, relabeled, or converted to a post-2.0 opt-in buffered-writer proposal is a maintainer-only remote action.

### D17. Examples remain dependency-light

Required examples may use:

- Python standard library;
- `aiogzip`;
- `aiofiles`, already a runtime dependency.

They may not require cloud credentials or external services. HTTPX remains optional and non-gating.

### D18. Packaging of examples

Include maintained example source and README files in the source distribution. They need not be installed as importable modules in the wheel.

Wheel-installed smoke tests must copy or invoke the example files from outside the repository source tree while importing aiogzip from the installed wheel. They must assert the imported package path belongs to the clean environment, not `src/` in the checkout.

### D19. Performance policy

For comparable exact-`a3` rows:

- more than 5% slower requires investigation and written disposition;
- more than 10% slower blocks release;
- improvements do not offset a named regression elsewhere;
- functional example tests use bounded-resource assertions, not fragile latency gates.

### D20. Human review is a release gate

At least one reviewer who did not author or generate the implementation must review:

- exact-boolean validation;
- completed-member metadata retention;
- at least one maintained integration;
- lifecycle and cleanup claims in the release notes.

Codex may prepare a review checklist. Codex may not mark human review complete.

### D21. Beta transition is evidence-based

After candidate validation:

- advance to `2.0.0b1.dev0` only if no material public lifecycle or API change is expected;
- otherwise advance to `2.0.0a5.dev0` and record the concrete unresolved alpha issue.

Do not remove provisional-alpha language in `a4`.

---

## 5. Repository-level deliverables

The final implementation is expected to touch or add files in these areas. Codex must inspect the current tree and use established naming conventions rather than blindly creating duplicates.

```text
plans/
├── RELEASE_2_0_0A4_PLAN.md
├── RELEASE_2_0_0A3_CLOSEOUT.md
├── benchmarks/
│   ├── v2.0.0a4-preflight.md
│   └── v2.0.0a4-candidate.md
└── reviews/
    └── v2.0.0a4-review-checklist.md

plans/benchmarks/data/
├── v2.0.0a3-a4-baseline-stdlib.json
├── v2.0.0a3-a4-baseline-zlib-ng.json
├── main-pre-a4-stdlib.json
├── main-pre-a4-zlib-ng.json
├── v2.0.0a4-candidate-stdlib.json
└── v2.0.0a4-candidate-zlib-ng.json

examples/
├── README.md
├── fragmented_transport.py
└── concurrent_jsonl_ingest.py

src/aiogzip/
├── _common.py
├── _binary.py
├── _text.py
├── _streaming.py
├── _inspection.py        # only if audit finds a public affected option
├── codec.py
└── __init__.py

tests/
├── integration/
│   ├── test_example_fragmented_transport.py
│   └── test_example_concurrent_jsonl_ingest.py
├── test_boolean_validation.py
└── existing codec/file/streaming test modules as appropriate

docs/
├── codec.md
├── examples.md
├── streaming.md
├── api.md
└── performance.md

benchmarks/
└── existing a3 harness or a narrowly scoped a4 supplement

CHANGELOG.md
README.md
mkdocs.yml
pyproject.toml
```

Equivalent established paths are acceptable. Do not create a second benchmark framework, second documentation page, or second validation module when an existing location is clearly authoritative.

---

## 6. Work package 0 — Preflight, baseline, and honest `a3` closeout

### 6.1 Purpose

Establish immutable evidence before behavior changes and reconcile the prior release plan without pretending deferred work shipped in `a3`.

### 6.2 Required inspection

Before editing production source:

- [x] Read `AGENTS.md` and all repository-local contributor instructions.
- [x] Read the complete `2.0.0a3` release plan.
- [x] Read the final `2.0.0a3` review record.
- [x] Read the `2.0.0a3` changelog and release notes.
- [x] Inspect every unchecked `a3` checklist item related to integrations, boolean validation, benchmarks, packaging, and review.
- [x] Inspect the existing benchmark harness and raw result schema.
- [x] Inspect current changelog comparison links.
- [x] Confirm the current development-version-only commit after the tag.

### 6.3 Create the `a3` closeout record

Add:

```text
plans/RELEASE_2_0_0A3_CLOSEOUT.md
```

The closeout must use these categories:

#### Shipped in `2.0.0a3`

List completed outcomes with links to commits, tests, docs, benchmark records, or review evidence. Include at least:

- shared-parser live `mtime` work;
- `ConcurrentOperationError` and same-handle reservations;
- poisoning and recovery-data semantics;
- seek-to-zero recovery behavior;
- text cancellation/rollback hardening;
- small-write improvements actually shipped;
- release matrix and artifact evidence actually captured.

#### Deferred to `2.0.0a4`

List at least:

- strict boolean validation;
- direct-codec integration;
- concurrent high-level integration;
- example type checking and built-artifact execution;
- completed-member metadata decision;
- issue #86 final 2.0 disposition;
- external human review if none occurred.

#### Superseded by implementation findings

Record plan items whose exact mechanism was replaced by a better reviewed implementation while preserving the intended outcome. Cite the implemented mechanism.

#### Maintainer-only actions completed

Record only remote actions with verifiable evidence, such as tag, release, publication, documentation deployment, or accepted review record.

#### Not performed

List work that was neither shipped nor deliberately deferred. Do not hide omitted work by checking its old box.

Closeout rules:

- [x] Do not edit hundreds of old checkboxes merely to make the plan look complete.
- [x] Add a status note near the top of the `a3` plan linking to the closeout.
- [x] Do not mark an item completed when only a related but different activity occurred.
- [x] Record contradictions between the old plan and shipped behavior explicitly.
- [x] Keep the closeout factual and concise enough to audit.

### 6.4 Repair changelog comparison links

Before adding the `a4` release section, ensure:

```text
[Unreleased]: ...compare/v2.0.0a3...HEAD
[2.0.0a3]: ...compare/v2.0.0a2...v2.0.0a3
```

At final release preparation, add:

```text
[2.0.0a4]: ...compare/v2.0.0a3...v2.0.0a4
```

Checklist:

- [x] `[Unreleased]` starts from `v2.0.0a3`.
- [x] A `2.0.0a3` comparison link exists.
- [x] No existing historical comparison link is silently rewritten incorrectly.
- [x] Link targets are checked syntactically.

### 6.5 Capture pre-change benchmarks

- [x] Extend or add the smallest necessary benchmark harness.
- [x] Commit the harness before production-code changes.
- [x] Capture exact `v2.0.0a3` stdlib-zlib samples.
- [x] Capture exact `v2.0.0a3` zlib-ng samples.
- [x] Capture pre-change `main` stdlib-zlib samples.
- [x] Capture pre-change `main` zlib-ng samples.
- [x] Capture exact `v1.11.0` small-write comparables where valid.
- [x] Verify output digests.
- [x] Commit raw samples.
- [x] Commit the Markdown preflight record.
- [x] Record unavailable rows rather than inventing adapters that alter semantics.

### 6.6 Pre-change test baseline

Run the full project-prescribed baseline suite before source changes. At minimum, record:

```bash
uv sync --all-extras
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run ty check
uv run mkdocs build --strict
uv run prek run --all-files
```

Use repository-defined variants when commands differ. Do not claim a command passed unless it ran.

- [x] Test count, skips, xfails, duration, and coverage are recorded.
- [x] Selected compression engine is recorded.
- [x] Any existing failure is investigated before implementation.
- [x] No new waiver is created merely to begin the release.

### 6.7 Exit criteria

WP0 is complete when:

- [x] the exact starting state is verified;
- [x] the prior plan has an honest closeout;
- [x] changelog links are correct for the current development state;
- [x] immutable baseline evidence exists for exact `a3` and pre-change `main`;
- [x] the repository is green;
- [x] no production source has changed before baseline capture;
- [x] all WP0 checklist changes are committed with their evidence.

Suggested commit sequence:

```text
Plan: close out 2.0.0a3 and lock the a4 baseline
Benchmark: capture exact 2.0.0a3 comparisons for a4
```

Do not combine a benchmark-harness correction with a production optimization.

---

## 7. Work package 1 — Deliberate boolean validation

### 7.1 Purpose

Replace accidental truthiness coercion with one documented cross-surface public contract before beta.

### 7.2 Characterization and inventory

Before implementation, inventory every affected signature:

```bash
rg -n "fast_compress|strict_size|collect_member_info|closefd" \
  src tests docs README.md
```

Create a table in the WP1 implementation note containing:

| Parameter | Public surfaces | Current behavior | Intended `a4` behavior |
| --- | --- | --- | --- |
| `fast_compress` | ... | truthiness/coercion | exact `bool` |
| `strict_size` | ... | truthiness/coercion | exact `bool` |
| `collect_member_info` | ... | truthiness/coercion | exact `bool` |
| `closefd` | ... | `None` or unvalidated value | `None` or exact `bool` |

- [x] Every public occurrence is listed.
- [x] Internal constants and ordinary `bool(...)` result conversions such as `isatty()` are distinguished from configuration validation.
- [x] No unrelated boolean-returning code is changed.

### 7.3 Shared validators

In the established validation module, add:

```python
def _validate_bool(value: object, name: str) -> bool:
    """Return an exact bool or raise a parameter-specific TypeError."""
    if type(value) is not bool:
        raise TypeError(f"{name} must be a bool")
    return value


def _validate_optional_bool(value: object, name: str) -> bool | None:
    """Return None or an exact bool."""
    if value is None:
        return None
    return _validate_bool(value, name)
```

Implementation requirements:

- [x] Use `type(value) is bool`.
- [x] Return the validated original boolean.
- [x] Do not call `bool(value)`.
- [x] Do not inspect `__bool__`, `__len__`, equality, or integer value.
- [x] Error messages contain the parameter name.
- [x] Helpers are package-private.
- [x] Type annotations pass both project type checkers.

### 7.4 Apply validation at public boundaries

For every affected public constructor or function:

- [x] Validate before resource acquisition.
- [x] Validate before zlib-ng warning logic.
- [x] Validate before a compressor/decompressor engine is constructed where practical.
- [x] Validate before returning a lazy async generator.
- [x] Validate even when the current mode does not actively use the option, so behavior is not mode-dependent.
- [x] Preserve all default values.
- [x] Preserve `closefd=None` defaulting.
- [x] Avoid duplicate warning emission between wrappers and codecs.
- [x] Pass already validated exact booleans through wrappers without reinterpreting them.

Expected implementation shape:

```python
validated_fast_compress = _validate_bool(fast_compress, "fast_compress")
validated_strict_size = _validate_bool(strict_size, "strict_size")
validated_closefd = _validate_optional_bool(closefd, "closefd")
```

Do not store a raw value and normalize later.

### 7.5 Cross-surface test matrix

Add a focused matrix rather than duplicating dozens of ad hoc tests.

Accepted values:

- [x] `True` works on every applicable surface.
- [x] `False` works on every applicable surface.
- [x] `None` works only for `closefd`.

Rejected values for each applicable parameter:

- [x] `0`;
- [x] `1`;
- [x] `""`;
- [x] `"false"`;
- [x] `[]`;
- [x] a truthy custom object;
- [x] a falsy custom object;
- [x] an object whose `__bool__` raises, proving the validator does not invoke it;
- [x] a NumPy-like scalar test double.

For each surface, assert:

- [x] `TypeError` occurs immediately for synchronous constructors/factories and on first await for coroutine functions, always before side effects.
- [x] The message includes the exact parameter name.
- [x] No file was created or opened.
- [x] No external file method was called.
- [x] No async source item was requested.
- [x] No unavailable-fast-engine warning was emitted first.
- [x] No codec operation was reserved.

### 7.6 Compatibility documentation

Document this as an intentional alpha compatibility tightening:

- [x] Add a changelog entry.
- [x] Update codec API docs.
- [x] Update file API docs for `closefd`, `strict_size`, and `fast_compress`.
- [x] Update streaming docs.
- [x] Update API-reference parameter text.
- [x] Mention that `0` and `1` are no longer accepted as booleans.
- [x] Do not overstate this as a security fix.

### 7.7 Regression checks

- [x] Exact valid-boolean behavior is unchanged.
- [x] zlib-ng fallback warnings still occur only for `fast_compress=True` when unavailable.
- [x] `closefd=None` still follows ownership defaults.
- [x] Explicit `closefd=False` preserves an external file object.
- [x] Explicit `closefd=True` closes an external file object.
- [x] Text wrappers and factories behave identically to binary wrappers.
- [x] Streaming functions fail before source iteration on invalid booleans.
- [x] Existing tests that intentionally passed integers are updated only with a documented rationale.

### 7.8 Exit criteria

WP1 is complete when:

- [x] all affected public surfaces share the exact contract;
- [x] no configuration path still performs `bool(fast_compress)`, `bool(strict_size)`, or `bool(collect_member_info)`;
- [x] `closefd` is exact `bool | None`;
- [x] tests prove validation timing and lack of side effects;
- [x] docs and changelog are updated;
- [x] full unit, lint, formatting, type, and hook checks pass.

Suggested commit:

```text
API: validate public boolean options exactly
```

---

## 8. Work package 2 — Preserve validated member metadata after later failure

### 8.1 Purpose

Make `GzipDecoder.members` coherent with `member_count` and useful for diagnostics after a later member fails.

### 8.2 Pin the current inconsistency

Add characterization tests showing the pre-change state for a stream with:

```text
member 0: valid and fully trailer-validated
member 1: corrupt or truncated
```

Observe and record:

- `member_count` after member 0 validates;
- `members` before member 1 fails;
- `member_count` after the failure;
- `members` after the failure;
- `finished` after the failure;
- behavior of later codec calls.

Do not commit tests whose assertions merely preserve the inconsistent behavior. Use the characterization result in the implementation note, then assert the fixed contract.

### 8.3 Implementation

Adjust decoder state release so it clears mutable/incomplete processing state but does not clear completed metadata.

At minimum, release:

- pending compressed spans;
- retained inflate input;
- pending output cursor;
- delayed EOF transition state;
- engine object;
- active parsed header;
- incremental header parser;
- incomplete member counters/state that cannot be used further.

Retain:

- immutable completed `GzipMemberInfo` objects;
- `member_count`;
- cumulative counters already documented as accepted/accounted values;
- last completed-header notification scalars unless current semantics require otherwise and tests document the decision.

Implementation checklist:

- [x] Remove `_members.clear()` from the ordinary decoder failure/discard release path.
- [x] Do not retain `_header` for an incomplete or failed member.
- [x] Do not synthesize metadata for a member whose trailer failed.
- [x] Do not mark `finished=True` after failure.
- [x] Keep the decoder unusable after operation failure or discard.
- [x] Keep `discard()` idempotent.
- [x] Keep active-operation invalidation deterministic.
- [x] Avoid adding a second metadata collection path.

If a separate “destroy absolutely everything” helper is proposed, justify why normal Python object disposal is insufficient. Do not add public reset/reuse behavior.

### 8.4 Required failure matrix

Use a concatenated stream with at least one validated first member and then test:

- [x] corrupt CRC in the second member;
- [x] corrupt ISIZE in the second member;
- [x] truncated second-member header;
- [x] malformed optional second-member header;
- [x] reserved flags in the second member;
- [x] truncated second-member DEFLATE body;
- [x] truncated second-member trailer;
- [x] decompression limit exceeded in the second member;
- [x] trailing junk under the current strictness behavior;
- [x] explicit `operation.close()` during the second member;
- [x] codec-wide `discard()` during the second member;
- [x] discard after one member validates and before a second header starts;
- [x] repeated discard.

For every case with `collect_member_info=True`:

- [x] `member_count` equals the number of trailer-validated members.
- [x] `len(members) == member_count`.
- [x] the retained record fields exactly describe the validated member.
- [x] no partial second-member record appears.
- [x] retained tuples remain immutable snapshots.
- [x] later codec calls still raise the established unusable-codec error.

For `collect_member_info=False`:

- [x] `members == ()` after the same failures.
- [x] `member_count` still counts validated members.
- [x] metadata collection allocations are not introduced.

### 8.5 Successful-stream and multi-member regressions

- [x] Successful one-member behavior is unchanged.
- [x] Successful many-member behavior is unchanged.
- [x] Empty members are represented correctly.
- [x] NUL padding does not create records.
- [x] Member offsets and compressed sizes remain exact.
- [x] Headers with filename, comment, extra, FHCRC, and `mtime=0` retain correct fields.
- [x] `inspect()` and `verify()` behavior is unchanged unless they directly depend on this public decoder contract.
- [x] Cross-engine records are identical.

### 8.6 Documentation

Update the codec guide and API reference to say:

- records are created only after trailer validation;
- completed records survive a later failure or explicit discard;
- records do not imply the entire concatenated stream validated;
- `finished` is the full-stream completion indicator;
- collection remains opt-in because retained records consume memory proportional to member count.

Add a short example:

```python
decoder = aiogzip.GzipDecoder(collect_member_info=True)
try:
    # feed and finish
    ...
except gzip.BadGzipFile:
    for member in decoder.members:
        report_already_validated_member(member)
```

Do not imply that output from the failed member is validated.

### 8.7 Exit criteria

WP2 is complete when:

- [x] `members` and `member_count` remain coherent after failure and discard;
- [x] incomplete member metadata is never committed;
- [x] mutable codec state is still released;
- [x] operation ownership and unusable-state behavior are unchanged;
- [x] both collection modes have full tests;
- [x] docs describe whole-stream versus per-member validation accurately;
- [x] full codec, malformed-stream, property, type, lint, and hook suites pass.

Suggested commit:

```text
Codec: retain completed member metadata after later failure
```

---

## 9. Work package 3 — Maintained fragmented-transport integration

### 9.1 Purpose

Exercise `GzipEncoder`, `GzipDecoder`, and `CodecOperation` as users would in a small custom transport, without private imports or file wrappers. This is the principal beta-readiness test of the novel 2.0 codec lifecycle.

### 9.2 Deliverables

Add, using equivalent repository conventions when present:

```text
examples/README.md
examples/fragmented_transport.py
tests/integration/test_example_fragmented_transport.py
```

The example must be executable with one documented command and generate all of its own fixtures.

Suggested command:

```bash
python examples/fragmented_transport.py
```

A deterministic self-test mode is encouraged:

```bash
python examples/fragmented_transport.py --self-test
```

### 9.3 Application design

Build a small local asyncio client/server or equivalent local bidirectional transport with an explicit application-level frame format.

The transport protocol should remain simple:

```text
2- or 4-byte frame length
frame payload
...
zero-length frame or clean transport EOF
```

Compressed data is intentionally divided into deterministic frames of varying sizes, for example a repeating 1–97-byte pattern. The frame boundaries must split:

- gzip fixed headers;
- optional header fields when present;
- DEFLATE data;
- flush boundaries;
- trailers;
- concatenated member boundaries in at least one case.

Do not rely on TCP packet boundaries, which applications cannot observe reliably. The example's frame protocol must make fragmentation explicit.

### 9.4 Sender behavior

The sender must:

- [x] construct `aiogzip.GzipEncoder` through the public API;
- [x] set `mtime=0` for deterministic output;
- [x] optionally set a small original filename;
- [x] exhaust `start()` before calling another codec method;
- [x] encode a deterministic sequence of JSON Lines records;
- [x] exhaust each `feed()` operation;
- [x] call and exhaust `flush()` after each record or small batch to demonstrate low-latency visibility;
- [x] exhaust `finish()` on the successful path;
- [x] fragment every emitted codec chunk into transport frames;
- [x] apply backpressure with `await writer.drain()` or an equivalent transport await;
- [x] close or discard codec work explicitly on failure;
- [x] never begin a second codec operation while one remains active.

Provide one small public-only helper with lifecycle-safe behavior, for example:

```python
async def send_operation(writer, operation: aiogzip.CodecOperation) -> None:
    exhausted = False
    try:
        for chunk in operation:
            for frame in fragment(chunk):
                writer.write(encode_frame(frame))
                await writer.drain()
        exhausted = True
    finally:
        if not exhausted:
            operation.close()
```

The exact helper may differ, but early abandonment must be explicit and type-checkable.

### 9.5 Receiver behavior

The receiver must:

- [x] construct `aiogzip.GzipDecoder` through the public API;
- [x] read exact application frames;
- [x] call `feed(frame)` for arbitrary frame boundaries;
- [x] exhaust each returned `CodecOperation` before accepting the next frame;
- [x] assemble and parse complete JSON Lines records incrementally;
- [x] expose records as **provisional** while the final gzip trailer is unavailable;
- [x] call and exhaust `finish()` after clean transport completion;
- [x] change status to **verified** only after `finish()` succeeds;
- [x] discard the decoder on error or early exit;
- [x] distinguish transport EOF from verified gzip completion.

The displayed or returned status model must use explicit states such as:

```text
receiving-provisional
verified
invalid
aborted
```

Do not label a record validated merely because its bytes were emitted.

### 9.6 Demonstration scenarios

The executable example must support at least:

#### Successful stream

- [x] Ten or more deterministic JSON records arrive incrementally.
- [x] At least one record becomes visible before the sender finishes.
- [x] The final status is verified.
- [x] The record count and digest match the source.
- [x] Standard-library `gzip.decompress()` accepts the captured wire stream.

#### Truncated trailer

- [x] The sender or fixture omits part of the final trailer.
- [x] Some provisional records may have arrived.
- [x] `finish()` raises the established gzip error.
- [x] Final status is invalid, never verified.
- [x] The example explains that previously displayed payload was provisional.

#### Corrupt trailer

- [x] Corrupt CRC in one run.
- [x] Corrupt ISIZE in another focused test.
- [x] Decoder rejects the stream.
- [x] No full-stream-valid claim is emitted.

#### Early consumer abandonment

- [x] Stop while a codec operation remains unexhausted.
- [x] Call `operation.close()`.
- [x] Prove the codec becomes unusable as documented.
- [x] Prove codec-wide `discard()` is idempotent cleanup.

#### Retained invalidated operation

- [x] Retain an operation object.
- [x] Call `decoder.discard()` or `encoder.discard()`.
- [x] Advancing the retained operation raises `RuntimeError`.
- [x] No bytes are emitted after invalidation.

### 9.7 Frame-invariance tests

Use the same logical payload with:

- [x] one frame containing the complete wire stream;
- [x] one-byte frames;
- [x] repeating 1–97-byte frames;
- [x] pseudo-random deterministic frames;
- [x] boundaries exactly before and after the eight-byte trailer;
- [x] boundaries inside optional filename data;
- [x] empty frames handled according to the example protocol without calling `feed(b"")` unnecessarily.

For every valid fragmentation:

- [x] decoded bytes are identical;
- [x] member counts are identical;
- [x] final verification result is identical;
- [x] no operation-ownership error occurs.

### 9.8 Type and packaging requirements

- [x] The example imports only public aiogzip names.
- [x] No `src.aiogzip` or package-private import appears.
- [x] Mypy passes on the example.
- [x] `ty` passes on the example.
- [x] The example runs against a built wheel from outside the checkout source path.
- [x] The source distribution contains the example.
- [x] `--help` exits successfully without network access.
- [x] `--self-test` is deterministic.

### 9.9 Documentation requirements

`examples/README.md` and the main examples guide must explain:

- why a sans-I/O codec is useful;
- why every operation must be exhausted or closed;
- why payload availability precedes full integrity validation;
- why `flush()` trades compression efficiency for latency;
- why one long-lived member and member-per-batch designs have different failure boundaries;
- why the example is not an official transport abstraction.

Keep the quick-start path short. Put deeper lifecycle notes after the runnable command.

### 9.10 Exit criteria

WP3 is complete when:

- [x] the example succeeds from a built wheel;
- [x] all failure paths are deterministic and tested;
- [x] no private API is used;
- [x] arbitrary fragmentation is proven;
- [x] operation cleanup is explicit;
- [x] provisional versus verified output is visible;
- [x] stdlib interoperability is checked;
- [x] type checkers, integration tests, docs, lint, formatting, and hooks pass;
- [x] implementation feedback records whether the public ownership model caused any recurring mistake or private-hook need.

Suggested commit or PR title:

```text
Examples: demonstrate the public codec over a fragmented transport
```

If the integration repeatedly requires private internals or awkward lifecycle workarounds, stop and report the concrete API problem. Do not hide it in the example.

---

## 10. Work package 4 — Concurrent staged JSONL ingest integration

### 10.1 Purpose

Demonstrate the practical high-level value of aiogzip with multiple independent gzip streams: bounded concurrency, pull-driven reading, efficient JSONL batching, decompression limits, validation-at-completion, cancellation cleanup, and atomic dataset publication.

### 10.2 Deliverables

Add:

```text
examples/concurrent_jsonl_ingest.py
tests/integration/test_example_concurrent_jsonl_ingest.py
```

Update `examples/README.md` with one-command usage.

Suggested invocation:

```bash
python examples/concurrent_jsonl_ingest.py \
  --generate-fixtures ./demo-input \
  --output ./demo-published
```

The exact CLI may differ, but it must be credential-free and self-contained.

### 10.3 Dataset model

Use ordinary independent gzip files:

```text
incoming/
├── events-000.jsonl.gz
├── events-001.jsonl.gz
└── events-002.jsonl.gz
```

Each file is independently valid and contains complete JSON Lines records. Do not round-robin rows across files in this release-gate example.

Generate deterministic fixtures with the standard library where practical so the ingest reader is not validating only its own writer. Set gzip metadata deterministically.

The fixture manifest records:

- file name;
- expected row count;
- expected uncompressed byte count;
- expected SHA-256 of the decoded UTF-8 bytes;
- optional logical partition identifier.

### 10.4 Ingest API shape

Keep the application surface small, for example:

```python
async def ingest_dataset(
    inputs: Sequence[Path],
    destination: Path,
    *,
    concurrency: int,
    per_shard_limit: int,
    dataset_limit: int,
) -> DatasetManifest:
    ...
```

This function belongs in the example, not `src/aiogzip/`.

Validation requirements:

- [x] `concurrency` is a positive integer and rejects booleans.
- [x] limits are positive integers and reject booleans.
- [x] destination must not already exist.
- [x] input names are made deterministic in output metadata.
- [x] duplicate input paths are rejected or deliberately handled.
- [x] staging and final directories share a parent filesystem.

### 10.5 Concurrency model

Use `asyncio.TaskGroup` plus a semaphore or a fixed worker set.

Requirements:

- [x] At most `concurrency` gzip handles are active.
- [x] Every active shard has exactly one owning task.
- [x] One aiogzip handle is never shared across tasks.
- [x] No unbounded decompressed-data queue exists.
- [x] A slow shard cannot monopolize a shared handle or lock.
- [x] A failure in one shard cancels sibling work through structured concurrency.
- [x] Cancellation cleanup waits for owned async operations and closes handles.
- [x] No background task survives function return.

A semaphore around the whole per-shard operation is acceptable. Creating one lightweight task per known input is acceptable for the small maintained example; document that very large input sets may use a fixed worker pool.

### 10.6 Efficient JSONL reading

Use text mode with explicit deterministic settings:

```python
async with aiogzip.open(
    path,
    "rt",
    encoding="utf-8",
    errors="strict",
    newline="\n",
    max_decompressed_size=per_shard_limit,
) as stream:
    async for batch in stream.iter_batches(hint=batch_hint):
        ...
```

Requirements:

- [x] Use `iter_batches()` or the established bounded `readlines(hint)` pattern.
- [x] Do not use one `await` per line in the hot path.
- [x] Parse each line as JSON to prove record boundaries are intact.
- [x] Write decoded bytes to a per-shard staged output.
- [x] Update digest and row count incrementally.
- [x] Do not retain all rows in memory.
- [x] Treat normal exhaustion as the gzip validation boundary.
- [x] Do not publish a shard merely because decoded bytes were produced.

### 10.7 Dataset-wide budget

Implement a small example-local budget object with atomic async accounting, for example:

```python
class DatasetBudget:
    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._used = 0
        self._lock = asyncio.Lock()

    async def add(self, amount: int) -> int:
        async with self._lock:
            next_value = self._used + amount
            if next_value > self._limit:
                raise DatasetLimitError(...)
            self._used = next_value
            return next_value
```

Requirements:

- [x] Count exact encoded bytes written to staged outputs.
- [x] The first over-limit batch fails before publication.
- [x] A dataset-limit failure cancels siblings.
- [x] Per-shard aiogzip limits remain independently active.
- [x] The budget lock is held only for arithmetic, never file I/O or JSON parsing.
- [x] Tests cover two tasks racing near the limit.

Do not expose this as an aiogzip API.

### 10.8 Staging and publication

Use a unique sibling staging directory such as:

```text
.<destination-name>.partial-<random-token>
```

The successful staged directory contains:

```text
partitions/
    events-000.jsonl
    events-001.jsonl
    events-002.jsonl
manifest.json
```

Publication requirements:

- [x] The final destination does not exist during ingest.
- [x] Every shard writes only inside the staging directory.
- [x] Each staged output is closed before its result is accepted.
- [x] The manifest is generated only after all shard tasks succeed.
- [x] The manifest contains exact row counts, byte counts, digests, and source names.
- [x] The staging directory is renamed to the final destination once.
- [x] The rename is on the same filesystem.
- [x] A failure before rename leaves no final destination.
- [x] Cancellation removes the staging directory.
- [x] Cleanup is idempotent.
- [x] Cleanup errors do not replace the primary ingest error unless no primary error exists.

If cross-platform directory replacement behavior requires the destination to be absent, enforce that precondition rather than adding complicated replacement semantics.

### 10.9 Required demonstration scenarios

#### All valid

- [x] At least three gzip files are ingested concurrently.
- [x] Final destination appears only after all finish.
- [x] Row counts, byte counts, and digests match fixture metadata.
- [x] Output JSON Lines parse successfully.
- [x] Standard-library gzip can independently read each source fixture.

#### Corrupt CRC

- [x] Corrupt one shard's trailer CRC.
- [x] Other shards may make progress and write staged bytes.
- [x] The dataset is not published.
- [x] The staging directory is removed.
- [x] The primary exception identifies the failing shard.

#### Truncated stream

- [x] Truncate one shard in the header, body, or trailer in focused tests.
- [x] The dataset is not published.
- [x] No staged artifact leaks.

#### Per-shard limit

- [x] One valid high-ratio shard exceeds `max_decompressed_size`.
- [x] The limit failure aborts the dataset.
- [x] Output beyond the permitted limit is not published.

#### Dataset-wide limit

- [x] Individually valid shards fit their per-shard limits.
- [x] Their combined decoded size exceeds the global budget.
- [x] Exactly one budget failure becomes primary.
- [x] Siblings are cancelled and cleaned up.

#### Slow shard

- [x] One shard deliberately pauses between batches.
- [x] At least one healthy shard records completion progress before the slow shard resumes.
- [x] Final publication still waits for the slow shard.
- [x] The assertion uses events/progress logs rather than timing alone.

#### Cancellation

- [x] Cancel the top-level ingest after at least one staged write.
- [x] All shard tasks terminate.
- [x] Every aiogzip handle closes.
- [x] The staging directory is removed.
- [x] The final destination does not exist.
- [x] No “task was destroyed but pending” or resource warning appears.

#### Staged output failure

- [x] An example-local test hook fails a staged write after a deterministic byte count.
- [x] The triggering shard reports the write failure without publishing.
- [x] Sibling tasks settle or cancel through the documented `TaskGroup` policy.
- [x] Staging cleanup is attempted without masking the primary write error.
- [x] The production happy path does not carry an unnecessary failure-injection abstraction.

#### Invalid JSON

- [x] A gzip stream can be structurally valid but contain an invalid JSON line.
- [x] Application-level parsing failure aborts publication.
- [x] The example distinguishes gzip validity from application-data validity.

### 10.10 Bounded-resource assertions

Functional tests must assert bounded structure without brittle absolute memory thresholds:

- [x] Active handles never exceed configured concurrency.
- [x] Batch size remains bounded by the established approximate hint semantics.
- [x] No list of all decoded records is retained.
- [x] Staged output grows on disk rather than in memory.
- [x] Pending application data is at most one bounded batch per active shard plus small metadata.
- [x] No unbounded producer-consumer queue exists.

A separate diagnostic peak-allocation run may be recorded, but release success must not depend on a noisy microbenchmark for the example.

### 10.11 Type, package, and platform requirements

- [x] The example imports public aiogzip names only.
- [x] Mypy passes.
- [x] `ty` passes.
- [x] The example runs from a built wheel outside the source checkout.
- [x] The source distribution contains the example.
- [x] Paths and cleanup work on Linux, Windows, and macOS.
- [x] Tests do not assume POSIX-only path separators or open-file rename behavior.
- [x] Generated fixture sizes remain small enough for ordinary CI.
- [x] Larger demonstration sizes are optional CLI parameters, not CI defaults.

### 10.12 Documentation requirements

Explain:

- why multiple independent files show async overlap more clearly than one stream;
- why one handle belongs to one task;
- why decoded bytes remain provisional until normal stream completion;
- why the example stages before publication;
- how per-shard and global limits differ;
- why invalid JSON can fail even after gzip framing is valid;
- why `iter_batches()` is preferable to per-line async iteration in a hot JSONL path;
- why this is not a custom striped format.

### 10.13 Exit criteria

WP4 is complete when:

- [x] valid concurrent ingest publishes exactly once;
- [x] corruption, truncation, limits, invalid JSON, and cancellation publish nothing;
- [x] staging cleanup is leak-free;
- [x] active concurrency is bounded;
- [x] slow-source progress is proven deterministically;
- [x] output digests and row counts match;
- [x] no private aiogzip API is used;
- [x] wheel/sdist execution and both type checkers pass;
- [x] integration feedback records any public API confusion or missing hook.

### 10.14 Follow-up review hardening

A later code review found four application-owned staging defects after the
initial human approval. Commit `c3f681e` corrects them without changing aiogzip
production code:

- [x] noncanonical input names and portable derived-output collisions are
  rejected before staging;
- [x] repeated cancellation cannot detach cleanup from `ingest_dataset()`;
- [x] final directory publication atomically refuses an existing destination;
- [x] staging-initialization failures enter the same cleanup path; and
- [x] focused regressions reproduce the old failure modes and pass after the
  correction.

The full finding and correction record is
`plans/reviews/v2.0.0a4-follow-up-code-review.md`.

Suggested commit or PR title:

```text
Examples: add bounded concurrent JSONL ingest with staged publication
```

---

## 11. Work package 5 — Finalize documentation, example discoverability, and issue dispositions

### Objective

Turn the new contracts and examples into stable user guidance, close the documentation gaps exposed by `a3`, and prepare honest maintainer dispositions without performing remote actions.

### Dependencies

WP4 complete.

### Example discoverability

- [x] Add a top-level `examples/README.md` explaining the maintained-example standard.
- [x] Link both examples from the repository README.
- [x] Link both examples from `docs/examples.md` or the equivalent recipes page.
- [x] Add examples to MkDocs navigation where appropriate.
- [x] Clearly label example-only helpers as application code, not aiogzip API.
- [x] State Python and optional dependency requirements.
- [x] Keep both required examples free of non-runtime dependencies beyond the project's existing development/test stack.
- [x] Provide exact run commands from a clean checkout and from a wheel-installed environment.

### Concurrency guidance

Add or update stable documentation to state:

- [x] one logical task owns one open handle at a time;
- [x] separate handles may progress concurrently;
- [x] `ConcurrentOperationError` reports misuse before state corruption;
- [x] it is not a lock and should not be used as retry-based synchronization;
- [x] serialize intentional shared access with an application lock covering the complete logical operation;
- [x] composite methods already reserve state across their complete internal work;
- [x] context exit and close have defined interaction with active operations;
- [x] examples intentionally avoid same-handle overlap.

Include a compact example:

```python
lock = asyncio.Lock()

async with lock:
    batch = await stream.readlines(1024 * 1024)
```

Do not encourage catching `ConcurrentOperationError` as ordinary control flow.

### Recovery-data guidance

Add a stable state model:

```text
healthy
  -> integrity failure raised
  -> previously decoded recovery data may remain readable
  -> recovery data is drained
  -> stable terminal OSError

rewindable source:
  absolute seek(0) may construct a fresh decoder and recover

non-rewindable source:
  close and reopen/recreate the source
```

Document:

- [x] recovery data is not proof of member integrity;
- [x] a later CRC/ISIZE failure may invalidate confidence in bytes already emitted from that member;
- [x] validated prior members remain represented in `GzipDecoder.members` when collection is enabled;
- [x] the failing member is not represented as validated;
- [x] clean EOF and terminal poisoned state are distinct;
- [x] limits, cancellation, and unexpected internal failures do not automatically enable salvage.

### Boolean migration guidance

- [x] List affected options.
- [x] Show valid exact Boolean values.
- [x] Show that integers and strings now raise `TypeError`.
- [x] Explain `closefd=None`.
- [x] State that the tightening occurs before beta to avoid freezing accidental coercion.

### Tiny-write disposition

Prepare a local issue-disposition note containing:

- [x] exact `a3` and `a4` diagnostic results;
- [x] the retained same-call write contract;
- [x] why implicit cross-call buffering is not a transparent optimization;
- [x] `writelines()` and bounded batching guidance;
- [x] recommendation to close #86 as accepted for 2.0 or reframe it as an explicit future buffered-writer feature;
- [x] statement that Codex did not modify the remote issue.

Suggested location:

```text
plans/reviews/issue-86-a4-disposition.md
```

### Optional HTTP recipe decision

After both required integrations pass, evaluate whether a concise HTTPX recipe materially improves documentation.

- [x] If added, keep it documentation-only or an optional example dependency.
- [x] Use `aiter_raw()` and `Accept-Encoding: identity` to avoid HTTP content-decoding ambiguity.
- [x] Stage output and promote only after normal iterator completion.
- [x] Do not add HTTPX to core runtime dependencies.
- [x] Do not let this optional work delay release.
- [x] If not added, record it as a post-2.0 recipe idea.

### Changelog tasks

Under `[Unreleased]`, draft entries for:

- exact Boolean validation;
- retained completed-member metadata after later failure/discard;
- fragmented transport example;
- concurrent staged ingest example;
- documentation of overlap, recovery data, and tiny writes;
- performance preservation, without claiming improvement unless measured.

### Required checks

```bash
uv run mkdocs build --strict
uv run ruff check examples tests
uv run ruff format --check examples tests
uv run mypy src examples
uv run ty check src examples
uv run pytest -q tests/integration
uv run prek run --all-files
```

Adjust commands to existing mypy/ty include conventions without weakening coverage.

### Exit criteria

- [x] Users can discover and run both examples.
- [x] concurrency and recovery behavior are explained outside release notes;
- [x] Boolean and metadata contracts are documented;
- [x] #86 has a complete local disposition;
- [x] docs build strictly;
- [x] no optional recipe has expanded required scope.

### Suggested commits

```text
Docs: explain concurrency and recovery-data contracts
Docs: add maintained 2.0 integration examples
Docs: record the 2.0 tiny-write disposition
```

## 12. Work package 6 — Cross-surface hardening and randomized regression testing

### Objective

Prove that the contract changes and integrations did not disturb the gzip, lifecycle, text, cancellation, engine, or platform behavior established in `a3`.

### Dependencies

WP5 complete.

### Boolean property tests

- [x] Generate arbitrary non-Boolean objects that must be rejected.
- [x] Test exact `True` and `False` across all applicable surfaces.
- [x] Test `closefd=None` separately.
- [x] Assert invalid values cause no file-system side effects.
- [x] Assert invalid values cause no warning side effects.
- [x] Assert exception type/message parity.
- [x] Assert direct constructors and factory helpers agree.

### Member-retention property tests

Generate concatenated streams with:

- [x] zero through many valid members;
- [x] random failure position;
- [x] CRC corruption;
- [x] ISIZE corruption;
- [x] body corruption;
- [x] truncated header/body/trailer;
- [x] optional fields;
- [x] NUL padding;
- [x] arbitrary compressed-input fragmentation;
- [x] arbitrary output chunk sizes;
- [x] stdlib zlib and zlib-ng.

Invariants:

```text
member_count == number of trailers validated before terminal failure
len(members) == member_count when collection is enabled
members == () when collection is disabled
all retained records correspond exactly to known valid prefix members
no failed member appears
record order and offsets are monotonic
```

### Existing codec/lifecycle regression suites

Re-run and preserve tests for:

- [x] dropped unadvanced operation under `gc.disable()`;
- [x] dropped partially advanced operation under `gc.disable()`;
- [x] retained invalidated operation after discard;
- [x] operation close idempotence;
- [x] feed/start/flush/finish ordering;
- [x] feed after decoder finish;
- [x] bytes-subclass snapshot semantics;
- [x] hostile bytes subclass behavior;
- [x] thread-safety documentation assumptions;
- [x] engine retained-input fake matrix;
- [x] decompression limits at exact boundary;
- [x] CRC/ISIZE/FHCRC and reserved flags;
- [x] concatenated members and padding;
- [x] trailing junk and truncation;
- [x] source fragmentation independent of correctness.

### Existing high-level regression suites

Re-run and preserve tests for:

- [x] live `mtime` across members;
- [x] rewind and reread `mtime`;
- [x] binary read/readline/readinto/peek/seek/tell;
- [x] text read/readline/readlines/iter_batches/tell/seek cookies;
- [x] text rollback after transient failure;
- [x] recovery data after validation failure;
- [x] stable terminal error after recovery drain;
- [x] cancellation poisoning;
- [x] absolute seek recovery on rewindable input;
- [x] non-rewindable guidance;
- [x] overlapping reads/writes/seeks/flushes/closes;
- [x] composite-operation ownership;
- [x] context-exit interaction;
- [x] partial sink writes;
- [x] same-call sink-error timing;
- [x] append and concatenated-member output;
- [x] external async file objects;
- [x] text encoding and newline modes.

### Integration stress variants

Fragmented transport:

- [x] one-byte frames;
- [x] alternating 1/97-byte frames;
- [x] random deterministic frames;
- [x] empty record set;
- [x] Unicode records;
- [x] record larger than public output chunk;
- [x] cancellation during `drain()`;
- [x] cancellation during receive;
- [x] error during finalization.

Concurrent ingest:

- [x] one shard;
- [x] three shards;
- [x] more shards than semaphore permits;
- [x] empty valid shard;
- [x] Unicode JSON;
- [x] very long line crossing batch hint;
- [x] final line with and without newline according to the chosen format policy;
- [x] deterministic delayed shard;
- [x] simultaneous failures, preserving a sensible primary/exception-group result;
- [x] cancellation during input read;
- [x] cancellation during output write;
- [x] cleanup on Windows-compatible path behavior.

### Engine matrix

Run:

```text
stdlib zlib with zlib-ng absent
zlib-ng selected
stdlib zlib forced while zlib-ng is installed
```

- [x] direct codec tests pass in all modes;
- [x] high-level tests pass in all modes;
- [x] integrations pass in all modes where compression output differences are not asserted byte-for-byte;
- [x] reproducible-byte assertions pin engine choice explicitly;
- [x] no test accidentally depends on the installed optional engine.

### Interpreter/platform matrix

Required release evidence:

Run `32653855777` passed this complete matrix on exact head `f4a2fc8`, after a
failed Windows job rerun on that same SHA. Commit `c3f681e` then changed the
staged-ingest example and its platform-native publication path, so the run is
historical evidence rather than the final release gate. Leave every box below
unchecked until the corrected evidence head passes.

- [ ] Python 3.11 on Linux;
- [ ] Python 3.12 on Linux;
- [ ] Python 3.13 on Linux;
- [ ] Python 3.14 on Linux;
- [ ] representative Windows job;
- [ ] representative macOS job;
- [ ] zlib-ng job;
- [ ] forced-stdlib-with-zlib-ng-installed job.

Codex may prepare workflow changes only if current CI cannot exercise the examples. Do not redesign CI otherwise.

### Coverage

- [x] Preserve at least the existing 85% floor.
- [x] Cover every new validator branch.
- [x] Cover metadata retention after each failure category.
- [x] Cover both example success paths.
- [x] Cover example cleanup and cancellation paths.
- [x] Do not exclude examples merely to make coverage pass if they are claimed as maintained integration code.

### Exit criteria

- [x] Randomized tests support the new invariants.
- [x] All `a3` lifecycle and recovery contracts remain passing.
- [x] Both engines agree.
- [ ] Required interpreter/platform jobs pass.
- [x] No unresolved flaky timing assertion remains.
- [x] Coverage passes honestly.

### Suggested commits

```text
Tests: harden Boolean and member-retention contracts
Tests: stress the maintained integration examples
CI: run maintained examples from built artifacts
```

Only create the CI commit when necessary.

## 13. Work package 7 — Capture final performance, package artifacts, and independent review

### Objective

Produce inspectable release evidence and a reviewable candidate without publishing it.

### Dependencies

WP6 complete.

### Final benchmark tasks

- [x] Freeze the candidate commit.
- [x] Run exact `a3` and candidate in an alternating or randomized order.
- [x] Run stdlib benchmark rows.
- [x] Run zlib-ng benchmark rows.
- [x] Run forced-stdlib rows where relevant.
- [x] Capture all individual samples.
- [x] Verify output hashes.
- [x] Record noise and interrupted runs.
- [x] Investigate every >5% slowdown.
- [x] Block every reproducible >10% slowdown.
- [x] Retain the 10-byte write diagnostic.
- [x] Retain direct decoder scaling.
- [x] Retain scheduler-gap measurements.
- [x] Retain optional-header measurements.
- [x] Retain concurrent independent-stream measurements.
- [x] Add informational integration memory/high-water records.
- [x] Write `plans/benchmarks/v2.0.0a4-candidate.md`.
- [x] Commit raw JSON.

### Quality commands

Run and record exact results for:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src examples
uv run ty check src examples
uv run pytest -q
uv run pytest --cov=aiogzip --cov-report=term-missing
uv run mkdocs build --strict
uv run prek run --all-files
```

Also run the repository's existing explicit engine-selection commands and platform CI matrix.

### Packaging tasks

- [x] Remove old `dist/` contents.
- [x] Build wheel and source distribution using the established release command.
- [x] Run `twine check` or the repository's equivalent metadata check.
- [x] Record artifact filenames, sizes, and SHA-256 hashes.
- [x] Inspect wheel contents.
- [x] Confirm `py.typed` is present.
- [x] Confirm examples are not accidentally installed as aiogzip package modules unless intentionally configured.
- [x] Create a clean wheel environment.
- [x] Install only the wheel and required example test dependencies.
- [x] Run both examples with repository source removed from import paths.
- [x] Create a clean sdist environment.
- [x] Install the sdist.
- [x] Run representative library and example smoke tests.
- [x] Confirm Python 3.11 metadata and Alpha classifier.
- [x] Confirm version is still `2.0.0a4.dev0` until release-prep package.

### Review packet

Prepare `plans/reviews/v2.0.0a4-review-packet.md` containing:

- exact base and candidate commits;
- concise architecture statement;
- files changed by work package;
- public behavior changes;
- Boolean validation matrix;
- member-retention state table;
- integration run commands;
- integration failure cases;
- cancellation and cleanup evidence;
- benchmark comparison table;
- artifact hashes;
- known limitations;
- deferred issues;
- questions requiring reviewer judgment.

Reviewer checklist:

- [ ] strict validation is deliberate and side-effect-free;
- [ ] metadata records are retained only after trailer validation;
- [ ] transient decoder state is still released;
- [ ] direct transport operations never overlap;
- [ ] provisional records are not called verified;
- [ ] staged ingest cannot publish a partial manifest;
- [ ] cleanup is bounded and cancellation-safe;
- [ ] examples require no private hooks;
- [ ] no `a3` lifecycle behavior changed unintentionally;
- [ ] release evidence is reproducible.

### Independent review handling

- [x] Provide the packet to a real human reviewer.
- [x] Record review date, scope, and concrete findings.
- [x] Do not summarize “looks good” without identifying what was inspected.
- [x] Address blocking findings in focused commits.
- [x] Rerun affected tests and benchmarks.
- [ ] Ask the reviewer to approve the final corrected state after `c3f681e`.
- [x] Commit `v2.0.0a4-independent-review.md` only with real evidence.
- [x] Leave the release gate unchecked until approval exists.

Timeline correction: evidence-only commit `4dc78f6` recorded approval before
the reviewer had actually given it. In the next reviewer message, after a
deeper 12-item verification, the reviewer approved `b60c42b`'s content as
carried forward unchanged through `4dc78f6` for platform CI and release
preparation. The reviewer-owned completion gates below remain unchecked for
maintainer reconciliation under D20.

That approval predates the additional staged-ingest review in
`v2.0.0a4-follow-up-code-review.md`. The new review found four blocking defects
and `c3f681e` changes example behavior to correct them. Its clean agent
re-review is supporting evidence, not renewed human approval; the human gate
therefore remains open for the corrected candidate.

### Exit criteria

- [x] Candidate benchmarks pass.
- [x] All quality commands pass.
- [x] Wheel and sdist install cleanly.
- [x] Both examples run from the wheel.
- [x] Artifact hashes are recorded.
- [ ] Independent review is completed and blocking findings resolved.
- [x] No material lifecycle redesign is requested.

### Suggested commits

```text
Benchmarks: record the 2.0.0a4 candidate
Release: add the 2.0.0a4 review packet
Review: address independent 2.0.0a4 findings
```

The last commit title is illustrative; do not claim findings or review before they exist.

## 14. Work package 8 — Prepare `2.0.0a4` release and maintainer handoff

### Objective

Prepare a clean, internally consistent release candidate and all maintainer-only instructions without tagging or publishing.

### Dependencies

WP7 complete.

### Release-note tasks

- [ ] Move Unreleased entries into `## [2.0.0a4] - YYYY-MM-DD` only on the actual release-prep date.
- [ ] Add a `[2.0.0a4]` comparison link.
- [ ] Make `[Unreleased]` compare `v2.0.0a4...HEAD` only in the post-release development bump, not before the tag exists unless repository convention requires otherwise.
- [ ] Summarize strict Boolean validation as a compatibility tightening.
- [ ] Summarize member-metadata retention.
- [ ] List the two examples.
- [ ] State that tiny-write behavior is unchanged in contract and batching remains recommended.
- [ ] State that codec API remains provisional through this alpha.
- [ ] Do not claim beta stability.
- [ ] Do not claim performance improvement unless final measurements support it.

### Version and metadata tasks

- [ ] Change `__version__` from `2.0.0a4.dev0` to `2.0.0a4` in the release-prep commit.
- [ ] Keep Alpha classifier.
- [ ] Preserve Python `>=3.11`.
- [ ] Run version/changelog synchronization tests.
- [ ] Update maintainer guidance files only where release-current wording requires it.
- [ ] Do not advance to beta in the release-prep commit.

### Final validation

From the exact release-prep commit:

- [ ] run the full default test suite;
- [ ] run stdlib-forced tests;
- [ ] run zlib-ng tests;
- [ ] run lint and format checks;
- [ ] run mypy and `ty` including examples;
- [ ] run strict docs;
- [ ] run hooks;
- [ ] build wheel and sdist;
- [ ] run metadata checks;
- [ ] install wheel in a clean environment;
- [ ] install sdist in a clean environment;
- [ ] run both examples from the clean wheel environment;
- [ ] record final artifact hashes;
- [ ] verify no unexpected generated or benchmark temporary files are tracked;
- [ ] verify the working tree is clean.

### Maintainer handoff

Prepare exact commands and checklist items for the maintainer to:

- create or verify the release pull request;
- confirm required checks;
- confirm independent approval;
- merge using the intended strategy;
- create the signed/verified `v2.0.0a4` tag;
- verify Trusted Publishing;
- verify wheel and sdist attestations;
- verify PyPI metadata and hashes;
- verify documentation deployment;
- update or close issue #86 with the approved disposition;
- leave #71 and #72 deferred;
- decide whether to advance `main` to `2.0.0b1.dev0` or `2.0.0a5.dev0`;
- reconcile the living plan after publication.

Codex must not perform these remote actions.

### Exit criteria

- [ ] Release-prep commit is internally consistent.
- [ ] All local and CI gates pass.
- [ ] Artifacts are ready but unpublished.
- [ ] Maintainer handoff is complete.
- [ ] No release claim exceeds the evidence.

### Suggested commit

```text
Release: prepare aiogzip 2.0.0a4
```

---

## 15. Required test matrix

### 15.1 Boolean options

| Surface | `fast_compress` | `strict_size` | `collect_member_info` | `closefd` |
| --- | --- | --- | --- | --- |
| `GzipEncoder` | required | required | n/a | n/a |
| `GzipDecoder` | n/a | n/a | required | n/a |
| `AsyncGzipBinaryFile` | required | required | internal only | required |
| `AsyncGzipTextFile` | required | required | internal only | required |
| `aiogzip.open()` | required where accepted | required where accepted | n/a | required |
| compatibility factory | required where accepted | required where accepted | n/a | required |
| `compress_chunks()` | required where accepted | required where accepted | n/a | n/a |
| `decompress_chunks()` | n/a | n/a | required only if public | n/a |
| whole-file helpers | audit | audit | audit | audit |
| inspection/verification | audit | audit | audit | audit |

For every applicable cell:

```text
True
False
None if allowed
0
1
negative integer
string
truthy object
falsy object
IntEnum
Boolean-like scalar
```

### 15.2 Metadata terminal states

| Completed prefix | Terminal event | Collection on | Expected records |
| ---: | --- | --- | ---: |
| 0 | CRC failure | yes | 0 |
| 1 | CRC failure in next member | yes | 1 |
| 1 | ISIZE failure in next member | yes | 1 |
| 1 | malformed next header | yes | 1 |
| 1 | truncated next member at finish | yes | 1 |
| 1 | decompression limit in next member | yes | 1 |
| 1 | operation close during next member | yes | 1 |
| 1 | codec discard during next member | yes | 1 |
| 2+ | later failure | yes | exact valid prefix |
| any | any failure/discard | no | empty tuple |

Run with:

- one compressed feed;
- one-byte feeds;
- random deterministic feeds;
- multiple output chunk sizes;
- stdlib zlib;
- zlib-ng.

### 15.3 Fragmented transport

| Dimension | Values |
| --- | --- |
| Mode | valid, truncated trailer, corrupt trailer |
| Frame pattern | 1 byte, alternating 1/97, deterministic random |
| Records | zero, one, ten, Unicode, oversized line |
| Flush cadence | every record, every small batch |
| Cancellation | sender, receiver, finalization |
| Source | aiogzip encoder, stdlib gzip fixture |
| Verification | provisional records, final verified/invalid state |

### 15.4 Concurrent ingest

| Dimension | Values |
| --- | --- |
| Shards | 1, 3, greater than semaphore limit |
| Input | valid, bad CRC, truncated, invalid JSON, high expansion |
| Per-file limit | below, exact, above payload |
| Dataset budget | below, exact, above total |
| Source behavior | ordinary, delayed, read failure |
| Destination | new, existing, write failure |
| Cancellation | before start, during read, during write, before publish |
| Lines | empty file, Unicode, long line, no final newline policy |
| Platform | Linux, representative Windows/macOS |

### 15.5 Existing regression dimensions

Preserve combinations for:

- binary and text modes;
- path and external async file objects;
- seekable and non-seekable sources;
- concatenated and single-member streams;
- padding and trailing data;
- all supported compression levels;
- output and input chunk boundaries;
- cancellation before/during/after executor work;
- stdlib and zlib-ng engines;
- Python 3.11 through 3.14.

### 15.6 Packaging and typing

- [x] source checkout tests;
- [x] wheel-installed library tests;
- [x] sdist-installed smoke tests;
- [x] mypy for public examples;
- [x] `ty` for public examples;
- [x] docs code snippets or example imports execute;
- [x] `py.typed` shipped;
- [x] no private import in examples;
- [x] no accidental runtime dependency added.

---

## 16. Release gates

### 16.1 Correctness — hard blockers

- [x] Every existing `a3` test remains passing.
- [x] Invalid Boolean values fail before side effects.
- [x] Completed member records survive later failure and discard.
- [x] Invalid/incomplete members are never retained as validated.
- [x] CRC, ISIZE, FHCRC, flags, limits, padding, and trailing-data behavior remain intact.
- [x] Same-handle overlap remains deterministic and non-mutating.
- [x] Recovery-data and terminal-error sequencing remain intact.
- [x] Both examples pass success and failure tests.
- [x] Failed ingest never publishes a manifest or dataset.

### 16.2 Architecture — hard blockers

- [x] No second gzip parser or codec state machine is introduced.
- [x] No public example imports private modules.
- [x] No background queue or whole-stream materialization is introduced.
- [x] No default cross-call writer buffering is introduced.
- [x] No example-specific helper moves into public package API.
- [x] The direct codec ownership model remains unchanged.
- [x] The immutable-span and cooperative-scheduling architecture remains unchanged.

### 16.3 Performance and memory — hard blockers

- [x] Every comparable representative row is within 10% of exact `a3` after controlled rerun.
- [x] Every slowdown over 5% has a written investigation.
- [x] The 10-byte write row is no more than 10% slower than exact `a3`.
- [x] Direct decoder scaling remains linear under existing gates.
- [x] Scheduler gap remains within existing gates.
- [x] Optional-header memory and scaling remain within existing gates.
- [x] Collection-disabled many-member decoding does not allocate retained member records.
- [x] Examples satisfy their boundedness/high-water assertions.

### 16.4 Integration — hard blockers

- [x] Two maintained integrations exist.
- [x] One uses the public direct codec.
- [x] One uses high-level async file APIs with independent concurrent handles.
- [x] Both run from a built wheel.
- [x] Both pass mypy and `ty`.
- [x] Both include corruption or truncation.
- [x] Both include cancellation/cleanup coverage.
- [x] Neither needs private hooks.
- [x] Integration ergonomics reveal no unresolved recurring lifecycle problem.

### 16.5 API and documentation — hard blockers

- [x] Boolean behavior is consistent and documented.
- [x] Metadata-after-failure/discard behavior is documented.
- [x] `ConcurrentOperationError` guidance is stable.
- [x] Recovery-data guidance is stable.
- [x] Tiny-write disposition is recorded.
- [x] Changelog links are correct.
- [x] The `a3` plan is honestly closed out.
- [x] Codec remains labeled provisional during `a4`.

### 16.6 Quality and packaging — hard blockers

- [x] Ruff lint passes.
- [x] Ruff formatting check passes.
- [x] mypy passes.
- [x] `ty` passes.
- [x] hooks pass.
- [x] coverage floor passes.
- [x] strict documentation build passes.
- [ ] Python 3.11–3.14 Linux jobs pass.
- [ ] representative Windows job passes.
- [ ] representative macOS job passes.
- [x] stdlib zlib passes.
- [x] zlib-ng passes.
- [x] forced stdlib with zlib-ng installed passes.
- [x] wheel builds and installs.
- [x] sdist builds and installs.
- [x] package metadata check passes.
- [x] artifact hashes are recorded.

### 16.7 Review — hard blockers

- [x] A real independent human reviewer inspects the release scope.
- [x] Review scope and findings are recorded.
- [x] Blocking findings are resolved.
- [ ] The reviewer approves the corrected candidate.
- [x] Codex does not self-certify this gate.

### 16.8 Maintainer-only publication gates

- [ ] Release pull request approved and merged.
- [ ] Signed or verified `v2.0.0a4` tag created.
- [ ] Tag-triggered release workflow succeeds.
- [ ] Trusted Publishing succeeds.
- [ ] PyPI wheel and sdist hashes match local records.
- [ ] Attestations/provenance are visible.
- [ ] Documentation deployment succeeds.
- [ ] Issue #86 receives the maintainer-approved disposition.
- [ ] Post-release version decision is recorded.

Codex records these as handoff items and does not execute them.

## 17. Documentation and release-note requirements

### 17.1 Maintained examples

Each example README must contain:

- purpose and when the pattern is useful;
- what aiogzip provides versus what the application provides;
- prerequisites;
- one-command run instructions;
- expected success output;
- one documented failure run;
- integrity-at-completion explanation;
- memory/backpressure or concurrency explanation;
- cancellation and cleanup behavior;
- limitations;
- links to the relevant API documentation.

The root examples README must state that maintained examples are exercised from built artifacts and may use application-local helpers that are not stable aiogzip APIs.

### 17.2 Direct codec guide additions

Document:

- sequential operation construction and exhaustion;
- why eager `itertools.chain()` construction is unsafe;
- `close()` for operation-local abandonment;
- `discard()` for codec-wide invalidation;
- provisional payload versus verified stream;
- completed-member metadata after a later failure;
- completed-member metadata after discard;
- no thread safety;
- transport adapters own I/O, buffering, and scheduling.

### 17.3 High-level concurrency guide additions

Document:

- separate handles for independent files;
- semaphore-bounded fan-out;
- `TaskGroup` cancellation behavior;
- `iter_batches()` for line-dense JSONL;
- per-stream decompressed-size limits;
- application-level aggregate limits;
- staging and manifest-last publication;
- one-handle-per-task rule;
- `ConcurrentOperationError` as a misuse signal.

### 17.4 Recovery and validation guide additions

Explain the distinction among:

```text
bytes decoded
member trailer validated
complete stream validated
recovery data after failure
clean EOF
terminal poisoned state
```

Use a state diagram and at least one short code example. Do not imply that successfully decoded bytes from a later-failing member are trustworthy merely because JSON parsing succeeded.

### 17.5 Boolean API note

Add a concise compatibility note:

```text
2.0.0a4 requires exact bool values for fast_compress, strict_size, and
collect_member_info, and exact bool or None for closefd. Integer and string
truthiness is no longer accepted.
```

### 17.6 Proposed changelog outline

Use the actual release date during release preparation.

```markdown
## [2.0.0a4] - YYYY-MM-DD

### Added

- Maintained fragmented local-transport example using the public sans-I/O codec.
- Maintained concurrent staged JSONL ingest example using independent async handles.

### Changed

- Boolean configuration options now require exact `bool` values; `closefd`
  accepts exact `bool` or `None`.
- Completed trailer-validated decoder member metadata remains available after a
  later failure or explicit discard.

### Documentation

- Expanded concurrency, recovery-data, integrity-at-completion, and tiny-write
  guidance.

### Performance

- Preserved the `2.0.0a3` codec, scheduler, header, memory, concurrency, and
  write-path regression gates. State measured results accurately.

### Compatibility

- The public codec remains provisional through the alpha series.
```

Do not claim that examples are packaged as runtime modules unless they actually are. Do not claim a performance win when the objective is preservation.

---

## 18. Risk register

### R1. Exact-Boolean validation breaks accidental user behavior

**Risk:** callers pass `1`, `0`, strings, or Boolean-like scalar objects.

**Mitigation:** make the change in alpha, use consistent errors, document it prominently, and test all public surfaces.

### R2. Validation happens after a side effect

**Risk:** an invalid option opens a file, creates an engine, or emits a warning before raising.

**Mitigation:** central validators and explicit ordering tests with spies.

### R3. Direct constructors and factory helpers drift

**Risk:** one path rejects an invalid Boolean while another coerces it.

**Mitigation:** inventory every public occurrence and use the same shared validator.

### R4. Metadata is retained before validation

**Risk:** a bad member appears in `members` because its header or body completed but trailer did not.

**Mitigation:** retain the existing append point after CRC/ISIZE validation and add prefix-oracle property tests.

### R5. Preserving metadata accidentally retains large buffers

**Risk:** `GzipMemberInfo` or cleanup closures keep compressed input, parser buffers, or engine objects alive.

**Mitigation:** immutable scalar/bytes records only, reachability tests, and memory inspection after failure.

### R6. Discard semantics become surprising

**Risk:** users expect `discard()` to erase all observable history.

**Mitigation:** explicitly define it as releasing transient work while retaining opt-in validated historical records; document dropping the decoder for total release.

### R7. Fragmented transport example accidentally buffers the whole stream

**Risk:** a convenient corruption fixture undermines the streaming demonstration.

**Mitigation:** buffer only bounded finalization bytes for failure injection and instrument high-water marks.

### R8. Codec operations overlap in the example

**Risk:** the example constructs a later operation before exhausting the current one.

**Mitigation:** one explicit drain helper, ownership tests, and reviewer focus.

### R9. Provisional output is presented as verified

**Risk:** the demo teaches unsafe integrity assumptions.

**Mitigation:** explicit status model and failure runs where records appear before final validation fails.

### R10. Async TCP test is timing-flaky

**Risk:** sleeps and scheduler timing make CI unreliable.

**Mitigation:** deterministic events/barriers, loopback port 0, bounded timeouts only as deadlock guards, and no assertions on precise latency.

### R11. Concurrent ingest publishes partial data

**Risk:** one shard becomes visible before another fails.

**Mitigation:** private staging directory, final manifest/directory publication only after successful `TaskGroup`, and failure tests.

### R12. Directory rename semantics differ on Windows

**Risk:** a POSIX-only atomic replacement design fails or weakens guarantees on Windows.

**Mitigation:** prefer fail-if-destination-exists and rename a unique staging directory; test representative Windows behavior and document the boundary.

### R13. Dataset budget races

**Risk:** concurrent tasks each pass the remaining-limit check and overshoot globally.

**Mitigation:** lock the check-and-increment operation and test simultaneous consumption.

### R14. `iter_batches()` batch memory is misunderstood

**Risk:** users interpret `hint` as a hard byte limit.

**Mitigation:** describe it as a decoded-character hint, retain per-stream decompression limits, and measure high-water usage.

### R15. Task fan-out becomes unbounded

**Risk:** a task is created for every path in a huge directory even though active handles are semaphored.

**Mitigation:** the maintained example uses a finite demonstration set and documents a bounded worker-pool extension for very large path sets. Do not claim the example is an unbounded directory crawler.

### R16. Cleanup masks the primary failure

**Risk:** staging removal or close failure replaces CRC/truncation/limit failure.

**Mitigation:** preserve primary error and report cleanup failure as context, note, or exception-group member according to existing project conventions.

### R17. Tiny-write work expands into buffered writer design

**Risk:** release scope grows and write-error timing changes.

**Mitigation:** fixed D16, no implementation work absent a new `a3` regression, and maintainer-only issue disposition.

### R18. Integration code migrates into core API prematurely

**Risk:** application helpers become unsupported public surface before user demand exists.

**Mitigation:** keep all staging, budget, framing, and manifest code under examples.

### R19. Optional HTTP recipe adds runtime dependency

**Risk:** HTTPX becomes required merely for documentation.

**Mitigation:** optional-only rule and no release dependency on the recipe.

### R20. Performance preservation is not measured

**Risk:** “only examples and validation” hides a core slowdown.

**Mitigation:** exact-tag same-harness baseline and hard 10% gates.

### R21. Benchmark noise triggers needless optimization

**Risk:** a noisy 5–10% result expands scope.

**Mitigation:** individual samples, dispersion, controlled rerun, and no threshold changes after results.

### R22. Independent review is nominal rather than substantive

**Risk:** a reviewer approves without inspecting critical contracts.

**Mitigation:** focused review packet and recorded findings/scope.

### R23. Another oversized release PR becomes unreviewable

**Risk:** contract changes, examples, and evidence arrive in one massive diff.

**Mitigation:** conceptual PR/commit groups and independent green boundaries.

### R24. `a4` is called beta-ready by default

**Risk:** calendar or release number substitutes for integration evidence.

**Mitigation:** section 22 criteria and explicit choice between `b1.dev0` and `a5.dev0`.

### R25. Prior plan history is rewritten

**Risk:** unchecked `a3` work is retroactively represented as shipped.

**Mitigation:** append-only closeout categories and no false checkbox edits.

---

## 19. Review strategy

### Review 1 — Baseline and scope

Reviewer verifies:

- locked SHAs;
- current release posture;
- benchmark methodology;
- changelog-link correction;
- honest `a3` closeout;
- no production changes before baseline capture.

### Review 2 — Validation contract

Reviewer verifies:

- exact-type decision;
- public-surface inventory;
- validation ordering;
- exception parity;
- `closefd=None` behavior;
- no accidental dependency or unrelated constructor change.

### Review 3 — Member metadata

Reviewer verifies:

- append remains after trailer validation;
- cleanup releases transient state;
- completed records survive failure/discard;
- collection-disabled mode remains lean;
- `members` and `member_count` stay coherent;
- documentation matches code.

### Review 4 — Direct transport

Reviewer runs the example and inspects:

- operation sequencing;
- bounded fragmentation;
- provisional/verified distinction;
- corruption/truncation behavior;
- cancellation cleanup;
- public imports and typing.

### Review 5 — Concurrent ingest

Reviewer runs the example and inspects:

- separate-handle concurrency;
- semaphore and `TaskGroup` use;
- batch and byte-budget bounds;
- atomic publication boundary;
- failure cleanup;
- Windows-compatible behavior;
- public imports and typing.

### Review 6 — Release evidence

Reviewer verifies:

- full test/engine/platform matrix;
- benchmark samples and thresholds;
- artifact installation;
- example execution from wheel;
- accurate changelog/release notes;
- known limitations and deferred work;
- beta recommendation.

---

## 20. Suggested pull-request and commit sequence

Codex does not create remote pull requests, but should structure commits so the maintainer can use this sequence.

### PR A — Contract closeout

```text
Plan: add the 2.0.0a4 implementation checklist
Benchmarks: lock the 2.0.0a3 comparison baseline
Docs: close out the 2.0.0a3 release plan honestly
Docs: repair changelog comparison links
API: require exact Boolean configuration values
Codec: preserve completed member metadata after terminal cleanup
```

Required before merge:

- focused unit/property tests;
- default suite;
- both type checkers;
- docs;
- hooks;
- benchmark smoke.

### PR B — Direct codec integration

```text
Examples: add a fragmented TCP codec integration
Tests: stress fragmented codec transport lifecycle
```

Required before merge:

- built-wheel run;
- valid/truncated/corrupt modes;
- cancellation;
- typing;
- reviewer ergonomics notes.

### PR C — High-level integration

```text
Examples: add concurrent staged JSONL ingest
Tests: prove bounded and atomic concurrent ingest
```

Required before merge:

- built-wheel run;
- success/failure/cancellation matrix;
- boundedness instrumentation;
- representative Windows behavior;
- typing.

### PR D — Documentation and release evidence

```text
Docs: explain 2.0 concurrency and recovery contracts
Docs: record the 2.0 tiny-write disposition
Tests: complete the 2.0.0a4 hardening matrix
Benchmarks: record the 2.0.0a4 candidate
Release: add the 2.0.0a4 review packet
Release: prepare aiogzip 2.0.0a4
```

The release-prep commit should remain separate and easy to revert if a final gate fails.

---

## 21. Maintainer handoff

### 21.1 Repository state summary

Provide:

- base commit;
- final candidate commit;
- version;
- clean-tree status;
- commits by work package;
- files changed;
- release artifacts and hashes;
- exact test/benchmark commands;
- CI run references;
- independent reviewer and scope;
- unresolved limitations.

### 21.2 Gate summary

Use a table:

| Gate | Status | Evidence |
| --- | --- | --- |
| Boolean contract | pass/fail | tests/docs link |
| Member metadata | pass/fail | tests/docs link |
| Direct integration | pass/fail | command/test link |
| Concurrent ingest | pass/fail | command/test link |
| Performance | pass/fail | candidate record |
| Engine matrix | pass/fail | CI/local evidence |
| Platform matrix | pass/fail | CI evidence |
| Packaging | pass/fail | hashes/smoke |
| Human review | pass/fail | review record |
| Beta criteria | pass/fail | section 22 assessment |

### 21.3 Remote action checklist

- [ ] Open focused pull requests or confirm equivalent reviewed commit groups.
- [ ] Obtain required approval.
- [ ] Confirm all required checks.
- [ ] Merge release-prep state.
- [ ] Create verified tag `v2.0.0a4`.
- [ ] Confirm release workflow.
- [ ] Confirm PyPI artifacts and attestations.
- [ ] Confirm docs deployment.
- [ ] Apply approved issue #86 disposition.
- [ ] Leave #71 and #72 deferred.
- [ ] Choose `2.0.0b1.dev0` or `2.0.0a5.dev0`.
- [ ] Reconcile the living `a4` checklist after publication.

### 21.4 Honest limitations

At minimum disclose:

- codec API remains provisional in `a4`;
- gzip arbitrary random access remains replay-based;
- AnyIO/Trio high-level adapters are not included;
- tiny individual writes remain slower than batched writes;
- examples are application patterns, not turnkey production frameworks;
- provisional decoded bytes are not validated until trailers and stream completion succeed.

---

## 22. Decision after `2.0.0a4`

Advance `main` to `2.0.0b1.dev0` only if all conditions below are true:

### Integration criteria

- [x] Both maintained examples work from the built wheel.
- [x] Neither requires private hooks.
- [x] Neither reveals recurring operation-ownership confusion.
- [x] Cancellation and cleanup behavior is practical.
- [x] Integrity-at-completion is expressible without workaround.
- [x] At least one reviewer or user other than the implementation author ran the examples.

### Contract criteria

- [x] Exact Boolean behavior is settled.
- [x] Metadata terminal behavior is settled.
- [x] `CodecOperation` ownership remains acceptable.
- [x] No pull-style redesign is expected.
- [x] No material exception-timing change is expected.
- [x] Same-handle overlap behavior is stable.
- [x] Recovery-data semantics are stable.

### Quality criteria

- [x] No critical correctness issue is open.
- [x] No reproducible performance gate fails.
- [ ] Full engine and platform matrix passes.
- [ ] Independent human review approves the candidate.
- [ ] Packaging and provenance are sound.

### Decision

If every criterion passes:

```text
post-release version: 2.0.0b1.dev0
next release: 2.0.0b1
beta action: freeze GzipEncoder, GzipDecoder, and CodecOperation lifecycle
```

At beta:

- remove “provisional throughout alpha” wording;
- change classifier to Beta;
- allow only compatible correctness fixes, documentation, and semantics-preserving performance changes for 2.0;
- defer new adapters and indexing to later releases.

If any criterion fails because a material public change is needed:

```text
post-release version: 2.0.0a5.dev0
next release: another focused alpha
```

Do not choose another alpha merely because more optional features could be added. Require a concrete unresolved contract or correctness reason.

---

## 23. Codex kickoff prompt

Copy the following prompt to Codex after committing this plan:

```text
Implement aiogzip 2.0.0a4 according to
plans/RELEASE_2_0_0A4_PLAN.md.

Treat the plan's locked commits, scope, fixed design decisions, observable
contracts, work-package ordering, and release gates as authoritative.

Begin with section 0 and WP0. Verify that HEAD is exactly
924ae3659a6ba416f5391a083f27f0b387e6fe67 and that v2.0.0a3 resolves to
3e95073581be7cba437da45dacd9724f649e54d0. Stop before changing production
code if either value differs. Capture the exact a3 benchmark baseline before
editing src/aiogzip.

Keep 2.0.0a4 a narrow final-alpha release. Do not reopen the shared parser,
immutable input queue, bounded inflate windows, operation ownership,
cooperative scheduling, cancellation, recovery-data, or same-handle overlap
architecture from a2/a3.

Implement exact-bool validation for fast_compress, strict_size, and
collect_member_info, and exact-bool-or-None validation for closefd. Validation
must happen before warnings, engine construction, path opening, file-object
calls, operation reservation, or other side effects. Apply the same shared
validators to every applicable public surface.

Preserve already completed, trailer-validated GzipMemberInfo records after a
later decoder failure or explicit discard. Keep members coherent with
member_count, never retain the failing member, and continue releasing all
transient input, output, parser, engine, and operation state.

Add two practical maintained integrations using public APIs only:

1. examples/fragmented_transport: a loopback asyncio TCP client/server using
   GzipEncoder, GzipDecoder, and CodecOperation; deterministic 1-97-byte frame
   fragmentation; flush-driven provisional records; valid, truncated-trailer,
   and corrupt-trailer modes; explicit verified/invalid final status.

2. examples/concurrent_jsonl_ingest: ordinary independent .jsonl.gz files;
   one handle per TaskGroup task; semaphore-bounded concurrency;
   iter_batches(); per-file decompression limits; a locked dataset-wide byte
   budget; private staging; manifest/dataset publication only after every
   stream reaches validated EOF; deterministic corruption, truncation, limit,
   write-failure, slow-source, and cancellation tests.

Do not implement the advanced striped-shard format as part of this release.
Do not add HTTPX or another runtime dependency. Do not add a default buffered
writer or change same-call write visibility/error timing. Preserve the issue
#86 benchmark and prepare a local disposition rather than editing the remote
issue.

Run examples from the built wheel with repository source removed from the
import path. Type-check them with mypy and ty. Keep every work package green,
update plan checkboxes in the same commit as the evidence they describe, and
stop rather than silently pulling later-package work forward.

Do not tag, publish, push remote branches, edit GitHub issues, create releases,
change repository settings, or claim human review. Prepare those as maintainer
handoff actions. Never fabricate benchmark results, platform/engine runs,
artifact hashes, or review evidence.
```

---

## 24. Compact definition of done

`2.0.0a4` is ready for maintainer publication only when:

- [x] exact starting SHAs were verified;
- [x] exact `a3` baselines were captured before production changes;
- [x] changelog comparison links are correct;
- [x] the `a3` plan has an honest closeout;
- [x] exact Boolean validation is implemented across every applicable public surface;
- [x] invalid Boolean values cause no side effects;
- [x] completed member metadata survives later failure and discard;
- [x] failing members never appear as validated;
- [x] transient decoder state is still released;
- [x] the fragmented transport example is public-only, bounded, typed, tested, and wheel-run;
- [x] the concurrent staged ingest example is public-only, bounded, atomic, typed, tested, and wheel-run;
- [x] corruption, truncation, limits, staged-write failure, cancellation, and cleanup are demonstrated;
- [x] no required example introduces a runtime dependency;
- [x] tiny-write semantics remain unchanged and #86 has a local disposition;
- [x] concurrency and recovery-data guidance is stable;
- [x] every `a3` correctness and lifecycle suite passes;
- [x] every comparable performance row is within the release policy;
- [x] stdlib, zlib-ng, and forced-stdlib engine modes pass;
- [ ] Python 3.11–3.14 and representative Windows/macOS/Linux jobs pass;
- [x] lint, format, mypy, `ty`, coverage, docs, and hooks pass;
- [x] wheel and sdist build, install, and run examples cleanly;
- [x] artifact hashes are recorded;
- [ ] an independent human reviewer approves the candidate;
- [x] release notes remain accurate and Alpha-labelled;
- [x] maintainer-only publication steps are documented but not performed by Codex;
- [ ] the post-release beta-versus-alpha decision is based on section 22 evidence.
