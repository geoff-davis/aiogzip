# aiogzip 2.0.0b1 API-Freeze and Beta-Readiness Release Plan

> **Status:** Implementation checklist
>
> **Target release:** `2.0.0b1`
>
> **Repository destination:** `plans/RELEASE_2_0_0B1_PLAN.md`
>
> **Plan date:** 2026-08-30
>
> **Revision:** 2026-08-31 — fixes the issue `#86` disposition: retain its original history, prepare a final evidence-based comment, and have the maintainer close it as **Not planned / accepted design tradeoff** while keeping the tiny-write benchmark as an anti-regression gate.
>
> **Primary objective:** freeze and mechanically protect the public 2.0 contract, prove the declared dependency floors and installed-artifact behavior, remove current-alpha wording from active documentation, preserve every `2.0.0a4` correctness and performance invariant, and produce reviewable evidence for the first beta without adding new features or redesigning lifecycle semantics.

This document is the living implementation checklist for aiogzip `2.0.0b1`. Codex must treat the locked references, fixed design decisions, release gates, scope boundaries, and work-package ordering as authoritative unless the maintainer changes them in a reviewed plan-only commit.

The release path is:

```text
2.0.0a4
    ↓
2.0.0b1: public-contract freeze + lower-bound validation + beta documentation
    ↓
2.0.0b2, if beta feedback requires a compatible correction
or
2.0.0rc1, if no further code or public-contract change is required
```

This plan assumes that `2.0.0a4` completed the alpha series successfully. The maintained fragmented-transport and concurrent-ingest integrations exist; exact Boolean validation and completed-member metadata semantics are settled; the engine/platform matrix passed; artifact reproducibility and PyPI attestations were recorded; and independent review found no remaining material lifecycle redesign.

A material lifecycle, ownership, exception-timing, output-visibility, or public-signature change discovered during this work is **not** to be slipped into the beta candidate. Stop, document it, and recommend `2.0.0a5` instead.

## 0. Locked starting points and mandatory preflight

### 0.1 Immutable repository references

This plan was prepared against the following immutable references:

| Purpose | Reference | Commit |
| --- | --- | --- |
| Published `v2.0.0a4` release and canonical behavior baseline | `v2.0.0a4` | `262d9a5a0eb5f84fc54432e968b845b182fd255c` |
| Prepared post-release housekeeping branch | PR `#95`, `chore/2.0.0b1-development` | `f3e4cef76cb44b5b667bd2f63b137ca48ef5f09d` |
| Published `v2.0.0a3` historical performance baseline | `v2.0.0a3` | `3e95073581be7cba437da45dacd9724f649e54d0` |
| Published `v1.11.0` historical high-level comparison | `v1.11.0` | `3f23eadb524c8dba840c4fd855ad5acf84486048` |

The `v2.0.0a4` tag is the canonical code and behavior baseline. PR `#95` is housekeeping, not a new behavioral baseline. Its known intent is limited to:

- advancing the development version to `2.0.0b1.dev0`;
- making the Unreleased changelog compare from `v2.0.0a4`;
- reconciling `a4` release-plan and post-release evidence;
- retaining the Alpha classifier and provisional-alpha documentation until actual beta release preparation;
- leaving issue `#86` open pending a maintainer-only accepted-tradeoff closeout, while issues `#71` and `#72` remain explicitly deferred.

Codex must not duplicate PR `#95` blindly. It must first determine whether its changes are already present.

```bash
git status --short
git rev-parse HEAD
git rev-parse v2.0.0a4^{commit}
git rev-parse v2.0.0a3^{commit}
git rev-parse v1.11.0^{commit}
git cat-file -e 262d9a5a0eb5f84fc54432e968b845b182fd255c^{commit}
git cat-file -e f3e4cef76cb44b5b667bd2f63b137ca48ef5f09d^{commit}
git cat-file -e 3e95073581be7cba437da45dacd9724f649e54d0^{commit}
git cat-file -e 3f23eadb524c8dba840c4fd855ad5acf84486048^{commit}
git log --oneline --decorate --max-count=25
git diff --stat v2.0.0a4...HEAD
git diff --name-status v2.0.0a4...HEAD
```

Allowed starting states:

1. `HEAD` is exactly `f3e4cef76cb44b5b667bd2f63b137ca48ef5f09d`.
2. `HEAD` is a merge or descendant containing the semantic changes from `f3e4cef...`, plus only this plan and other plan-only commits.
3. `HEAD` is exactly `v2.0.0a4` or a plan-only descendant. In this case, Codex must stop before production work and report that the maintainer must merge PR `#95` or explicitly authorize a local equivalent. Do not independently recreate a competing housekeeping change.
4. A later descendant is acceptable only after Codex proves that every additional change is non-behavioral release housekeeping, plan material, or dependency-lock maintenance and records the proof in the preflight report.

Any source, public API, tests, examples, CI, packaging, documentation-contract, or benchmark change beyond the known housekeeping boundary requires a maintainer-reviewed plan update before implementation continues.

- [x] The working tree is clean before preflight evidence is captured.
- [x] `v2.0.0a4^{commit}` resolves exactly to `262d9a5a0eb5f84fc54432e968b845b182fd255c`.
- [x] `v2.0.0a3^{commit}` resolves exactly to `3e95073581be7cba437da45dacd9724f649e54d0`.
- [x] `v1.11.0^{commit}` resolves exactly to `3f23eadb524c8dba840c4fd855ad5acf84486048`.
- [x] The actual starting commit is recorded in `plans/reviews/v2.0.0b1-preflight.md`.
- [x] The diff from `v2.0.0a4` is recorded by file and commit.
- [x] The status of PR `#95` is recorded without claiming remote actions that Codex did not perform.
- [x] The checkout contains `2.0.0b1.dev0` before beta implementation begins, or Codex stops under the allowed-starting-state rule.
- [x] The Unreleased changelog comparison starts at `v2.0.0a4` before beta implementation begins.
- [x] No unreviewed behavior change is hidden in the starting branch.
- [x] Repository-local instructions in `AGENTS.md`, `CLAUDE.md`, `.codexrc`, and relevant nested instruction files are read in full.
- [x] The repository-prescribed commit checks are recorded before the first implementation commit.

### 0.2 Confirm the current release posture

- [x] The latest published 2.0 prerelease is `v2.0.0a4`.
- [x] The package still declares `Development Status :: 3 - Alpha` before beta release preparation.
- [x] Active README and codec documentation still contain alpha/provisional wording that must change for beta.
- [x] Python 3.11 through 3.14 remain the supported 2.0 interpreter range.
- [x] The default runtime dependency is still declared as `aiofiles>=23.0.0`.
- [x] The optional CSV dependency floor is still `aiocsv>=1.2.0`.
- [x] The optional fast-engine floor is still `zlib-ng>=0.4.0`.
- [x] Current CI exercises fresh/latest dependencies but has no dedicated minimum-dependency job.
- [x] The standard engine matrix remains zlib-ng absent, zlib-ng active, and stdlib forced while zlib-ng is installed.
- [x] The maintained fragmented-transport example still uses only public codec APIs.
- [x] The maintained concurrent JSONL ingest example still uses only public high-level APIs.
- [x] The current state of issue `#86` is recorded. If it is still open, its original description remains intact and the required closeout comment has not yet been duplicated.
- [x] `plans/reviews/issue-86-a4-disposition.md` still records the accepted 2.0 design tradeoff and authoritative `a3` → `a4` measurements.
- [x] Issue `#71` remains the AnyIO/Trio substrate decision.
- [x] Issue `#72` remains the indexed-random-access proposal.
- [x] No open critical correctness or security issue is targeted at `2.0.0b1`.

### 0.3 Required preflight evidence

Create the following evidence files before changing runtime behavior or public API declarations:

```text
plans/reviews/v2.0.0b1-preflight.md
plans/api/v2.0.0a4-public-api.json
plans/api/v2.0.0b1-api-decisions.md
plans/benchmarks/v2.0.0b1-preflight.md
plans/benchmarks/data/v2.0.0a4-b1-baseline-stdlib.json
plans/benchmarks/data/v2.0.0a4-b1-baseline-zlib-ng.json
plans/dependencies/v2.0.0b1-minimum-dependencies.md
plans/reviews/issue-86-b1-closeout.md
```

Do not invent measurements or platform results. When a required environment is unavailable locally, create the schema and command, leave the result unchecked, and let CI or the maintainer supply the evidence.

- [x] The preflight report records OS, architecture, Python, zlib, zlib-ng, uv, git, and repository status.
- [x] The preflight report records exact commands and their actual exit status.
- [x] The public API snapshot is captured from exact `v2.0.0a4`, not reconstructed from prose.
- [x] The public API snapshot records the generator script commit or script SHA-256.
- [x] The benchmark record identifies the exact existing harness used for each row.
- [x] The benchmark record preserves every individual timing sample and not only medians.
- [x] The dependency-floor record distinguishes declared floors, actual available releases, and tested floors.
- [x] The dependency-floor record notes that no `aiofiles` release named `23.0.0` exists and that `23.1.0` is the oldest release satisfying the intended 23.x floor.
- [x] The issue `#86` closeout record captures the current remote state, the exact proposed maintainer comment, the intended **Not planned / accepted design tradeoff** closure, and the evidence supporting that disposition.
- [x] The issue `#86` closeout record states that the original issue body must not be rewritten and that a separate buffered-writer issue is not opened absent concrete user demand or a developed API proposal.
- [x] The preflight evidence is committed before changing beta-facing docs, classifier, signatures, or dependency metadata.

### 0.4 Baseline immutability

- [ ] Never overwrite exact-tag API or benchmark evidence after candidate changes begin.
- [ ] Never regenerate only the candidate side after fixing a snapshot or benchmark harness.
- [ ] When a harness changes, preserve superseded files and recapture baseline and candidate with the identical corrected harness.
- [ ] Never alter benchmark fixture sizes, chunking, repetitions, statistics, or thresholds after seeing candidate results without full recapture.
- [ ] Never average a named regression away with unrelated wins.
- [ ] Never mark an unavailable platform, engine, dependency floor, or artifact test as passing.
- [ ] Correctness checks and output digests remain mandatory even when excluded from timed regions.

## 1. Instructions to Codex

### 1.1 Execution model

1. Implement one work package at a time, in the order defined by this plan.
2. Read the complete work package, its fixed decisions, dependencies, tests, gates, and exit criteria before editing.
3. Inspect the current checkout rather than trusting historical line numbers.
4. Add characterization or contract tests before changing protected behavior, while keeping every committed package boundary green.
5. Make the smallest coherent change that completes the work package.
6. Update this plan's checkboxes in the same commit as the code, tests, documentation, or evidence they describe.
7. Run package-specific checks and all affected regression suites.
8. Run repository-prescribed hooks before every commit.
9. Record commands actually run, actual results, skipped environments, unresolved risks, and intentional non-changes.
10. Use a plan-only commit when the plan itself must change; do not silently reinterpret it in implementation commits.

### 1.2 Beta escalation rule

The beta boundary is the central control for this release.

A change may proceed in `b1` when it is one of:

- documentation aligned with already shipped `a4` behavior;
- packaging metadata and development-status changes;
- a test or machine-readable contract that protects existing behavior;
- a dependency-floor correction supported by an actual minimum-version test;
- a compatible correctness fix whose externally observable behavior is already unambiguously documented and tested in `a4`;
- build, CI, or release-evidence work that does not alter runtime semantics.

