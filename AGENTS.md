# Repository guide

**aiogzip** is an asyncio gzip file library with a synchronous sans-I/O codec (`GzipEncoder`, `GzipDecoder`).
The 2.0 line requires Python 3.11 or newer; fixes for older interpreters belong on the `1.x` maintenance branch.

`CLAUDE.md` imports this file; edit here only. It holds what an agent would get wrong without being told. What
shipped is in `CHANGELOG.md`, the current version is `__version__` in `src/aiogzip/__init__.py`, the stability
policy is `docs/stability.md`, and `plans/README.md` indexes every plan and review record.

## Setup

```bash
uv sync --all-extras   # from the committed lockfile, so every machine runs the same tool versions
uv run prek install    # once per clone; installs the pre-commit and pre-push hooks
```

Mismatched development environments have corrupted benchmark comparisons before. The lockfile pins development
only: CI deliberately installs unpinned (`uv pip install --system`, which resolves fresh from PyPI and never reads
`uv.lock`) so new dependency releases are exercised across Python 3.11 to 3.15 before users hit them. Dependabot's
`uv` ecosystem keeps `uv.lock` current.

## Before starting work

This library is developed from several machines, so the local checkout can silently lag origin. Before reviewing
code or starting any change:

```bash
git fetch origin
git log --oneline main..origin/main   # any output means local main is stale
```

If local main is behind, fast-forward it (`git checkout main && git pull --ff-only`) and branch from the updated
main, then `uv sync --all-extras`. As a cross-check, compare `__version__` with the newest released
`CHANGELOG.md` entry and the latest tag (`git tag --sort=-v:refname | head -1`). On a release commit all three
agree. Between releases `__version__` is a development version ahead of the latest tag (for example `2.0.3.dev0`
after `v2.0.2`) with an `[Unreleased]` changelog section; that is normal. A `__version__` at or behind a tag that
origin has moved past means the clone is stale.

Why: a stale checkout once produced a full package review and a 21-commit branch built on v1.7.0 while origin was
at v1.8.0. Two commits duplicated shipped work, the PR opened conflicting, and everything had to be rebased. The git
status shown at session start reflects only the local clone.

The `check-branch-fresh` pre-push hook (`scripts/check_branch_fresh.sh`) backstops this: it refuses a push when
`origin/main` has commits missing from the branch, which also catches main moving mid-session. It fails open when
offline. For an intentionally behind push: `SKIP=check-branch-fresh git push`.

## Commands

| Task | Command |
| --- | --- |
| All hooks on all files (required before every commit) | `uv run prek run --all-files` |
| Tests | `uv run pytest` |
| Tests with coverage | `uv run pytest --cov --cov-report=term-missing` |
| One test class | `uv run pytest tests/test_text_io.py::TestNewlineHandlingBugs -v` |
| Lint and format check, as CI does | `uv run ruff check .` and `uv run ruff format --check .` |
| Type check, as CI does | `uv run mypy src tests/typing/public_api_positive.py` |
| Second type checker, as CI does | `uv run ty check src tests/typing/public_api_positive.py` |
| Docs build, as CI does | `uv run mkdocs build --strict` |

## Commits

- Before creating a commit, run `uv run prek run --all-files` and fix any issues it reports.
- Do not create a commit while `prek` is failing unless the user explicitly asks for it.
- Treat `ruff format --check` failures as blocking, even if `ruff check` and tests pass.
- Never commit to `main`; open a pull request. `gh pr merge <n> --auto --merge` lands it when checks pass.
- Subject: `Fix:`, `Add:` or `Update:` and a short description; then a body saying what changed and why, and
  `Fixes: #123` where it applies.
- Code may use Python 3.11 syntax. Avoid broad syntax-only modernization of untouched modules; keep changes
  focused and reviewable.

## Tests

- New behavior needs a test. CI enforces a coverage floor with `--cov-fail-under=85`; the current figure is the
  badge in `README.md`.
- Most test files are named for their subject. Edge-case tests are grouped in classes named for their priority,
  and a test file may define any of them; `tests/test_regressions.py` has all three: `TestHighPriorityEdgeCases`
  (security and data integrity), `TestMediumPriorityEdgeCases` (robustness), `TestLowPriorityEdgeCases` (defensive
  validation). `TestNewlineHandlingBugs` in `tests/test_text_io.py` holds the newline bug fixes.
