# WP5 small-item investigation evidence

SHA-256 of `evidence.tar.xz`: `00dc7f96aff1b21910132190cb9691e5ed012eef4447ec3a2a0e8cf7fdb9bb22`.

The archive preserves original file bytes, including scripts and JSON without
formatting changes. Extract into an empty directory to inspect the evidence.
Subdirectories:

- `overnight`: collected September 28 stdlib throughput window, with raw hashes
  and provenance reconciliation.
- `checkpoint-split`: exploratory checkpoint-ceiling ablation and raw captures.
- `lazy-budget`: rejected lazy-budget patch, paired captures and summary.
- `first-step`: frozen dirty first-step patch, eight captures covering all 16
  throughput cases, manifest, reproducing summary script and summary.

The diagnostic manifests identify copied environments, pins, sampling and script
hashes. Absolute paths refer to the original machine. Reproduction scripts may
need path adjustment; retain originals when doing so. Only the overnight bundle
was collected under the declared host screen; daytime diagnostics are exploratory.
The final None-sentinel refinement is not part of the timed first-step patch.
See the [investigation record](../../../../reviews/v2.0.0b2-wp5-small-item-investigation.md)
for interpretation, limitations and remaining qualification.