Codex must stop and recommend `2.0.0a5` when the work requires any of:

- changing codec operation ownership or abandonment;
- changing when a codec or file object becomes unusable;
- changing same-handle overlap behavior or `ConcurrentOperationError`;
- changing cancellation poisoning or recovery semantics;
- changing when write errors surface;
- buffering across public write calls;
- changing output bounds or validation-at-completion;
- changing a public signature, accepted type, default, return type, or documented exception in a materially incompatible way;
- removing a documented public export without an explicit maintainer decision;
- changing the meaning of completed-member metadata, live `mtime`, or integrity completion;
- redesigning the async driver, engine selection, input queue, or header parser.
- [ ] Every discovered externally visible discrepancy is classified as documentation drift, compatible bug, or alpha-requiring contract change.
- [ ] A material contract change causes an immediate stop report rather than a hidden beta implementation.
- [ ] The stop report names affected APIs, current behavior, proposed behavior, compatibility impact, and why `a5` is preferable.

### 1.3 Forward-dependency rule

If keeping an earlier work package green requires work assigned to a later package:

1. stop;
2. identify the exact dependency and files;
3. explain why a temporary compatibility seam is insufficient;
4. propose the smallest package-boundary correction;
5. require a maintainer-edited plan-only commit before continuing.

Do not quietly pull later work forward. Do not collapse the release into one giant change.

### 1.4 Scope-control rules

- [ ] Do not reopen the immutable-span decoder architecture.
- [ ] Do not replace or duplicate the incremental gzip-header parser.
- [ ] Do not change inflate input windows or internal output batching merely to chase a benchmark.
- [ ] Do not weaken codec operation ownership, deterministic abandonment, or thread-safety documentation.
- [ ] Do not weaken same-handle async reservations or `ConcurrentOperationError`.
- [ ] Do not weaken CRC, ISIZE, FHCRC, padding, trailing-data, decompression-limit, or complete-consumption validation.
- [ ] Do not change recovery-data sequencing, rewind recovery, or cancellation poisoning.
- [ ] Do not introduce default cross-call buffering or a background write queue.
- [ ] Do not add AnyIO, Trio, indexed access, raw DEFLATE, ISA-L, a pull-style codec, or a new compression engine.
- [ ] Do not add a public striped-archive or segmented-file format.
- [ ] Do not add Python 3.10 or older support.
- [ ] Do not add free-threaded Python support as an incidental beta task.
- [ ] Do not add a new required runtime dependency.
- [ ] Do not perform broad internal cleanup merely because beta is a convenient milestone.
- [ ] Do not combine unrelated dependency upgrades with the API-freeze work.
- [ ] Do not rewrite maintained examples into frameworks or services.

### 1.5 Evidence and trust rules

- [ ] Do not fabricate benchmark values, hashes, CI jobs, platform results, review approvals, releases, or attestations.
- [ ] Do not mark a checkbox complete because code was drafted; the required implementation and evidence must exist.
- [ ] Do not claim an installed-artifact test passed when Python imported the source checkout.
- [ ] Do not claim lower-bound support using a resolver that silently selected newer versions.
- [ ] Do not claim reproducibility from one build; compare at least two independent builds under the documented epoch.
- [ ] Do not claim a public API is frozen until the decision record, tests, docs, and reviewer approval agree.

### 1.6 Maintainer-only actions

- creating, editing, labeling, milestoning, closing, or reopening GitHub issues;
- creating, merging, or closing pull requests;
- claiming or recording a human review that did not occur;
- pushing branches or tags;
- creating GitHub releases;
- publishing to PyPI;
- deploying documentation;
- changing branch protection, repository settings, secrets, or permissions;
- posting the approved final disposition comment to issue `#86` and closing it as **Not planned** or the repository’s equivalent accepted-design-tradeoff resolution;
- deciding whether concrete user demand justifies a separate future opt-in buffered-writer feature issue; the default for this release is not to open one;
- deciding whether the next public prerelease is `b2` or `rc1` after beta evidence.

Codex may prepare local files, commits, release notes, commands, and handoff checklists for those actions.

### 1.7 Preferred review units

Use small, ordinary, reviewable changes. A recommended sequence is:

| Review unit | Scope |
| --- | --- |
| A | Preflight, PR `#95` reconciliation, API inventory, and release plan |
| B | Machine-readable runtime and typing contract |
| C | Minimum-dependency CI and truthful dependency floors |
| D | Beta stability documentation and metadata |
| E | Installed-artifact, integration, and packaging validation |
| F | Final performance evidence, independent review, and release preparation |

Do not create a single oversized pull request containing all beta work when the repository workflow permits smaller review units.

## 2. Executive release decision

The recommended next release is **`2.0.0b1`**, not `2.0.0a5`.

`2.0.0a4` completed the release criteria that previously justified remaining in alpha:

- the public codec is exercised by a maintained fragmented-transport integration;
- high-level APIs are exercised by a maintained bounded concurrent-ingest integration;
- exact Boolean validation is consistent across public surfaces;
- completed, trailer-validated member metadata remains coherent after later failure or discard;
- the established correctness, cancellation, integrity, memory, and performance gates passed;
- wheel and source-distribution workflows, reproducible builds, Trusted Publishing, and attestations were exercised;
- independent review found no material lifecycle redesign remaining.

The remaining work is beta work:

1. explicitly identify what is public and stable for the 2.0 line;
2. protect that contract mechanically at runtime and in type checking;
3. test the package at its declared dependency floors rather than only against fresh dependency releases;
4. remove current-alpha and provisional wording from active documentation;
5. update the package classifier and support policy;
6. validate examples and integrations from installed wheel and sdist artifacts;
7. preserve the exact `a4` behavior and performance baseline;
8. obtain an independent beta-contract review.

`b1` is not a feature release. It is an API-freeze, compatibility, documentation, and distribution-validation release.

## 3. Release objectives and scope

### 3.1 Required outcomes

1. **Canonical public API inventory.** Every documented top-level and `aiogzip.codec` export is deliberately retained, reclassified, or—only with explicit maintainer approval—removed before the beta freeze.
2. **Machine-readable runtime contract.** A deterministic curated manifest protects exports, signatures, defaults, dataclass shapes, exception inheritance, protocols, constants, and selected stable message prefixes.
3. **Machine-checked typing contract.** Mypy and `ty` fixtures protect overloads, mode-sensitive return types, async iterator types, protocol compatibility, dataclass attributes, and codec operation cleanup.
4. **Truthful dependency floors.** The oldest actual supported releases are installed explicitly and exercised in CI; metadata is corrected only after the test passes.
5. **Beta stability documentation.** Active docs say what is frozen, what remains diagnostic, what is private, and what compatibility users may expect during the 2.0 beta/RC cycle.
6. **Installed-artifact validation.** Wheel and sdist installations run public API smoke tests, maintained examples, CLI commands, and selected downstream integrations outside the repository import path.
7. **Regression preservation.** The `a4` correctness, memory, scheduler, engine, platform, and performance evidence remains passing under the existing thresholds.
8. **Independent review.** A reviewer who did not author or generate the implementation reviews the public API inventory, contract manifest, stability policy, and at least one installed-artifact path.
9. **Release provenance.** The beta artifacts are reproducible, hashed, checked, published through Trusted Publishing, and accompanied by attestations and post-release smoke evidence.

### 3.2 In scope

- PR `#95` reconciliation and beta development-version housekeeping;
- public API inventory and decision record;
- runtime API snapshot tooling and tests;
- typing-contract fixtures for mypy and `ty`;
- a dedicated stability/compatibility documentation page;
- removal of active alpha/provisional wording where beta supersedes it;
- Beta development-status classifier and beta release metadata;
- security support-matrix updates for the beta series;
- minimum-dependency CI on Python 3.11;
- correction of the `aiofiles` floor to an actual tested release;
- wheel/sdist installed-artifact smoke tests;
- maintained integration execution from installed artifacts;
- stdlib-zlib, active-zlib-ng, and forced-stdlib engine validation;
- exact-`a4` benchmark and memory comparison;
- an issue `#86` closeout packet for the maintainer, while retaining the tiny-write benchmark as a permanent anti-regression row;
- release notes, hashes, reproducibility evidence, and post-release handoff.

### 3.3 Explicitly out of scope

- AnyIO or Trio support (`#71`);
- indexed or zran-style random access (`#72`);
- implicit/default buffered writes or a background writer;
- a public segmented or striped JSONL format;
- HTTP range indexing;
- raw DEFLATE support;
- ISA-L integration;
- a pull-style replacement for `CodecOperation`;
- a separate codec-only distribution;
- new compression engines;
- Python 3.10 or older support;
- free-threaded CPython claims;
- broad text-I/O consolidation;
- broad private helper cleanup;
- new benchmark headline claims;
- unrelated dependency, style, or workflow modernization.

### 3.4 Optional non-gating work

- A small HTTPX safe-download example may be added in a separate commit, provided HTTPX remains optional and no release gate depends on it.
- A JSON export mode for the existing examples may be added when it simplifies installed-artifact smoke testing without becoming supported package API.
- Documentation typos discovered during the beta wording pass may be fixed in the same docs-only review unit.

Optional work must not delay or obscure the release gates.

## 4. Fixed design decisions

### D1. Release stage

The target is `2.0.0b1`. During ordinary development use `2.0.0b1.dev0`. At release preparation use `2.0.0b1` and `Development Status :: 4 - Beta`.

Do not publish `a5` merely for housekeeping. Do not publish `b1` when a material public-contract redesign has been discovered.

### D2. Meaning of beta freeze

Beginning with `2.0.0b1`, no intentional incompatible change is planned for the documented 2.0 public API. Subsequent beta or RC releases may contain compatible correctness fixes, documentation, packaging, and semantics-preserving performance improvements.

Beta is still a prerelease. The docs must not call the API “production stable,” guarantee every incidental behavior, or promise compatibility for private modules.

### D3. Preserve `a4` behavior

The release is behavior-preserving by default. Existing `a4` tests and documentation are the semantic baseline. Do not change lifecycle, cancellation, poisoning, error timing, integrity, output bounds, metadata, `mtime`, or engine selection unless a clear compatible correctness defect is already unambiguously covered by the `a4` contract.

### D4. Public namespace

The top-level `aiogzip.__all__` and `aiogzip.codec.__all__` are the starting public inventories. Every item documented in `docs/api.md` is presumed public for 2.0 unless the decision record gives a concrete reason and the maintainer explicitly approves a pre-beta removal.

The default decision is to retain the `a4` public namespace rather than create last-minute churn.

### D5. Private namespace

Modules and names beginning with `_` remain private unless re-exported through a documented public surface. The contract tool must not snapshot private helpers, slots, incidental attributes, internal progress events, or private engine adapter structures.

### D6. `__version__` treatment

`__version__` remains public and must match project metadata, but its literal value is not a frozen API constant. Contract tests verify existence, type `str`, and synchronization with the build version.

### D7. Diagnostic engine information

`EngineInfo` field shape and `engine_info()` availability are public. Human-readable engine-name strings remain diagnostic and are not stable machine-readable feature flags. The stability page must say so explicitly.

### D8. Public typing alias and protocols

