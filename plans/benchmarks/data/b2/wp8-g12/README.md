# WP8 G12 benchmark evidence

`evidence.tar.xz` (hash in `sha256.json`) holds the October 6 WP8 benchmark
window and its follow-up:

- `results-20261006-031022/`: the window, C0 against `93fd3af`, with the 16
  capture JSONs and logs, `captures.tsv` with capture boundaries,
  `foreign.log` from the foreign-CPU monitor, `quiet-gate.log`,
  `provenance.txt` and `summary-93fd3af.txt`;
- `salvage-micro.txt` (in the results directory) and `salvage_micro.py`: the
  targeted interleaved micro-test for the one flagged row, and
  `salvage-micro-driver-transcribed.txt`, Claude's transcription of the driver
  it ran inline. Its CPU pinning, worktree commits and cleanliness, and
  commands are implementer-reported;
- `run.sh`, `quiet_gate.py`, `summarize.py` and the service, as reviewed
  before the run;
- `failed_abort_probe.py` and `failed-abort-probe.txt`: the failed-abort probe
  run against C0 and `93fd3af`. Its commits, worktrees and ordering are
  implementer-reported.

See the [G12 record](../../../../reviews/v2.0.0b2-wp8-completion.md).
