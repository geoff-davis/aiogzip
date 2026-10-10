# Plans

Release plans, design records, review records and benchmark evidence. Files
stay at the paths they were committed under; this index is the way in.

## Active: 2.0.0b2

2.0.0b2 was published on 2026-10-07; development continues as
`2.0.0rc1.dev0`. The [post-release record](reviews/v2.0.0b2-post-release.md)
covers publication (G21) and the RC handoff (G22). The b2 release plan is
[Revision 2](RELEASE_2_0_0B2_PLAN.md). The
G00–G22 register in that plan is authoritative. Reproducing a defect does not
complete its repair gate, and local tests do not establish release readiness.

An exact byte copy of the supplied revision is kept as
[review input](reviews/inputs/b2/RELEASE_2_0_0B2_PLAN_REVISION_2.md.txt). The
`.txt` suffix keeps the original Markdown free of formatter changes. The
untracked working copy `RELEASE_2_0_0B2_PLAN_REVISION_2.md` in this directory
is byte-identical to it. It stays untracked until the maintainer decides what
to do with it.

Durable invariants (start here):

- [File-state model](design/v2.0.0b2-file-state-model.md): source symbols,
  lifecycle and read-health tables, ownership and settlement, C0, the text
  checkpoint, the bridge allowlist, the parity map, performance constraints
  and the behavior exceptions.
- [Behavior-exception ledger](reviews/v2.0.0b2-behavior-exceptions.md):
  every approved difference from b1 (BC1–BC10).
- [Findings and evidence limitations](reviews/v2.0.0b2-findings.md)

### RC1 plan

The [2.0.0rc1 plan](RELEASE_2_0_0RC1_PLAN.md) (gates R01–R14) starts from the
b2 baselines in plan §17. It was drawn from two read-only reviews of
`v2.0.0b2` that used the same [brief](reviews/data/rc1/rc1-review-prompt.txt):
[Claude Opus 5.5](reviews/data/rc1/opus-review.md.txt) and
[Codex](reviews/data/rc1/codex-review.md.txt). Plan §18 still lists the
deferred work.

- [R12 pre-registration: RC1 timing windows](reviews/v2.0.0rc1-r12-preregistration.md)
- [R12 record: RC1 timing windows](reviews/v2.0.0rc1-r12-record.md), with
  [its evidence](benchmarks/data/rc1/r12/README.md)
- [R13 candidate review](reviews/v2.0.0rc1-candidate-review.md), with the
  [Claude reviewer prompt](reviews/data/rc1/r13/claude-review-prompt.txt)
- [Post-release: R14](reviews/v2.0.0rc1-post-release.md); 2.0.0rc1 was
  published on 2026-10-09 and development continues as `2.0.0rc2.dev0`

### RC2 plan

The [2.0.0rc2 plan](RELEASE_2_0_0RC2_PLAN.md) (gates S01–S09) covers the
three deferred R13 limitations the maintainer chose to fix before 2.0.0.

- [S06 pre-registration: RC2 timing windows](reviews/v2.0.0rc2-s06-preregistration.md)
- [S06 record: RC2 timing windows](reviews/v2.0.0rc2-s06-record.md), with
  [its evidence](benchmarks/data/rc2/s06/README.md)
- [Post-release: S08 and S09](reviews/v2.0.0rc2-post-release.md), with the
  [S08 review texts](reviews/data/rc2/s08/); 2.0.0rc2 was published on
  2026-10-10 and development continues as `2.0.0rc3.dev0`

### 2.0.0 plan

The [2.0.0 plan](RELEASE_2_0_0_PLAN.md) (gates T01–T10) takes 2.0.0rc2's
source unchanged to a stable release. It was drawn from two read-only
readiness reviews: [Claude Opus 5.5](reviews/data/2.0.0/opus-review.md.txt)
and [Codex](reviews/data/2.0.0/codex-review.md.txt), with their
[prompts](reviews/data/2.0.0/).

Each release's artifact hashes are recorded under
[release artifact records](releases/README.md); the publish workflow uploads
only the recorded files.

### b2 design records

- [WP1 native-work settlement](design/v2.0.0b2-native-settlement.md)
- [WP2 source consumption and settlement](design/v2.0.0b2-source-consumption.md)
- [WP3 opening ownership](design/v2.0.0b2-open-ownership.md)
- [WP6 explicit binary read health](design/v2.0.0b2-wp6-read-health.md)
- [WP7 text replay-origin object](design/v2.0.0b2-wp7-text-origin.md)
- [WP8 text/binary bridge](design/v2.0.0b2-wp8-bridge.md)
- [WP9 hot-path parity and codec guidance](design/v2.0.0b2-wp9-parity.md)
- [WP10 stateful, adversarial and installed qualification](design/v2.0.0b2-wp10-qualification.md)

### b2 gate records

- [WP0 preflight](reviews/v2.0.0b2-preflight.md),
  [WP0 local qualification](reviews/v2.0.0b2-qualification.md) and
  [WP0 review response](reviews/v2.0.0b2-wp0-review-response.md)
