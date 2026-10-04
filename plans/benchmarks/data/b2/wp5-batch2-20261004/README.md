# Batch 2, night of October 4

The two G06 collector bundles from WP5 batch 2, with archive hashes in
`sha256.json`, plus the exploratory investigation probes.

- `g06-stdlib-derived` and `g06-zlib-ng-followup-derived` hold every file of
  each bundle except its 18 raw capture JSONs (warmups and blocks): the
  inventory, manifest, runner status, events and logs, comparison, scaling
  report and collector review. The raw captures stay in the local evidence
  store, where the whole-bundle archives have SHA-256
  `6ad6639b5ea35640e028ebe32c307048e4f5e6178b2bfdb4261e996f157e6be5`
  (stdlib) and
  `57070d6bf67a996142ab251784ccd48d2b2cef594eaa421f7658efd2803d8afe`
  (zlib-ng); each file's hash is in its bundle's `raw-sha256.json`.
- `investigation-probes` holds the exploratory scripts and outputs behind the
  G06 disposition: the matrix-prefix ABBA timing, the same with a fixed glibc
  mmap threshold, fresh-process 8 and 16 MiB timings, and a transcription of
  the fresh-process exact-row timing, which printed only to the terminal. They ran outside
  qualification on a busy host and support the disposition, not qualification.

The collector reports no analysis errors. See the
[results review](../../../../reviews/v2.0.0b2-wp5-batch2-results.md).
