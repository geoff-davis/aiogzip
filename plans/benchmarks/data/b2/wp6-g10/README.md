# WP6 G10 benchmark evidence

`evidence.tar.xz` (hash in `sha256.json`) holds the October 5 benchmark window
and its follow-up:

- `results-20261005-021530/`: the 16 capture JSONs and logs, `captures.tsv`
  with capture boundaries, `foreign.log` from the foreign-CPU monitor,
  `quiet-gate.log` and `provenance.txt`;
- `run.sh`, `quiet_gate.py`, `summarize.py` and the one-off service and timer,
  as reviewed before registration;
- `microprobe.py`, `micro-text.txt` and `micro-salvage.txt`: the targeted
  micro-test of the two flagged stdlib benchmarks, and
  `micro-driver-transcribed.txt`, Claude's transcription of the driver command
  it ran inline. Its commits, worktrees, ordering and CPU pinning are
  implementer-reported.

See the [G10 record](../../../../reviews/v2.0.0b2-wp6-completion.md).
