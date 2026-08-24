# aiogzip 2.0.0a3 release closeout

`2.0.0a3` was published on 2026-08-16 from commit
`3e95073581be7cba437da45dacd9724f649e54d0`. This record reconciles the living
`a3` plan with what actually shipped. It does not rewrite unchecked historical
checkboxes.

## Shipped in `2.0.0a3`

- Shared-parser live `mtime` replaced the binary reader's duplicate header
  probe. Concatenated-member, read-ahead, corruption, cancellation, and rewind
  behavior is covered by the codec, binary, text, seek, and property suites.
  Evidence: implementation squash `6c3947dda0543d7b7babea1b874f14c9acaaffaa`,
  `tests/test_file_mtime.py`, and `plans/reviews/v2.0.0a3-d17-review.md` areas
  1–4.
- `ConcurrentOperationError` and whole-call same-handle reservations shipped
  across primitive and composite binary/text operations. Evidence:
  `tests/test_file_lifecycle.py`, `tests/test_file_state_matrix.py`, and the
  lifecycle matrix in `plans/reviews/v2.0.0a3-review.md`.
- Reader poisoning, validation-recovery data, stable terminal errors, and
  absolute `seek(0)` recovery on rewindable inputs shipped. Evidence: the
  `2.0.0a3` changelog, `tests/test_file_state_matrix.py`, and D17 area 2.
- Text cancellation, rollback, replay-origin, newline, and close-state
  hardening shipped. Evidence: `tests/test_text_position_properties.py`, the
  round 10–13 records in `plans/reviews/v2.0.0a3-review.md`, and D17 areas 2–3.
- Semantics-preserving small-write improvements shipped without cross-call
  buffering or changed sink-error timing. The 10-byte diagnostic improved over
  `2.0.0a2` but remained slower than `v1.11.0`; batching remained the supported
  guidance. Evidence:
  `plans/benchmarks/v2.0.0a3-small-write-disposition.md` and D17 area 5.
- The release harness, raw header/write/performance records, local full-suite
  result (1,875 passed, one skipped), strict documentation build, both type
  checkers, formatting/lint, and hooks were captured. D17 independently
  reviewed the core repair and benchmark methodology and was accepted by the
  maintainer on 2026-08-16.
- The configured Python 3.11–3.14 Linux, Python 3.12 Windows/macOS, stdlib,
  zlib-ng, and forced-stdlib CI matrix passed for the release commits. The
  release tag publication workflow also passed. Evidence: GitHub Actions runs
  `31970154882`, `31971557024`, `31971855097`, and `31971986396`.
- PyPI contains the published wheel and sdist. Recorded SHA-256 values are
  `e5efd9129b0755f69c890a728df970e512910e6206462743f00626436d1c2d5c`
  (`aiogzip-2.0.0a3-py3-none-any.whl`) and
  `7f3bb642a3974deb060282aabecf44ca7e1d72dc36aa02e466a159570a9f8257`
  (`aiogzip-2.0.0a3.tar.gz`).

## Deferred to `2.0.0a4`

- Exact-`bool` validation for `fast_compress`, `strict_size`, and
  `collect_member_info`, plus exact-`bool | None` validation for `closefd`.
- A maintained public-codec fragmented-transport integration.
- A maintained concurrent high-level ingest integration. The `a3` striped
  safe-upload design is superseded by `a4`'s narrower independent-file staged
  JSONL ingest.
- Example type checking and execution from built wheel/sdist artifacts.
- The completed-member metadata decision raised as D17 comment A3-1:
  `member_count` survived later failure while collected `members` did not.
- Final 2.0 disposition of issue #86. `a3` measured and documented the strict
  per-call tradeoff but did not change the remote issue.
- A new independent human review of the `a4` contract changes and at least one
  maintained integration.

## Superseded by implementation findings

- The planned narrow live-`mtime` repair expanded into reviewed read/write
  lifecycle hardening after characterization exposed same-handle overlap,
  poisoning, rollback, and close-state defects. The resulting shared
  reservation and recovery-state behavior preserves the intended integrity
  outcome and is recorded in the thirteen review rounds.
- The proposed `a3` public integrations were not partially shipped. Their
  beta-readiness objective is carried by the smaller, independently testable
  `a4` fragmented-transport and staged-ingest examples.
- Several proposed helper consolidations were rejected or deferred after
  pinned benchmarks showed hot-path regressions. The retained inlined guards,
  writer paths, restore blocks, and one-shot close observer are enumerated
  under “Explicit post-a3 deferrals” in the review record.

## Maintainer-only actions completed

- The release change was reviewed and merged to `main`.
- Lightweight tag `v2.0.0a3` resolves to
  `3e95073581be7cba437da45dacd9724f649e54d0`.
- GitHub prerelease `v2.0.0a3` was published on 2026-08-16.
- The tag-triggered Trusted Publishing workflow succeeded and PyPI received
  the wheel and sdist listed above.
- Documentation and GitHub Pages deployment workflows succeeded.
- The post-release development version advanced to `2.0.0a4.dev0` at
  `924ae3659a6ba416f5391a083f27f0b387e6fe67`.

## Not performed

- No maintained direct-codec or high-level integration example shipped in
  `a3`; D17 explicitly left that beta-entry condition open.
- Strict Boolean validation did not ship.
- Example typing and built-artifact execution were not demonstrated because
  the required examples did not exist.
- No candidate record consolidated every final `a3` benchmark and integration
  gate into the originally proposed `v2.0.0a3-candidate.md`.
- Issue #86 was not closed, relabeled, or rewritten remotely.
- The living `a3` plan was not retroactively reconciled after publication;
  this closeout supplies that missing audit without altering old checkboxes.
