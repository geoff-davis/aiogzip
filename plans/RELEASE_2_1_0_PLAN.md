# aiogzip 2.1.0 plan

> **Status:** active from 2026-11-16, when the maintainer decided D1 to D8
> (§2). Drafted on 2026-11-14. 2.0.3 was published on 2026-11-26 and `main`
> moved to `2.1.0.dev0` the same day, which meets M01's release condition.
>
> **Theme:** gzip from anywhere, not just files. 2.1.0 is the first feature
> release after 2.0. It adds public names and changes none.
>
> **Source:** the
> [features report](reviews/data/2.0.0/code-review/features-report.md.txt)
> and the [2.0.0 code review record](reviews/v2.0.0-code-review.md), whose
> follow-up "decide the 2.1 scope from the features report" this plan
> closes. The work items are GitHub issues #199 to #214, filed on
> 2026-11-14 with implementation notes; #215 holds their priority order.
> Each gate below names its issue and does not repeat the issue's notes.
> The GitHub milestones `2.0.3`, `2.1.0` and `Backlog` mirror §2, §3 and §6.

## 1. Baselines and rules

```text
public API baseline:       v2.0.0 (frozen manifest tests/data/public_api_2_0.json)
runtime baseline:          v2.0.3 once D2 ships it; v2.0.2 until then
approved behavior fixes:   exception ledger, BC1–BC36 as of 2026-11-16 (BC34 is
                           reserved for #233); 2.1 entries follow 2.0.3's last
file-state model:          plans/design/v2.0.0b2-file-state-model.md
performance baseline:      set by M02; none exists for 2.0.x yet
```

Rules:

- **Additive only.** `docs/stability.md` allows a minor release to add
  public names and parameters. Every signature, default, overload,
  exception type and dataclass shape in the 2.0 manifest stays as it is.
  A gate that finds it needs to change one stops and is recorded in §2 as a
  decision.
- **One gzip state machine.** New entry points drive `GzipEncoder` and
  `GzipDecoder` through the existing async driver. None adds framing, a
  member loop or its own offload policy.
- **Behavior and state changes are recorded.** A change to a documented
  transition needs a file-state model update, and a change to observable
  behavior needs a ledger row, in the same PR. M07 is the one gate known to
  need both.
- **Hot paths are measured.** A PR that touches the read, readline or
  iteration paths in `_binary.py` or `_text.py` carries an interleaved
  before/after comparison against the M02 baseline, following the protocol
  in `AGENTS.md`. Timing runs need a quiet window that the maintainer
  names.
- **One PR per concern,** with both engines' suites and the hosted matrix
  green, and the review named in D7 before merge.
- **The maintainer's explicit sign-off closes each gate.** Local tests do
  not establish that a gate is complete.

## 2. Maintainer decisions

Decided by the maintainer on 2026-11-16: each recommendation below is
accepted as written. Two notes record what changed between the draft and
the decision.