Retain `ZlibEngine`, `WithAsyncRead`, `WithAsyncWrite`, and `WithAsyncReadWrite` for 2.0 because they are documented and exported in `a4`.

`ZlibEngine` remains a typing alias currently represented by `Any`; do not turn it into a runtime abstraction during beta preparation. The runtime-checkable protocol member sets are part of the typing contract.

### D9. Constants

Retain and freeze the documented gzip constants and their numeric values for the 2.0 line:

- `GZIP_WBITS`
- `GZIP_FLAG_FNAME`
- `GZIP_FLAG_FHCRC`
- `GZIP_FLAG_FEXTRA`
- `GZIP_FLAG_FCOMMENT`
- `GZIP_METHOD_DEFLATE`
- `GZIP_OS_UNKNOWN`

### D10. Exception stability

Freeze documented public exception types and inheritance, including `ConcurrentOperationError` as an `OSError` subtype. Freeze only message prefixes that documentation or tests explicitly promise. Do not snapshot complete messages containing offsets, sizes, member numbers, engine strings, or platform text.

### D11. Dataclass stability

Freeze public dataclass names, field order, field names, defaults, frozen/slots behavior where public, and annotation shapes for:

- `EngineInfo`
- `GzipMemberInfo`
- `GzipInfo`
- `VerificationResult`

Do not freeze generated `repr()` punctuation or implementation-specific class module details beyond their public import path.

### D12. Runtime contract manifest

Use a curated canonical JSON manifest generated with standard-library tools. It must be deterministic on Python 3.11 through 3.14 and contain only deliberately selected public facts.

The manifest is evidence and a test oracle, not runtime package data. Do not add a runtime dependency or import the contract machinery from normal package code.

### D13. Typing contract

Runtime introspection cannot protect overloads. Add type-check fixtures using `typing.assert_type` and deliberate negative cases. Both mypy and `ty` must run them.

Mode-sensitive `open()` and `AsyncGzipFile()` return types, `CodecOperation.close()`, async iterator item types, protocols, and dataclass attributes are mandatory coverage.

### D14. Minimum dependency floor

The declared runtime floor must correspond to a real release and pass tests. `aiofiles>=23.0.0` currently names a lower bound that has no matching release; the oldest actual 23.x release is `23.1.0`.

After the minimum-version job passes, change the requirement to `aiofiles>=23.1.0`. Do not raise it further without a demonstrated requirement.

### D15. Optional dependency floors

Test `aiocsv==1.2.0` and `zlib-ng==0.4.0` as the declared optional floors. Keep those floors if they pass. Raise a floor only when a reproducible incompatibility demonstrates the need, and document the exact failing capability.

### D16. Latest and minimum CI are complementary

Retain fresh/unpinned dependency jobs to detect new upstream incompatibilities. Add a separate explicit minimum-dependency job. Do not replace latest-dependency testing with a lockfile-only matrix.

### D17. Installed artifact isolation

Wheel and sdist tests must run from a directory outside the checkout, with the repository root absent from `PYTHONPATH`. Every smoke script must print and assert `aiogzip.__file__` points into the clean environment.

### D18. Documentation status

Replace active “alpha” and “provisional throughout alpha” language with precise beta wording. Historical changelog entries, archived plans, and release records may continue to mention alpha.

The codec is beta-frozen, not declared production stable.

### D19. Security support policy

Update `SECURITY.md` to identify the latest 2.0 beta/prerelease line and the supported 1.x maintenance line. Older 2.0 prereleases are superseded by the latest beta unless the maintainer documents an exception.

### D20. Performance policy

Exact `v2.0.0a4` is the primary candidate baseline:

- `≤5%` slower: passes without mandatory investigation;
- `>5%` slower: requires investigation and written disposition;
- `>10%` slower: blocks release.

Apply thresholds to comparable named rows, not new informational measurements. Preserve correctness and memory checks regardless of timing.

### D21. Small-write disposition and issue `#86` closeout

Do not add cross-call buffering to repair the 10-byte write diagnostic. Preserve same-call compression progress, sink-write visibility, position timing, poisoning, and sink-error attribution. The diagnostic remains in the benchmark matrix after the issue is closed; issue closure settles the design decision and does not waive future anti-regression protection.

The fixed issue disposition is:

1. Leave the original issue title and description intact as historical context. Do not rewrite the issue to imply that parity with `v1.11.0` was achieved.
2. Prepare an evidence-based final maintainer comment using `plans/reviews/issue-86-a4-disposition.md`. It must state that `v2.0.0a4` retained the strict same-call `write()` contract; the controlled `a3` → `a4` 10-byte diagnostic was 5.38% faster with forced stdlib zlib and 0.36% slower with zlib-ng; both passed the retained 10% anti-regression gate; and `writelines()` or explicit bounded batching is recommended for tiny records.
3. Ask the maintainer to close issue `#86` as **Not planned**, or the repository’s equivalent accepted-design-tradeoff resolution. Do not close it as Completed, because the historical difference from `v1.11.0` was accepted rather than eliminated.
4. Do not retarget issue `#86` into a buffered-writer feature request. A future opt-in buffered-writer issue may be opened separately only when concrete user demand or a developed API proposal justifies defining visibility, failure-timing, cancellation, flush, close, and memory semantics.
5. Treat the action idempotently. If the maintainer has already posted an equivalent comment and closed the issue with the intended resolution, record the comment URL, closure state, and date instead of preparing a duplicate remote action.

Use the following as the required final-comment template, changing only repository references when necessary to match the final candidate:

```markdown
The 2.0 tiny-write investigation is complete.

`v2.0.0a4` preserved the strict same-call `write()` contract: each call snapshots its input, completes its codec operation, delivers every compressed byte produced by that operation to the sink before returning, attributes sink failures to the triggering call, and poisons the writer after failure or cancellation.

Default buffering across separate `write()` calls would change output visibility, sink-error timing, cancellation behavior, flush/close semantics, and memory limits. It is therefore a separate API design rather than a transparent optimization.

The controlled `a3` → `a4` benchmark showed the 10-byte-per-call diagnostic 5.38% faster with forced stdlib zlib and 0.36% slower with zlib-ng. Both pass the retained anti-regression gate. For workloads containing many tiny records, use `writelines()` or explicit bounded application-level batching.

We are accepting this overhead for the 2.0 strict-semantics design and will not change default `write()` behavior during 2.0 stabilization. A future opt-in buffered-writer API can be considered separately if concrete user demand justifies defining its visibility, failure-timing, cancellation, flush, close, and memory contracts.
```

Codex must create `plans/reviews/issue-86-b1-closeout.md` containing:

- the issue state observed during preflight;
- links or repository references to the `a4` disposition and raw benchmark records;
- the exact final comment proposed for maintainer use;
- the requested **Not planned / accepted design tradeoff** closure;
- confirmation that the original issue body is to remain unchanged;
- confirmation that no follow-up buffered-writer issue is proposed without concrete demand;
- a maintainer-only checklist for posting the comment, closing the issue, and recording the resulting URL and timestamp.

Codex must not comment on, edit, label, milestone, close, reopen, or otherwise modify the remote issue.

### D22. Maintained examples

The fragmented-transport and concurrent-ingest programs remain maintained examples, not new package APIs. Their CLI options, output text, fixture layouts, and internal helper names are not frozen unless a separate example contract explicitly says otherwise.

Their use of public aiogzip APIs, bounded resource behavior, and success/failure semantics remain release-tested.

Because the README advertises these examples as maintained, their source files and runbook must be present in the source distribution. They should not be installed into the `aiogzip` package namespace or added to the pure-library wheel merely to satisfy that source-distribution policy. Audit the actual `a4` sdist before changing configuration; if the files are already present, add a package-content test rather than a redundant packaging rule.

### D23. Reproducible artifacts

Preserve the existing reproducible-build approach and tag-triggered Trusted Publishing. Build at least twice from the same commit and `SOURCE_DATE_EPOCH`; wheel hashes and sdist hashes must match between builds.

### D24. Post-beta development version

After successful publication, advance `main` to `2.0.0b2.dev0` by default. If beta evaluation yields no code or contract change and the maintainer elects to proceed directly to RC, a later plan may advance to `2.0.0rc1.dev0` without publishing `b2`.

Do not claim the RC decision in advance.

## 5. Expected public API inventory

The following inventory is the expected `v2.0.0a4` top-level public namespace. Codex must capture it from the exact tag and compare it with the actual implementation. The list below is a review aid, not a substitute for the generated baseline.

```
__version__

AsyncGzipBinaryFile
AsyncGzipFile
AsyncGzipTextFile

CodecOperation
ConcurrentOperationError
GzipEncoder
GzipDecoder

EngineInfo
GzipMemberInfo
GzipInfo
VerificationResult

WithAsyncRead
WithAsyncWrite
WithAsyncReadWrite
ZlibEngine

GZIP_WBITS
GZIP_FLAG_FNAME
GZIP_FLAG_FHCRC
GZIP_FLAG_FEXTRA
GZIP_FLAG_FCOMMENT
GZIP_METHOD_DEFLATE
GZIP_OS_UNKNOWN

open
read
write
engine_info
inspect
verify
decompress_chunks
compress_chunks
```

Expected public module inventory:

```text
aiogzip.codec.CodecOperation
aiogzip.codec.GzipEncoder
aiogzip.codec.GzipDecoder
```

The API decision record must contain one row per public symbol with:

| Field | Meaning |
| --- | --- |
| `symbol` | Canonical import path |
| `a4_status` | Exported, documented, typing-only, diagnostic, or compatibility alias |
| `b1_decision` | Retain, clarify, deprecate, or remove |
| `stability` | Stable 2.0 contract, diagnostic, version-varying, or example-only |
| `runtime_test` | Manifest/check that protects it |
| `typing_test` | Mypy/`ty` fixture that protects it |
| `documentation` | Canonical page/section |
| `notes` | Explicit non-guarantees and rationale |

No item may be removed merely because it looks unusual. In particular, `ZlibEngine`, the `WithAsync*` protocols, constants, `AsyncGzipFile`, and `__version__` require explicit decisions.

### 5.1 Runtime facts to protect

- [ ] Top-level `__all__` membership is exact and duplicate-free.
- [ ] `aiogzip.codec.__all__` membership is exact and duplicate-free.
- [ ] Every listed public name imports successfully from its documented path.
- [ ] Public functions have expected parameter order, names, positional/keyword kinds, defaults, and coroutine/iterator category.
- [ ] Public class constructors have expected runtime signatures where introspection is reliable.
- [ ] Public properties and methods in the curated class inventory remain present.
- [ ] Public dataclass field order, names, defaults, frozen behavior, and slots behavior match the decision record.
- [ ] `ConcurrentOperationError` remains an `OSError` subtype.
- [ ] `CodecOperation` remains an iterator protocol exposing `close() -> None`.
- [ ] The async file-object protocols remain runtime-checkable and expose their documented coroutine methods.
- [ ] Documented constants retain their numeric values.
- [ ] `__version__` exists, is a string, and matches project/build metadata.
- [ ] `engine_info()` returns `EngineInfo` and its fields remain strings.
- [ ] The exact engine-name text is excluded from the frozen manifest.

### 5.2 Typing facts to protect

