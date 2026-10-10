# RC2 S06 timing evidence

The hash of the archive is in `sha256.json`. Both windows ran on 2026-10-10
as one user systemd service pinned to CPU 13 behind the G17 quiet gate, with
R12's harness.

- `windows.tar.xz`: the pre-registered S06 windows.
  - `results-ab-20261010-010000/`: rc1 `d382f17` against the RC2 candidate
    `0b9c7c4`.
  - `results-aa-20261010-011210/`: the candidate against itself.
  - Each window holds 48 capture JSONs and their logs (16 runner,
    16 write-size and 16 `rc1_paths.py`), `captures.tsv`, `foreign.log`,
    `quiet-gate.log`, `environment.json`, `uv-sync-check.log`,
    `provenance.txt` and `window.json`, with each window's `summary.txt`
    beside it.
  - `harness/` holds the driver, the retry wrapper, `summarize.py`, the
    helpers, `rc1_paths.py`, `runner-rows.json`, both manifests,
    `harness.sha256` and both units, as registered.
  - `journal.log` is the service log for all five timer firings.

See the [S06 pre-registration](../../../../reviews/v2.0.0rc2-s06-preregistration.md)
and the [S06 record](../../../../reviews/v2.0.0rc2-s06-record.md).
