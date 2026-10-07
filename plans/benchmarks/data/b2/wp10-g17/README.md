# WP10 G17 benchmark evidence

`aa-evidence.tar.xz` (hash in `sha256.json`) holds the October 7 G17 A/A
control window and its inputs:

- `results-aa-20261007-024602/`: C0 against C0, both engines, with the 32
  capture JSONs and logs, `captures.tsv` with capture boundaries,
  `foreign.log` from the foreign-CPU monitor, `quiet-gate.log`,
  `environment.json`, `uv-sync-check.log`, `provenance.txt`, `window.json`
  and `summary.txt`;
- `preflight-20261007-015721/`: the functional preflight's manifest,
  durations, environment and `expected-rows.json` (not timing evidence; its
  bulky outputs are not archived);
- `harness/`: the drivers, `summarize.py`, `quiet_gate.py`,
  `envcheck.py`, the structural step lists, the manifests,
  `expected-rows.json`, `harness.sha256` and both units, as registered.

See the [G17 pre-registration](../../../../reviews/v2.0.0b2-g17-preregistration.md)
and the [G17 record](../../../../reviews/v2.0.0b2-wp10-qualification.md#g17-performance).