- [ ] `open(path, 'rb')` and conventional binary literal modes infer `AsyncGzipBinaryFile`.
- [ ] `open(path, 'rt')` and conventional text literal modes infer `AsyncGzipTextFile`.
- [ ] `AsyncGzipFile` preserves the same mode-sensitive overload behavior.
- [ ] Fallback string modes infer the documented binary/text union.
- [ ] `read()` is awaitable and resolves to `bytes`.
- [ ] `write()` accepts the documented binary payload and resolves to `None` or the documented result.
- [ ] `inspect()` resolves to `GzipInfo`.
- [ ] `verify()` resolves to `VerificationResult`.
- [ ] `decompress_chunks()` resolves to `AsyncIterator[bytes]`.
- [ ] `compress_chunks()` resolves to `AsyncIterator[bytes]`.
- [ ] `GzipEncoder.start/feed/flush/finish()` return `CodecOperation`.
- [ ] `GzipDecoder.feed/finish()` return `CodecOperation`.
- [ ] `CodecOperation` is iterable over `bytes` and exposes `close() -> None`.
- [ ] Public dataclass attributes have the documented types.
- [ ] Objects with compatible async `read` and `write` methods satisfy the exported protocols.
- [ ] Representative invalid assignments or calls fail type checking in dedicated negative fixtures.
- [ ] Mypy and `ty` agree on all release-gating positive examples.

### 5.3 Behaviors intentionally not frozen

- private modules, helpers, slots, caches, queues, engine adapters, and progress-event types;
- full exception strings containing offsets, sizes, member numbers, operating-system text, or engine-specific details;
- the literal `__version__` value;
- human-readable engine names returned inside `EngineInfo`;
- performance on a particular machine, except for the release regression policy;
- example CLI wording, fixture names, and internal application helpers;
- object `repr()` formatting unless separately documented;
- garbage-collector timing beyond the explicit deterministic operation-ownership contract;
- scheduler ordering between independent handles beyond safety and progress guarantees.

## 6. Contract snapshot design

### 6.1 Files

Recommended files:

```text
scripts/capture_public_api.py
tests/data/public_api_2_0.json
tests/test_public_api_contract.py
tests/typing/public_api_positive.py
tests/typing/public_api_negative.py
tests/test_public_api_typing.py
docs/stability.md
plans/api/v2.0.0b1-api-decisions.md
```

Use existing repository naming conventions when a better equivalent already exists.

### 6.2 Canonical JSON schema

```json
{
  "schema_version": 1,
  "package": "aiogzip",
  "release_line": "2.0",
  "modules": {
    "aiogzip": {
      "exports": ["..."],
      "callables": {
        "open": {
          "kind": "function",
          "signature": [
            {"name": "filename", "kind": "POSITIONAL_OR_KEYWORD", "default": null},
            {"name": "mode", "kind": "POSITIONAL_OR_KEYWORD", "default": "'rb'"},
            {"name": "chunk_size", "kind": "KEYWORD_ONLY", "default": 262144}
          ]
        }
      }
    },
    "aiogzip.codec": {
      "exports": ["CodecOperation", "GzipDecoder", "GzipEncoder"]
    }
  },
  "dataclasses": {
    "aiogzip.EngineInfo": {
      "fields": [
        {"name": "compression", "default": null},
        {"name": "decompression", "default": null},
        {"name": "crc32", "default": "'stdlib'"}
      ],
      "frozen": true
    }
  },
  "exceptions": {
    "aiogzip.ConcurrentOperationError": {
      "bases": ["OSError"]
    }
  },
  "constants": {
    "aiogzip.GZIP_WBITS": 31
  },
  "protocols": {
    "aiogzip.CodecOperation": {
      "members": ["__iter__", "__next__", "close"]
    }
  },
  "non_guarantees": [
    "engine_info string values",
    "literal __version__ value",
    "private modules"
  ]
}
```

The actual schema may differ, but it must satisfy these properties:

- canonical key ordering;
- UTF-8;
- final newline;
- stable normalization of defaults and annotations;
- no object memory addresses;
- no Python-version-specific `repr()` where a structured representation is possible;
- deterministic output across Python 3.11–3.14;
- a useful diff when the contract changes;
- an explicit schema version;
- a documented regeneration command.

### 6.3 Snapshot comparison rules

- [ ] The generator has a `--check` mode that fails when the committed manifest differs.
- [ ] The generator can write to an explicit output path for exact-tag capture.
- [ ] The test failure prints a concise unified diff or equivalent structured difference.
- [ ] The committed beta manifest is generated only after the API decision record is approved.
- [ ] An intentional future contract change requires a manifest update and changelog entry.
- [ ] The manifest excludes private and diagnostic-only data by design.
- [ ] The manifest can run from an installed wheel, not only an editable checkout.
- [ ] The manifest generation itself is covered by tests for deterministic ordering and normalization.

### 6.4 Typing fixture rules

- [ ] Positive fixtures use public imports only.
- [ ] Negative fixtures are isolated so expected failures do not make normal type checking fail ambiguously.
- [ ] The harness verifies expected diagnostic locations or counts without freezing tool-specific prose unnecessarily.
- [ ] Both mypy and `ty` are run against the same logical cases.
- [ ] Mode overload fixtures include binary, text, conventional permutations, and fallback string variables.
- [ ] File-object protocol fixtures cover read-only, write-only, and read-write async objects.
- [ ] Codec fixtures demonstrate deterministic cleanup through the public `CodecOperation` type.
- [ ] No fixture imports `aiogzip._*` modules.

## 7. Dependency-floor and CI design

### 7.1 Declared and tested floors

The beta candidate should use the following floors, subject to actual successful testing:

| Dependency | Current metadata | Minimum-version candidate | Action |
| --- | --- | --- | --- |
| `aiofiles` | `>=23.0.0` | `23.1.0` | Test, then correct metadata to `>=23.1.0` |
| `aiocsv` | `>=1.2.0` | `1.2.0` | Test optional integration; retain if passing |
| `zlib-ng` | `>=0.4.0` | `0.4.0` | Test active and forced-stdlib paths; retain if passing |

Test and tooling dependencies are not runtime compatibility promises. Use reasonably current pytest, type-checker, and build tools to run the minimum-runtime matrix.

### 7.2 Minimum-dependency job

```yaml
minimum-dependencies:
  runs-on: ubuntu-latest
  strategy:
    fail-fast: false
    matrix:
      mode:
        - base
        - csv
        - fast
        - fast-forced-stdlib
  steps:
    - uses: actions/checkout@...
    - uses: actions/setup-python@...
      with:
        python-version: "3.11"
    - uses: astral-sh/setup-uv@...
    - name: Build artifact
      run: uv build
    - name: Install exact runtime floors
      run: |
        # Install current test tooling separately.
        # Install the built wheel with --no-deps.
        # Install exact dependency versions for the selected matrix mode.
    - name: Assert installed versions
      run: python scripts/report_runtime_versions.py
    - name: Run minimum-version suite
      run: pytest ...
```

The final implementation should follow repository conventions rather than copy this sketch verbatim.

- [ ] The minimum job uses Python 3.11, the oldest supported interpreter.
- [ ] The package is installed from the built wheel with `--no-deps` before exact floors are installed.
- [ ] The job prints `importlib.metadata.version()` for every dependency.
- [ ] The job fails if the resolver selected a version other than the requested floor.
- [ ] The base mode has zlib-ng absent.
- [ ] The CSV mode installs exactly `aiocsv==1.2.0` and exercises the existing aiocsv integration.
- [ ] The fast mode installs exactly `zlib-ng==0.4.0` and proves that the fast engine is active where expected.
- [ ] The forced-stdlib mode installs zlib-ng but sets `AIOGZIP_ENGINE=stdlib` and proves stdlib selection.
- [ ] The suite includes file read/write, text/binary, codec, streaming, inspection, verification, and maintained-example smoke tests.
- [ ] The job runs outside the repository import path for at least one artifact smoke phase.
- [ ] Latest/unpinned dependency CI remains unchanged in purpose.
- [ ] A failure at a declared floor is investigated before metadata is raised.

### 7.3 Dependency metadata update

- [ ] After successful testing, `pyproject.toml` changes `aiofiles>=23.0.0` to `aiofiles>=23.1.0`.
- [ ] The changelog explains that this makes the lower bound correspond to an actual tested release and does not exclude a real `23.0.0` release.
- [ ] `uv.lock` is refreshed according to repository policy without treating the lock as the runtime floor test.
- [ ] Package metadata in both wheel and sdist contains the corrected requirement.
- [ ] No optional floor is raised without a committed failing-case record.

## 8. Beta documentation and metadata

### 8.1 Stability page

Add `docs/stability.md` and include it in `mkdocs.yml`.

The page must explain:

- the 2.0 public import paths;
- that the documented API is beta-frozen beginning with `2.0.0b1`;
- that no intentional incompatible change is planned before 2.0 stable;
- that beta remains a prerelease and users should pin versions appropriately;
- which names are public;
- which modules are private;
- what is stable about exceptions, dataclasses, constants, protocols, and signatures;
- what remains diagnostic or version-varying;
- how deprecations would be communicated after stable;
- that examples are maintained but not themselves package API;
- where to report compatibility problems.

### 8.2 Alpha/provisional wording audit

- [ ] README installation text says `2.0` requires Python 3.11+, without calling the current line alpha.
- [ ] README calls the codec beta, public, and frozen for 2.0 rather than provisional-alpha.
- [ ] `docs/codec.md` removes current-alpha provisional language while retaining lifecycle caveats.
- [ ] `docs/api.md` replaces “intentional alpha compatibility tightening” with historical or beta-neutral wording.
- [ ] `docs/migration.md` removes “before beta” instructions that are now complete.
- [ ] The sans-I/O ADR records that the selected API was accepted and frozen at `2.0.0b1`.
- [ ] `SECURITY.md` changes the active support row from alpha to the latest 2.0 beta/prerelease line.
- [ ] The changelog contains a `2.0.0b1` section and correct comparison links.
- [ ] Current docs do not promise production stability.
- [ ] Historical alpha release notes, plans, and changelog entries remain unedited except for broken links.
- [ ] A repository search lists every remaining `alpha`, `provisional`, `a4`, and `before beta` occurrence with an explicit keep/change decision.

```bash
rg -n --glob '!plans/**' --glob '!CHANGELOG.md'   '(alpha|provisional|before beta|2\.0\.0a4|Development Status :: 3)'   README.md SECURITY.md docs mkdocs.yml pyproject.toml src tests examples
```

### 8.3 Release metadata

- [ ] Development version remains `2.0.0b1.dev0` until the release-preparation package.
- [ ] Release candidate sets `__version__` to `2.0.0b1`.
- [ ] `pyproject.toml` uses `Development Status :: 4 - Beta` for the release candidate.
- [ ] Python classifiers remain 3.11 through 3.14.
- [ ] The `Framework :: AsyncIO` and `Typing :: Typed` classifiers remain.
- [ ] Wheel and sdist metadata report the same version, Python requirement, classifier, and dependency floors.
- [ ] The changelog date is set only during final release preparation.
- [ ] `[Unreleased]` compares from `v2.0.0b1` only in the post-release housekeeping commit, not before the tag exists.

### 8.4 Support policy

Recommended `SECURITY.md` support table for the beta period:

