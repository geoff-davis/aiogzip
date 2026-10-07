# WP7 G11 benchmark evidence

`evidence.tar.xz` (hash in `sha256.json`) holds both October 5 WP7 benchmark
windows and their follow-up:

- `results-20261005-205000/`: the first window, C0 against `cb90a75`, which
  found the `readlines(64)` regression; `summary-cb90a75.txt` is its summary;
- `results-20261005-210450/`: the rerun, C0 against `feea4a4`;
  `summary-feea4a4.txt` is its summary;
- each results directory holds the 16 capture JSONs and logs, `captures.tsv`
  with capture boundaries, `foreign.log` from the foreign-CPU monitor,
  `quiet-gate.log` and `provenance.txt`;
- `run.sh`, `quiet_gate.py`, `summarize.py`, the original service and timer,
  and the rerun service, as reviewed before each run;
- `allocations-feea4a4.json`: the replay-origin allocation probe at `feea4a4`;
- `snap_micro.py`, `rl64.py`, `large.py`, `large4.txt` and `large-mmap.txt`:
  the targeted micro-tests, and `micro-driver-transcribed.txt`, Claude's
  transcription of the driver commands it ran inline and of outputs it printed
  rather than saved. Their commits, worktrees, ordering and CPU pinning are
  implementer-reported.

See the [G11 record](../../../../reviews/v2.0.0b2-wp7-completion.md).