- `tests/test_agents_md_paths.py` fails if a repository path or `tests/...::Class` named in this file does not
  exist. `tests/test_doc_examples.py` checks every fenced `python` block in `README.md`, this file and
  `docs/*.md`.

## Architecture invariants

`src/aiogzip/codec.py` is the single production gzip state machine. It owns
RFC 1952 framing, raw DEFLATE engine state, CRC/ISIZE accounting, member
traversal, padding, metadata, and decompression limits. `_binary.py`,
`_streaming.py`, and `_inspection.py` are transport wrappers and must not grow
their own gzip framing or member loops.

The public `GzipEncoder` and `GzipDecoder` are synchronous sans-I/O codecs.
Their state-changing methods return lazy reserved operations. Exhaust or
explicitly close every operation; never depend on iterator finalizers, eagerly
materialize an operation before producing output, or read the next source item
while the current operation still has output. Async wrappers own executor
offload, cancellation, source/sink cleanup, and backpressure.

Codec input is deliberately stricter than file `write()`: exact `bytes` is
zero-copy, a `bytes` subclass is snapshotted to exact `bytes`, and mutable or
general buffers are rejected. Codec instances and operation iterators are not
thread-safe. Preserve these ownership and immutable-input boundaries when
changing the architecture.

### File-state invariants

The asyncio file handles' lifecycle, read health, source and native-work
ownership, text checkpoint and text/binary bridge are specified in
`plans/design/v2.0.0b2-file-state-model.md`, which names the tests that pin
each rule (including the stateful harness in `tests/stateful/`). Every
approved behavior difference from b1 is recorded in
`plans/reviews/v2.0.0b2-behavior-exceptions.md`. Read both before changing
`_binary.py`, `_text.py` or `_source_io.py`. A change to a documented
transition or to observable behavior needs a model or ledger update, not a
silent test edit. `plans/README.md` indexes every plan and record.

## Gotchas

### Newline Handling

- CRLF sequences can split across chunk boundaries
- Must track `_trailing_cr` state to prevent `\r\n` → `\n\n`
- Use `_find_line_terminator()` helper for newline-aware searching
- Tests that write arbitrary/random text and assert a byte-exact round-trip
  must pass `newline=""`: default `newline=None` translates `\n` to
  `os.linesep` on write, which is a no-op on Linux/macOS but breaks the
  assertion on Windows CI. Worse, a failing `==` between multi-hundred-KB
  blobs sends pytest's assertion introspection into a difflib comparison
  that runs for many minutes — the job dies at its time cap looking like a
  hang, not a failure (`faulthandler_timeout` in pyproject exists to make
  such hangs identify themselves).

### Unicode Handling

- Multibyte characters can split across buffers
- Decoding uses an incremental codec (`codecs.getincrementaldecoder`) that
  retains incomplete trailing bytes between chunks
- Different encodings have different max incomplete byte counts

### Error Handling

- Always wrap zlib errors in OSError with descriptive messages
- Use `from e` for proper exception chaining
- Test both expected (zlib.error) and unexpected (RuntimeError) error paths

## Performance Regression Checks

The read/readline/iteration paths in `_binary.py` and `_text.py` are hot:
seemingly harmless changes there (an extra branch, attribute lookup, or
method call per line/chunk) have measurably cost throughput before. When
touching them, benchmark before and after:

Check out the baseline *source* in a worktree, but run both sides with the
**same venv, interpreter, and benchmark runner**. Comparable captures require
explicit clean source roots so the JSON contains commit, dirty-tree,
environment, and engine attestations:

```bash
git worktree add /tmp/aiogzip-baseline main

# Baseline source, current runner and venv
uv run python benchmarks/run_benchmarks.py \
    --category io,micro --source-root /tmp/aiogzip-baseline \
    --engine stdlib --output /tmp/bench-before.json

# Clean candidate commit, current runner and venv
uv run python benchmarks/run_benchmarks.py \
    --category io,micro --source-root . \
    --engine stdlib --output /tmp/bench-after.json

# Compare
uv run python benchmarks/bench_compare.py /tmp/bench-before.json /tmp/bench-after.json

git worktree remove /tmp/aiogzip-baseline
```

