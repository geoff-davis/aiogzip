# aiogzip 2.0.0rc2 plan

> **Status:** draft, 2026-10-09. Development version `2.0.0rc2.dev0`.
>
> **Source:** the maintainer's choice, on 2026-10-09 after 2.0.0rc1 was
> published, of three deferred
> [R13 limitations](reviews/v2.0.0rc1-candidate-review.md#remaining-limitations)
> to fix before 2.0.0, and the
> [RC1 post-release follow-ups](reviews/v2.0.0rc1-post-release.md#post-release-decision).

## 1. Baselines and rules

```text
public API baseline:       v2.0.0b1 (frozen manifest tests/data/public_api_2_0.json)
approved behavior fixes:   b2 exception ledger (BC1-BC15), extended here from BC16
immediate runtime oracle:  v2.0.0rc1 (no differential reference yet; b2 and b1 are)
performance baseline:      v2.0.0rc1
```

The RC1 plan's rules carry over unchanged: no public API change, a ledger
row for each observable behavior change, Codex review of each repair before
it merges, the maintainer's explicit sign-off on every gate, timing only in
an authorized quiet window with a Codex-confirmed pre-registration, and one
PR per repair with both engines' suites and the hosted matrix green.

## 2. Gate register

| Gate | Item | Acceptance |
| --- | --- | --- |
| S01 | Cancelled abort settlement (R13 N3) | A cancellation while an exit's abort settles the active call still closes the owned file first, and keeps the body's exception as context; ledger BC16 |
| S02 | Shielded-future logging (R13 F2) | A native call that fails after a cancellation is reported once, through the cancellation, with nothing logged to the loop's exception handler on Python 3.14+ |
| S03 | Opening cleanup note (R13 F1, related) | A repeated cancellation during `_acquire_path`'s cleanup close is not noted as a cleanup failure, and a close failure behind it is noted, as for the scan (BC14) |
| S04 | Windows gate race | The inspection-settlement test race from the RC1 release-merge run is fixed (PR #136) |
| S05 | Differential rerun | Stateful and differential sweeps against b2 and b1 pass, with every new difference claimed by a ledger row |
| S06 | Performance | S02's change on the offload path, and any other hot-path change, timed against rc1 in an authorized window; no unexplained cost above 5% |
| S07 | Python 3.15 | Promoted from the informational job into the build matrix and branch protection if `setup-python` offers 3.15.0 before S08; otherwise stays informational |
| S08 | RC review and approval | Cross review of the exact candidate by Codex and a fresh Claude subagent; hosted CI at that SHA; the maintainer's explicit approval |
| S09 | Publication | Release preparation, exact-artifact publication and post-release record, as for RC1 |

- [x] S01 — PR #138 (BC16), signed off 2026-10-10
- [x] S02 — PR #140 (BC18), signed off 2026-10-10
- [x] S03 — PR #139 (BC17), signed off 2026-10-10
- [x] S04 — PR #136, signed off 2026-10-10
- [x] S05 — [Differential rerun](#s05-differential-rerun), signed off 2026-10-10
- [x] S06 — [Timing windows](reviews/v2.0.0rc2-s06-record.md), signed off 2026-10-10
- [ ] S07
- [ ] S08
- [ ] S09

## 3. Gate results

### S05: differential rerun

Sweeps on the candidate `0b9c7c4` (main after #136–#140) ran from a clean
worktree with its own `tests/stateful/differential.py`, against the b2
(`962bfe4`) and b1 (`048700f`) references in `.cache/wp10/`. They used seeds
0–5999, the R04 block 1,000,000–1,000,199 and the R02 seek-cancel block
2,000,000–2,000,199, on both engines. All twelve runs reported 0 failed, and
the two engines gave identical claim counts:

| Reference | Seeds | Claims |
| --- | --- | --- |
| b2 | 0–5999 | BC11 1 |
| b2 | 1,000,000–1,000,199 | BC11 1, BC12 4 |
| b2 | 2,000,000–2,000,199 | BC11 6 |
| b1 | 0–5999 | BC2 605, BC3 358, BC7 18, BC8 214, BC9 21, BC10 1, BC11 1 |
| b1 | 1,000,000–1,000,199 | BC2 26, BC3 10, BC7 2, BC8 8, BC9 1, BC11 1, BC12 4 |
| b1 | 2,000,000–2,000,199 | BC2 33, BC3 9, BC11 7 |

The 0–5999 and 1,000,000 rows equal RC1's recorded R11 results. The b2 rows
equal the sweeps run on the S01 fix (`181c29c`) before it merged. No
difference needed a new predicate: BC16–BC18 change only abort-settlement,
cancelled-open and logging paths that the generator does not reach with a
differing outcome. The stateful suite (`tests/stateful/`) passes in both
engine modes as part of the full suite at the candidate.

*Closed 2026-10-10: Codex approved, maintainer signed off ("I sign off").*

## 4. Deferred past 2.0

F3 (`tell()` during `readlines()`), `writelines()` with empty `str`
subclasses, and RC1 plan §5's implementation and API opportunities: custom-sink
error wrapping, an `aiofiles` fallback, an `inspect()` limit, the b2 plan §18
opportunities, AnyIO/Trio (#71) and indexed access (#72).
