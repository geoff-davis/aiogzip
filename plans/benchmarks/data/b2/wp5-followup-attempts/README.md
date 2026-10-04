# G08 stdlib follow-up attempts

Three collector bundles, preserved byte-for-byte in `attempts.tar.xz`, with the
archive hash in `sha256.json`. None started a measurement block, so none is a
series:

- `20260930-wp4-stopped`: the WP4 follow-up, stopped at the maintainer's request
  during its second warmup (runner status `failed`, SIGTERM).
- `20261002-wp4-deferred` and `20261002-wp5-deferred`: both overnight windows
  deferred; the host never met the quiet policy.

The collector reports no analysis errors for any of them. The maintainer then
disposed of the selected rows without a follow-up series.

See the [follow-up record](../../../../reviews/v2.0.0b2-wp5-followup-20260930.md).
