# RC1 R12 timing evidence

Hashes of every archive are in `sha256.json`. All three runs took place on
2026-10-09, each as its own user systemd service pinned to CPU 13 behind the
G17 quiet gate.

- `windows.tar.xz`: the pre-registered R12 windows.
  - `results-ab-20261009-010000/`: b2 `962bfe4` against the candidate
    `dd70af4`.
  - `results-aa-20261009-011210/`: the candidate against itself.
  - Each window holds 48 capture JSONs and their logs (16 runner,
    16 write-size and 16 `rc1_paths.py`), `captures.tsv`, `foreign.log`, `quiet-gate.log`,
    `environment.json`, `uv-sync-check.log`, `provenance.txt` and
    `window.json`, with each window's `summary.txt` beside it.
  - `harness/` holds the driver, the retry wrapper, `summarize.py`, the
    helpers, `rc1_paths.py`, `runner-rows.json`, both manifests,
    `harness.sha256` and both units, as registered.
  - `journal.log` is the service log for all five timer firings.
- `attrib.tar.xz`: the attribution of the `inspect()`/`verify()` cost
  (`attrib-20261009-064918/`). It holds 144 process JSONs, `runs.tsv`,
  `foreign.log`, `quiet-gate.log`, `environment.json` and `provenance.txt`,
  plus its summary, the harness as registered (`harness/`, including the
  launch command) and `journal.log`.
- `recheck.tar.xz`: the re-check of the read fix (`recheck-20261009-073404/`).
  It holds 72 process JSONs and the same records, plus its summary, harness
  and `journal.log`.

See the [R12 pre-registration](../../../../reviews/v2.0.0rc1-r12-preregistration.md)
and the [R12 record](../../../../reviews/v2.0.0rc1-r12-record.md).
