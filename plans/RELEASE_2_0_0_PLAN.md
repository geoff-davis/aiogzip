# aiogzip 2.0.0 plan

> **Status:** draft, 2026-10-10. Development version `2.0.0rc3.dev0`.
>
> **Source:** two read-only readiness reviews of `main` at `3dd9e94`, made
> after 2.0.0rc2 was published and with PRs #145 and #146 included. One was
> by a fresh Claude Opus 5.5 subagent and one by Codex; their texts are in
> [`reviews/data/2.0.0/`](reviews/data/2.0.0/). They agreed:
>
> - no source defect blocks 2.0.0;
> - no rc3 is needed if the release's `src/` equals v2.0.0rc2 apart from
>   `__version__`;
> - everything remaining is metadata, documentation, workflow and process
>   work.

## 1. Baselines and rules

```text
public API baseline:       v2.0.0b1 (frozen manifest tests/data/public_api_2_0.json)
runtime baseline:          v2.0.0rc2 (src/ must equal it except __version__)
approved behavior fixes:   b2 exception ledger, BC1–BC18
correctness evidence:      RC2 S05 differential sweeps, retained
performance evidence:      RC2 S06 timing windows, retained
```

The RC plans' rules carry over:

- no public API change;
- the maintainer's explicit sign-off on every gate;
- one PR per concern, with both engines' suites and the hosted matrix green;
- Codex review of each PR before it merges.

This plan adds a **source freeze**. Any change under `src/` other than
`__version__`, including a comment or docstring, stops this plan. The change
then goes through an rc3 under the RC2 plan's rules: a ledger row if it
changes behavior, differential sweeps, and timing if it touches a hot path.
Because `src/` is unchanged, S05 and S06 still stand for 2.0.0, and no new
timing window is needed.

## 2. Maintainer decisions

