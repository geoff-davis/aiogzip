# aiogzip 2.0.0rc1 plan

> **Status:** draft, 2026-10-08. Development version `2.0.0rc1.dev0`.
>
> **Source:** two independent read-only reviews of the released `v2.0.0b2`
> (`962bfe4`), from the same [brief](reviews/data/rc1/rc1-review-prompt.txt):
> [Claude Opus 5.5](reviews/data/rc1/opus-review.md.txt) and
> [Codex](reviews/data/rc1/codex-review.md.txt). This plan also takes in the
> [b2 post-release follow-ups](reviews/v2.0.0b2-post-release.md#rc-handoff).
>
> **Not a promise of an RC.** If the repairs here, or beta feedback, show a
> need for a public-contract change, the next release is `2.0.0b3`.

## 1. Baselines and rules

From the b2 RC handoff (plan §17):

```text
public API baseline:       v2.0.0b1 (frozen manifest tests/data/public_api_2_0.json)
approved behavior fixes:   b2 exception ledger (BC1-BC10), extended here
immediate runtime oracle:  v2.0.0b2
performance baseline:      v2.0.0b2, with historical continuity rows
```

- **No public API change.** [docs/stability.md](../docs/stability.md) allows
  "compatible correctness fixes, documentation and packaging updates" in
  release candidates. A repair that needs a signature, exception type or
  dataclass change goes to b3 instead.
- **Observable behavior changes get a ledger row.** Each repair that turns a
  wrong result into an error, or otherwise changes what a caller sees, gets a
  new row (BC11 onward) in the
  [behavior-exception ledger](reviews/v2.0.0b2-behavior-exceptions.md) and,
  where it touches file-handle state, a row in the
  [file-state model](design/v2.0.0b2-file-state-model.md). Tests are not
  edited silently to match new behavior.
- **Reviews.** Claude implements. Codex reviews each repair read-only before
  it merges. Every gate closes on the maintainer's explicit sign-off.
- **Benchmarks are deferred.** The maintainer's machine is not quiet. No
  timing run happens until the maintainer says it is, and then only with
  authorization and a Codex-confirmed pre-registration, as in b2. Repairs
  that touch a measured path (R01's text seek, R03, R04, R08, R15's close, and R09
  if it changes `readinto`) record their timing check as pending; R12 collects
  them.
- **Each repair merges as its own PR** with both engines' full suites green
  locally and the hosted matrix green.

## 2. Gate register

| Gate | Item | Acceptance |
| --- | --- | --- |
| R01 | Text seek failure | A failed or cancelled text `seek()` can never be followed by wrong text; ledger and state-model rows |
| R02 | Stateful model | The model rejects wrong text after a failed seek and exercises `SEEK_END`; the harness closes handles on timeout |
| R03 | Inspection settlement | `inspect()` and `verify()` settle their own open and native reads under cancellation |
| R04 | `SEEK_END` | End-relative seeks account for buffered output when EOF is already known |
| R05 | Exact-artifact publication | The publish job uploads exactly the files it validated, with checked hashes |
| R06 | Action pinning | Every workflow action pinned to an exact version |
| R07 | CI matrix | Python 3.14 on Windows and macOS, a macOS zlib-ng leg; branch-protection contexts updated |
| R08 | `writelines()` bound | Text `writelines()` retains a bounded number of pending entries |
| R09 | Small repairs | Cancellation-count leak, recorded secondary errors, CLI errors, `readinto` comment |
| R10 | Documentation | Error-wrapping asymmetry, closed-handle iteration, negative seeks, decode-error retry, `inspect()` memory |
| R11 | Differential rerun | Stateful and differential sweeps against b2 and b1 pass, with every new difference claimed by a ledger row |
| R12 | Performance | Deferred timing checks for R01, R03, R04, R08, R15 and any R09 `readinto` change run in a quiet window; no unexplained cost above 5% |
| R13 | RC review and approval | Cross review of the exact RC candidate; hosted CI at that SHA; the maintainer's explicit approval |
| R14 | Publication | Release preparation, exact-artifact publication and post-release record, as for b2 |
| R15 | Cancelled close | A cancelled `close()` or context exit settles the owned native close; no handle reports closed over an open file |

- [x] R01
- [x] R02
- [x] R03
- [x] R04
- [x] R05
- [x] R06
- [x] R07
- [x] R08
- [x] R09
- [x] R10
- [x] R11
- [x] R12
- [x] R13
- [ ] R14
- [x] R15

## 3. Order

1. R02's harness timeout fix first. It is small, test-only, and stops the
   Windows job failing on seed 734 (two of the last four Windows runs).
2. R01 together with R02's model tightening, since the model change is what
   proves R01 stays fixed.
3. R04, then R03, then R15 (both reuse the native settlement path).
4. R05–R07 (workflow-only, can run in parallel with the repairs).
5. R08–R10.
6. R11, then R12 when the machine is quiet, then R13 and R14.

## 4. Repairs

### R01: failed or cancelled text seek

**Defect (Opus, reproduced).** `AsyncGzipTextFile.seek()` moves the binary
reader first and resets the text decoder, buffer and origin only afterwards
([`_text.py` `seek`](../src/aiogzip/_text.py)). `_seek_to_plain_position`
clears the buffer only at the end of its replay. If the binary seek or the
replay raises, or the task is cancelled, the old buffered text and origin
remain over a binary position that has moved, binary health stays HEALTHY,
and the next read returns wrong text with no error. Reproductions:

- a cookie seek whose source read fails once with no effect: `read()` returns
  `'lineline 0000…'` instead of `'line 0030…'`;
- a forward plain seek: a malformed line, then lines 3–16 skipped;
- cancelling a seek on a real file opened by path: stale lines, then a jump.

It is not a b2 regression; b1 and 1.11.0 behave the same.

**Repair (as implemented and reviewed, PR #114).** The text seek is a
transaction over the binary read cursor, the binary reader's logical position
and decoder identity. At the start of a seek the text handle records that
cursor and a snapshot of its own read state (decoder state, buffer and offset,
pending CR, newline record, pending lines, origin and poison latch). On any
`BaseException`:

1. *Cursor moved:* the binary reader becomes `BROKEN` with EOF set (also from
   validation salvage, since the position is unknown), its decoder is
   discarded when no binary read call is active, and the text poison latch
   clears the buffer. Text and binary reads refuse until `seek(0)`. Binary
   health stays the single authority (G12) and recovery is the established
   BC2/BC10 path.
2. *Cursor unchanged:* nothing was consumed, so the text snapshot is
   restored when binary health still permits a no-effect retry (BC2); a
   failure that set salvage or `BROKEN` without moving the cursor keeps that
   policy.

Rejections before anything moves (whence and cookie validation, the text
reservation, an active binary call, an unhealthy cookie origin) therefore
change nothing without separate pre-checks. An earlier draft's pre-check
design was replaced because a cookie seek can re-anchor text over a no-op
binary seek; the snapshot covers that case.

Re-anchoring the text origin at the binary position with a fresh decoder is
rejected: even a character boundary is not enough for stateful encodings and
newline state. Recovery depends on a physical rewind or an intact replay
cache, and configured limits still apply; a non-rewindable source has to be
reopened.

**Behavior change.** BC11: after a failed or cancelled text seek, reads raise
until recovery instead of returning wrong text. Add the ledger row, a
file-state model row for "text seek fails or is cancelled", and a
`docs/errors.md` sentence.

**Tests.** Cookie and plain targets, each with a no-effect source failure, a
consumed-input failure, cancellation at several points (including a native
file opened by path), and a decompression-limit failure. Assert that the next
read either returns exactly the right continuation or raises, never wrong
text, and that `seek(0)` then recovers where the source can rewind. A
rejection test with an active binary read asserts unchanged health, decoder
and continuation. Mutation check: removing the invalidation must fail the
tests.

*Closed 2026-10-07: Codex approved, maintainer signed off, merged in PR #114.*

### R02: stateful model and harness

- **Timeout cleanup.** `tests/stateful/interpreter.py` abandons `drive()`
  when `SCENARIO_TIMEOUT` (30 s) fires and never closes the handle, so on
  Windows `TemporaryDirectory` cleanup fails with `WinError 32`. After a
  timeout: release the gate, let the scenario's own tasks settle (cancelling
  them after a grace period), then close the handle, all bounded. Record the
  cleanup outcome beside the timeout event, which still fails the scenario.
  A worker stuck past the bound is left to the `faulthandler_timeout`
  watchdog; cleanup cannot safely release a file a worker still uses. Seed
  734 is fixed by the generator, so give scenarios more time on slow runners
  rather than lightening it; do not hide a real hang. *(Done in PR #113:
  `SCENARIO_TIMEOUT` is 90 s. A forced-timeout sweep then found the harness
  deadlocking when the timeout landed on a gate-parked native call, since
  the exit waits for it (BC1) and the gate opened only after the exit; the
  deadline now expires the gate, releasing every later arming too. The same
  sweep found R15.)*
- **Failed text seeks.** `model.handle_error` widens the model after a
  failed text seek instead of requiring refusal or exact content
  ([`tests/stateful/model.py`](../tests/stateful/model.py)). Tighten it to
  the R01 rule, and add a cancel-during-seek event with payloads larger than
  one chunk. Text payloads are currently at most 3,000 characters. *(The
  model now treats a failed text seek as `BROKEN`, merged with R01 in PR
  #114. The cancel-during-seek event followed, test-only: seeds from
  2,000,000 are text scenarios of 3,000, 20,000 or 60,000 characters (up
  to about 150 KB, more than twice the largest source chunk), and their
  `cancel` events can park a cookie seek (`seek_mark`). The gate takes a
  skip count (`after`): it lets that many source accesses (reads, seeks,
  native executor jobs) through before it parks one, so the cancel can
  land after the replay has moved the cursor. 200 block seeds join the PR
  set; in 7 of them a cancelled cookie seek has moved the cursor, and
  without the skip none does. The model now fails any nonzero read that
  returns after a failed text seek moved the cursor, until the reader
  leaves BROKEN. Reverting R01's invalidation (restoring the old text over
  the moved cursor) fails 9 of the 200 seeds, 6 of them on public reads,
  and the pinned seeds 2000137 and 2000160. The block also found a model
  gap: after a failed text seek moved the cursor, the model kept its last
  position as certain, so a cookie taken on the BROKEN reader named the
  wrong place once a seek to it recovered the reader. Such a reader may
  now stand at any offset (seeds 2000322 and 2001408 join the regression
  seeds), and a cookie taken at an uncertain position keeps its set of
  offsets, which a seek to it restores, so the text after that recovery is
  still checked against the payload. A second gap failed seed 2000012 on
  Windows 3.14 CI only. The stateful test compresses its wires at run time,
  and compressing this one with zlib-ng reproduces the failure locally,
  consistent with Windows 3.14's bundled zlib-ng. On that wire a cancel
  lands inside `read(-1)` on a custom source without a checkpoint. The read
  consumed an unknown amount before the cancel broke the reader, but the
  model kept the read's start as certain, so a cookie taken on the BROKEN
  reader named a later offset than the model allowed. A cancel that breaks
  the reader now lets the position drift forward, as a failure that breaks
  it already did; two model tests pin the trace. With zlib-ng wires, seeds
  0–1,999, 1,000,000–1,000,399 and 2,000,000–2,001,999 pass the model;
  before the change only 2000012 failed. Seeds 2,000,200–2,001,999 pass the
  model with stdlib wires too. R11's sweeps
  (0–5999 and the R04 block against b2 and b1, 0–5999 against c0) give
  the same results as before.)*
