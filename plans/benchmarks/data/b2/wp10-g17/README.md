# WP10 G17 benchmark evidence

Hashes of every archive are in `sha256.json`. `aa-evidence.tar.xz` holds
the October 7 G17 A/A control window and its inputs:

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

The October 7 final windows are split to keep each file under the
repository's 1,000 KB limit:

- `c0-captures.tar.xz`: `results-c0-20261007-034407/` without its
  structural outputs (the 32 capture JSONs and logs, `captures.tsv`,
  `foreign.log`, `quiet-gate.log`, `environment.json`, `provenance.txt`,
  `window.json` and `summary.txt`), the harness as registered by
  amendment 2 (`harness/`), and `structural-analysis.md`, the read-only
  evaluation of every structural step against its criterion;
- `c0-structural-other.tar.xz`: the C0 window's structural outputs and logs
  except `g06-longline-timing`;
- `c0-g06-timing-<engine>-<side>.tar.xz`: the four `g06-longline-timing`
  outputs and logs;
- `wp0-window.tar.xz`: `results-wp0-20261007-042119/`, complete.

See the [G17 pre-registration](../../../../reviews/v2.0.0b2-g17-preregistration.md)
and the [G17 record](../../../../reviews/v2.0.0b2-wp10-qualification.md#g17-performance).