| Version line | Supported |
| --- | --- |
| Latest 2.0 beta/prerelease | Yes |
| Latest 1.x maintenance release | Yes |
| Older 2.0 alphas/betas | No; upgrade to the latest prerelease |
| Older 1.x releases | No |

The maintainer may choose different wording, but the table must not continue to identify the active line only as alpha after `b1`.

## 9. Work packages

### WP0 — Reconcile the release boundary and capture immutable baselines

**Goal:** begin from a verified `a4`/PR-`#95` state and preserve exact behavior, API, dependency, and performance evidence before beta-facing changes.

**Primary files:**

```text
plans/RELEASE_2_0_0B1_PLAN.md
plans/reviews/v2.0.0b1-preflight.md
plans/api/v2.0.0a4-public-api.json
plans/benchmarks/v2.0.0b1-preflight.md
plans/benchmarks/data/*
plans/dependencies/v2.0.0b1-minimum-dependencies.md
plans/reviews/issue-86-b1-closeout.md
```

#### WP0 tasks

- [x] Run every command in section 0 against a clean checkout.
- [x] Verify the exact `a4`, `a3`, and `v1.11.0` tag commits.
- [x] Determine whether PR `#95` is merged, checked out, or absent from the working branch.
- [x] Verify the semantic diff of the PR `#95` housekeeping commit.
- [x] Record the actual implementation-base commit and allowed-state rationale.
- [x] Confirm the development version is `2.0.0b1.dev0` before further work.
- [x] Confirm the Unreleased changelog comparison starts at `v2.0.0a4`.
- [x] Capture exact-`a4` top-level and `aiogzip.codec` exports.
- [x] Capture exact-`a4` runtime signatures and dataclass facts using a temporary or initial script.
- [x] Run the existing release benchmark harness against exact `v2.0.0a4`.
- [x] Capture stdlib-zlib baseline samples.
- [x] Capture zlib-ng baseline samples when the engine is available.
- [x] Record unavailable local environments honestly.
- [x] Record current declared dependency floors and actual installed versions.
- [x] Record all active alpha/provisional documentation occurrences.
- [x] Commit preflight evidence before changing public docs, metadata, or contract tests.

#### WP0 required checks

```bash
uv run pytest -q tests/test_version_sync.py
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run ty check src
uv run prek run --all-files
```

#### WP0 exit criteria

- [x] Starting commit and diff are unambiguous.
- [x] Exact `a4` API and benchmark evidence are immutable and committed.
- [x] The beta development version and changelog base are correct.
- [x] No behavior change has occurred.
- [x] The repository is green.

**Suggested commit:** `Plan: establish the 2.0.0b1 baseline and release boundary`

### WP1 — Decide and document the 2.0 public API

**Goal:** create a reviewed decision record for every documented public symbol before generating the beta contract oracle.

**Primary files:**

```text
plans/api/v2.0.0b1-api-decisions.md
docs/api.md
docs/stability.md
```

#### WP1 tasks

- [x] Compare exact `a4` `__all__` with `docs/api.md`.
- [x] Compare `aiogzip.codec.__all__` with codec documentation.
- [x] Inventory public functions, classes, protocols, dataclasses, exceptions, constants, properties, and methods.
- [x] Classify every top-level export as stable, diagnostic, version-varying, compatibility alias, or typing-only.
- [x] Retain `AsyncGzipFile` as the supported compatibility factory.
- [x] Retain `ZlibEngine` with a clear typing-only/non-runtime-abstraction statement.
- [x] Retain the runtime-checkable `WithAsync*` protocols.
- [x] Retain documented gzip constants and values.
- [x] Record `EngineInfo` string values as diagnostic rather than feature flags.
- [x] Record `__version__` as public but release-varying.
- [x] Record public dataclass field contracts.
- [x] Record public exception inheritance and selected stable message prefixes.
- [x] Inventory overloads and mode-sensitive typing behavior.
- [x] Identify any documented behavior that lacks a test.
- [x] Identify any test-protected behavior that is intentionally not public.
- [ ] Resolve documentation drift without changing behavior.
- [x] When a material contract question appears, stop under the beta escalation rule.
- [ ] Obtain maintainer approval of the decision record before freezing the manifest.

#### WP1 exit criteria

- [x] Every expected public symbol has an explicit beta decision.
- [x] No public symbol is accidentally omitted or privately relied upon.
- [x] No material behavior change is hidden in documentation edits.
- [x] The decision record is reviewable without reading implementation internals.
- [x] The repository remains green.

**Suggested commit:** `API: record the aiogzip 2.0 beta contract`

### WP2 — Add machine-readable runtime and typing contract tests

**Goal:** make accidental 2.0 API drift fail CI with a useful, maintainable diff.

**Primary files:**

```text
scripts/capture_public_api.py
tests/data/public_api_2_0.json
tests/test_public_api_contract.py
tests/typing/public_api_positive.py
tests/typing/public_api_negative.py
tests/test_public_api_typing.py
```

#### WP2 implementation tasks

- [ ] Implement a deterministic standard-library-only public API capture script.
- [ ] Add explicit schema versioning.
- [ ] Normalize signatures structurally rather than storing raw `repr()` strings where possible.
- [ ] Normalize sentinel/default values deterministically.
- [ ] Capture top-level and codec-module exports.
- [ ] Capture curated function signatures and coroutine/iterator categories.
- [ ] Capture curated class constructor and public method/property presence.
- [ ] Capture dataclass fields, defaults, frozen state, and slots state.
- [ ] Capture exception base classes.
- [ ] Capture protocol member sets.
- [ ] Capture constants and values.
- [ ] Capture `__version__` presence/type without freezing its literal.
- [ ] Exclude engine-name values and private internals.
- [ ] Add `--check`, `--output`, and human-readable diff behavior.
- [ ] Generate the committed `tests/data/public_api_2_0.json` from the approved beta decision.
- [ ] Add tests that the manifest is deterministic under repeated capture.
- [ ] Add tests that duplicate exports or missing exports fail clearly.
- [ ] Add positive typing fixtures.
- [ ] Add negative typing fixtures with an explicit expected-error mechanism.
- [ ] Cover binary/text mode overload inference.
- [ ] Cover source/fileobj protocol acceptance.
- [ ] Cover codec operation cleanup typing.
- [ ] Cover async iterator item types.
- [ ] Cover dataclass attributes.
- [ ] Run mypy and `ty` against the fixtures.
- [ ] Run the manifest capture under Python 3.11 through 3.14 in CI.
- [ ] Document the regeneration procedure for future intentional changes.

#### WP2 prohibitions

- [ ] Do not capture private modules or private members.
- [ ] Do not freeze exact exception messages that contain dynamic context.
- [ ] Do not freeze engine diagnostic strings.
- [ ] Do not depend on third-party API-diff libraries.
- [ ] Do not import test contract code from package runtime modules.
- [ ] Do not make a runtime signature change merely to simplify the snapshot.

#### WP2 required checks

```bash
uv run pytest -q tests/test_public_api_contract.py tests/test_public_api_typing.py
uv run python scripts/capture_public_api.py --check tests/data/public_api_2_0.json
uv run mypy src tests/typing/public_api_positive.py
uv run ty check src tests/typing/public_api_positive.py
uv run pytest -q
uv run prek run --all-files
```

#### WP2 exit criteria

- [ ] An accidental public export/signature/dataclass/exception/constant change fails CI.
- [ ] Typing overload regressions fail both mypy and `ty` checks.
- [ ] The manifest is stable across supported Python versions.
- [ ] The manifest encodes only approved public facts.
- [ ] No runtime behavior changes were needed.

**Suggested commit:** `Tests: freeze the aiogzip 2.0 public API contract`

### WP3 — Prove minimum dependencies and correct declared floors

**Goal:** demonstrate that the beta works with the oldest dependencies it claims to support, while retaining latest-dependency coverage.

**Primary files:**

```text
.github/workflows/ci.yml
pyproject.toml
uv.lock
scripts/report_runtime_versions.py
plans/dependencies/v2.0.0b1-minimum-dependencies.md
CHANGELOG.md
```

#### WP3 tasks

- [ ] Add a Python 3.11 minimum-dependency CI job.
- [ ] Build the candidate wheel before installing runtime floors.
- [ ] Install the wheel with `--no-deps`.
- [ ] Install exactly `aiofiles==23.1.0` in all minimum-runtime modes.
- [ ] Install exactly `aiocsv==1.2.0` in the CSV mode.
- [ ] Install exactly `zlib-ng==0.4.0` in fast modes.
- [ ] Print and assert exact installed versions.
- [ ] Verify base mode has no zlib-ng installation.
- [ ] Verify fast mode selects zlib-ng where expected.
- [ ] Verify forced-stdlib mode honors `AIOGZIP_ENGINE=stdlib` with zlib-ng installed.
- [ ] Run the full suite where practical; otherwise document and justify the selected minimum-version subset.
- [ ] Run maintained examples in at least one minimum-version mode.
- [ ] Run aiocsv integration at its floor.
- [ ] Run public API manifest and typing smoke checks at the minimum runtime floor.
- [ ] Record every exact command and result.
- [ ] Change metadata to `aiofiles>=23.1.0` only after the floor passes.
- [ ] Retain `aiocsv>=1.2.0` if passing.
- [ ] Retain `zlib-ng>=0.4.0` if passing.
- [ ] If an optional floor fails, capture a minimal reproduction before proposing a metadata raise.
- [ ] Preserve latest/unpinned dependency CI jobs.
- [ ] Update dependency-floor documentation and changelog.
- [ ] Refresh `uv.lock` under repository policy.

#### WP3 exit criteria

- [ ] Every declared runtime/optional floor is an actual release.
- [ ] Every declared floor is exercised in CI.
- [ ] The resolver cannot silently substitute a newer release.
- [ ] Latest-dependency testing remains in place.
- [ ] Wheel metadata contains the tested floors.
- [ ] No unnecessary floor increase occurred.

**Suggested commit:** `CI: test and declare the 2.0 minimum dependencies`

### WP4 — Publish the beta stability contract in documentation

**Goal:** align every active user-facing page with the first beta and make stability boundaries explicit.

**Primary files:**

```text
README.md
SECURITY.md
CHANGELOG.md
mkdocs.yml
docs/stability.md
docs/api.md
docs/codec.md
docs/migration.md
docs/errors.md
docs/streaming.md
docs/adr-sans-io-codec.md
```

#### WP4 tasks

- [ ] Add `docs/stability.md` to the documentation navigation.
- [ ] State the beta compatibility policy in plain language.
- [ ] List canonical public modules and imports.
- [ ] Explain that private `_` modules remain unstable.
- [ ] Explain diagnostic versus stable engine information.
- [ ] Explain exception-type and message-prefix guarantees.
- [ ] Explain dataclass, protocol, constant, and overload stability.
- [ ] Explain that examples are maintained but not package API.
- [ ] Remove active provisional-alpha wording from README.
- [ ] Remove active provisional-alpha wording from codec docs.
- [ ] Update API exact-Boolean history without implying it is newly changing in beta.
- [ ] Update migration language that previously deferred decisions until beta.
- [ ] Update the ADR status to accepted/frozen for 2.0 beta without rewriting its historical rationale.
- [ ] Update security support rows.
- [ ] Add a `2.0.0b1` changelog section.
- [ ] Add correct release comparison links.
- [ ] Keep historical alpha references in historical records.
- [ ] Run a targeted repository search for stale status language.
- [ ] Run strict docs build.
- [ ] Run Markdown lint/hooks.
- [ ] Verify every public API link and code sample.
- [ ] Ensure docs do not overstate beta as stable production software.

