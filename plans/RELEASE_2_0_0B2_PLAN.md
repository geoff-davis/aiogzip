# aiogzip 2.0.0b2: Correctness, Performance, and File-State Plan

> **Revision 2 — 2026-09-07. Supersedes the September 1 b2 plan.**
> **Status:** WP0–WP4 completed locally; WP5 onward and release qualification remain pending.
> **Target:** `2.0.0b2`.
> **Commit this file as:** `plans/RELEASE_2_0_0B2_PLAN.md`.
> **Historical reviewed starting point:** `dc8950cb334e1cf4082f2bf50074464e06c72287`.
> **Public API baseline:** `v2.0.0b1` / `048700fe9f6030f8a2b6da92b685bcd108a17dd1`.
> **Historical alpha:** `v2.0.0a4` / `262d9a5a0eb5f84fc54432e968b845b182fd255c`.
> **Expected version at the reviewed starting point:** `2.0.0b2.dev0`.
> These are review anchors, not a claim that GitHub `main` still points to them.

## Release decision

Keep `2.0.0b2`, but change its objective from an exclusively behavior-preserving
refactor to **targeted correctness and performance repairs followed by a protected
file-state refactor**.

The public API frozen in b1 remains the signature/type/lifecycle compatibility
baseline. Existing unsafe behavior is not made permanent by recording it in a golden
trace. Confirmed defects receive narrow, explicitly recorded behavioral exceptions;
unaffected behavior remains protected.

Execute in this order:

```text
preflight + corrected test oracle
    -> native-work cancellation ownership
    -> source-I/O and opening ownership
    -> small-hint readlines complexity repair
    -> long-line, read-ahead, and stream-fairness qualification
    -> pin corrected reference C0
    -> binary read health
    -> text replay origin and text/binary bridge
    -> hot-path parity + full qualification
    -> external review + b2 publication
```

The state refactor must not begin while the new correctness questions are unresolved.
The large, demand-bounded-reader redesign is NOT a default b2 deliverable. Measure
current read-ahead, enforce existing limits, and record the decision before designing
an operation continuation across file calls.

### What changed in this revision

* Adds real-thread and whole-loop-shutdown cancellation tests; a cancelled asyncio
  helper is not accepted as proof that native work has stopped.
* Adds consumed-but-undelivered source input and acquisition/close races as explicit
  correctness questions, including a concatenated-member data-loss fixture.
* Makes the reproduced small-hint pending-line complexity problem a targeted repair,
  with structural work-count tests as well as timings.
* Adds long-line scaling, highly compressible partial reads, and across-item fairness.
* Replaces raw text-cookie equality with symbolic, per-handle cookie round trips.
* Separates semantic compatibility from diagnostic batching/call-count observations.
* Resolves the binary/text package dependency with temporary read-only accessors.
* Makes binary health authoritative instead of mandating another cached enum in text.
* Consolidates acceptance criteria in one gate register; work packages refer to those
  IDs rather than repeating the entire release checklist.

## 0. Evidence and scope of the review

### 0.1 Inputs and evidence levels

The supplied review is a reason to investigate, not a substitute for running the
package. Use this table in the preflight record without upgrading an observation into
a stronger claim.

| ID | Observation | Evidence supplied | Required next step |
| --- | --- | --- | --- |
| F1 | Cancelling caller and helper can allow cleanup while executor work runs | Isolated `_offloaded_next` control-flow reproduction using a blocked real thread | Reproduce through actual package driver; test whole-loop shutdown |
| F2 | Cancelled read can consume bytes without delivering them | Installed-aiofiles probe; aiogzip consequence not yet run | Test actual package with `member A` followed by `member B` and native I/O |
| F3 | Concurrent opens / close during opening can lose resource ownership | Source-level finding; packaged probe not run | Deterministic acquisition, initialization, cancellation, and close tests |
| F4 | Repeated small-hint `readlines()` rescans/copies the pending suffix | Isolated source-extracted helper; quadratic timings | Reproduce in package and repair aggregate work complexity |
| F5 | Generic newline paths may copy growing long-line strings repeatedly | Source-level concern | End-to-end scaling and allocation measurements |
| F6 | A tiny file read may inflate/buffer a whole compressed source item | Source-level finding; fixture generated | Measure actual partial-read memory, read-ahead, and first-result latency |
| F7 | Immediately ready, empty, or tiny source items can evade fairness budgets | Source-level concern; packaged probe not run | Deterministic sibling-progress and cancellation tests on both stream wrappers |
| F8 | Golden traces contain handle-specific cookies and incidental I/O counts | Plan/source mismatch identified in review | Correct oracle before capturing a baseline |
| F9 | Early binary field removal breaks later text migration | Plan dependency mismatch | Install temporary derived accessors, remove during bridge migration |

The prior Fable review reported 2,337 passing tests, one skip, both engines on Python
3.12, and 93% overall coverage. Preserve that as attributed historical evidence.
Do not use it as a candidate result or a required exact test count.

This revision edits the supplied plan using the supplied review and probe notes. It
does not claim a fresh repository audit or newly executed package tests.

### 0.2 Probe archive

The companion input is `AIOGZIP_B2_REVIEW_PROBES.zip`:

```text
SHA-256: 94c41cc4389d74d0900478a50a5fb1887851830a1c3f522844c8fffc5fad11b3
Contents:
  aiogzip_review_probes.py
  AIOGZIP_B2_REVIEW_PROBES_README.md
  isolated_pending_lines_results.json
```

The script was syntax-checked in the prior review, not executed against a complete
package. Convert the relevant probes into repository regression tests; do not treat
printed observations as a release certificate. Check actual helper signatures before
adapting private probes. Signature drift is not evidence that a defect disappeared.

In particular, do NOT copy the probe's broad `asyncio.all_tasks()` cancellation into
an ordinary pytest session. Identify test-owned tasks precisely. Exercise actual
runner shutdown and blanket cancellation only in an isolated subprocess with an
independent watchdog. Always release blocked threads in cleanup.

Retain supplied evidence unchanged under a review-input directory, with its origin
and hashes. If the ZIP is unavailable in Codex, implement the scenarios from this
plan, record that fact, and do not claim the supplied script ran.

### 0.3 Immutable references and current-state verification

Read repository instructions (`AGENTS.md`, `CLAUDE.md`, `.codexrc`, and nested rules).
Protect existing user edits. Do not reset or overwrite them to obtain a clean tree.

```bash
git status --short
git fetch --tags --prune
git rev-parse HEAD
git rev-parse HEAD^{tree}
git describe --always --dirty --tags
git rev-parse v2.0.0b1^{commit}
git rev-parse v2.0.0a4^{commit}
git cat-file -e dc8950cb334e1cf4082f2bf50074464e06c72287^{commit}
git log --oneline --decorate -40
git diff --name-status v2.0.0b1...HEAD
git diff v2.0.0b1...HEAD -- src/aiogzip
```

Accept the historical starting point or a descendant with only reviewed plan,
evidence, dependency, or housekeeping changes. Record dependency differences rather
than silently attributing them to source changes. If production code has advanced,
inventory every change, determine which findings still apply, and make a plan-only
baseline update before implementation. Never silently retarget a locked baseline.

Record current version, tags, open PRs/issues, issue #86 disposition, public manifest,
supported Python/engine matrix, and canonical commands. Remote reads are permitted;
remote writes remain maintainer-only.

### 0.4 Working records

Use a small number of authoritative records:

```text
plans/reviews/v2.0.0b2-preflight.md
plans/reviews/v2.0.0b2-findings.md
plans/reviews/v2.0.0b2-behavior-exceptions.md
plans/design/v2.0.0b2-file-state-model.md
plans/benchmarks/v2.0.0b2-results.md
plans/benchmarks/data/b2/                         # individual immutable run outputs
plans/reviews/v2.0.0b2-qualification.md
plans/reviews/v2.0.0b2-release-prep.md
plans/README.md
```

Do not overwrite exact-tag measurements. Every retained run identifies source SHA,
tree, dirty state, harness revision, import origin, interpreter/build, platform,
dependencies, engine fields, fixture hashes, command, result, and relevant limitations.
Performance runs also retain all samples, repetitions, run order, and dispersion.

## 1. Compatibility, ownership, and execution rules

### 1.1 Three baselines, not one infallible oracle

Use three kinds of evidence:

1. **Normative contracts and independent invariants:** documented ownership, gzip
   correctness, no lost/duplicated data, no native mutation after release, and explicit
   validation/visibility rules.
2. **Historical behavior:** exact b1 traces, kept unchanged even when a defect is found.
3. **Corrected reference C0:** a clean commit after the approved correctness/speed
   packages and before the state refactor. C0 is the direct oracle for the refactor.

The runtime public API manifest must remain byte-identical to b1. Signatures,
exports, accepted types, defaults, exception inheritance, dataclass contracts,
constants, and public codec operation lifecycle remain frozen.

Unchanged scenarios match b1 semantically. Approved defect scenarios match explicit
correct expectations, not the unsafe b1 trace. The state refactor then matches C0,
including all approved corrections. Never regenerate b1 goldens from candidate code.

