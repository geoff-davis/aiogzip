# Batch 1, night of October 3

The seven collector bundles from WP5 batch 1, with archive hashes in
`sha256.json`. Each bundle holds its raw-file inventory (`raw-sha256.json`),
frozen manifest, runner status, events and logs, derived reports, collector
review and continuation guidance.

- G08 scheduling (stdlib and zlib-ng), G07 and G06 stdlib are preserved whole,
  one archive each.
- Each G08 zlib-ng throughput bundle is split across three archives so every
  file fits the repository's size limit: `-derived` holds everything except
  the raw capture JSONs, `-raw1` the warmups and blocks 0–1, and `-raw2`
  blocks 2–3. Together they cover every file exactly once.
- G06 zlib-ng had every block rejected and no usable row. `-derived` holds
  everything except its ten raw capture JSONs (about 7 MB each). Those stay in
  the local evidence store, where the whole bundle's archive has SHA-256
  `f5cf548d43b40758d573de5cba75bc444df03461fc3a5e664ca0716508f1475c`; each
  file's hash is in the bundle's `raw-sha256.json`.

The collector reports no analysis errors for any bundle. None is a gate
decision. See the [results review](../../../../reviews/v2.0.0b2-wp5-batch1-results.md).