Notes:

- **Never `uv run` from inside the baseline worktree** — it creates a fresh
  venv that can resolve a *different Python version* (interpreter speed
  differences of ±10% masquerade as code regressions) and may lack the
  `fast` extra (zlib-ng vs stdlib skews read benchmarks several-fold).
  With `--source-root`, the runner verifies the source swap and records
  `aiogzip.__file__` itself.
- Comparable captures require clean committed source roots. For an uncommitted
  exploratory run, omit `--source-root`; the runner still verifies
  `--engine`, but records no source/environment attestation and the comparator
  rejects the result by design. Commit the candidate before producing a
  before/after comparison or release evidence. Before an exploratory run,
  confirm the environment's imported package and active engines explicitly:
  `uv run python -c 'import aiogzip; print(aiogzip.__file__); print(aiogzip.engine_info())'`.
- Pin the codec with `--engine stdlib` on both sides. The runner applies and
  verifies the library's stdlib-only environment override; use
  `--engine zlib-ng` to request and verify the optional engine.
- Run on a quiet machine — background load skews results badly. Interleave
  several before/after rounds and compare per-benchmark *minimum* times;
  single-run deltas are noise.
- `io,micro` covers the hot paths; use `--all` for changes to compression,
  concurrency, or memory behavior.
- Treat deltas that survive interleaved min-of-N comparison as real; chase
  anything above ~5% with a targeted timeit-style micro-test before
  concluding either way.

## CI

The project uses GitHub Actions which tests against Python 3.11 through 3.15.
Linux runs the full version sweep; Windows runs 3.12 and 3.14 and macOS runs
3.14 to guard platform-specific paths (e.g. `os.linesep` newline
translation). The macOS build leg also reruns the suite with zlib-ng; keep
macOS jobs to about two per run, because GitHub runs few macOS jobs at a time
per account and queued ones have been cancelled before starting.

The Linux 3.15 leg installs uv's managed CPython 3.15.0 (`uv venv
--managed-python`, with `UV_PYTHON` pointing `uv pip install --system` at
it), because `actions/setup-python` did not offer 3.15.0 when 3.15 was
promoted for 2.0.0rc2. Switch it to setup-python once that offers 3.15.0.
The informational `python-preview` job that ran 3.15 pre-releases was
removed at the promotion; re-add one for 3.16 when setup-python offers its
pre-releases (not a required check, `continue-on-error`, no classifier).
The README and docs home page show the supported range as a static badge
(`python-3.11–3.15`); when a version is added or dropped, update it with the
classifiers. `tests/test_version_sync.py` fails until they agree.

`main` has branch protection requiring every CI job (lint, all build matrix
legs, fast-engine — not coverage-comment), and repo auto-merge is enabled:
`gh pr merge <n> --auto --merge` lands a PR when checks pass. **Gotcha:**
the required checks are matched by job name, so changing the matrix (adding
a Python version, renaming a job, swapping an OS) requires updating the
branch-protection contexts too, or merges block forever waiting on a
check that no longer exists (a *new* leg that isn't required will pass
unnoticed instead). Update via
`gh api -X PUT repos/geoff-davis/aiogzip/branches/main/protection`.

The test matrix installs the `[test]` extra (not `[dev]`, which adds
lint-only tooling). mypy and types-aiofiles belong to `[test]` because
`test_factory_typing.py` shells out to `mypy --strict` and silently skips
when mypy is absent.

`astral-sh/setup-uv` publishes no moving major tag from v8 on — pin the
exact version (e.g. `@v8.3.0`); a bare `@v8` fails to resolve. Dependabot's
github-actions ecosystem keeps the pin current.

## Releases

`/release-prep`, merge, then `/release-tag`. Publishing is tag-triggered. `/release-tag` pushes the signed tag,
creates the GitHub release, then watches the publish workflow and confirms the version is live on PyPI before
reporting the release complete.

## Context window

A full context window is compacted, and the session continues: the conversation is replaced by a summary and work
carries on. Running low is not a reason to stop, rush, or hand work to a subagent that would not otherwise get it.
When the token usage reminder shows the window is nearly full (auto-compaction fires at about 13k to 15k tokens
remaining), reach a clean state first: notes or the plan file updated, and the working tree either committed or
described.