#### WP4 required checks

```bash
uv run mkdocs build --strict
uv run ruff check .
uv run ruff format --check .
uv run prek run --all-files
rg -n --glob '!plans/**' --glob '!CHANGELOG.md'   '(provisional 2\.0 alpha|throughout 2\.0 alpha|before the API reaches beta|Development Status :: 3)'   README.md SECURITY.md docs mkdocs.yml pyproject.toml
```

#### WP4 exit criteria

- [ ] Active documentation consistently describes the release as beta.
- [ ] Stability and non-guarantees are explicit.
- [ ] No historical release record was rewritten misleadingly.
- [ ] Strict documentation build passes.
- [ ] Docs match the machine-readable API decision record.

**Suggested commit:** `Docs: define the aiogzip 2.0 beta stability contract`

### WP5 — Validate installed artifacts and downstream-facing integrations

**Goal:** prove that users receive the frozen API, examples, metadata, and integrations from wheel and sdist installations—not just from a source checkout.

**Primary files:**

```text
scripts/smoke_installed_artifact.py
scripts/run_maintained_examples.py
tests/test_installed_artifact.py
.github/workflows/ci.yml
examples/README.md
plans/reviews/v2.0.0b1-installed-artifacts.md
```

#### WP5 artifact matrix

At minimum, validate:

| Artifact | Platform | Python | Dependency mode |
| --- | --- | --- | --- |
| wheel | Linux | 3.11 | minimum/base |
| wheel | Linux | 3.14 | latest/base |
| wheel | Linux | 3.12 | latest/fast |
| wheel | Windows | 3.12 | latest/base |
| wheel | macOS | 3.12 | latest/base |
| sdist-built install | Linux | 3.12 | latest/base |
| sdist-built install | Linux | 3.12 | latest/fast |

The existing platform matrix may absorb some rows; avoid gratuitous duplication.

#### WP5 tasks

- [ ] Build wheel and sdist from a clean checkout.
- [ ] Inspect the exact sdist file list and record whether `examples/README.md`, `examples/fragmented_transport.py`, and `examples/concurrent_jsonl_ingest.py` are present.
- [ ] If maintained examples are absent from the sdist, add `examples/` to the flit sdist include policy and test it.
- [ ] Confirm maintained examples are not installed into the `aiogzip` package namespace in the wheel.
- [ ] Create clean virtual environments outside the repository.
- [ ] Install artifacts without editable mode.
- [ ] Run from a working directory outside the repository.
- [ ] Assert `aiogzip.__file__` is inside the clean environment.
- [ ] Assert package metadata version and dependency requirements.
- [ ] Run top-level import and public API manifest smoke checks.
- [ ] Run binary and text file read/write smoke tests.
- [ ] Run codec encode/decode and standard-library interoperability smoke tests.
- [ ] Run `compress_chunks()` and `decompress_chunks()` smoke tests.
- [ ] Run `inspect()` and `verify()` against valid and corrupt fixtures.
- [ ] Run the fragmented-transport maintained example.
- [ ] Run fragmented-transport corruption and truncation scenarios.
- [ ] Run the concurrent-ingest maintained example.
- [ ] Run concurrent-ingest corruption, truncation, cancellation, and limit scenarios.
- [ ] Verify maintained examples use only public aiogzip imports.
- [ ] Run CLI inspect/verify commands from the installed artifact when applicable.
- [ ] Run the aiocsv integration from an installed artifact.
- [ ] Run the tarfile-style integration from an installed artifact.
- [ ] Verify zlib-ng active and forced-stdlib behavior in clean environments.
- [ ] Record exact artifact path, size, SHA-256, Python, OS, and dependency versions.
- [ ] Do not treat example output wording as frozen API.

#### WP5 exit criteria

- [ ] Both artifact types import and behave correctly outside the checkout.
- [ ] The sdist contains the maintained example sources and runbook.
- [ ] The wheel remains a library artifact without an accidental examples package.
- [ ] Both maintained examples run from installed artifacts.
- [ ] Public API manifest matches the candidate artifact.
- [ ] Minimum and latest dependency modes pass their intended paths.
- [ ] No undeclared runtime dependency is imported.
- [ ] No example requires private aiogzip hooks.

**Suggested commit:** `Tests: validate beta artifacts and maintained integrations`

### WP6 — Run correctness, engine, platform, memory, and performance hardening

**Goal:** prove that the contract-freeze and packaging work did not regress `a4`.

**Primary evidence:**

```text
plans/benchmarks/v2.0.0b1-candidate.md
plans/benchmarks/data/v2.0.0b1-candidate-stdlib.json
plans/benchmarks/data/v2.0.0b1-candidate-zlib-ng.json
plans/reviews/v2.0.0b1-hardening.md
```

#### WP6 correctness matrix

- [ ] Full test suite passes on Python 3.11, 3.12, 3.13, and 3.14 on Linux.
- [ ] Representative full suite passes on Windows.
- [ ] Representative full suite passes on macOS.
- [ ] Full stdlib-zlib path passes with zlib-ng absent.
- [ ] Active zlib-ng path passes.
- [ ] Forced stdlib path passes while zlib-ng is installed.
- [ ] Property-based valid-stream tests pass.
- [ ] Malformed header, body, trailer, CRC, ISIZE, FHCRC, reserved-flag, padding, and trailing-data tests pass.
- [ ] Concatenated-member tests pass.
- [ ] Completed-member metadata retention tests pass.
- [ ] Live `mtime` tests pass across concatenated members and rewind.
- [ ] Codec operation abandonment and discard tests pass with GC disabled.
- [ ] Same-handle overlap tests pass for binary and text handles.
- [ ] Cancellation and poisoning tests pass.
- [ ] Recovery-data sequencing tests pass.
- [ ] Seek and rewind-cache tests pass.
- [ ] Text cookie and newline tests pass.
- [ ] Partial sink-write and sink-error timing tests pass.
- [ ] Strict-size and decompression-limit tests pass.
- [ ] Public API contract tests pass on every supported Python version.
- [ ] Minimum-dependency jobs pass.
- [ ] Coverage remains at or above the configured floor.

#### WP6 performance matrix

- [ ] Representative `decompress_chunks()` 512/256 KiB row is compared with exact `a4`.
- [ ] Representative `decompress_chunks()` 64/64 KiB row is compared with exact `a4`.
- [ ] Representative `compress_chunks()` rows are compared with exact `a4`.
- [ ] Direct one-large-feed decoder scaling is compared with exact `a4`.
- [ ] Transport-sized decoder input is compared with exact `a4`.
- [ ] One-item async-source scheduler responsiveness is compared with exact `a4`.
- [ ] Fragmented optional-header time and peak allocation are compared with exact `a4`.
- [ ] Full binary read peak allocation is compared with exact `a4`.
- [ ] Concurrent independent-stream throughput is compared with exact `a4`.
- [ ] Bounded JSONL batching is compared with exact `a4`.
- [ ] Write-size curve from 10 B through 256 KiB is compared with exact `a4`.
- [ ] Extreme one-call-per-10-byte diagnostic is retained.
- [ ] Every correctness-bearing benchmark verifies output length and digest.
- [ ] Every slowdown over 5% has a written investigation.
- [ ] Every slowdown over 10% blocks release.
- [ ] New API-contract and artifact tests are not presented as performance improvements.

#### WP6 issue `#86` closeout

- [ ] Candidate retains same-call write visibility and error timing.
- [ ] No hidden cross-call buffer exists.
- [ ] The 10-byte diagnostic does not regress more than 10% against exact `a4`.
- [ ] The 10-byte diagnostic remains in the continuing benchmark matrix after issue closure.
- [ ] Documentation recommends `writelines()` or explicit bounded application batching for tiny records.
- [ ] `plans/reviews/issue-86-b1-closeout.md` records the current issue state and cites the authoritative `a4` disposition.
- [ ] The closeout record contains an exact final comment that does not claim the historical regression was eliminated.
- [ ] The final comment states the retained strict same-call semantics and the controlled `a3` → `a4` results: 5.38% faster with forced stdlib zlib and 0.36% slower with zlib-ng.
- [ ] The closeout record instructs the maintainer to leave the original issue body unchanged.
- [ ] The closeout record instructs the maintainer to close issue `#86` as **Not planned** or the repository’s equivalent accepted-design-tradeoff resolution, not Completed.
- [ ] The closeout record does not retarget `#86` and does not propose a separate buffered-writer issue absent concrete demand or a developed API proposal.
- [ ] The handoff is idempotent: when an equivalent closeout already exists remotely, it records the existing comment URL and closure instead of requesting duplication.
- [ ] Codex does not perform any remote issue action.

#### WP6 exit criteria

- [ ] All correctness and API-contract gates pass.
- [ ] All required engines and platforms pass.
- [ ] All named performance rows satisfy policy or the release is blocked.
- [ ] No new memory or scheduler regression is present.
- [ ] Issue `#86` has a complete maintainer-ready closeout record, and its tiny-write benchmark remains an active anti-regression gate.

**Suggested commit:** `Release: record 2.0.0b1 hardening and regression evidence`

### WP7 — Obtain independent beta-contract review

**Goal:** have a reviewer who did not author or generate the implementation assess what is being frozen.

The review must cover the actual candidate commit, not an earlier code head.

#### WP7 reviewer checklist

- [ ] Reviewer confirms the public API inventory matches actual exports and docs.
- [ ] Reviewer examines every retain/diagnostic/private decision.
- [ ] Reviewer examines the runtime manifest schema and exclusions.
- [ ] Reviewer examines overload/type-contract fixtures.
- [ ] Reviewer examines `ConcurrentOperationError` inheritance and guidance.
- [ ] Reviewer examines codec operation ownership and cleanup wording.
- [ ] Reviewer examines cancellation, poisoning, recovery-data, and write-error timing statements.
- [ ] Reviewer examines dataclass and metadata contracts.
- [ ] Reviewer examines minimum-dependency CI and exact installed-version assertions.
- [ ] Reviewer runs or inspects installed-artifact smoke evidence.
- [ ] Reviewer inspects both maintained examples for public-only API use.
- [ ] Reviewer inspects stale alpha/provisional wording search results.
- [ ] Reviewer confirms no material lifecycle redesign is concealed in the beta candidate.
- [ ] Reviewer confirms AnyIO, indexed access, and buffered-writer work remain deferred.
- [ ] Reviewer records approval, requested changes, or blocking findings against the exact SHA.

#### WP7 response to findings

- [ ] Every finding has an owner and disposition.
- [ ] Corrective commits invalidate prior approval until the reviewer covers the new head.
- [ ] A material contract finding triggers the beta escalation rule and likely `a5`.
- [ ] Review evidence names the reviewer, date, exact commit, scope, commands, and conclusion.
- [ ] Codex does not claim the review complete on the reviewer's behalf.

#### WP7 exit criteria

- [ ] At least one genuinely independent human approval covers the final candidate.
- [ ] No unresolved blocking review finding remains.
- [ ] The review explicitly supports the `b1` freeze decision.