### 1.2 Narrow behavioral exceptions

This revision authorizes investigation and scoped repairs for F1-F4 and confirmed
fairness failures under F7. Before each repair, add a finding and exception entry
showing the exact reproducer and the invariant violated. The plan does not authorize
unrelated public redesigns.

Each exception entry contains:

```text
ID and originating finding
exact baseline and test environment
minimal package-level failing test and observed result
documented contract / independent invariant
correct expected behavior
smallest affected public scenarios
signature / accepted-type / exception impact
implementation and regression-test commits
performance and cancellation consequences
approval basis and any further maintainer decision
```

Expected bounded categories:

| Category | Permitted correction, once reproduced | Not permitted by implication |
| --- | --- | --- |
| BC1 / F1 | Wait for actual work completion before cleanup; cancellation still propagates | Silently swallow cancellation or change CodecOperation lifecycle |
| BC2 / F2 | Prevent retry from accepting a suffix after lost input; retain bytes exactly once or fail safely | Claim every arbitrary async source is cancellation-atomic |
| BC3 / F3 | Prevent duplicate acquisition, leaks, or late resurrection during open/close | Introduce a new public resource-management API |
| BC4 / F4 | Remove repeated suffix copying/scanning with identical line/hint results | Change hint overshoot, newline translation, or error/salvage semantics |
| BC5 / F7 | Add bounded cooperative checkpoints across immediately ready source items | Add a background producer, prefetch queue, or empty public output signals |

If a proposed fix requires changing a documented accepted type, adding a public
exception, redefining salvage, or broadly changing error/validation timing, stop that
package for a focused maintainer decision and plan amendment. Do not use a generic
"bug fix" exemption to weaken the freeze. A confirmed lost-data or native-state race
cannot be waived merely because b1 did it.

### 1.3 Completion has three distinct meanings

Keep these separate in code, tests, and documentation:

* **Output produced:** a byte chunk has been yielded.
* **Operation completed:** iteration has reached `StopIteration`, committing codec
  completion and releasing its reservation.
* **Native work settled:** the actual executor call has returned, failed, or was
  successfully prevented from starting.

A done/cancelled asyncio task or wrapper future proves neither of the latter two by
itself. Likewise, decoder state not yet changing does not prove a source read had no
transport side effect.

### 1.4 Execution discipline

Work in package order; keep commits green; update a gate only in the commit containing
its code or evidence. Do not pull later-package work forward without an explicit
boundary revision, except the temporary compatibility seam already authorized in WP6.

No broad module rewrite, automatic "cleanup" across untouched files, blanket
annotation modernization, implicit cross-call write buffering, new engine, or codec
API replacement. Preserve `_normalized_retained()` and its fake-engine tests.

Use repository-required hooks and quality commands. Small private typing, executor
argument, or warning-helper changes are optional and must follow the ownership fixes,
not precede them. Do not optimize a warning at the expense of its category, location,
count, message, or timing.

### 1.5 Remote actions and unavailable evidence

Codex may read remote state and prepare local commits, tests, artifacts, issue comments,
and publication commands. It may not push, merge, tag, publish, change issues/settings,
or claim hosted CI or human approval. Missing platform or review evidence is an open
release gate, not a fabricated result or a reason to mark a local package failed.

## 2. Canonical acceptance register

This is the only release checklist. Work packages below specify the implementation
and tests for these IDs. Mark a gate complete here with links to its evidence; do not
create competing copies of the same checkboxes in every section.

| Gate | Owner | Acceptance criterion |
| --- | --- | --- |
| G00 | WP0 | Reviewed source anchors, actual HEAD, inputs, and engine identities recorded |
| G01 | WP0 | Semantic oracle uses symbolic cookies and separates diagnostics; b1 baseline retained |
| G02 | WP1 | Native-work settlement survives direct helper cancellation, repeated cancellation, and loop shutdown |
| G03 | WP2 | Source cancellation/failure cannot silently skip, duplicate, or race consumed input |
| G04 | WP3 | Opening, initialization, cancellation, and closing maintain exactly one resource owner |
| G05 | WP4 | Small-hint pending-line draining has aggregate linear work and unchanged results |
| G06 | WP5 | Generic long-line scaling measured; each confirmed issue repaired or explicitly dispositioned |
| G07 | WP5 | Partial-read read-ahead/allocation/latency measured; existing resource limits remain enforced |
| G08 | WP5 | Both streaming wrappers yield cooperatively across empty/tiny/ready sources without read-ahead |
| G09 | WP5 | Corrected reference C0 and behavioral-exception ledger pinned before state refactor |
| G10 | WP6 | Three-state binary health and transitions match C0; temporary accessors are read-only |
| G11 | WP7 | Text-origin snapshots do not alias; cookies/newlines/rollback and hot-path budgets preserved |
| G12 | WP8 | Binary health is authoritative; bridge and callback ownership tested; temporary seam removed |
| G13 | WP9 | Named parity matrices cover retained hot-path duplication; private cleanup is justified |
| G14 | WP10 | Stateful, adversarial, cancellation, and fault-injection tests pass with no unexplained semantic drift |
| G15 | WP10 | b1 public manifest and positive/negative typing contracts remain intact |
| G16 | WP10 | Required interpreter/platform/engine/dependency and installed-artifact evidence passes |
| G17 | WP10 | Performance, asymptotic-work, memory, and fairness gates pass with honest dispositions |
| G18 | WP10 | Docs, plan index, maintained examples, and qualification record are complete |
| G19 | WP11 | External human approval covers exact final candidate; findings closed or accepted appropriately |
| G20 | WP11 | Version, changelog, reproducible artifact evidence, hashes, and release notes are consistent |
| G21 | Maintainer | Tag, public publication, hashes, smokes, and documentation verified |
| G22 | Maintainer | Post-release record and RC plan rebased on verified b2 |