- [WP1 completion: native settlement](reviews/v2.0.0b2-wp1-completion.md)
- [WP2 completion: source settlement](reviews/v2.0.0b2-wp2-completion.md)
- [WP3 completion: opening ownership](reviews/v2.0.0b2-wp3-completion.md)
  and [progress](reviews/v2.0.0b2-wp3-progress.md)
- [WP4 pending-line batching](reviews/v2.0.0b2-wp4-progress.md#maintainer-qualification)
- [WP5 completion: G06–G08](reviews/v2.0.0b2-wp5-completion.md) and
  [progress](reviews/v2.0.0b2-wp5-progress.md)
- [G09 corrected reference C0](reviews/v2.0.0b2-c0-record.md), with its
  [preparation notes](reviews/v2.0.0b2-c0-preparation.md) and
  [checklist](reviews/v2.0.0b2-g09-c0-checklist.md)
- [WP6 completion: G10 binary read health](reviews/v2.0.0b2-wp6-completion.md)
- [WP7 completion: G11 text replay origin](reviews/v2.0.0b2-wp7-completion.md)
- [WP8 completion: G12 bridge and one health authority](reviews/v2.0.0b2-wp8-completion.md)
- [WP9 completion: G13 hot-path parity](reviews/v2.0.0b2-wp9-completion.md)
- [WP10 qualification: G14–G18](reviews/v2.0.0b2-wp10-qualification.md)
- [G17 pre-registration: performance windows](reviews/v2.0.0b2-g17-preregistration.md)
- [WP11 release preparation: G20](reviews/v2.0.0b2-release-prep.md)
- [WP11 candidate review: G19](reviews/v2.0.0b2-candidate-review.md)
- [Post-release: G21 and G22](reviews/v2.0.0b2-post-release.md)

### b2 WP5 working records

- Timing method:
  [timing protocol](reviews/v2.0.0b2-wp5-timing-protocol.md),
  [timing tools](reviews/v2.0.0b2-wp5-timing-tools.md),
  [window runner](reviews/v2.0.0b2-wp5-window-runner.md),
  [provisional quiet policy](reviews/v2.0.0b2-wp5-provisional-quiet-policy.md)
  and [batched calibration preflight](reviews/v2.0.0b2-calibration-batched-preflight.md)
- Repairs:
  [unpublished-read cookies](reviews/v2.0.0b2-wp5-cookie-fix.md) and
  [generic long-line accumulation](reviews/v2.0.0b2-wp5-generic-lines.md)
- Investigations and preparation:
  [small-item overhead](reviews/v2.0.0b2-wp5-small-item-investigation.md),
  [long-line measurements](reviews/v2.0.0b2-wp5-longline-measurements.md),
  [G07 read resources](reviews/v2.0.0b2-wp5-read-resources.md) and
  [non-timing preflight](reviews/v2.0.0b2-wp5-next-qualification.md)
- Windows:
  [September 28](reviews/v2.0.0b2-wp5-nightly-20260928.md),
  [September 29](reviews/v2.0.0b2-wp5-nightly-20260929.md)
  ([results](reviews/v2.0.0b2-wp5-nightly-20260929-results.md)),
  [September 30](reviews/v2.0.0b2-wp5-nightly-20260930.md)
  ([results](reviews/v2.0.0b2-wp5-nightly-20260930-results.md)),
  [September 30 stdlib follow-up](reviews/v2.0.0b2-wp5-followup-20260930.md),
  [overnight queue](reviews/v2.0.0b2-wp5-overnight-queue.md),
  [morning review](reviews/v2.0.0b2-wp5-morning-review.md),
  [batch 1](reviews/v2.0.0b2-wp5-batch1.md)
  ([results](reviews/v2.0.0b2-wp5-batch1-results.md)) and
  [batch 2](reviews/v2.0.0b2-wp5-batch2.md)
  ([results](reviews/v2.0.0b2-wp5-batch2-results.md))
- Drafts and dispositions:
  [G06 and G07 drafts](reviews/v2.0.0b2-wp5-g06-g07-2f78925-drafts.md),
  [G08 drafts](reviews/v2.0.0b2-wp5-g08-2f78925-drafts.md),
  [G08 stdlib draft](reviews/v2.0.0b2-wp5-g08-stdlib-wp5-draft.md) and
  [G08 disposition](reviews/v2.0.0b2-wp5-g08-disposition.md)

### b2 benchmark evidence

- [WP0 baseline measurements](benchmarks/v2.0.0b2-results.md)
- [Quiet-policy calibration](benchmarks/v2.0.0b2-quiet-policy-calibration.md)
- [Placement diagnostic](benchmarks/v2.0.0b2-placement-diagnostic.md)
- [G06 long-line resources](benchmarks/v2.0.0b2-wp5-longline-resources.md)
- [G07 partial-read resources](benchmarks/v2.0.0b2-wp5-read-resources.md)
- Raw data is under `benchmarks/data/b2/`. Each directory's README, where it
  has one, describes its runs:
  [WP5 batch 1](benchmarks/data/b2/wp5-batch1-20261003/README.md),
  [WP5 batch 2](benchmarks/data/b2/wp5-batch2-20261004/README.md),
  [WP5 follow-up attempts](benchmarks/data/b2/wp5-followup-attempts/README.md),
  [WP5 September 29 results](benchmarks/data/b2/wp5-nightly-20260929-results/README.md),
  [WP5 September 30 results](benchmarks/data/b2/wp5-nightly-20260930-results/README.md),
  [WP5 small items](benchmarks/data/b2/wp5-small-item-20260928/README.md),
  [G10](benchmarks/data/b2/wp6-g10/README.md),
  [G11](benchmarks/data/b2/wp7-g11/README.md),
  [G12](benchmarks/data/b2/wp8-g12/README.md),
  [G13](benchmarks/data/b2/wp9-g13/README.md) and
  [G17](benchmarks/data/b2/wp10-g17/README.md)

## Completed plans

- [2.0.0b1: API freeze and beta readiness](RELEASE_2_0_0B1_PLAN.md)
- [2.0.0a4: integration and beta readiness](RELEASE_2_0_0A4_PLAN.md), with
  [WP1 Boolean validation](RELEASE_2_0_0A4_WP1_BOOLEAN_VALIDATION.md) and
  [WP2 member metadata](RELEASE_2_0_0A4_WP2_MEMBER_METADATA.md)
- [2.0.0a3: beta readiness](RELEASE_2_0_0A3_PLAN.md) and its
  [closeout](RELEASE_2_0_0A3_CLOSEOUT.md)
- [2.0.0a2: regression repair](RELEASE_2_0_0A2_PLAN.md)
- [2.0.0a1](RELEASE_2_0_0A1_PLAN.md)
- [Engine abstraction, zlib-ng and batched readline](ENGINE_AND_READLINE_PLAN.md)
- [Test-suite refactor](TEST_SUITE_REFACTOR_PLAN.md)

## Earlier reviews and records

- 2.0.0b1:
  [preflight](reviews/v2.0.0b1-preflight.md),
  [hardening](reviews/v2.0.0b1-hardening.md),
  [documentation audit](reviews/v2.0.0b1-documentation-audit.md),
  [installed artifacts](reviews/v2.0.0b1-installed-artifacts.md),
  [independent review](reviews/v2.0.0b1-independent-review.md),
  [review response](reviews/v2.0.0b1-review-response.md),
  [release preparation](reviews/v2.0.0b1-release-prep.md),
  [post-release](reviews/v2.0.0b1-post-release.md),
  [API decisions](api/v2.0.0b1-api-decisions.md) and
  [minimum dependencies](dependencies/v2.0.0b1-minimum-dependencies.md)
- 2.0.0a4:
  [documentation decisions](reviews/v2.0.0a4-documentation-decisions.md),
  [review packet](reviews/v2.0.0a4-review-packet.md),
  [independent review](reviews/v2.0.0a4-independent-review.md),
  [follow-up code review](reviews/v2.0.0a4-follow-up-code-review.md),
  [maintainer handoff](reviews/v2.0.0a4-maintainer-handoff.md),
  [release preparation](reviews/v2.0.0a4-release-prep.md) and
  [post-release](reviews/v2.0.0a4-post-release.md)
- 2.0.0a3: [review record](reviews/v2.0.0a3-review.md) and
  [D17 independent review](reviews/v2.0.0a3-d17-review.md)
- Issue #86: [a4 disposition](reviews/issue-86-a4-disposition.md) and
  [b1 closeout](reviews/issue-86-b1-closeout.md)

## Earlier benchmark evidence

- 2.0.0b1: [preflight](benchmarks/v2.0.0b1-preflight.md) and
  [candidate](benchmarks/v2.0.0b1-candidate.md)
- 2.0.0a4: [preflight](benchmarks/v2.0.0a4-preflight.md) and
  [candidate](benchmarks/v2.0.0a4-candidate.md)
- 2.0.0a3: [preflight](benchmarks/v2.0.0a3-preflight.md),
  [header verification](benchmarks/v2.0.0a3-header-verification.md) and
  [small-write disposition](benchmarks/v2.0.0a3-small-write-disposition.md)
- 2.0.0a2: [candidate](benchmarks/v2.0.0a2-candidate.md),
  [compression analysis](benchmarks/v2.0.0a2-compression-analysis.md),
  [framework rerun](benchmarks/v2.0.0a2-framework-rerun.md),
  [local validation](benchmarks/v2.0.0a2-local-validation.md),
  [packaging validation](benchmarks/v2.0.0a2-packaging-validation.md),
  [WP3 buffer tuning](benchmarks/v2.0.0a2-wp3-buffer-tuning.md),
  [WP4 header parser](benchmarks/v2.0.0a2-wp4-header-parser.md) and
  [WP5 scheduler](benchmarks/v2.0.0a2-wp5-scheduler.md)
- 2.0.0a1: [candidate](benchmarks/v2.0.0a1-candidate.md) and
  [regression baseline](benchmarks/v2.0.0a1-regression-baseline.md)
- 1.11.0: [release baseline](benchmarks/v1.11.0-baseline.md)