| ID | Decision | Recommendation |
| --- | --- | --- |
| D1 | Scope | Required: M03 to M05 and M09 (#199, #200, #201, #205). Stretch: M06 to M08 (#202, #203, #204), each dropped to 2.2 without a replan if it is not merged when M10 starts. |
| D2 | Where 2.0.x patches come from once `main` is `2.1.0.dev0` | Ship the error-message pass (#199) as 2.0.3 from `main` first, since it adds no names. Then move `main` to `2.1.0.dev0`. Cut a `2.0.x` branch from the last 2.0 tag only when a patch is actually needed. |
| D3 | Pre-release | One `2.1.0rc1` with a one-week window before `2.1.0`. The new names are frozen from 2.1.0 onward, so this is the last cheap point to rename one. |
| D4 | Shape of the iterable source (#201) | A separate adapter class passed as `fileobj`. It leaves the frozen `fileobj` parameter's meaning alone and keeps `open()`'s validation simple. The class name is decided at M05. |
| D5 | One-shot helpers (#200): synchronous twins, and the default limit | Add `aiogzip.codec.compress()` and `decompress()` as well as the async pair. Default `max_decompressed_size=None`, as everywhere else in the API, with the recipe for untrusted input showing a limit. |
| D6 | Value of the `mode` attribute (#203) | The normalized mode string, such as `"rb"` or `"wt"`, which is what the `repr()` already shows. `gzip.GzipFile.mode` is an integer and is not worth copying. |
| D7 | Review process | Keep Codex review of each `src/` PR and a cross review of the release candidate. Docs-only and CI-only PRs need the hosted matrix alone. |
| D8 | API manifest | Add `tests/data/public_api_2_1.json` as the 2.1 contract. Keep `public_api_2_0.json` unchanged, with a test that the 2.1 manifest contains every 2.0 entry unaltered. |

**D1, added scope.** The member-count limit (#231) was filed after the
draft and is on the `2.1.0` milestone. It is gate M14, with the stretch
rule: it moves to 2.2 without a replan if it is not merged when M10 starts.

**D2, as it stands.** The error-message pass (#199) merged to `main` on
2026-11-14, after 2.0.2. 2.0.3 ships it together with the fixes for #232
and #234, and the fix for #233 once its PR (#236) merges. `main` moves to
`2.1.0.dev0` after 2.0.3 is published. No PR that adds a public name
merges before then.

## 3. Gate register

| Gate | Item | Issue | Acceptance |
| --- | --- | --- | --- |
| M01 | Start | | D1 to D8 decided and recorded here. 2.0.3 is published and `main` is `2.1.0.dev0`. The plans index links this plan. |
| M02 | Performance baseline | #206 | See [M02 below](#m02-performance-baseline). |
| M03 | Error-message pass | #199 | See [M03 below](#m03-error-message-pass). |
| M04 | One-shot `compress()` and `decompress()` | #200 | See [M04 below](#m04-one-shot-helpers). |
| M05 | Reader adapter for `AsyncIterable[bytes]` | #201 | See [M05 below](#m05-iterable-reader). |
| M06 | Binary `iter_batches()` and `iter_chunks()` (stretch) | #202 | See [M06 below](#m06-binary-iteration). |
| M07 | `await open()`, `aclose()`, `mode` (stretch) | #203 | See [M07 below](#m07-handle-parity). |
| M08 | `ResourceWarning` for an unclosed handle (stretch) | #204 | See [M08 below](#m08-resourcewarning). |
| M09 | Documentation | #205, #214, #217 to #220 | See [M09 below](#m09-documentation). |
| M10 | 2.1 API contract | | See [M10 below](#m10-api-contract). |
| M11 | Performance check | | See [M11 below](#m11-performance-check). |
| M12 | Candidate, review and feedback | | See [M12 below](#m12-candidate-review-and-feedback). |
| M13 | Publication | | See [M13 below](#m13-publication). |
| M14 | Member-count limit (stretch; before M10) | #231 | See [M14 below](#m14-member-count-limit). |

- [ ] M01
- [ ] M02
- [ ] M03
- [ ] M04
- [ ] M05
- [ ] M06
- [ ] M07
- [ ] M08
- [ ] M09
- [ ] M10
- [ ] M11
- [ ] M12
- [ ] M13
- [ ] M14

M03's change is merged (#199, closed 2026-11-14). The gate closes when 2.0.3
ships it and the maintainer signs off.

### Order

```text
M01 ─┬─ M02 ──────────────────────────────┐
     ├─ M03 (merged; ships as 2.0.3)      │
     ├─ M04 ─┐                            ├─ M10 ─ M11 ─ M12 ─ M13
     ├─ M05 ─┴─ M09                       │
     └─ M06, M07, M08, M14 (stretch) ─────┘
```

M04, M05 and M14 are independent of each other. M06 needs M02's baseline. M09's
recipes for HTTP and object-store bodies need M04 and M05; its other parts
do not. M10 starts when the required gates are merged; a stretch gate not
merged by then moves to 2.2.

## 4. Gate details

### M02: performance baseline

Acceptance:

- A clean-source capture of `--all` on the runtime baseline (§1), on the stdlib engine and on zlib-ng, recorded with its environment
  attestation under `plans/benchmarks/`.
- The same capture on `v2.0.0a1` and `v1.11.0`, so the record shows what
  changed since the published table and since 1.x.
- `docs/performance.md`'s table, date, Python version and quoted
  multipliers are updated from it. #161 is closed.
- Each workload more than about 5% slower than its a1 figure has its own
  issue with a targeted micro-test. Fixing them is not part of this gate.

This gate needs a quiet window. It can run at any point before M06 and M11,
which compare against it.

### M03: error-message pass

Merged as #199. Acceptance:

- A synchronous file object passed as `fileobj` gives a message that says
  what was wrong and names `aiofiles.threadpool.wrap()`, in read and in
  write mode.
- An error raised while reading a path-opened file carries the filename as
  an exception note. The codec's own errors do not change.
- "Not a gzipped file" reports the leading bytes and, for Zstandard, bzip2,
  xz and zip signatures, names the format.
- No exception type changes. The stable message prefix
  `decompressed output exceeded max_decompressed_size` is untouched.
- The sync-object detection is on the error path only, and the PR shows the
  read path's bytecode or timing is unchanged.

Closed point: the changed messages are outside the freeze and got a
changelog entry, not a ledger row.

### M04: one-shot helpers

Acceptance:

- `aiogzip.compress()` and `aiogzip.decompress()`, and the codec twins if
  D5 keeps them, with the options and input types #200 lists.
- Hypothesis parity with `gzip.compress()` and `gzip.decompress()` on both
  engines, including multi-member input and trailing zero padding.
- The limit raises before the full expansion is held in memory. A test
  pins peak output at and one byte past the limit.
- Large inputs are offloaded and small ones are not, through the existing
  thresholds; a fairness test shows the event loop is not held.
- A cancelled call returns only after its in-flight native step settles.

### M05: iterable reader

Acceptance:

- The adapter D4 chooses works as `fileobj` for binary and text reads,
  including `readline()`, `iter_batches()` and backward seeks within the
  rewind cache.
- Items of one byte, of exactly `chunk_size` and larger all work, as do
  multibyte characters and CRLF pairs split across items.
- A source exception, an early exit and a cancellation during `__anext__`
  each leave the adapter terminal and the gzip handle in the state the
  file-state model already specifies for a custom source.
- It has a synchronous `tell()` and passes `aclose()` through.
- The PR states whether the file-state model needed a change. The
  expectation is that it does not.

### M06: binary iteration

Stretch. Acceptance:

- `iter_batches(hint)` and `iter_chunks(size)` on the binary handle, with
  the semantics of the text handle's `iter_batches()` and of a
  `read(size)` loop.
- `tell()` is exact at every batch and chunk boundary.
- Interleaved `io,micro` comparison against M02 shows no regression in the
  existing read and readline benchmarks.

### M07: handle parity

Stretch. Acceptance:

- `await aiogzip.open(...)` opens and returns the handle;
  `async with await aiogzip.open(...)` works; `open()` on an open handle
  still raises.
- `aclose()` behaves as `close()`. `mode` has the value D6 sets.
- The file-state model's lifecycle table and the ledger record the
  `__aenter__` relaxation, and the stateful harness covers entering an open
  handle.
- Positive typing cases for both checkers.

### M08: ResourceWarning

Stretch. Acceptance:

- A handle that was opened and dropped without `close()` emits one
  `ResourceWarning` naming the user-facing class, the file and the mode. A
  writer's message says the output is incomplete.
- The finalizer changes no state and performs no I/O.
- No warning after `close()`, after a failed `open()`, or for a handle
  that was never opened.
- aiogzip's own suite passes with `-W error::ResourceWarning`.
- The changelog warns users who run their tests with warnings as errors.

### M09: documentation

Acceptance:

- The recipes #205 lists, with each claim about another library checked
  against its current documentation.
- A CLI section in the docs.
- Every `open()` and constructor parameter is documented in one place
  (#217, done for 2.0.x), extended with the parameters this release adds.
- Overstated compatibility claims and pre-release phrasing are gone from
  the user-facing pages and docstrings (#218, done), and the pages this
  release adds do not bring them back.
- `SECURITY.md` covers every entry point that takes untrusted input (#219,
  done for 2.0.x), extended to the one-shot `decompress()`, the iterable
  reader and M14's limit if it lands.
- The error guide's taxonomy covers text-mode encoding errors, the
  library's warnings and the exception notes M03 adds (#220, done).
- `docs/api.md` documents every new name. `docs/migration.md` gains a
  short "new in 2.1" section; nothing needs migrating.
- `docs/index.md` and the README mention the one-shot helpers and the
  iterable reader where they currently describe the workaround.
- `AGENTS.md` needs no version entry: #214 fixed the stale commands and
  #240 replaced the version history with pointers to `CHANGELOG.md`.
- The strict docs build and `tests/test_doc_examples.py` pass.

### M10: API contract

Acceptance:

- `tests/data/public_api_2_1.json` is captured and checked in CI as D8
  describes, and the test that it contains the 2.0 manifest passes.
- `__all__`, `tests/test_public_exports.py` and the typing contract tests
  for mypy and ty cover every new name.
- `docs/stability.md` describes the 2.x surface instead of "the supported
  2.0 surface", and says the 2.1 additions are covered from 2.1.0.
- The release artifact builder and the installed-artifact checks use the
  2.1 manifest.

After this gate no public name is added or renamed without reopening it.

### M11: performance check

Acceptance:

- Interleaved `io,micro` captures of the candidate against the M02
  baseline, on both engines, compared by per-benchmark minimum.
- No existing benchmark is more than about 5% slower, or each one that is
  has a targeted micro-test and a recorded decision.
- Benchmarks exist for the one-shot helpers and the iterable reader, with
  `asyncio.to_thread(gzip.decompress, ...)` and `decompress_chunks()` as
  their comparisons. Their results go in the performance guide.

Needs a quiet window.

### M12: candidate, review and feedback

Acceptance:

- The changelog entry lists every addition and every ledger row.
- A cross review of the exact candidate, as D7 sets, with the required
  hosted checks green at that commit.
- If D3 keeps it: `2.1.0rc1` published, the feedback window passed, and
  the reports received and their dispositions recorded.
- The maintainer's explicit approval.

### M13: publication

Acceptance:

- Release preparation and tagging through the existing release workflow,
  with the recorded artifact hashes.
- The PyPI publish and the GitHub release are both confirmed.
- The docs deploy a `2.1` version and `latest` follows it.
- `main` moves to the next development version, and the plans index marks
  this plan complete.

### M14: member-count limit

Stretch. Added on 2026-11-16 from #231, so it is numbered out of order; it
must merge before M10 or it moves to 2.2. Acceptance:

- The PR records which of #231's options it takes. The expected one is a
  `max_members` limit, default `None`, on `inspect()`, `verify()`,
  `GzipDecoder`, `decompress_chunks()` and the file handles.
- Exceeding it raises a plain `OSError` with a stable message prefix, as
  the size limit does, before the record for the member past the limit is
  kept.
- A test pins `inspect()`'s peak memory on a file of many empty members,
  with the limit and without.
- The member loop stays in `codec.py`. No wrapper counts members itself.
- `SECURITY.md` and the untrusted-input recipe show the limit next to
  `max_decompressed_size`.
- If the check is on the read path, the PR carries the comparison the
  hot-path rule in §1 requires.

## 5. Alongside this plan

These change no public API and gate nothing here. They can merge at any
time, with two constraints.

| Issue | Item | Constraint |
| --- | --- | --- |
| #212 | Retire finished-release scaffolding | Done on 2026-11-14. |
| #209 | Coverage-guided fuzzing | A scheduled job, never a required check. Add harness cases for the M04 and M05 entry points when they exist. |
| #210 | Free-threaded CI leg | Informational until it has been green for a while. |
| #239, #160 | macOS queue cancellations; Python 3.15 through setup-python | CI only. A matrix change must update the branch-protection contexts. |
| #213 | Duplication and dead code | Dead code and the shared cleanup helper at any time. Hot-path items not between M10 and M13, so M11 measures only the release's own changes. |

## 6. Deferred past 2.1.0

- **Internal native-file layer** (#211), and AnyIO/Trio (#71) after it.
- **Member-chunked writing and a member index** (#207), then **parallel
  compression** (#208). Both need a file-state model revision.
- **In-memory seek checkpoints** (#72): decide once #207 exists.
- **Tightening the `open()` fallback overload,** so a misspelled keyword
  fails type checking. The freeze covers overload behavior, so this needs
  its own decision.
- **CLI flags:** a size limit (#230), several paths and an `info`
  subcommand. The last two are not yet filed.
- **ISA-L:** `docs/adr-isal.md` stands.
- Stretch gates M06 to M08 and M14, if D1 drops them.

## 7. Risks

- **A new name is wrong and then frozen.** D3's release candidate and M10's
  single freeze point are the mitigation.
- **The iterable reader meets a source the model does not cover.** M05
  requires the PR to state whether the model changed; if it must, that is a
  model revision with its own review, not a test edit.
- **Hot-path drift from many small additions.** M02 before the first
  feature PR, per-PR comparisons for read-path changes and M11 at the end.
- **No quiet window.** M02 and M11 wait for one. The feature gates do not,
  apart from M06.
- **Stretch gates delay the release.** D1's rule moves them to 2.2 without
  a replan.