| ID | Decision | Status |
| --- | --- | --- |
| D1 | Feedback window before tagging 2.0.0 | Decided 2026-10-10: one week after rc2. 2.0.0 is not tagged before 2026-10-17. Public reports received in the window and their dispositions are recorded at T06. |
| D2 | 1.x support window | Decided 2026-10-10: security fixes only for 1.x until 2027-04-30. Python 3.10, the last interpreter only 1.x serves, reached end of life on 2026-10-01. No 1.x security fix is known to be needed now (see [T05](#t05-support-policy)). |
| D3 | `dev` docs alias after 2.0.0 | Decided 2026-10-10: development builds on `main` deploy to one version named `dev`, and only released versions deploy to numbered `major.minor` versions, which `latest` follows. See [T02](#t02-docs-versioning). |
| D4 | Hosted rehearsal of the fixed build path | Decided 2026-10-10: no TestPyPI rehearsal. The publish workflow's hash gate, which fails closed, is the check. |
| D5 | Branch protection for `1.x` | Decided 2026-10-10: light protection. Applied the same day: force-pushes and deletion blocked, enforced for admins, with no required PRs or checks. See [T05](#t05-support-policy). |

## 3. Gate register

| Gate | Item | Acceptance |
| --- | --- | --- |
| T01 | RC2 closeout | S09 signed off; #145 and #147 merged; #146's build-interpreter pin merged |
| T02 | Docs versioning | See [T02 below](#t02-docs-versioning) |
| T03 | Stable metadata and wording | See [T03 below](#t03-stable-metadata-and-wording) |
| T04 | Migration guide and changelog | See [T04 below](#t04-migration-guide-and-changelog) |
| T05 | Support policy | See [T05 below](#t05-support-policy) |
| T06 | Feedback | D1's window has passed. Recorded: how feedback was solicited, the public reports received and their dispositions, and representative workload results. Any of these the maintainer waives is recorded as a waiver. |
| T07 | Plans index | See [T07 below](#t07-plans-index) |
| T08 | Release preparation and source identity | See [T08 below](#t08-release-preparation-and-source-identity) |
| T09 | Candidate review and approval | Cross review of the exact candidate by Codex and a fresh Claude subagent; all required hosted checks green at that SHA; the maintainer's explicit approval |
| T10 | Publication | See [T10 below](#t10-publication) |

- [x] T01 (signed off 2026-10-10)
- [ ] T02
- [ ] T03
- [ ] T04
- [ ] T05
- [ ] T06
- [ ] T07
- [ ] T08
- [ ] T09
- [ ] T10

## 4. Gate details

### T02: docs versioning

The acceptance has four parts:

- Following D3, the workflow deploys a development version on `main` to the
  single `dev` docs version, and a stable or prerelease version to its
  `major.minor` docs version.
- A test pins the version cases.
- The stale versions are deleted with `mike delete` before the fix merges.
- One deploy is verified after the fix merges.

`.github/workflows/docs.yml:60` sets `DOCS_VERSION="${VERSION%.*}"`, which
strips only the last dot segment. So every `.dev0` version on `main` has
published its own docs version: `2.0.0a3` through `2.0.0rc3`. The merge of
PR #145 created `2.0.0rc3` and moved `dev` onto it. Left alone, `2.0.1.dev0`
would publish a `2.0.1` version.

The fix should take the first two release components, for example with
`packaging.version.Version(v).release[:2]`, and route development versions to
`dev`. It belongs in a small script that a test can pin. The test should cover:

- `1.11.0`;
- `2.0.0`;
- `2.0.0rc2`;
- `2.0.0rc3.dev0`;
- `2.0.1.dev0`;
- `2.1.0.dev0`.

The stale versions are deleted with `mike delete`: `2.0.0a3`, `2.0.0a4`,
`2.0.0b1`, `2.0.0b2`, `2.0.0rc1`, `2.0.0rc2` and `2.0.0rc3`. This is a write
to `gh-pages`, so it needs the maintainer's go-ahead (given 2026-10-10). It
must happen after the last push to `main` under the old workflow, or that push
recreates one, and before the fix's own deploy: deleting `2.0.0rc3` also drops
the `dev` alias, and mike refuses to deploy a version named `dev` while an
alias of that name exists (checked locally against mike's current release). So
the fix PR is the next merge to `main` after the deletion.

**D3 (decided).** Once the version derivation is fixed, a `.dev0`
push on `main` after 2.0.0, such as `2.0.1.dev0`, would deploy to `2.0`: the
version `latest` serves. Stable readers would then see unreleased changes.
So `main`'s development builds should deploy to a single version named `dev`,
titled with the full development version. Numbered `major.minor` versions
would be deployed only by stable and prerelease versions, so `latest` serves
only released docs. This also stops the clutter at its source. During the
rest of the RC phase, `2.0` keeps rc2's docs and `dev` shows `2.0.0rc3.dev0`.

The workflow and the test are outside `src/`. The deletion is a gh-pages
operation that needs the maintainer's go-ahead.

### T03: stable metadata and wording

The acceptance is that `pyproject.toml` declares `Development Status :: 5 -
Production/Stable`, and that no current release or support claim in shipped
files describes 2.0 as a beta or prerelease. Historical references stay
accurate, such as changelog entries and "frozen as of `2.0.0b1`".

The README becomes the PyPI description and the classifier goes into the
metadata; neither can change after upload. So this lands before release
preparation, and its tests pin the stable classifier.

- `tests/test_version_sync.py:88-89` asserts the Beta classifier. It changes
  in the same PR to assert `5 - Production/Stable` and the absence of Beta.
- `README.md:25-27`: "The 2.0 beta is a prerelease".
- `docs/stability.md`: written for the beta throughout. Rewrite it as the
  stable policy, keeping its definition of the public surface and of what the
  freeze covers. It should state:
  - what 2.x minor and patch releases may change;
  - the deprecation rule;
  - the Python-version support rule.

  The compatibility boundary is restated, not widened.
- `SECURITY.md:9-11`: the supported-versions table lists the latest 2.0 beta.
- Beta wording in `docs/migration.md:10,89-90`, `docs/codec.md:8`,
  `docs/streaming.md:13` and `docs/api.md:64,120`.

### T04: migration guide and changelog

The acceptance has three parts: a consolidated 1.11 → 2.0 behavior section in
`docs/migration.md`; a `[2.0.0]` CHANGELOG entry with its comparison link; and
the two stale passages below corrected.

The migration page now says that ordinary asyncio callers need not change
their code and that the main change is the Python 3.11 floor
(`docs/migration.md:46-52`). It should list the changes a 1.11 user can hit,
each linking to the detailed rule in `docs/errors.md` rather than copying the
ledger:

- overlapping calls on one handle raise `ConcurrentOperationError`;
- `mtime` reports the last completed member header;
- when the underlying source's read fails or is cancelled, the reader stays
  usable only if the failure is proven to have consumed no input; otherwise
  it is terminal until `seek(0)`;
- a custom source's synchronous `tell()`, if it has one, provides that proof.
  It is now called before each physical read and seek and after a failure,
  so it must be cheap and free of side effects. A source without one still
  works, but a failed read on it leaves the reader terminal until `seek(0)`;
- after an integrity failure (a CRC-32 or `ISIZE` mismatch), output already
  decoded stays readable as unvalidated recovery data, and later reads raise
  the terminal `OSError`;
- a text read that raises `UnicodeDecodeError` does not make the reader
  terminal, but it has consumed the chunk it was decoding, so it must not be
  retried; `seek(0)` or reopening with another `encoding` recovers;
- cancellation waits for native I/O already in a worker thread;
- exact-Boolean validation;
- text-mode recovery through saved cookies.

The `[2.0.0]` entry should summarize 1.11.0 → 2.0.0 for users who skipped
the prereleases, and list what changed since rc2.

Stale text elsewhere:

- `docs/index.md:136` still says handle state is mutated without locking.
- `examples/README.md:46` names `dist/aiogzip-2.0.0b2*.whl`.

### T05: support policy

The acceptance is that D2 and D5 are decided, and D2 is stated in
`SECURITY.md`, `docs/stability.md` and `docs/migration.md`.

No 1.x security fix is known to be needed:

- GitHub reports no open Dependabot alerts. All 19 alerts ever raised were in
  `uv.lock` development tooling, which is not shipped, and all are fixed.
- There are no repository security advisories.
- The 2.0 Security changelog entries either restate a protection 1.x already
  has, such as per-call `max_decompressed_size` bounding, or cover the new
  codec API.
- The 2.0 correctness fixes, BC1–BC18, are cancellation, ownership and
  recovery repairs. They are not security fixes, and they depend on the 2.0
  architecture, so they are not backported.

**D5 (decided, applied 2026-10-10).** Previously, `1.x` had no protection. Its CI workflow triggers
only on `main`, so no checks run on `1.x` pushes or PRs; only the docs
workflow runs there. Light protection, blocking force-pushes and branch
deletion, costs nothing and guards the line users on Python 3.8–3.10 rely on.
Requiring PRs or status checks would also need 1.x's CI workflow to trigger
on `1.x`. That is worth doing only together with the first 1.x fix.

### T07: plans index

`plans/README.md` still says "Active: 2.0.0b2", says development continues
as `2.0.0rc1.dev0`, and describes the ledger as BC1–BC10. The acceptance is
that it points to this plan, that the ledger is described as BC1–BC18, and
that the b2, RC1 and RC2 sections are kept as history.

### T08: release preparation and source identity

The acceptance has five parts:

1. `/release-prep` for `2.0.0`, with the changelog dated.
2. The artifact record is built with the fixed script (#146), uv 0.9.22 and
   the project venv's Python 3.14. It is built twice, with identical hashes.
3. `git diff v2.0.0rc2 <candidate> -- src/` shows only `__version__`.
4. `tests/data/public_api_2_0.json` is byte-identical to rc2's.
5. Both engines' suites pass, and the installed-artifact smokes and the
   maintained examples pass.

### T10: publication

1. The merge commit is compared with the SHA reviewed and approved at T09.
   Every difference in the release inputs is reviewed, and the maintainer
   approves the actual tag target.
2. The signed tag is pushed on that commit, and the publish run passes
   `test`, `build` and `publish`.
3. The GitHub release is created with `--latest`, after the publish run
   succeeds.
4. On PyPI:
   - the hashes equal the record;
   - the stable classifier is shown;
   - the default version becomes `2.0.0`;
   - the attestations verify.
5. A clean public install passes the smokes and the examples.
6. In the docs, `latest` and the site default serve `2.0`, `1.11` is still
   served, and `dev` follows D3.
7. The post-release record is written, and development moves to
   `2.0.1.dev0`.

## 5. Deferred past 2.0.0

These were judged by both reviewers as not blocking:

- **Source LOWs from RC2's S08,** each a `src/` change, so for 2.0.1:
  - the stale "no shield" docstring in `_inspection.py`;
  - `_acquire_path`'s cancellation-branch cleanup noting a
    `KeyboardInterrupt` from the late close instead of propagating it.
    Ordinary SIGINT does not produce this: the close runs in a worker thread,
    and `asyncio.run` turns SIGINT into cancellation. Only a close
    implementation that raises `KeyboardInterrupt` itself reaches it.
- **Python 3.15 on setup-python:** switch the 3.15 leg from uv's managed
  CPython to `actions/setup-python` once it offers 3.15.0.
- **Dependabot PRs** #102 (setup-uv) and #124 (uv lock): keep the qualified
  toolchain for the release unless an update has a concrete benefit.
- **Performance page:** add a dated caveat to `docs/performance.md`'s
  2.0.0a1 numbers, optionally as part of T04.
- **Earlier deferrals,** unchanged:
  - F3;
  - `writelines()` with empty `str` subclasses;
  - custom-sink error wrapping;
  - an `aiofiles` fallback;
  - an `inspect()` limit;
  - the b2 plan §18 opportunities;
  - AnyIO/Trio (#71);
  - indexed access (#72).