* [x] G00 — [Preflight and source/engine evidence](reviews/v2.0.0b2-preflight.md#wp0-completion)
* [x] G01 — [Oracle and local qualification](reviews/v2.0.0b2-qualification.md#wp0-local-completion)
* [x] G02 — [Native settlement repair and paired evidence](reviews/v2.0.0b2-wp1-completion.md)
* [x] G03 — [Source settlement, BC2 policy and verification](reviews/v2.0.0b2-wp2-completion.md#maintainer-review-correction)
* [x] G04 — [Opening ownership and exact BC3 qualification](reviews/v2.0.0b2-wp3-completion.md#cleanup-cancellation-review-correction)
* [x] G05 — [Linear pending-line draining and maintainer qualification](reviews/v2.0.0b2-wp4-progress.md#maintainer-qualification)
* [ ] G06
* [ ] G07
* [ ] G08
* [ ] G09
* [ ] G10
* [ ] G11
* [ ] G12
* [ ] G13
* [ ] G14
* [ ] G15
* [ ] G16
* [ ] G17
* [ ] G18
* [ ] G19
* [ ] G20
* [ ] G21
* [ ] G22

A finding may be closed as not reproduced only with the exact tested scenario,
environment, and explanation. Failure to reproduce a helper signature or failure to
obtain a platform is not proof of absence. Open high-risk correctness questions block
the state-refactor entry gate G09.

## 3. Work-package order and boundaries

| Package | Change | Production areas expected |
| --- | --- | --- |
| WP0 | Reproduction harness and semantic baseline | None |
| WP1 | Native executor-completion ownership | `_codec_async.py`, narrowly related driver code |
| WP2 | Source-I/O cancellation and safe recovery | `_binary.py`, private I/O support as needed |
| WP3 | Open/acquire/close ownership | Binary/text acquisition and cleanup only |
| WP4 | Small-hint line complexity | `_text.py` pending-line helper |
| WP5 | Long-line/read-ahead qualification and stream fairness | Targeted text/streaming/driver paths only |
| WP6 | Explicit binary read-health state | `_binary.py` plus temporary derived compatibility seam |
| WP7 | Text replay-origin structure | `_text.py` and its focused tests |
| WP8 | Narrow text/binary bridge | Wrapper integration and deletion of temporary seam |
| WP9 | Duplication parity and safe optional cleanup | Named codec/file hot paths and private typing |
| WP10 | Full correctness, speed, artifact, and documentation qualification | Primarily tests, evidence, docs |
| WP11 | Exact-candidate review and release preparation | Metadata and evidence |

One work package may use several small commits. Pair adjacent packages in a PR only
when each boundary stays green. Keep correctness repairs distinct from state
representation changes so failures can be bisected.

## 4. WP0 — Reproduce findings and repair the test oracle

**Acceptance:** G00, G01. No production edits in this package.

### 4.1 Environment and baseline runs

Use the repository's actual development instructions. At the reviewed baseline the
following commands were intended; verify names/options before running them:

```bash
uv sync --all-extras --frozen
uv run python -c 'import aiogzip; print(aiogzip.__file__); print(aiogzip.engine_info())'
uv run pytest -q
AIOGZIP_ENGINE=stdlib uv run pytest -q
uv run pytest --cov=aiogzip --cov-report=term-missing --cov-report=json --cov-fail-under=85
uv run mypy src tests/typing/public_api_positive.py
uv run ty check src tests/typing/public_api_positive.py
uv run ruff check .
uv run ruff format --check .
uv run python scripts/capture_public_api.py --check tests/data/public_api_2_0.json
uv run mkdocs build --strict
uv run prek run --all-files
```

Record actual compressor, decompressor, and CRC engines. An environment variable is
not engine evidence. Include active zlib-ng, forced stdlib with zlib-ng installed,
and a base environment with zlib-ng absent in final qualification. Exercise explicit
fast compression where an engine comparison requires it; installing zlib-ng does not
by itself prove it compressed a benchmark.

Do not rerun every slow benchmark before every commit. Capture the full baseline once,
run affected rows per package, and run the full matrix at the candidate. A harness
correction affecting comparability requires paired baseline/candidate recapture.

### 4.2 Package-targeted reproductions

Adapt each F1-F7 scenario into a minimal local test or measurement against the actual
checkout, record import origin, and classify it in the findings ledger. First commit
passing characterization tests of observed behavior, with the undesired outcome
clearly named. A strict expected-failure regression for desired behavior is acceptable
while documenting the defect; remove its expected-failure marker in the repair commit.
Do not leave an unexpected passing test silently classified as a failure.

Do not apply source patches during reproduction. Keep source-extracted helper tests
as supporting evidence only; they do not replace an end-to-end package regression.

Suggested test organization (reuse existing modules when equivalent):

```text
tests/test_native_work_settlement.py
tests/test_source_io_cancellation.py
tests/test_open_ownership.py
tests/test_readlines_complexity.py
tests/test_stream_fairness.py
tests/test_file_state_trace.py
scripts/capture_file_state_trace.py
```

Import and engine verification must precede interpreting results. Release evidence
must say whether a test covered a real codec, an instrumented package driver, a fake
source, or an actual executor-backed I/O operation.

### 4.3 Symbolic text-cookie normalization

A text `tell()` result is opaque and can contain a handle-specific nonce. Do not
compare raw integers across handles, subprocesses, baseline and candidate runs, or
interpreter versions. Do not patch nonce generation for determinism.

Give each scenario deterministic handle names and per-handle cookie names:

```text
H1:C1 := H1.tell()
H1.read(17) -> text
H1.seek(H1:C1)
H1.read(17) -> the same text
H2.seek(foreign H1:C1) -> the documented rejection
```

Each execution keeps its own token-to-real-cookie map. Repeated observations of the
same local cookie may reuse the local token so equality/round-trip relationships
remain testable. Literal `seek(0)` is a distinct portable operation; it does not
justify normalizing every opaque cookie to zero. Binary offsets remain numeric.

Exercise foreign-handle rejection within the same execution using the actual foreign
cookie. Exercise stale-cookie and invalid-cookie behavior where documented. Compare
those public results, not implementation bits.

The trace harness must also avoid observation side effects: call `tell()` only where
the scenario explicitly requests it, rather than after every event. Extra tell/seek
calls can alter text fast paths and distort both behavior and performance.

### 4.4 Two trace channels

**Semantic channel (gated):** methods and normalized arguments, returned data/digests,
exception class and documented stable prefix, public numeric positions, symbolic
cookie relationships, mtime/newlines/closed where specified, ordering of committed
output and errors, cancellation outcome, and transaction publication/rollback.

**Diagnostic channel (recorded):** source read counts and sizes, sink write counts and
sizes, batching boundaries, allocations, internal progress events, task identities,
and instrumentation of native work. Normalize addresses, temporary paths, and other
unstable incidental details only by explicit rules.

Do not require diagnostic byte identity. Promote an observation to a gate only when
it expresses an intentional contract or resource bound: for example, no second
concurrent read, no sink output deferred beyond the triggering write, no read-ahead
before consumer demand, or bounded work per fairness checkpoint.

A different number of sink writes is not automatically a compatibility break. A sink
error moving to a later public call is. Test visibility and attribution directly.

Within failure scenarios pin source-item boundaries when comparing error delivery.
Do not pretend gzip trailer discovery must occur at identical logical reads under
arbitrary changes in input fragmentation.

### 4.5 Golden generation and comparison

Run the same harness revision in isolated processes for b1, the reviewed starting
point, and the candidate. Assert the imported package resolves under the requested
source root or installed environment. Never import two versions under the same module
name in one process and trust the result.

Suggested interface:

```text
--source-root PATH --engine NAME --seed N --output PATH --verify-import-origin
```

Retain baseline semantic traces and separate diagnostic outputs. Maintain a small
reviewed set of scenarios rather than one enormous opaque snapshot. The comparison
report lists every semantic difference and its exception ID, or fails. Exception
allowlisting is scenario-specific, not a regex that suppresses whole error classes.

Use independent assertions alongside differential tests: round-trip data matches the
fixture, no byte is emitted beyond the configured limit, no member disappears, native
work precedes cleanup, and failed datasets are never published. Baseline equality
alone is not proof of correctness.

### 4.6 Pre-refactor state and resource inventory

Inventory all assignments to read health, EOF, closed state, active-call state,
waiters, decoder references, buffers, and text origin fields. Include initialization,
opening, post-acquisition initialization, failed opening, and closing—not just reads.

The transition record must distinguish codec state from source position. Include
source failures both before any effect and after consumption, repeated cancellation,
close while opening, direct public `buffer` use, salvage exhaustion, successful and
failed rewind, and external-resource ownership under `closefd`.

For I/O fixtures, a positive-size `read()` returning `b""` is EOF. It is NOT a
transient "try again" signal. A zero-size request is a separate case. An async
iterable can legitimately yield empty items; test those separately in WP5. Model a
transient file-source condition with waiting or its supported exception convention.

## 5. WP1 — Native-work settlement under cancellation

**Acceptance:** G02. Treat F1 as a correctness blocker once package reproduction
confirms the isolated result. Complete this before removing executor arguments or
restructuring read health.

### 5.1 Authoritative completion

The owner of mutable codec state must retain a trustworthy signal that the actual
native advancement has completed or was prevented from starting. A wrapper task
being cancelled/done is insufficient, even when it was previously awaited through
`asyncio.shield()`.

Evaluate eliminating the additional cancellable helper task and directly shielding a
privately retained executor future. If cancellation of any retained wrapper can still
hide a running call, use a worker-owned result/completion record, or the original
executor future whose terminal state has the needed semantics. Do not assume that an
`asyncio.Future.cancelled()` value describes the underlying thread.

The design record must identify:

* who owns the operation, input snapshot, and native completion record;
* the single submit/start transition, including work queued but not running;
* how completion and exceptions are published after worker mutation ends;
* how repeated task cancellation is handled while waiting for settlement;
* when operation close/discard, input release, and waiter notification become safe.

Do not create an unbounded executor, a pool per stream, or a background producer just
to gain a different future type. Prefer the smallest ownership repair consistent
with the existing execution policy.

### 5.2 Cancellation semantics

The first caller cancellation begins safe settlement; it does not authorize immediate
cleanup. Repeated cancellation must not reopen that race. Preserve the caller's
cancellation outcome rather than returning a successful result just because the
worker eventually succeeded. Record how a simultaneous native exception is surfaced
or retained for diagnosis; do not lose it in an unobserved-future warning.

Queued work has two safe terminal cases: cancellation is proved to have prevented
execution, or execution is allowed to settle before cleanup. A racy check of a
"started" Boolean followed by discard is not proof that it cannot start afterward.

Never call codec cleanup from a worker finalizer that can race the owning task. Native
completion signaling must occur after the final access to mutable operation state.

Cancellation can be delayed by an uninterruptible native call. Document that limit;
there is no safe claim that arbitrary blocked threads can be forcibly terminated.

### 5.3 Required deterministic tests

Use a real executor thread blocked by `threading.Event`, with independent cleanup and
a watchdog. Instrument entry, final mutation, completion publication, cleanup, and
input release. Assert ordering rather than elapsed milliseconds.

| Scenario | Required property |
| --- | --- |
| Caller cancelled once | Cleanup waits for actual work settlement |
| Caller cancelled repeatedly | Same ordering; final cancellation is propagated |
| Existing helper cancelled directly | It cannot make live work appear safely finished |
| Caller and helper cancelled | No premature close/discard or input release |
| Work queued behind a blocked worker | It either never starts or settles safely |
| Worker returns output / no output / completion | Correct operation state and output handling |
| Worker raises before or after output | Failure observed; cleanup still ordered |
| Outer timeout / TaskGroup failure | Structured cleanup retains native ownership |
| Actual runner shutdown | Global task cancellation cannot bypass settlement |

If the fix eliminates the helper task, test the equivalent ownership boundary and
retain the old failing test as a regression of observable behavior, not a demand to
recreate the helper.

Run whole-runner shutdown in a child process. Use a parent timeout or an independent
thread timer; an asyncio timeout cannot rescue a starved loop. Release all gates in
`finally`, bound subprocess lifetime, and report a hang as failure rather than a skip.
Also exercise one real encoder/decoder operation through the repaired driver; the
instrumented operation alone does not cover integration cleanup.

**Exit:** no native codec mutation occurs after operation cleanup, every cancellation
path has a final owner, and dual-engine cancellation suites pass. Retain a focused
BC1 entry and paired latency/throughput measurements before proceeding.

## 6. WP2 — Source-I/O consumption and safe recovery

**Acceptance:** G03. Decoder health cannot be determined solely by whether decoder
advancement started. Transport position and in-flight I/O must also be owned.

### 6.1 Classify source outcomes

For every source-read/seek path, distinguish:

| Outcome | Retry rule |
| --- | --- |
| Proven no effect before operation starts | Preserve existing retry behavior |
| Known completed read with result safely retained | Deliver exactly once in correct order |
| Consumption occurred but result was lost | Never resume as a healthy suffix-only stream |
| Side effects unknown after cancellation or error | Fail safely unless the source contract proves retry safe |
| Work still running | No retry, rewind, close, or resource release may race it |

Exception type alone does not prove no source effect. A custom async source can move
its cursor and then raise or suspend. Do not infer cancellation atomicity from an
async method signature. Do not promise protection against hidden background activity
in arbitrary nonconforming sources.

For library-owned executor-backed I/O, retain authoritative settlement just as for
codec work. For supported external async sources, document the required cancellation
and completion contract and conservatively handle uncertain consumed input.

### 6.2 Default repair policy and alternatives

The conservative default for unrecoverable or uncertain consumed input is terminal
read failure (`BROKEN` in the later state model), not `VALIDATION_SALVAGE` and not
clean EOF. This must be a BC2 exception with exact tests and compatibility notes.
Recovery is allowed only through a safely settled, successful rewind/reopen.

Retaining the completed read result for retry is also acceptable when the design
proves ordered, exactly-once delivery, bounded storage, and settlement before further
I/O. Choose and record one policy for each supported source path. Do not alternate
between poisoning and retry based on incidental timing.

Preserve genuinely no-effect transient-error recovery where it can be established.
If making all external read errors terminal would broaden the documented contract
beyond the scoped cancellation fix, obtain a separate maintainer decision rather
than silently sacrificing retry behavior.

### 6.3 Mandatory data-loss regression

Construct two independently valid members with distinct payloads:

```text
gzip(A) || gzip(B)
```

The source consumes all of member A, signals a barrier, then pauses before returning
it. Cancel the aiogzip reader. After settlement, attempt another read.

Acceptable results under the selected policy:

* a safe terminal error until rewind/reopen; or
* a retry delivering the full logical input exactly once, followed by validated EOF.

Unacceptable: successful return of only B, duplicate A, premature EOF, or rewind/close
concurrent with the outstanding physical read. A later member is intentionally used
because its valid gzip header can conceal lost earlier input.

Run this with a deterministic custom source and with actual aiofiles/executor-backed
I/O around a gated underlying read. Record dependency versions and which paths were
exercised. A fake coroutine alone does not establish native-work safety.

Additional cases: loss inside header/body/trailer; cancellation before start and after
completion; repeated cancellation; source exceptions after cursor advancement;
seekable and non-seekable sources; `closefd=False`; binary and text reads; subsequent
`seek(0)`; failed rewind; direct public `buffer` access; top-level context exit.

**Exit:** no missing or duplicated input can be accepted as a successful gzip stream;
settlement precedes transport reuse; text and binary expose the selected safe failure
policy; untouched retry/salvage scenarios remain protected.

## 7. WP3 — Opening, acquisition, and close ownership

**Acceptance:** G04. Opening is a separate resource lifecycle, not a new `_ReadHealth`
member.

### 7.1 Reserve before the first suspension

Reserve opening ownership synchronously before awaiting acquisition. Reuse existing
same-handle exclusion where appropriate; otherwise add the smallest private opening
reservation. No second opener may acquire a competing resource and overwrite the
first handle reference.

Keep an acquired resource under local ownership until initialization succeeds and it
is published to the handle. If cancellation loses an acquisition result while native
open still runs, a trustworthy completion owner must recover and close that result.
Use the settlement guarantees established in WP1/WP2 rather than starting another
unowned helper task.

Closing during opening must have a deterministic selected outcome: safely wait for
acquisition to settle and close it, or reject the conflicting call under the existing
public concurrency policy. In either case, no late completion may resurrect a handle
that close reported as closed. Pin the outcome before implementation and use a BC3
entry when correcting an unsafe baseline race.

Do not add a public exception or change ordinary idempotent open/close behavior
without separate approval. Reuse `ConcurrentOperationError` only where its documented
scope and the recorded correction justify it.

### 7.2 Initialization and resource ownership tests

Use event-gated acquisition and count resources opened, published, and closed. Test
both read and write modes, binary and text wrappers, path-backed and external file
objects where the scenario applies.

Cover overlapping `open()` calls; `close()` during acquisition; cancellation before
acquisition starts, after a resource exists, and during initialization; decoder or
encoder creation failure; initial header sink failure/partial write; seekability
probe failure; repeated close; exceptional context exit; acquisition completing after
cancellation; and retry after a failed open when the contract permits it.

Every library-owned acquired resource must be either the one published live resource
or closed exactly once. Externally owned resources must obey `closefd`; cleanup must
not close someone else's stream to hide an ownership bug. A cleanup exception must
not silently replace the primary operation failure; preserve the existing error
precedence where safe and record any required correction.

Use real delayed executor acquisition in at least one test, not only fake `async def`
open. Ensure close cannot race a still-running initialization/write or abandon its
completion record.

**Exit:** no leaked acquisition, double owner, or late resurrection; callback and
waiter references have a final owner on every failure path; regular open/close traces
remain unchanged outside BC3.

## 8. WP4 — Linear small-hint line batching

**Acceptance:** G05. Once F4 is reproduced in the actual package, repair it before
restructuring text checkpoint state.

### 8.1 Complexity invariant

The reviewed pending-line branch slices the complete remaining pending list and sums
its lengths before serving a small hint. Repeating a one-line hint over N pending
lines can inspect/copy N + (N-1) + ... + 1 elements.

The required replacement has aggregate work proportional to lines actually consumed
plus public calls, not to the repeatedly remaining suffix. For a pending batch of N
lines drained in B calls, require O(N + B) line inspections and output-list element
copies, apart from initial batch creation. A single unlimited read may traverse the
remaining batch once.

A generator replacing the suffix slice does not solve a complete rescan on every
call. Avoid both full-suffix copying and full-suffix length summation.

Prefer a bounded scan stopping as soon as the current hint's result is determined.
Retain an efficient bulk transfer for large/unlimited hints. Add a remaining-length
counter only if justified by measurements and maintained correctly across all
consumption, rollback, seek, salvage, and close paths.

### 8.2 Semantic cases

Preserve current `readlines(hint)` conventions, including nonpositive/unlimited hints,
whole-line overshoot of positive hints, a first line longer than the hint, exact
boundary behavior, empty input, newline-only lines, and an unterminated final line.
Do not split a line to meet a hint. Preserve exception precedence and transient-error
rollback for a composite call.

Interleave `read()`, `readline()`, `readlines()`, iteration, tell/seek, and pending-line
refills. Include poisoned validation salvage with complete lines and partial tails.
Exercise newline modes and multibyte encodings through the applicable public path,
not only the isolated helper.

### 8.3 Structural and performance tests

Add a named test for total pending-line work using test-only instrumentation. Count
length inspections or actual selected/visited entries and list-copy work; do not
introduce permanent production counters just for the test. A suitable instrumented
private pending batch is acceptable alongside public integration tests.

The test must fail for the historical suffix algorithm and pass for aggregate-linear
work. Predeclare its accounting rule and linear bound in the test. Merely counting
public calls is insufficient because both algorithms make B calls.

Measure 2,048, 4,096, 8,192, 16,384, and 32,768 short pending lines, drained by hint=1
and other small hints. Also measure realistic JSONL and large/unlimited hints. Keep
input generation, correctness hashing, and instrumentation outside timed regions.

Use the supplied isolated timings only as reproduction leads. Same-machine candidate
measurements are required. After measurement noise is controlled, sustained near-4x
time growth on doubling N fails; target near-2x and investigate above 2.5x. The
structural linear-work gate is authoritative and runs in ordinary CI; release timing
trends are supporting evidence, not a brittle millisecond unit test.

**Exit:** package-level results are unchanged, total work is linear, realistic bulk
batching does not regress materially, and exact tests replace the isolated probe as
the release evidence.

## 9. WP5 — Long lines, read-ahead, and stream-wide fairness

**Acceptance:** G06-G09. These are separate questions; do not solve all of them by
silently changing file-layer validation timing.

### 9.1 Generic long-line scaling

Measure newline-free data and a single very long line across `newline=None`, `""`,
`"\n"`, `"\r"`, and `"\r\n"`, distinguishing specialized and generic paths. Include
UTF-8 and a supported multibyte/stateful encoding. Test terminators absent, at the
end, and split across source/decoder boundaries; include a final trailing CR.

Use logical sizes such as 1, 2, 4, 8, and 16 MiB, several compressed-input chunk sizes,
and both compressible and incompressible content. Record copying/allocation, peak
memory, total time, and doubling ratios. Keep scanning complexity separate from
string-building complexity: an incremental scan offset does not make repeated
concatenation cheap.

If repeated copying is confirmed and a localized fragments-plus-final-join change
preserves cookies, decoder replay, rollback, and salvage, implement it here with
focused tests. Otherwise document an explicit maintainer disposition and future design
boundary; do not bury the finding under the general refactor.

A returned line can inherently be very large. Do not claim constant-memory unlimited
`readline()` or fix it by truncating records. A new maximum-line-size option is future
API work, not an unannounced b2 behavioral limit. Existing decompressed-size limits
must still be enforced correctly.

### 9.2 Highly compressible partial reads

Construct a highly compressible payload (start at 16 MiB, also measure smaller and
larger cases) whose compressed representation fits one normal source read. Generate
and hash the fixture before allocation/timing measurement.

On fresh handles measure `read(1)`, small `readinto()`, `peek(1)`, and bounded
`readline(size)`. Also measure `read1()` where supported. Repeat in text mode where
meaningful and under a modest number of concurrent independent handles.

Record separately:

* logical requested/returned size;
* compressed bytes fetched and accepted;
* total bytes inflated during that call;
* retained plaintext after returning;
* transient Python allocation and, where practical, process resident memory;
* time to first result and event-loop scheduling gap;
* validation, error, salvage, and metadata observations;
* seekable-input results versus non-seekable rewind-cache results.

A codec `output_chunk_size` bounds each emitted chunk, not the aggregate retained by
a file wrapper. Report both. Exclude the already-generated input fixture from the
incremental allocation measurement and document what native allocation tools miss.

Test existing `max_decompressed_size` at, below, and above the boundary. Failure must
not emit forbidden bytes or be mistaken for validated EOF. Include member boundaries
inside a source item and a corrupt final trailer after an early logical read.

For b2 the required outcome is measured behavior, correct existing limits, and a
clear disposition. A localized removal of redundant copies is allowed when delivery,
validation, mtime, and salvage timing remain protected. **Do not retain a partially
drained codec operation across public file calls as an incidental optimization.**
That demand-bounded-reader design requires a separate compatibility decision.

Document the current read-ahead tradeoff in user guidance, especially for concurrent
untrusted streams. Do not call it a proved security vulnerability without an actual
threat-model and exposure assessment.

### 9.3 Across-item fairness

Add finite, deterministic sources that yield immediately, without internal awaits:

| Source | Compression | Decompression |
| --- | --- | --- |
| Many empty items | Empty feeds must not spin forever without checkpoints | Empty items must count toward work before being skipped |
| Tiny nonempty items | Highly compressible data can produce little output | Fragmented headers/bodies must still permit progress |
| Many empty gzip members | Generated as input fixture where relevant | Member processing consumes work despite zero plaintext |
| Single large item | Existing output/raw-progress budgets preserved | Existing no-output-progress budgets preserved |
| Slow destination | Backpressure retained | Backpressure retained |

An `await` of an already-completed source or destination is not proof that the event
loop yielded. Budgets must span codec operations and count empty items before any
`continue`. Maintain per-stream item/work/output counters, reusing existing budgets
where possible. Reset because a deliberate cooperative checkpoint occurred, not
merely because a new `feed()` operation began.

Start with private, bounded budgets (for example, an item-count ceiling plus existing
byte/raw-work ceilings); record selected values and their throughput/latency tradeoff.
Do not add a public tuning API. A checkpoint must not yield `b""` to users, prefetch
the next source item, create a producer task/queue, or weaken codec ownership cleanup.

Run a sibling ticker and capture its progress *before* the finite source is exhausted,
including before the final nonempty item. Test cancellation while processing a long
ready-source sequence, consumer early exit, source failure, and both engines. Use a
subprocess watchdog for starvation/infinite-source stress. A finite-source test that
only asserts ticks after completion is not sufficient.

Preserve throughput policy on representative nonpathological streams. Treat added
cancellation opportunities as a scoped BC5 scheduling correction and verify cleanup
at those checkpoints. Do not promise strict wall-clock preemption of a synchronous
codec step; bound cooperative work between checkpoints instead.

### 9.4 Pin corrected reference C0

Before WP6, every F1-F3 correctness scenario must have a package result and resolution:
fixed, demonstrated not affected with evidence, or blocked. F4 must be repaired if
reproduced. F5/F6 need an explicit recorded disposition; confirmed F7 starvation needs
bounded checkpoints. An unresolved data-loss/native-state race blocks progress.

Commit the correctness/performance packages cleanly and record C0's full commit/tree,
public manifest hash, semantic traces, behavioral exceptions, and targeted benchmark
results. Re-run the dual-engine suite and affected integration tests. Pin a local
reference without creating or pushing a release tag.

The subsequent enum/origin/bridge refactor is compared directly with C0. For unchanged
scenarios, retain the b1 comparison as an additional continuity check. Keep corrected
case expectations independently asserted rather than copied blindly from C0 output.

## 10. WP6 — Explicit binary read health and transition seam

**Acceptance:** G10. This is a representation change, not another opportunity to
alter the corrections settled at C0.

### 10.1 Three health values, orthogonal lifecycle

Introduce a private enum:

```python
class _ReadHealth(Enum):
    HEALTHY = auto()
    VALIDATION_SALVAGE = auto()
    BROKEN = auto()
```

Map the original semantic pair as follows, adjusting the inventory for the approved
correctness repairs already present at C0:

```text
(False, False) -> HEALTHY
(True, True)   -> VALIDATION_SALVAGE
(True, False)  -> BROKEN
(False, True)  -> invalid pair, never a legitimate new state
```

Keep EOF, closure, opening ownership, active calls, native work, and transport
position orthogonal. The enum removes one invalid Boolean combination; it does not
make every cross-product state valid. Test invariants involving buffers, decoder
presence, closure, and outstanding work explicitly.

Centralize exceptional transitions: validation failure, ordinary broken state,
transport uncertainty, successful rewind/reset, and abort. Leave straightforward
measured hot-path reads as direct enum comparisons where helper/property overhead
would be material. No new allocation per read byte or decoded output chunk.

### 10.2 Temporary read-only compatibility accessors

To keep this package green while text migration occurs later, remove the two stored
Boolean fields and expose temporary, derived read-only accessors under the old names
for existing text callers:

```text
_read_broken             := health is not HEALTHY
_read_validation_failed  := health is VALIDATION_SALVAGE
```

They must have no setters or independent storage. Binary transitions write only the
new authoritative health field. Update tests that assign legacy internals to use
appropriate fixtures/transitions rather than adding setters back.

Retain old buffer-sensitive health predicates only as thin derived adapters while
needed by text. List every temporary name in the design record with **WP8 removal**
as its owner. The final structural gate prohibits those legacy names in production
coupling; it does not falsely require their absence at this intermediate boundary.

This seam is pre-authorized. It is not permission to pull the full text bridge into
WP6 or to preserve legacy mutable flags indefinitely.

### 10.3 Transition tests

Use the C0 transition table, including immediate result, later result, buffer retained,
position, EOF, decoder cleanup, work settlement, observer events, and recovery path.
Cover healthy operation/EOF, each malformed/truncated/integrity failure, decompression
limits, known no-effect source errors, consumed/uncertain source outcomes, native
cancellation, repeated cancellation, overlap rejection, close/open interactions,
absolute rewind, failed rewind, and non-seekable recovery.

`VALIDATION_SALVAGE` remains recovery data after a reported validation failure, followed
by a terminal error when exhausted. It is not clean EOF or successfully verified
payload. An uncertain source read is not relabeled as salvage to make retry pass.

Use semantic transition methods for complex mutations. Commit the authoritative
state before notifying text, but ensure callback errors cannot bypass required cleanup
or leave an unowned decoder/resource. Do not add public callback behavior; these are
internal invariants.

**Exit:** C0 semantic traces pass, binary no longer stores the Boolean pair, temporary
text adapters are derived only, and affected binary/seek/salvage benchmarks stay within
policy. The full text suite must pass before this commit boundary.

## 11. WP7 — Text replay-origin object

**Acceptance:** G11. Preserve the complete replay checkpoint and avoid new hot-path
object or helper overhead.

### 11.1 Coherent state

Replace the five loose origin fields with one private slotted object. A suitable
shape is:

```python
@dataclass(slots=True)
class _TextBufferOrigin:
    byte_offset: int
    decoder_state: tuple[Any, int]
    trailing_cr: bool
    seen_newline_types: int
    chars_to_skip: int
```

Use the actual existing decoder-state contract for annotations. Do not narrow supported
codecs accidentally. The live object may be mutable; rollback captures must be
independent copies. Establish whether nested decoder state is immutable before sharing
it; do not blindly deep-copy arbitrary codec objects or retain mutable shared state.

Centralize coordinated capture, copy, restore, and reset. A simple hot-path character
count increment may remain inline when it is measured, explicitly listed, and covered
by parity tests. Do not introduce a helper call on every line solely to satisfy a
stylistic centralization rule.

No new origin object per character. Measure allocations per logical buffer origin
and per required rollback snapshot separately; necessary rollback copies are not
mistaken for leaks. Avoid creating a fresh dataclass for every consumed line when
only `chars_to_skip` changes.

### 11.2 Characterization and tests

Inventory every former assignment, reset, compaction, cookie pack/unpack, and rollback.
Preserve the existing order in which text output, byte position, decoder state,
trailing CR, and newline mask commit or roll back.

Run UTF-8 at multibyte splits, supported UTF-16 variants, and a currently supported
stateful encoding. Cover all newline settings; LF/CR/CRLF/mixed input; trailing CR;
no final newline; tell/seek before and after compaction; repeated cookie round trips;
foreign/stale cookie rejection; sized read and `readlines()` rollback; failed decode;
transient source error; approved source cancellation outcomes; validation salvage;
and direct public binary `buffer` interaction.

Test copy independence by mutating live and saved checkpoints separately. Add
structural tests for removal of old storage names without relying on source line
numbers. Do not serialize raw cookies into cross-run snapshots.

Re-run WP4 small-hint tests and WP5 long-line cases: a checkpoint refactor must not
reintroduce repaired suffix scans or growing-string copies.

**Exit:** one typed checkpoint represents the origin, rollback cannot alias, cookie
semantics match C0, and text read/batch/tell/seek plus allocation benchmarks pass.

## 12. WP8 — Narrow text/binary bridge; one health authority

**Acceptance:** G12. Remove the temporary WP6 seam here.

### 12.1 Binary health remains authoritative

Do not mandate a text-side `_binary_read_health` mirror. Prefer querying a narrow
binary-owned state/predicate at the points where text needs a decision. Use callbacks
for text-local side effects: retain or invalidate decoded buffers, decoder replay
state, and closure state as the established semantics require.

A cached health mirror is allowed only if a measured hot-path benefit justifies it and
every update path is tested. That is a recorded design exception, not the default.
Do not replace two duplicated booleans with two duplicated enums and call the
consistency problem solved.

Inventory all direct `self._binary_file._...` access and classify observer attachment,
health, usability/salvage, positions/buffers, lifecycle, and measured hot paths. Keep
only a small reviewed allowlist of intentional remaining private accesses.

### 12.2 Internal interface

Group private wrapper support in one labeled section of `_binary.py`. Candidate
operations include attaching/detaching observers, querying authoritative health,
checking text read usability with buffered text, deciding failed-call rollback, and
answering binary salvage exhaustion/line-boundary questions.

Use typed callbacks and ownership checks on attachment. A second wrapper must not
silently overwrite the first observer. Detach is idempotent and clears references
without closing externally owned resources. Do not create a second interface
replicating the entire binary file API; use a small Protocol only if it improves
actual static checking.

Define initial state synchronization and cleanup after failed opening/cancellation.
Observer failure cannot roll back already committed health or prevent mandatory
resource cleanup. Preserve primary error precedence and avoid unobserved callback
errors.

A same-health event can still matter: for example, a successful rewind may reset
text-local state even if both old and new health are HEALTHY. Characterize public
`buffer` behavior before deciding which events require notification. Do not infer that
"health did not change" means no invalidation is necessary, and do not invent a new
automatic synchronization guarantee for unsupported mixing of text and binary reads.

### 12.3 Required checks and deletion

Cover attachment, duplicate attachment, detach, failed open, close through text,
close through `buffer`, repeated close, validation salvage, ordinary breakage,
transport-uncertainty correction, successful/failed rewind, close during active work,
and callback reference lifetime. Test direct `buffer` operations explicitly.

If caching was approved, add an exhaustive cache-vs-authority invariant after every
relevant event, including reset and failure. Otherwise verify text decisions observe
the authoritative binary value and text-local buffers still receive required effects.

Delete WP6's derived `_read_broken` / `_read_validation_failed` accessors and obsolete
legacy predicate adapters after the last caller migrates. No assignments to binary
observer fields may remain in `_text.py`. Use an AST-based or otherwise robust
structural test for the private-access allowlist, not line-number matching.

**Exit:** the dependency seam is gone, remaining coupling is intentional and typed,
C0 close/rewind/salvage traces pass, and text hot-path performance remains within policy.

## 13. WP9 — Hot-path parity, codec guidance, and optional cleanup

**Acceptance:** G13. Keep tested, measured duplication where eliminating it would add
cost or change observable ordering.

### 13.1 Named parity matrices

Use one scenario matrix per duplicated behavior, with adapters for each driver. Test
equivalent outcomes without pretending the public iterator exposes internal progress
signals.

| Matrix | Paths | Required scenarios |
| --- | --- | --- |
| Operation advancement | `_Operation.__next__()` and `_advance_raw()` | Output, private progress, no-output work, completion, failure before/after output, reentrancy, non-active token, close, discard, invalidated retained iterator, release ordering |
| Encoder feed | Public `feed()` and private exact-bytes feed after snapshot | Active/unusable/unstarted/finished preconditions, strict-size boundary, exact bytes, hostile subclass, invalid/mutable input, snapshot failure, reservation and counter timing |
| Binary write reservation | Inline primitive `write()` and `_BinaryWriteReservation` | Success, empty write, partial/zero-progress sink, codec/sink failures, repeated cancellation, close/abort/overlap, waiter completion, position publication |
| Text inline paths | Each path explicitly kept inline and its reference path | Empty/boundary cases, encoding/newlines, buffering, rollback, salvage, cancellation, close and overlap where applicable |

For operation drivers compare the projected public byte stream and equivalent final
state; test raw progress separately. Do not require their number of advancements to
match when public `next()` intentionally hides internal events.

For feed, characterize exception precedence before deduplicating. A public call that
checks active state before input type must not silently reverse that order through
`snapshot -> private feed` delegation. Preserve subclass snapshotting without invoking
hostile conversion/iteration overrides.

For writes, each successful call still snapshots its accepted input, drives its codec
operation, delivers that operation's compressed output to the sink, and publishes
position only after successful sink writes. Same-call failures may not move to a later
write/flush/close. No cross-call buffering is introduced.

Comments in production identify the named parity tests. Do not make every duplicate
branch a helper merely for style. Maintain a concise map of why the duplication exists
and which benchmark constrains it.

### 13.2 Last yielded bytes are not completion

Add a focused encoder test that collects a valid gzip member including its trailer
without requesting the final `StopIteration`. Verify valid decompression of collected
bytes, `finished is False`, and the still-active reservation. Then exhaust and verify
completion. Separately verify early `close()` follows the existing abandonment rule.

Cover counted `next()`, an early `break`, `islice()`, complete `for` exhaustion, and
`b"".join(operation)`. Do not hold two state-changing operations at once in examples;
construct and exhaust them sequentially.

The guide should warn: receiving a chunk that happens to complete a valid gzip byte
sequence does not release operation ownership. Always exhaust, or explicitly close
and accept the documented unusable-codec outcome. Treat this as frozen behavior,
not a b2 API defect to "fix" with finalizers.

Keep the existing counter-timing distinction discoverable: `compressed_size` counts
feed-time accepted/snapshotted bytes; `uncompressed_size` advances during work. Do not
add `consumed_size` during b2. Record ergonomic evidence for a future additive helper
or separately reviewed API, not a mandatory 2.0 pull-style replacement.

### 13.3 Conditional dead-branch removal

Reinspect the actual `decoder.finish()` path after the correctness work. If it remains
a purely synchronous loop with no suspension/worker boundary, the inner
`except asyncio.CancelledError` for ordinary task cancellation may be removed with a
comment explaining the live cancellation boundaries.

If earlier repairs introduced a real await or delivery boundary there, retain the
needed handling. Do not satisfy the old plan by deleting a now-live branch. Run
actual preceding-read, worker, context-exit, and repeated-cancellation tests; a
coverage gap alone is not proof that error handling is dead.

### 13.4 Optional private cleanup

A more precise private `_reserve() -> _Operation` annotation may remove genuinely
redundant casts while public methods remain typed as `CodecOperation`. Run both type
checkers and the b1 manifest; do not expose the implementation type.

Remove an unused executor workload argument only after WP1 proves who retains the
input until native settlement. Test input release after every completion/failure and
measure any claimed benefit. Leave it unchanged if it still documents real ownership.

An internal warning helper is acceptable only with preserved category, message,
count, filtering behavior, timing, and user-facing stack location across codec,
streaming, and file use. Preserve `_normalized_retained()` and fake-engine coverage.
Do not globally lift Ruff annotation-modernization deferrals or touch public
annotation spelling as part of this cleanup.

## 14. WP10 — Stateful, adversarial, and installed qualification

**Acceptance:** G14-G18. This package collects final evidence; the earlier focused
tests must already pass at their own commit boundaries.

### 14.1 Stateful and differential testing

Generate deterministic public sequences covering binary/text read, read1, readinto,
peek, readline, readlines, iteration, tell, absolute/relative/backward seek, text
cookies, direct buffer access, source/sink failure, validation/limit failure,
cancellation, open/close, context exit, and rejected overlap.

Vary seekability, input fragmentation, encodings/newlines, member layouts, failure
boundaries, resource ownership, and native versus async source behavior. Use events
and explicit barriers for ordering; sleeps are not correctness synchronization.
Retain seeds and minimized failures. Run a bounded fixed seed set in PR CI and a
larger release set under both engines. Record the actual number used.

Compare semantics with b1 except enumerated corrections, and with C0 for the entire
state-refactor surface. A semantic mismatch has to be explained, not normalized away.
Additional invariants include:

* no native work touches discarded state or a closed/repositioned owned resource;
* no consumed input disappears and no retry duplicates data;
* no lost earlier member is hidden by a later valid member;
* no failed stream/dataset becomes validated EOF/publication;
* health/EOF/closure/ownership combinations obey the transition table;
* callback effects and rollback checkpoint copies are coherent;
* read/line complexity and fairness remain bounded as specified.

Use model assertions in tests rather than expensive invariant checks in every hot
production call. A timeout/hang is a failed test, never an inconclusive pass.

### 14.2 Retained codec and gzip coverage

Retain dropped/unadvanced/partially advanced operation tests with `gc.disable()` and
collection; bytes-subclass snapshot tests; strict input types; sequential lifecycle;
retained invalidated operations; rich headers and FHCRC split at every byte; reserved
flags; empty streams and members; concatenated members; padding; trailing junk;
CRC/ISIZE failures; header/body/trailer truncation; exact output-limit probes; sync
flush visibility; and randomized comparison with standard-library gzip.

Keep the fake non-aliasing engine matrix. Verify completed-member metadata after
later failure/discard, header-generation/live mtime behavior, binary/text seek and
cookie replay, append and exclusive creation, partial sink writes, and cancellation
settlement. Tests of arbitrary tiny source/output boundaries must still pass after
fairness changes.

### 14.3 Required environments

Retain Python 3.11-3.14 on Linux and representative Windows/macOS jobs, stdlib-only,
zlib-ng active, stdlib forced with zlib-ng installed, and declared minimum/current
dependency environments. Verify each job's imported engines and dependencies.

Do not turn the matrix into an unnecessary full Cartesian product; keep broad base
coverage and focused engine/platform stress lanes. Python 3.15 may be informational;
its new support declaration remains in the later RC plan unless separately scoped.

Run the full suite, actual coverage with the existing floor of at least 85%, Ruff,
formatting, mypy, ty, strict docs, and repository hooks. Record meaningful branch and
transition coverage of the new code, not just line counts. Validate both positive and
negative typing fixtures: negative tests must fail for intended reasons, not because
of a broken import or mismatched checker version.

### 14.4 Built artifacts and integrations

Build wheel and sdist in a clean worktree, run metadata validation, retain inventories
and hashes, and install each into a clean environment outside the repository import
path. Assert `aiogzip.__file__` resolves into that environment. Check the frozen public
manifest from installed artifacts, not only source.

Run codec/file/streaming/inspect/verify/CLI and optional aiocsv smokes. Ensure no new
private state type is exported accidentally. Preserve maintained example packaging
and typing.

The fragmented transport example must still show successful flush/fragmentation,
concatenated members, truncation, CRC/ISIZE failure, early close/discard, and invalidated
operation behavior. The concurrent JSONL ingest example must cover bounded concurrency,
per-shard/dataset limits, bad gzip, bad JSON, staged-write failure, top-level
cancellation, and atomic publication with matching row count/digest.

Add an integration-level cancellation case using the repaired native/source ownership
paths. Do not let a high-level example cancel its sibling tasks and leak internal
work while its isolated codec tests pass.

### 14.5 Documentation and plan index

Update the developer state-model document with source symbols, transition tables,
ownership/settlement diagram, corrected-reference C0, text checkpoint design, bridge,
remaining private-access allowlist, parity-test map, performance constraints, and
behavioral exceptions. Prefer stable symbol/test names over source line numbers.

Update user documentation for operation exhaustion, source-cancellation consequences,
known read-ahead/resource tradeoffs, fairness, and efficient line batching. Distinguish
provisional output, validation completion, and recovery data. Do not overstate thread
safety or constant-memory behavior.

Add or update `plans/README.md`: active b2, parked RC, completed plans, design records,
reviews, and benchmark evidence. Keep historical files at their existing paths in
this release. Check links. Agent instructions should point to durable invariants,
not duplicate this entire plan.

## 15. Performance and resource adjudication

**Acceptance:** G17; individual algorithm/resource gates remain G05-G08 and G11.

### 15.1 Comparisons

Use the same harness revision, host, interpreter, dependencies, engines, fixtures,
source boundaries, and statistics on both sides. Correctness checks and fixture
creation must not contaminate timed work; document the method used to verify output
without introducing an unbounded retention artifact into memory measurements.

Compare the final candidate both with the pre-change baseline (cumulative effect)
and with C0 (state-refactor effect). Package-by-package passes cannot hide several
small regressions that compound. Never overwrite historical raw outputs.

For comparable unaffected workloads:

```text
<= 5% slower: no mandatory timing investigation
> 5% slower: investigate and record disposition
> 10% slower attributable to candidate: block by default
```

Use A/A controls and balanced A/B/B/A runs when needed. Record medians, all samples,
and dispersion; do not choose the most favorable statistic or keep rerunning only
the candidate. Inconclusive measurements do not support a speed claim.

Correctness cannot be traded away to satisfy a timing gate. If the smallest safe
repair demonstrably exceeds the hard gate, require a specific maintainer-approved
performance-policy amendment with evidence and alternatives; do not silently exempt
it or revert to the race. Time spent correctly waiting for uninterruptible native
work is a cancellation-latency diagnostic, not directly comparable to unsafe early
return as a throughput "improvement."

### 15.2 Required workload families

| Family | Rows |
| --- | --- |
| Binary | Bulk/sized read, read1/readinto/peek, lines/batches, seek/rewind, salvage, simultaneous independent handles |
| Text | Bulk/sized reads, LF and generic newline paths, small/large hints, iter_batches/iteration, cookie tell/seek, multibyte/stateful decoding |
| Algorithm scaling | Tiny-hint pending batches, long lines without terminators, source-item count/empty streams |
| Partial-read amplification | Highly compressible read(1), readinto, peek, bounded readline; fresh and concurrent handles |
| Decoder preservation | Large single-feed vs chunked input, small output bounds, optional headers, normal 512/256 KiB and 64/64 KiB stream cases |
| Writes | 10 B, 100 B, 1 KiB, 4 KiB, 16 KiB, 64 KiB, 256 KiB; writelines; text writes; concurrent independent writers |
| Resources | Peak allocations, retained buffers/checkpoints, rewind cache, native work lifetime, scheduler gaps, cleanup |

The small-hint fix has a structural aggregate-linear-work gate independent of b1
percentages. Long-line work has an explicit scaling disposition. Partial-read memory
has a measured, approved behavior statement; it is not falsely compared to a promised
consumer-demand bound. Fairness has a bounded-work/sibling-progress test independent
of a machine-specific millisecond threshold.

Do not claim `readlines(hint)` is memory bounded merely because the returned list is
small: internal pending batches and expanded decoder items must be measured too.
Preserve established large-feed/header/scheduler memory gates from prior releases.

### 15.3 Claims

Release notes may state a proven algorithmic correction such as avoiding repeated
pending-suffix scans. Any numerical speedup requires paired, attributable measurements
and named conditions. Do not turn one isolated helper timing into a universal
throughput claim. Issue #86 remains an accepted strict-write tradeoff; its benchmark
stays active, and implicit write buffering remains out of scope.

## 16. WP11 — Exact-candidate review and release preparation

**Acceptance:** G19, G20. Publication is still a maintainer action.

Prepare the review packet from the actual candidate: source and C0 diffs, unchanged
public manifest, approved behavioral exceptions, all F1-F9 dispositions, real-thread
shutdown and source-consumption evidence, complexity/scaling reports, state-model and
bridge decisions, semantic traces, diagnostic changes, environments, artifacts, and
remaining limitations.

At least one non-maintainer human must approve the exact final candidate SHA under
the existing release policy. Agent reviews are useful inputs, not that approval.
Missing external review keeps release readiness open but does not prevent Codex from
finishing local code, tests, and artifacts. Never manufacture review evidence.

Review questions should emphasize actual native completion, ownership of late I/O
results, opening/closing resource publication, and whether a later member can mask
lost input. Also review cookie normalization, exception allowlisting, cumulative
performance, health authority, rollback aliasing, and deletion of the temporary seam.

Record every finding and its resolution. A post-review code or release-input change
requires review of the new final candidate; do not claim a previous SHA approves it.
Stage final metadata before the final review where practical to avoid needless cycles.

Set the version to `2.0.0b2` only after qualification, keep the Beta classifier, add a
dated changelog section and correct comparison links, build the final wheel/sdist,
validate metadata, and retain filenames, sizes, inventories, hashes, and installed
smoke results. Reuse existing reproducibility controls; do not fold the parked
publish-workflow redesign into this work.

Release notes must no longer say "runtime behavior is unchanged from b1" without
qualification. Name actual corrected cancellation/ownership or scheduling cases,
state that the public signature/type/codec-lifecycle contract remains frozen, explain
any user-visible safe-recovery change, and describe the private refactor separately.

An open correctness race or potential silent data loss is a blocker, not a deferred
future opportunity. Nonblocking long-line/read-ahead limitations require a clear
maintainer disposition and user-facing guidance.

## 17. Maintainer publication and RC handoff

**Acceptance:** G21, G22. Codex prepares commands/evidence but performs no remote write.

Merge only an approved candidate with passing required checks. Compare the approved
head with the merge result; review any source-tree difference. Create and verify the
annotated signed `v2.0.0b2` tag on the approved commit, then publish through the
repository's release process. Do not pre-mark hosted builds or publication complete.

Verify public wheel and sdist hashes, version/classifiers, Trusted Publishing and
attestations where configured, clean installed base/CSV/fast-extra smokes, maintained
examples, and deployed documentation. Record public discrepancies before declaring
the release verified. Keep the private security-report route intact.

After verification, create the post-release record, update Unreleased comparisons,
and advance to `2.0.0rc1.dev0` when no unresolved beta correctness issue requires
another beta. Do not guarantee an RC merely because a version number was planned.

Rebase the parked RC plan using:

```text
public API baseline:       v2.0.0b1
approved behavior fixes:   b2 exception ledger
immediate runtime oracle:  v2.0.0b2
performance baseline:      v2.0.0b2, with historical continuity rows
```

Remove the stale assumption that runtime source or every behavior is identical to
b1. Retain later Python 3.15 qualification, action pinning, PR documentation validation,
public feedback intake, exact-artifact publication, and external RC review. Reverify
actual supported versions and source SHAs when that work starts.

## 18. Deferred opportunities, not b2 release gates

Record these in a brief future-work section of the design record. Do not turn them
into automatic new APIs or remote issues.

| Opportunity | Benefit | Required design boundary |
| --- | --- | --- |
| Demand-bounded file reader | Less plaintext read-ahead and faster first small result | Private operation continuations; explicit validation/mtime/salvage timing policy |
| Broader resource policy | Header/member/metadata/compressed-input/record-size budgets for services | Opt-in limits and compatibility semantics; output-size limit alone is not every budget |
| Validated-member events and coarse index | Incremental metadata without retaining all history; member range reads | Commit only after validation; bind index to exact object digest/version |
| Execution/fairness policy | Isolation and predictable concurrency for many uploads | Settled native ownership first; no unsupported parallel-speed claims |
| Safer draining helpers | Fewer accidental abandoned codec operations | Additive helpers may be compatible later; replacing the iterator lifecycle needs a separate decision |
| Advanced striped JSONL | Parallel processing and ordered reconstruction | Separate format, sequence/manifest rules, bounded merging, standard gzip interoperability |

AnyIO/Trio, indexed/zran access, new engines, raw DEFLATE, default buffered writes,
free-threaded claims, codec-only packaging, global annotation cleanup, and moving
historical plans remain outside b2. A new security/data-integrity finding supersedes
these deferrals and receives a focused blocker package.

## 19. Reviewable PR sequence and risk controls

Suggested PR boundaries:

1. WP0: baseline, probe conversion, oracle correction, and findings ledger.
2. WP1: native completion ownership and shutdown regression tests.
3. WP2-WP3: source and acquisition ownership, in separate commits; split PRs if large.
4. WP4-WP5: line-complexity repair, resource evidence, and streaming fairness.
5. WP6: binary health with the temporary derived seam.
6. WP7-WP8: text origin and bridge, each independently green.
7. WP9-WP10: parity, full qualification, developer/user documentation.
8. WP11: final reviewed beta candidate and release evidence.

Keep every acceptance gate in section 2 authoritative. PR descriptions link to gate
IDs, results, and exception IDs rather than duplicating hundreds of unchecked tasks.

| Risk | Required control |
| --- | --- |
| Async wrapper cancellation mistaken for native completion | Worker/executor completion proof and real shutdown subprocess test |
| Input lost after transport advances | Exactly-once retention or safe terminal failure; A/B member regression |
| Resource acquired after cancellation or close | Acquisition reservation and final owner for late results |
| Existing bug frozen into golden output | Normative invariant + explicit exception + independent expectation |
| Cookie nonce makes traces nondeterministic | Per-handle symbolic cookie mapping, in-run foreign-handle rejection |
| Batching change rejected as semantic drift | Separate diagnostic channel and intentional resource bounds |
| State refactor masks a correctness fix | Correctness packages first, clean C0, bisectable commits |
| Text migration breaks early binary package | Temporary read-only derived accessors, removed in WP8 |
| Cached enum becomes another stale flag | Binary authority by default; caching needs evidence and synchronization tests |
| Long-line or partial-read fix changes trailer timing | Characterize first; no unreviewed operation-continuation redesign |
| Empty sources starve cancellation | Across-item budgets before skip, independent watchdog |
| Cleanup deadline permits unsafe early release | No release until real work settles; document noninterruptible-call limits |
| Thousands of tests obscure ownership assumptions | Named focused parity/transition tests and compact evidence register |
| Performance claims rely on noise | Same harness, cumulative comparison, raw samples, A/A and balanced runs |

## 20. Ready-to-paste Codex kickoff prompt

```text
Implement aiogzip 2.0.0b2 using Revision 2 of
plans/RELEASE_2_0_0B2_PLAN.md.

This revision supersedes the prior maintainability-only plan. Begin with WP0:
verify the historical references and actual HEAD, read the supplied review/probe
notes, reproduce findings against the actual package, and correct the trace oracle.
The package-targeted probe ZIP was not run against the full package in the prior
review. Do not report its scenarios as reproduced until you execute them.

Keep the public b1 API manifest and documented codec lifecycle frozen. Do not freeze
known bugs: use the narrow behavior-exception process in section 1.2. Preserve b1
historical traces, assert corrected behavior independently, and pin corrected
reference C0 before refactoring state.

Perform correctness work first: native operation settlement must survive direct
helper cancellation, repeated cancellation, and actual loop shutdown; a cancelled
asyncio wrapper is not proof that its worker stopped. Prevent consumed-but-undelivered
source data from producing a successful suffix-only gzip stream. Test gzip(A)||gzip(B).
Establish one owner for opening/acquisition/initialization and closing, including
late executor results. Use real-thread tests and deterministic event barriers.

Then repair repeated small-hint readlines suffix copying/scanning with aggregate
linear-work tests. Measure generic long lines and highly compressible partial reads.
Add across-item fairness for both streaming wrappers, counting empty items before
skip and preserving backpressure. Do not smuggle a demand-bounded reader redesign
into b2. Record resource tradeoffs explicitly.

The golden oracle must use symbolic per-handle text cookies and test round trips,
not compare raw cookie integers. Separate semantic outcomes from diagnostic I/O
counts and batching. The baseline is evidence, not the sole definition of correctness.

Only after C0 is pinned, replace binary read-health storage with HEALTHY,
VALIDATION_SALVAGE, and BROKEN. Keep EOF, closure, opening ownership, and active
work orthogonal. Use temporary derived read-only legacy accessors so the binary
package stays green, then remove them in WP8. Binary health is authoritative;
do not mandate a text-side enum cache.

Group text replay origin in a private slotted object with non-aliasing rollback
copies. Avoid per-character allocation and unnecessary per-line helper overhead.
Add the narrow text/binary bridge and named parity matrices for measured duplicated
paths. Clarify last-yield versus StopIteration without changing CodecOperation.
Remove the old synchronous cancellation branch only if it is still unreachable.
Keep _normalized_retained, public annotations, and strict same-call write behavior.

Use the canonical G00-G22 register once; update gates with their evidence in the
same commit. Preserve independently green work packages and small reviewable diffs.
Run cumulative and C0 performance comparisons, full engine/platform/dependency tests,
installed wheel/sdist and maintained examples, typing, lint, docs, and hooks.
Obtain external human approval on the exact candidate before publication readiness.

Do not push, merge, tag, publish, edit remote issues/settings, or invent test,
benchmark, engine, platform, artifact, hosted-CI, or review evidence. Leave
maintainer-only gates open. Defer the parked RC hardening program and future APIs.
```

## 21. Revision provenance

This revision replaces, rather than appends contradictory amendments to, the original
b2 plan. The original artifact remains unchanged for comparison.

```text
Original artifact: RELEASE_2_0_0B2_PLAN.md
Original SHA-256: 63c4db6b545d03219fe1ef873e08f5df4e3874a94f0b0a47cf2cca1c6c4ce93b
Review input: AIOGZIP_B2_REVIEW_PROBES.zip
Review input SHA-256: 94c41cc4389d74d0900478a50a5fb1887851830a1c3f522844c8fffc5fad11b3
Revision date: 2026-09-07
Repository destination: plans/RELEASE_2_0_0B2_PLAN.md
```

The accompanying change index maps old work packages and decisions to this revision.
The unified diff is generated against the exact original artifact above. Neither this
plan nor its checklist claims that implementation, repository tests, remote settings,
external review, or publication has been completed.