**Suggested commit:** `Review: record independent 2.0.0b1 contract approval`

### WP8 — Prepare and validate the `2.0.0b1` release candidate

**Goal:** produce the exact candidate artifacts, documentation, changelog, and evidence without performing maintainer-only publication.

#### WP8 release preparation

- [ ] Set `__version__` to `2.0.0b1`.
- [ ] Set the Development Status classifier to Beta.
- [ ] Finalize the `2.0.0b1` changelog date and section.
- [ ] Ensure changelog comparison links are correct.
- [ ] Ensure README and docs describe beta consistently.
- [ ] Ensure `SECURITY.md` supports the latest beta line.
- [ ] Ensure dependency floors match tested floors.
- [ ] Run version-sync tests.
- [ ] Run full lint, formatting, typing, docs, and test suites.
- [ ] Run public API contract generation in check mode.
- [ ] Build wheel and sdist from a clean checkout.
- [ ] Run `twine check` or repository-equivalent metadata validation.
- [ ] Inspect wheel and sdist file lists.
- [ ] Confirm `py.typed` is present.
- [ ] Confirm examples, docs, changelog, security policy, and required source files are included according to packaging policy.
- [ ] Confirm no benchmark raw data or local artifacts are accidentally packaged unless intended.
- [ ] Install wheel and sdist in clean environments.
- [ ] Run installed-artifact matrix.
- [ ] Build artifacts a second time with identical `SOURCE_DATE_EPOCH`.
- [ ] Compare wheel hashes exactly.
- [ ] Compare sdist hashes exactly.
- [ ] Record sizes and SHA-256 values.
- [ ] Record exact source commit and clean status.
- [ ] Record all CI workflow run identifiers once available.
- [ ] Prepare GitHub release notes.
- [ ] Prepare PyPI smoke commands.
- [ ] Prepare documentation-deployment verification commands.

#### WP8 release-note content

- [ ] Explain that this is the first beta and the 2.0 public API is frozen.
- [ ] Summarize the machine-readable API and typing contract.
- [ ] Summarize minimum-dependency CI and the corrected `aiofiles>=23.1.0` floor.
- [ ] Summarize beta documentation and support-policy updates.
- [ ] State that runtime behavior is intentionally preserved from `a4`.
- [ ] State that AnyIO/Trio and indexed access remain deferred.
- [ ] State the small-write semantics and batching recommendation without claiming the historical difference from `v1.11.0` was optimized away.
- [ ] State that issue `#86` is being closed as an accepted 2.0 design tradeoff, while the tiny-write benchmark remains part of regression testing.
- [ ] Link the maintained examples.
- [ ] Include Python and engine support.
- [ ] Include artifact hashes and provenance after publication evidence exists.
- [ ] Avoid new benchmark marketing claims unsupported by candidate evidence.

#### WP8 exit criteria

- [ ] The candidate version and classifier are correct.
- [ ] All release gates pass on the exact candidate SHA.
- [ ] Artifacts are reproducible.
- [ ] Wheel and sdist installed tests pass.
- [ ] Independent approval covers the exact candidate.
- [ ] No maintainer-only action is falsely marked complete.

**Suggested commit:** `Release: prepare aiogzip 2.0.0b1`

### WP9 — Maintainer publication and post-release handoff

Codex prepares this checklist but must not execute remote publication actions unless separately and explicitly authorized through an available tool and repository policy.

#### Maintainer publication checklist

- [ ] Merge the final candidate through the protected repository workflow.
- [ ] Verify required checks pass on the exact merge commit.
- [ ] Create a signed `v2.0.0b1` tag pointing to the intended commit.
- [ ] Verify the tag signature.
- [ ] Verify tag-triggered documentation workflow succeeds.
- [ ] Verify tag-triggered Trusted Publishing succeeds.
- [ ] Verify PyPI shows wheel and sdist for `2.0.0b1`.
- [ ] Verify PyPI attestations reference the correct repository, workflow, tag, filenames, and hashes.
- [ ] Compare published artifact hashes with the committed release record.
- [ ] Install public PyPI wheel in a clean environment.
- [ ] Run version, import-path, codec, file, streaming, inspect, verify, and maintained-example smoke tests.
- [ ] Verify public documentation displays beta wording and the stability page.
- [ ] Publish or finalize GitHub release notes.
- [ ] Confirm the original title and description of issue `#86` remain unchanged.
- [ ] Post the approved final disposition comment from `plans/reviews/issue-86-b1-closeout.md`, unless an equivalent comment is already present.
- [ ] Close issue `#86` as **Not planned** or the repository’s equivalent accepted-design-tradeoff resolution, not Completed.
- [ ] Record the final comment URL, closure state, closure reason, and timestamp in the release evidence.
- [ ] Do not retarget issue `#86` or open a buffered-writer follow-up without concrete user demand or a separately reviewed API proposal.
- [ ] Leave `#71` and `#72` deferred unless separately reprioritized.

#### Post-release development checklist

- [ ] Create a small post-release housekeeping change.
- [ ] Advance `main` to `2.0.0b2.dev0` by default.
- [ ] Make Unreleased compare from `v2.0.0b1`.
- [ ] Retain Beta classifier during beta development.
- [ ] Record exact tag, merge, workflow, artifact, attestation, docs, and PyPI evidence.
- [ ] Do not decide `rc1` solely from elapsed time; use beta feedback and contract evidence.
- [ ] Use `b2` when a compatible code or public-contract correction is needed.
- [ ] Allow a later plan to skip public `b2` and proceed to `rc1` only when no code/contract correction is required.

## 10. Release gates

### 10.1 Public API and typing

- [ ] Approved top-level and codec public inventories are complete.
- [ ] Runtime contract manifest matches the candidate.
- [ ] Typing fixtures pass mypy and `ty`.
- [ ] No undocumented public export was accidentally removed.
- [ ] No private implementation detail was accidentally frozen.
- [ ] Public dataclass, protocol, exception, constant, and overload contracts are documented.
- [ ] Engine diagnostic strings are explicitly excluded from machine-readable compatibility promises.
- [ ] No material lifecycle or signature change remains unresolved.

### 10.2 Documentation and metadata

- [ ] Active docs no longer describe the current API as alpha/provisional.
- [ ] Beta stability and non-guarantees are documented.
- [ ] README, API, codec, migration, errors, streaming, ADR, and security pages agree.
- [ ] Historical alpha records remain historically accurate.
- [ ] Version is `2.0.0b1` on the release candidate.
- [ ] Classifier is Beta.
- [ ] Changelog and comparison links are correct.
- [ ] Security support matrix is current.

### 10.3 Dependencies and installation

- [ ] `aiofiles==23.1.0` passes the minimum-runtime suite.
- [ ] `aiocsv==1.2.0` passes the optional CSV suite.
- [ ] `zlib-ng==0.4.0` passes the optional fast-engine suite.
- [ ] Forced stdlib works with zlib-ng installed at its floor.
- [ ] Metadata declares only tested floors.
- [ ] Latest/unpinned dependency CI also passes.
- [ ] Wheel and sdist install cleanly.
- [ ] The sdist contains maintained examples; the wheel contains only the intended library/package data.
- [ ] Installed tests import from the environment, not the checkout.
- [ ] No undeclared runtime dependency is required.

### 10.4 Correctness, platforms, and engines

- [ ] Python 3.11–3.14 Linux matrix passes.
- [ ] Representative Windows matrix passes.
- [ ] Representative macOS matrix passes.
- [ ] Stdlib-only engine mode passes.
- [ ] Active zlib-ng mode passes.
- [ ] Forced-stdlib-with-zlib-ng mode passes.
- [ ] Full integrity and malformed-stream suite passes.
- [ ] Cancellation, poisoning, overlap, recovery, seek, text, and write-error suites pass.
- [ ] Maintained integrations pass their success and failure scenarios.
- [ ] Coverage remains above the configured floor.

### 10.5 Performance and resources

- [ ] All comparable exact-`a4` rows are within 5%, or investigated when over 5%.
- [ ] No comparable row is more than 10% slower.
- [ ] Large-feed scaling remains linear.
- [ ] Optional-header processing remains bounded.
- [ ] Scheduler responsiveness remains within established gates.
- [ ] Peak memory remains within established gates.
- [ ] Concurrent-stream and JSONL batching behavior remains within established gates.
- [ ] Tiny-write diagnostic does not regress more than 10% from `a4`.
- [ ] No hidden buffering or semantics change was used to obtain a timing result.

### 10.6 Review, artifacts, and provenance

- [ ] Independent human approval covers the exact candidate.
- [ ] All blocking findings are resolved.
- [ ] Wheel and sdist pass metadata checks.
- [ ] Two independent builds produce identical hashes.
- [ ] Artifact sizes and SHA-256 values are committed.
- [ ] Installed-artifact matrix passes.
- [ ] Tag, Trusted Publishing, attestation, docs, and public-PyPI checks remain maintainer-only until actually completed.

### 10.7 Beta go/no-go

Release `2.0.0b1` only when every preceding gate is complete.

Choose `2.0.0a5` instead when:

- a maintained integration or contract test reveals a recurring ownership problem;
- a public signature/default/type must change incompatibly;
- exception timing or poisoning must change;
- output visibility or write buffering semantics must change;
- the operation iterator design needs revision;
- a documented public export must be removed without a compatibility path;
- a substantial engine, scheduler, or buffering redesign is required.

Delay the candidate without changing version stage when the only blockers are missing CI, review, artifact, documentation, or release evidence.

## 11. Risk register

| ID | Risk | Likelihood | Impact | Mitigation / release gate |
| --- | --- | --- | --- | --- |
| R1 | API snapshot overfreezes incidental implementation details | Medium | High | Curated schema, explicit exclusions, reviewer approval |
| R2 | Runtime introspection misses overload/type regressions | High without mitigation | High | Separate mypy and `ty` contract fixtures |
| R3 | Manifest differs across Python versions due to annotation/default representation | Medium | Medium | Structured normalization and 3.11–3.14 tests |
| R4 | A last-minute API cleanup causes unnecessary beta churn | Medium | High | Default-retain policy and explicit decision record |
| R5 | Declared dependency floor is untested or nonexistent | High today | Medium | Exact minimum-version CI and metadata correction |
| R6 | Resolver silently installs newer dependencies | Medium | High | `--no-deps`, exact pins, installed-version assertions |
| R7 | Installed-artifact tests import source checkout | Medium | High | External working directory and `aiogzip.__file__` assertion |
| R8 | Active docs continue to call the API provisional alpha | High today | Medium | Repository-wide status-language audit |
| R9 | Beta wording overpromises production stability | Medium | Medium | Dedicated stability page and review |
| R10 | Contract work accidentally changes runtime behavior | Low–medium | High | Exact `a4` tests, benchmarks, and escalation rule |
| R11 | Tiny-write benchmark prompts hidden buffering or a misleading “fixed” issue closure | Medium | High | Preserve exact write semantics and benchmark gate; close `#86` only as Not planned / accepted tradeoff with evidence |
| R12 | Engine diagnostic strings become accidentally frozen | Medium | Medium | Explicit manifest exclusion and docs |
| R13 | Minimum zlib-ng release behaves differently from current release | Medium | High | Active and forced-stdlib floor jobs |
| R14 | Artifact reproducibility regresses during metadata changes | Low–medium | High | Dual build with exact hash comparison |
| R15 | Review covers an obsolete candidate head | Medium | High | Record exact SHA and renew review after changes |
| R16 | One large PR becomes impossible to review | Medium | High | Small review units and ordinary diffs |
| R17 | Historical alpha records are rewritten inaccurately | Low | Medium | Restrict status cleanup to active docs |
| R18 | A real incompatible defect is rationalized into beta | Low–medium | Critical | Mandatory stop-and-recommend-`a5` rule |
| R19 | New feature work obscures beta closeout | Medium | High | Explicit exclusions for AnyIO, indexing, engines, buffering |
| R20 | Postrelease evidence is marked complete before publication | Medium | High | Maintainer-only checklist and no fabricated evidence |

