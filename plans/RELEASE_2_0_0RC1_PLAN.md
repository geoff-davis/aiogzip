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
  that touch a measured path (R03, R04, R08) record their timing check as
  pending; R12 collects them.
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
| R12 | Performance | Deferred timing checks for R03, R04 and R08 run in a quiet window; no unexplained cost above 5% |
| R13 | RC review and approval | Cross review of the exact RC candidate; hosted CI at that SHA; the maintainer's explicit approval |
| R14 | Publication | Release preparation, exact-artifact publication and post-release record, as for b2 |

- [ ] R01
- [ ] R02
- [ ] R03
- [ ] R04
- [ ] R05
- [ ] R06
- [ ] R07
- [ ] R08
- [ ] R09
- [ ] R10
- [ ] R11
- [ ] R12
- [ ] R13
- [ ] R14

## 3. Order

1. R02's harness timeout fix first. It is small, test-only, and stops the
   Windows job failing on seed 734 (two of the last four Windows runs).
2. R01 together with R02's model tightening, since the model change is what
   proves R01 stays fixed.
3. R04, then R03.
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

**Repair.** On any `BaseException` that escapes the binary seek or the
replay, before re-raising: clear the text buffer and any pending lines, reset
the decoder, and leave the handle refusing text reads until a successful
`seek(0)` (or another successful seek). Preferred mechanism, to be confirmed
in Codex's design review: poison the binary reader through its existing
poison path, so the established BC2/BC10 recovery (`seek(0)`) applies and the
binary health stays the single authority (G12). The alternative,
re-anchoring the text origin at the binary position with a fresh decoder, is
rejected unless shown safe: that position need not be a character boundary.
Also clear the buffer before `_seek_to_plain_position` starts replaying.

**Behavior change.** BC11: after a failed or cancelled text seek, reads raise
until recovery instead of returning wrong text. Add the ledger row, a
file-state model row for "text seek fails or is cancelled", and a
`docs/errors.md` sentence.

**Tests.** Cookie and plain targets, each with a no-effect source failure, a
consumed-input failure, cancellation at several points (including a native
file opened by path), and a decompression-limit failure. Assert that the next
read either returns exactly the right continuation or raises, never wrong
text, and that `seek(0)` then recovers everything. Mutation check: removing
the invalidation must fail the tests.

### R02: stateful model and harness

- **Timeout cleanup.** `tests/stateful/interpreter.py` abandons `drive()`
  when `SCENARIO_TIMEOUT` (30 s) fires and never closes the handle, so on
  Windows `TemporaryDirectory` cleanup fails with `WinError 32`. Close the
  handle (bounded, ignoring its errors) before leaving the run, and record
  the timeout as the scenario's outcome so it still fails visibly. Then
  either lighten seed 734 (a 7-byte `chunk_size` over about 330 KB) or give
  the scenario more time on slow runners; do not hide a real hang.
- **Failed text seeks.** `model.handle_error` widens the model after a
  failed text seek instead of requiring refusal or exact content
  ([`tests/stateful/model.py`](../tests/stateful/model.py)). Tighten it to
  the R01 rule, and add a cancel-during-seek event with payloads larger than
  one chunk. Text payloads are currently at most 3,000 characters.
- **`SEEK_END`.** The generator never issues end-relative seeks. Add them,
  including after an oversized `peek()`, to catch R04-class defects.
- Re-record the b1 reference runs (`tests/data/wp10_b1_runs.json`) if the run
  records change, as in b2.

### R03: inspection and verification settlement

**Defect (both reviewers; Codex reproduced with a controlled executor).**
`_scan_source` in `src/aiogzip/_inspection.py` awaits `aiofiles.open()` and
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
and text (`seek(0, SEEK_END)` on text reads to the end first).

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

### R10: documentation

In `docs/errors.md`, `docs/api.md` and `docs/recipes.md` as fitting:
`write()` and `flush()` wrap custom-sink errors differently (unifying is a
b3 candidate); iterating a closed handle ends iteration rather than raising
`ValueError`; read-mode negative seeks raise `OSError` where stdlib gzip
clamps; do not retry after a `UnicodeDecodeError`, use `seek(0)`; `inspect()`
member collection grows with the member count; and the BC11/BC12 behavior.

## 5. Deferred past RC1

Not RC1 work unless the maintainer pulls one in:

- F2 (cancelled `close()` does not wait for the native close) and F3
  (`tell()` during `readlines()`), from the
  [G19 review](reviews/v2.0.0b2-candidate-review.md).
- Unifying custom-sink error wrapping (needs an exception-type change; b3).
- Graceful fallback if `aiofiles` private internals change (Opus RC1-11);
  unpinned CI already exercises new `aiofiles` releases.
- An `inspect()` member or header-metadata limit (an API addition; plan §18
  resource policy).
- Python 3.15 qualification, public feedback intake and the external RC
  review named in b2 plan §17 stay on the RC path under R13 and R14.
- The b2 plan §18 opportunities, AnyIO/Trio (#71) and indexed access (#72).