- **Differential on the seek-cancel block.** Against b2, b1 and c0, 19,
  18 and 19 of the block's first 200 seeds had unclaimed differences. In
  14 of b2's 19 the only one was a harness artifact: a cookie seek that won
  its race with the cancel returned a cookie, which the trace did not
  symbolize inside a `cancel` row. The rest were BC11 consequences the R11
  predicate did not cover. *(Done on `test/rc1-r02-differential`. The trace
  symbolizes a parked event's first outcome as its call's, so the cookie
  is a symbol, and a closed reader's cancelled `seek_mark` row carries no
  cookie, as a direct one does (b1/2000039, BC3). BC11 now also triggers
  on a `cancel` whose seek call is cancelled; against b1 that row may also
  carry the lost-range `taken` of a native read the cancel stopped (BC2's
  L2 trigger), which the candidate's row lacks. Against the candidate's
  refusal it claims a text `seek_end` that returns a position, and a
  reference that reads on into a `UnicodeDecodeError` or `BadGzipFile`,
  or into an injected source failure that the scenario armed and the
  reference had not yet raised, with a `taken` range inside the wire. It
  also claims an `abort` around such a read when the abort outcome is the
  same on both sides. The error types are consistent with reading on from
  the moved cursor; they are not independent evidence of that cause. b1
  has no BC11, so its lossy model stays healthy over a moved cursor and
  stops checking content there until a completed `seek(0)`. The lossy run
  records each such span (`unmodeled`), which must match its own cursor
  witnesses and b1's `seek(0)` rows exactly, and BC2 claims nothing inside
  one (b1/2000121, an open span; b1/4533, a span closed by `seek(0)`, after
  which BC2 claims b1's lost input as before). Seeds 2,000,000–2,000,199
  then pass against b2 and c0 (BC11 claims 6 each). Against b1 the last
  difference, b1/2000100, is BC2's: a cancelled cookie seek entered from
  validation salvage, but its rewind to 0 recovered b1's reader before the
  cancel stopped the native read of the first chunk (`taken [0, 7]`). At
  maintainer direction BC2's narrow clause S claims that cancel row only,
  and BC11 claims b1's read on into `BadGzipFile` after it, so the block
  passes against b1 too.
  Eleven runs join `tests/data/rc1_reference_runs.json` (ten block runs and b1/4533),
  recorded on stdlib and
  zlib-ng with identical records, and their claims and near misses are
  pinned in `test_differential.py`. The base sweeps give R11's counts.)*
- **`SEEK_END`.** The generator never issues end-relative seeks. Add them,
  including after an oversized `peek()`, to catch R04-class defects.
  *(Done with R04: a separate seed block from 1,000,000, so lower seeds are
  unchanged; 200 block seeds join the PR set.)*
- Re-record the b1 reference runs (`tests/data/wp10_b1_runs.json`) if the run
  records change, as in b2.

*Closed 2026-10-08: Codex approved, maintainer signed off, merged in PRs #113, #114 and #125; the differential on the seek-cancel block is a follow-up.*

### R03: inspection and verification settlement

**Defect (both reviewers; Codex reproduced with a controlled executor).**
`_scan_gzip` in `src/aiogzip/_inspection.py` awaits `aiofiles.open()` and
native `read()` directly. A cancelled open can leave a late-opened file with
no owner, and a cancelled read lets cleanup close the source while the worker
is still reading it, which then raises `ValueError`. b2 fixed these classes
for the file handles (BC1, BC3, BC9) but not here.

**Repair.** Reuse the settled path acquisition from `_opening` and the
native-call settlement from `_source_io` for the scanner. Borrowed
`fileobj` sources keep their current ownership rules.

**Tests.** Gated acquisition and a gated started read for both `inspect()`
and `verify()`, with single and repeated cancellation and borrowed sources:
a late acquisition is closed exactly once, and cleanup runs only after the
worker's last access. Performance: settlement added 5–9% per call on the
file paths in b2 (G17 D1–D4); the timing check is deferred to R12.
*(Implemented on `fix/rc1-inspection-settlement`; ledger BC14, since BC13 is
reserved for R15.)*

*Closed 2026-10-07: Codex approved, maintainer signed off, merged in PR #116.*

### R04: `SEEK_END` with known EOF

**Defect (Codex, reproduced).** The binary `SEEK_END` branch drains buffered
output only inside `while not self._eof`. After a `peek()` large enough to
reach EOF, `seek(0, SEEK_END)` returns the current position (0 on a fresh
10-byte file, 1 after reading one byte) and `read()` still returns the data.
Also present in b1.

**Repair.** Account for the unread buffered output before the loop as well
as inside it. **Behavior change:** BC12, end-relative seeks now report the
true end; ledger row.

**Tests.** Offsets zero, negative and positive, after an oversized `peek()`
and after partial consumption, on physical and cached-rewind sources, binary
and text (`seek(0, SEEK_END)` on text reads to the end first). Drain unread
output without double-counting it. Controls with a corrupt trailer and with
`max_decompressed_size` show that seeking to the end cannot bypass
validation or limits. *(Implemented on `fix/rc1-seek-end`.)*

*Closed 2026-10-07: Codex approved, maintainer signed off, merged in PR #115.*

### R05–R07: workflows

- **R05.** Build the wheel and sdist once with pinned tools, run
  `scripts/smoke_installed_artifact.py` on those exact files, record their
  SHA-256 values, and upload exactly those files; a mismatch against the
  release record's hashes fails the job. Add a negative check that an
  altered artifact cannot reach the upload step. Rehearse on a test tag
  (TestPyPI) before the RC tag.
- **R06.** Pin every action in `ci.yml`, `docs.yml` and `publish.yml` to an
  exact version (only `setup-uv` is pinned today).
- **R07.** Add Python 3.14 legs on Windows and macOS and a macOS zlib-ng leg,
  and update the branch-protection contexts in the same change (CLAUDE.md
  gotcha). Refresh the stale coverage comment in `ci.yml`.

  *As implemented (PR #118).* The first Windows 3.14 run stopped at
  collection: harness fixtures rebuild gzip wires with `gzip.compress()`,
  whose bytes depend on the platform's zlib, and that leg's stdlib produced
  different streams (consistent with a zlib-ng-backed build; reproduced
  locally by swapping in zlib-ng's compressor). At maintainer direction
  (2026-10-08, "Pin oracle + gate replays"): `test_oracle.py` now reads its
  wire from the committed `tests/data/oracle_late_corruption.gz` (SHA-256
  checked), and `test_differential.py`, whose comparisons replay recorded
  traces or pinned wire offsets, is skipped as a whole where the generator
  does not reproduce those wires (`recorded_wires.py`: one SHA-256 over the
  generated wire of every recorded seed and every seed the module pins).
  Per-test gating was rejected in Codex review of `f8f6c95` as incomplete.
  `test_recorded_wires_are_reproduced` fails on any non-Windows platform that
  does not reproduce them, so Linux and macOS cannot skip silently. Branch-protection contexts are added after
  merge (a required context cannot be satisfied before its job exists on
  `main`), verified by a `gh api` read before R07 closes.

  *macOS legs reduced (2026-10-08, maintainer direction).* With four macOS
  jobs per run, overlapping runs left macOS jobs queued until they were
  cancelled with no step run (#118, #119 and `main` at `2c9bf3c`), consistent
  with GitHub's per-account limit on concurrent macOS jobs. The macOS 3.12
  build leg is dropped, and the separate macOS fast-engine job is folded into
  the macOS 3.14 build leg, which reruns the suite with the `[fast]` extra and
  attests zlib-ng active (job timeout 25 minutes). Each run again has two
  macOS jobs. The contexts `build (macos-latest, 3.12)` and
  `fast-engine (macos-latest)` leave branch protection before that change
  merges, since no job reports them afterwards.

*Closed 2026-10-08: Codex approved, maintainer signed off, merged in PR #118. PR #121 later cut the macOS jobs to two per run.*

### R08: text `writelines()` with empty inputs

**Defect (Codex; confirmed in code).** Each empty string is appended to
`pending`, but the flush threshold counts only characters, so a long run of
empty strings grows `pending` with the input count, contrary to the
bounded-memory claim in `docs/api.md`. Inherited from b1. Each entry is a
reference to the shared empty string.

**Repair.** Skip or coalesce empty inputs while keeping empty-write encoder
semantics (BOM handling for UTF-16 and UTF-32). **Tests:** long empty runs,
mixed inputs, iterator failure, BOM encodings, and a direct item-count bound.
Timing check deferred to R12.

**Repair (as implemented).** Empty strings (exact `str` only: a subclass may
override `__len__`, so it is stored as before; Codex review of `b7c971b`) are
no longer stored; a `pending_empty` flag records that one joined the current
batch, and every
flush condition tests `pending or pending_empty`. The batches handed to the
encoder path, and so the output bytes, are exactly those of the b2 algorithm:
an all-empty batch is still written (an empty UTF-16/32 write emits the BOM),
including before an iterator failure or a non-`str` item. No observable
behavior changes, so there is no ledger row. `tests/test_text_writelines_empty.py`
compares every batch with a reference model of the b2 algorithm
(parametrized and Hypothesis-generated inputs) and reads the live `pending`
list during 200,000 empty inputs (always 0) and a mixed run (at most
`chunk_size`). On the b2 source only the two bound tests fail; dropping empty
strings without the flag fails 19 of 28; trusting a subclass's zero length
fails the 5 subclass regressions that depend on it.

Both reviewers' categories are in the archived reports. R09 and R10 promote
several of Opus's nice-to-have findings (RC1-06, RC1-07, RC1-09, RC1-10 and
RC1-13) into required gates; that is this plan's decision, not the
reviewers' categorization.

*Closed 2026-10-08: Codex approved, maintainer signed off, merged in PR #119.*

### R09: small repairs (no behavior change beyond the noted ones)

- Cancellation count: when an abort cancels a custom source or sink call that
  then ends without `CancelledError`, still `uncancel()` once, so an
  enclosing `asyncio.timeout()` keeps classifying correctly (Opus RC1-06).
- Secondary errors during the context-exit abort are dropped
  (`except ...: pass` in `_binary.py`); attach them to the primary exception
  with `add_note()` (Opus RC1-07).
- CLI: non-`OSError` failures print a traceback and break `--json`; report
  them in the same form with exit status 2 (Opus RC1-10).
- `_common.py` claims `_MAX_CHUNK_SIZE` caps `readinto`; correct the comment
  or cap the internal fill without changing results (Opus RC1-09).

*Implemented as ledger row BC15.* The comment was corrected rather than the
fill capped: `readinto()` fills up to `len(b)` before copying so a failed
refill leaves the stream intact, and a piecewise fill would change that.
Unexpected CLI failures exit with status 2, argparse's usage status, keeping 1
for stream failures. A repeated cancellation during context-exit cleanup is
not noted as a cleanup failure unless it carries one as its cause.

*Closed 2026-10-08: Codex approved, maintainer signed off, merged in PR #120.*

### R10: documentation

In `docs/errors.md`, `docs/api.md` and `docs/recipes.md` as fitting:
`write()` and `flush()` wrap custom-sink errors differently (unifying is a
b3 candidate); iterating a closed handle ends iteration rather than raising
`ValueError`; read-mode negative seeks raise `OSError` where stdlib gzip
clamps; do not retry after a `UnicodeDecodeError`, use `seek(0)`; `flush()`
on an unopened write handle returns without error; `inspect()` member
collection grows with the member count, and each header's FNAME, FCOMMENT
and FEXTRA fields are buffered whole (up to 128 MiB each); and the BC11–BC13
behavior.

*As implemented (`docs/rc1-r10`).* Every item was rechecked against the code
before it was written down:

- `docs/errors.md`: a "Closed and unopened handles" section (closed-handle
  iteration ends; `flush()` on an unopened write handle returns), a
  "Custom sink errors" section (`write()` propagates the sink's exception;
  `flush()` wraps a non-`OSError` as `OSError` with the original as
  `__cause__`), the `UnicodeDecodeError` retry warning, and BC15's cleanup
  note and consumed abort cancellation.
- `docs/api.md`: `inspect()` memory and header buffering.
- `docs/recipes.md`: BC12's `SEEK_END` and the negative-seek difference from
  stdlib gzip.
- BC11, BC13 and BC14 were already documented, in `docs/errors.md` and
  `docs/api.md`.

Two corrections to the item list above. The 128 MiB limit applies to each
whole gzip header, not to each field: FEXTRA is at most 64 KiB by the format,
and FNAME and FCOMMENT are buffered whole (only when member metadata is
collected) and bounded by the header limit. A retry after
`UnicodeDecodeError` skips the rest of the decoded chunk, not only the
undecodable bytes (about 24,000 of 60,001 lines in a 60,001-line check).

*Closed 2026-10-08: Codex approved, maintainer signed off, merged in PR #122.*

### R15: cancelled `close()` leaks a queued native close

**Defect (found by the R02 forced-timeout sweep, 2026-10-08; reproduced on
b1 and b2).** `_close_underlying` awaits aiofiles' `close()`, which is
`run_in_executor(file.close)`. If `close()` or an exceptional context exit
is cancelled while that native close is still queued, asyncio cancels the
queued job, so the file is never closed. A normal `close()` has already
latched the handle closed, so a later `close()` is a no-op and the
descriptor stays open until garbage collection. (Abort cleanup marks the
handle closed only after its underlying cleanup succeeds.) With one executor worker kept busy, cancelling
`close()` on a binary or text handle opened by path leaves
`raw.closed == False`. G19 F2 recorded only that a cancelled `close()` "can
return before the native close finishes"; a queued close never runs at all.

**Repair.** Run the owned native close through the settlement used for every
other native call (`_settle_before_cancel` on an executor call the handle
submits itself): a queued close must run, never be prevented by the
cancellation, and cancellation waits for it to finish, then propagates, with
a native close failure as its cause (BC1 shape). This covers `close()`,
context exit and abort cleanup; opening cleanup already settles through
`_initial_call` and keeps that single ownership path. Preserve aiofiles'
executor and loop policy, `closefd` ownership, and the existing
primary-error, cause/context and observer-note rules. Custom async `close()`
methods keep their cooperative contract. **Behavior change:** BC13, a cancelled `close()` waits for the
owned native close instead of possibly abandoning it. The changelog and
`docs/errors.md` say so; the b2 records keep their F2 wording, with a
pointer to R15.

**Tests.** Gated executor with the close queued and with it running, single
and repeated cancellation, binary and text, read and write modes, context
exit and explicit `close()`, owned path and `closefd`/borrowed sources.
Assert exactly one close invocation on an owned file, settled before
cancellation propagates, and actual closure (no remaining descriptor) when
that invocation succeeds; borrowed files stay open. Also (Codex plan
review):

- cancellation during the final trailer write or flush, then a settled close;
- a native close that fails, alone and with simultaneous cancellation;
- failed opening initialization with cancelled cleanup;
- active read, write and seek aborts, keeping BC8's settlement order and
  BC9's rule that no reader revives;
- the handle's state and `close()` retry behavior after an abortive close
  completes but its cancellation propagates.

Mutation check: reverting to aiofiles' `close()` must fail the queued case.
Timing check deferred to R12. *(Implemented on `fix/rc1-cancelled-close`;
ledger BC13. Reverting to aiofiles' `close()` fails 124 of the original 159
tests in `tests/test_cancelled_close.py`, including every queued case.)*

*Closed 2026-10-08: Codex approved, maintainer signed off, merged in PR #117.*

### R11: differential rerun

The b2 harness compared the candidate with c0 and b1 only, on seeds below
1,000,000. R11 adds b2 as a reference and claims the rc1 differences.
*(As implemented, test-only; no `src/` change.)*

- **References.** `differential.py --reference b2` against the clean
  v2.0.0b2 worktree (`962bfe4`). b2 already carries BC1–BC10, so only
  BC11 and BC12 apply to it; b1 gets both as well, and c0 gets BC11
  (BC11 and BC12 are present in every earlier release).
- **Cookies.** A text `seek(0, SEEK_END)` returns a cookie with a random
  per-handle nonce, so the trace now symbolizes negative `seek_end`
  results as it already did `tell_mark` cookies. Binary positions are never
  negative, and no seed below 1,000,000 has a `seek_end`, so no recorded
  trace changes.
- **`BC11-TEXT-SEEK-FAILURE`.** After a text seek event that is identical
  on both sides, is an error, has a `cursor_moved` witness of `True` in both
  run records and leaves the candidate model BROKEN, each later differing
  read (text reads and `buffer_read`) where the candidate refuses with the
  broken-stream `OSError` and the reference returns data is claimed, until
  the candidate model leaves BROKEN.
- **`BC12-SEEK-END`.** For a binary scenario with a `seek_end` (direct or
  as a parked call), the runner also runs the reference with only the BC12
  loop change applied (`fixed_root`, which refuses a reference whose loop is
  not exactly the b1/b2 loop). That fixed run must agree with the reference
  before the first `seek_end`. Every predicate then judges the candidate
  against the fixed run, including BC2's lossy run, which replays on the
  fixed root, and BC12 claims each difference from the reference's own
  trace that the fixed run removes. A difference that remains against the
  fixed run needs its own claim.
- **BC7 through `seek_end`.** b1's text `seek(0, SEEK_END)` is `read()`
  then `tell()`, so a salvage ending inside a character raises BC7's F1a
  `UnicodeDecodeError` from the seek (seed 1000132). For a reader at text
  position 0, a shadow run of the candidate with `read(-1)` in place of the
  seek must have no violation and match the candidate's trace before it.
  Its text T must decode from some prefix of the model's salvage bound, and
  the k bytes after that prefix, k taken from b1's error, must complete no
  character. Only the seek is claimed.
- **F2 through `seek_end`.** BC2's F2 (an aborted custom-source call that b1
  let finish) now includes `seek_end` among the calls, which drain the
  source like reads (seed 1000089). The shadow rule is unchanged.

Sweeps on `3f595ee` plus this harness, seeds 0–5999 and 1,000,000–1,000,199,
both engines with identical results: 0 failed against b2 (BC11 1 + 1 seeds,
BC12 4) and against b1 (as b2's release record below 1,000,000, BC11 1;
in the block BC2 26, BC3 10, BC7 2, BC8 8, BC9 1, BC11 1, BC12 4). Against
c0, seeds 0–5999 pass on both engines with BC11 claiming seed 225. The recorded references
for the new claims are in `tests/data/rc1_reference_runs.json`, whose seeds
join the recorded-wire digest (the same on Python 3.12 and 3.14).

*Closed 2026-10-08: Codex approved, maintainer signed off, merged in PR #123.*

### R12: performance

The timing windows ran at 01:00 on 2026-10-09, as
[pre-registered](reviews/v2.0.0rc1-r12-preregistration.md). The repair rows
for R01, R04, R08 and R15 were within 5% of b2; R08's empty-string
`writelines` was about 15% faster. R03's `inspect()`/`verify()` were up to
13% slower on sub-millisecond calls. An attribution run traced that to the
settled reads, and PR #128 moved them to `_NativeSourceCall`. A re-check put
`verify()` within 5% of b2 except zlib-ng on a compressible file (+6.52%,
about 10 µs per call), which the maintainer accepted. Details and evidence
are in the [R12 record](reviews/v2.0.0rc1-r12-record.md).

*Closed 2026-10-09: Codex approved, maintainer signed off, merged in PRs #128
and #129.*

### R13: RC review and approval

Codex and a fresh Claude Opus 5.5 subagent cross-reviewed the candidate in
two rounds, recorded in the [candidate review](reviews/v2.0.0rc1-candidate-review.md).
Round 1 found documentation overstatements and one low diagnostic defect,
repaired in PR #135; the artifacts were rebuilt and round 2 found nothing.

*Closed 2026-10-09: the maintainer approved `f67dd99` (hosted run
37983380928, 22 of 22).*

## 5. Deferred past RC1

Not RC1 work unless the maintainer pulls one in:

- F3 (`tell()` during `readlines()`), from the
  [G19 review](reviews/v2.0.0b2-candidate-review.md). F2 moved into RC1 as
  R15 at the maintainer's direction (2026-10-08).
- Unifying custom-sink error wrapping (needs an exception-type change; b3).
- Graceful fallback if `aiofiles` private internals change (Opus RC1-11);
  unpinned CI already exercises new `aiofiles` releases.
- An `inspect()` member or header-metadata limit (an API addition; plan §18
  resource policy).
- Python 3.15 qualification, public feedback intake and the external RC
  review named in b2 plan §17 stay on the RC path under R13 and R14.
- The b2 plan §18 opportunities, AnyIO/Trio (#71) and indexed access (#72).