## 12. Definition of done

- [ ] The exact starting boundary and PR `#95` status are recorded.
- [ ] The `a4` API and performance baselines are immutable and inspectable.
- [ ] Every documented public export has an approved beta decision.
- [ ] A deterministic runtime contract manifest protects the approved API.
- [ ] Mypy and `ty` fixtures protect overload and protocol behavior.
- [ ] Minimum-dependency CI proves every declared floor.
- [ ] `aiofiles` metadata uses the oldest actual tested release.
- [ ] Latest-dependency CI remains active.
- [ ] A beta stability page is published and linked.
- [ ] Active alpha/provisional wording is removed or explicitly retained with rationale.
- [ ] Security support policy is current.
- [ ] Both maintained examples pass from wheel and sdist installations.
- [ ] Maintained example sources and runbook are included in the sdist without polluting the wheel package namespace.
- [ ] Public API, correctness, engine, platform, cancellation, memory, and performance gates pass.
- [ ] Issue `#86` has a maintainer-ready final comment and explicit **Not planned / accepted design tradeoff** closeout, with the original issue history preserved and the benchmark gate retained.
- [ ] Independent review approves the exact candidate.
- [ ] Candidate uses version `2.0.0b1` and Beta classifier.
- [ ] Wheel and sdist are reproducible and pass clean-install smoke tests.
- [ ] Release notes and hashes are prepared.
- [ ] Codex has not claimed remote publication or review actions it did not perform.
- [ ] The maintainer handoff clearly distinguishes completed local work from pending remote work.

## 13. Suggested pull-request and commit sequence

A practical sequence:

1. **PR A — Beta baseline and API decisions**
   - reconcile PR `#95`;
   - add this plan;
   - capture preflight evidence;
   - approve public API inventory.

2. **PR B — Contract protection**
   - runtime API manifest;
   - typing fixtures;
   - CI integration.

3. **PR C — Dependency floors**
   - minimum-version jobs;
   - `aiofiles>=23.1.0`;
   - floor evidence.

4. **PR D — Beta documentation**
   - stability page;
   - alpha/provisional wording;
   - security and metadata preparation.

5. **PR E — Artifact and integration validation**
   - clean wheel/sdist tests;
   - maintained examples;
   - downstream smoke paths.

6. **PR F — Release candidate**
   - final benchmark/hardening evidence;
   - independent approval;
   - version/classifier/changelog;
   - reproducible artifacts and handoff.

The repository may use a different branch structure, but keep the conceptual review boundaries.

## 14. Ready-to-paste Codex kickoff prompt

```text
Implement aiogzip 2.0.0b1 according to
plans/RELEASE_2_0_0B1_PLAN.md.

Treat the plan's locked tag and commit references, beta escalation rule,
fixed design decisions, regression gates, scope boundaries, and work-package
ordering as authoritative.

Begin with section 0 and WP0. Verify v2.0.0a4 at
262d9a5a0eb5f84fc54432e968b845b182fd255c. Determine whether PR #95's
housekeeping commit f3e4cef76cb44b5b667bd2f63b137ca48ef5f09d is already
present. Do not duplicate it or silently adapt to unrelated changes. Record
the actual starting commit and diff.

Capture exact-v2.0.0a4 public API and benchmark evidence before changing beta
documentation, classifier, signatures, or dependency metadata.

This is an API-freeze and distribution-validation release, not a feature
release. Preserve every v2.0.0a4 lifecycle, ownership, cancellation, poisoning,
recovery-data, integrity, output-bound, metadata, mtime, write-visibility,
engine, memory, and performance invariant.

Create a deliberate public API decision record, then add a curated deterministic
runtime contract manifest and mypy/ty typing-contract fixtures. Do not freeze
private details, complete dynamic error messages, literal version values, or
engine diagnostic strings.

Add an exact minimum-dependency CI matrix. Prove aiofiles 23.1.0, aiocsv 1.2.0,
and zlib-ng 0.4.0 before changing metadata. Keep latest/unpinned dependency CI.

Update active documentation from alpha/provisional status to a precise beta
stability contract, but do not call the package production stable or rewrite
historical alpha records.

Run both maintained integrations from clean wheel and sdist installations
outside the source checkout. Assert aiogzip.__file__ points into the clean
environment.

If any required work changes a public signature, accepted type, default,
lifecycle, operation ownership, cancellation/poisoning, exception timing,
write visibility, output bounds, metadata meaning, or other material contract,
STOP and recommend 2.0.0a5. Do not hide that change in b1.

Keep each work package green. Update checklist entries in the same commit as
their implementation or evidence. Stop rather than silently pulling later
packages forward. Do not fabricate benchmark, CI, platform, engine, artifact,
review, tag, release, documentation, PyPI, or attestation evidence.

For issue #86, preserve the original issue body, create
plans/reviews/issue-86-b1-closeout.md with the exact evidence-based final
comment, and instruct the maintainer to close the issue as Not planned / an
accepted 2.0 design tradeoff. Do not retarget it, do not claim the historical
regression was eliminated, and keep the tiny-write benchmark as an active
anti-regression row. Do not open a buffered-writer issue without concrete user
demand or a separately reviewed API proposal. Codex must not perform the remote
issue action.

Do not implement AnyIO/Trio, indexed access, default buffered writes, a new
engine, raw DEFLATE, a pull-style codec, or unrelated cleanup. Do not perform
remote maintainer actions such as issue changes, PR merges, tags, releases,
publishing, docs deployment, or repository settings changes.
```

## 15. Command matrix

Use repository-provided commands when they differ. Record every command actually run.

### 15.1 Fast local validation

```bash
uv run pytest -q tests/test_version_sync.py tests/test_public_api_contract.py tests/test_public_api_typing.py
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests/typing/public_api_positive.py
uv run ty check src tests/typing/public_api_positive.py
uv run mkdocs build --strict
uv run prek run --all-files
```

### 15.2 Full local validation

```bash
uv run pytest --cov --cov-report=term-missing --cov-fail-under=85
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run ty check src
uv run mkdocs build --strict
uv run prek run --all-files
```

### 15.3 Artifact validation

```bash
rm -rf dist build
SOURCE_DATE_EPOCH="$EPOCH" uv build
uv run python -m twine check dist/*

python -m venv /tmp/aiogzip-b1-wheel
/tmp/aiogzip-b1-wheel/bin/python -m pip install --upgrade pip
/tmp/aiogzip-b1-wheel/bin/python -m pip install dist/*.whl
cd /tmp
/tmp/aiogzip-b1-wheel/bin/python -c 'import aiogzip; print(aiogzip.__version__, aiogzip.__file__)'

python -m venv /tmp/aiogzip-b1-sdist
/tmp/aiogzip-b1-sdist/bin/python -m pip install --upgrade pip
/tmp/aiogzip-b1-sdist/bin/python -m pip install /path/to/dist/*.tar.gz
cd /tmp
/tmp/aiogzip-b1-sdist/bin/python -c 'import aiogzip; print(aiogzip.__version__, aiogzip.__file__)'
```

### 15.4 Reproducibility

```bash
rm -rf /tmp/aiogzip-build-1 /tmp/aiogzip-build-2
mkdir -p /tmp/aiogzip-build-1 /tmp/aiogzip-build-2

SOURCE_DATE_EPOCH="$EPOCH" uv build --out-dir /tmp/aiogzip-build-1
SOURCE_DATE_EPOCH="$EPOCH" uv build --out-dir /tmp/aiogzip-build-2

sha256sum /tmp/aiogzip-build-1/* /tmp/aiogzip-build-2/*
cmp /tmp/aiogzip-build-1/*.whl /tmp/aiogzip-build-2/*.whl
cmp /tmp/aiogzip-build-1/*.tar.gz /tmp/aiogzip-build-2/*.tar.gz
```

## 16. Source references used to prepare this plan

- Repository: https://github.com/geoff-davis/aiogzip
- `v2.0.0a4` release: https://github.com/geoff-davis/aiogzip/releases/tag/v2.0.0a4
- `v2.0.0a4` merge commit: https://github.com/geoff-davis/aiogzip/commit/262d9a5a0eb5f84fc54432e968b845b182fd255c
- Post-release housekeeping PR `#95`: https://github.com/geoff-davis/aiogzip/pull/95
- Housekeeping commit: https://github.com/geoff-davis/aiogzip/commit/f3e4cef76cb44b5b667bd2f63b137ca48ef5f09d
- `a4` release plan: https://github.com/geoff-davis/aiogzip/blob/v2.0.0a4/plans/RELEASE_2_0_0A4_PLAN.md
- Public API docs: https://github.com/geoff-davis/aiogzip/blob/v2.0.0a4/docs/api.md
- Codec docs: https://github.com/geoff-davis/aiogzip/blob/v2.0.0a4/docs/codec.md
- Current CI: https://github.com/geoff-davis/aiogzip/blob/v2.0.0a4/.github/workflows/ci.yml
- Current package metadata: https://github.com/geoff-davis/aiogzip/blob/v2.0.0a4/pyproject.toml
- Small-write issue `#86`: https://github.com/geoff-davis/aiogzip/issues/86
- AnyIO decision `#71`: https://github.com/geoff-davis/aiogzip/issues/71
- Indexed access `#72`: https://github.com/geoff-davis/aiogzip/issues/72
- aiofiles release history: https://pypi.org/project/aiofiles/#history
- aiocsv release history: https://pypi.org/project/aiocsv/#history
- zlib-ng release history: https://pypi.org/project/zlib-ng/#history

## 17. Final maintainer decision record

Complete this section only after all candidate evidence exists.

| Question | Decision | Evidence |
| --- | --- | --- |
| Does `b1` preserve `a4` runtime behavior? | Pending | |
| Is every documented public symbol deliberately classified? | Pending | |
| Do runtime and typing contract tests pass? | Pending | |
| Do minimum dependency floors pass? | Pending | |
| Are active docs beta-correct? | Pending | |
| Do wheel and sdist installed tests pass? | Pending | |
| Do both maintained integrations pass from artifacts? | Pending | |
| Do all engine/platform/correctness gates pass? | Pending | |
| Do all performance/resource gates pass? | Pending | |
| Does independent review approve the exact candidate? | Pending | |
| Is any material contract redesign still expected? | Pending | |
| Release `2.0.0b1`, return to `a5`, or delay for evidence? | Pending | |

The correct outcome is evidence-driven:

- **Release `2.0.0b1`** when all gates pass and no material redesign remains.
- **Return to `2.0.0a5`** when a material public-contract change is required.
- **Delay without changing stage** when only missing CI, review, docs, artifact, or publication evidence remains.
