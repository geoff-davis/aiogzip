# Development Notes for Claude Code

This document contains important reminders and best practices for maintaining the aiogzip library.

## Sync Before Working

This library is developed from multiple machines, so the local checkout can
silently lag origin. **Before reviewing code or starting any changes:**

```bash
git fetch origin
git log --oneline main..origin/main   # anything here means local main is stale
```

If local main is behind, fast-forward it (`git checkout main && git pull
--ff-only`) and branch from the updated main. As a cross-check, `__version__`
in `src/aiogzip/__init__.py` should match the newest `CHANGELOG.md` entry and
the latest tag (`git tag --sort=-v:refname | head -1`).

After pulling, also sync the dev environment from the committed lockfile so
every machine runs identical tool/dependency versions (mismatched dev envs
have corrupted benchmark comparisons before):

```bash
uv sync --all-extras
```

The lockfile pins development only — CI deliberately installs unpinned
(`uv pip install --system`, which resolves fresh from PyPI and never reads
`uv.lock`) so new dependency releases are exercised across Python 3.11-3.14
before users hit them. Dependabot's `uv` ecosystem keeps `uv.lock` current.

The lockfile resolves for Python 3.11 and newer, matching the 2.0 package
metadata. Compatibility fixes for older interpreters belong on the `1.x`
maintenance branch.

Why this matters: a stale checkout here once produced a full package review
and a 21-commit branch built on v1.7.0 while origin was already at v1.8.0 —
two commits duplicated already-shipped work, the PR opened conflicting, and
everything had to be rebased. The git status snapshot at session start only
reflects the local clone; it says nothing about freshness relative to origin.

A pre-push hook (`scripts/check_branch_fresh.sh`, wired up as the
`check-branch-fresh` hook in `.pre-commit-config.yaml`) backstops this: it
refuses a push when `origin/main` has commits missing from the branch's
history, which also catches main moving *mid-session*. Hooks run via `prek`
(a drop-in pre-commit replacement; same config file). The pre-push hook type
must be installed — `uv run prek install` handles it via
`default_install_hook_types`, but run it once on each machine/clone. Intentionally-behind pushes:
`SKIP=check-branch-fresh git push`. The hook fails open when offline.

## Test Coverage Best Practices

- **Current coverage:** ~93% (1,300+ tests)
- **Target:** Maintain or improve coverage. CI enforces a floor via
  `--cov-fail-under=85`.
- Always add tests for new features
- Document edge cases with descriptive test names

## Gzip Architecture

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

### Test Organization

Tests are organized by priority:

- `TestHighPriorityEdgeCases` - Security & data integrity
- `TestMediumPriorityEdgeCases` - Robustness
- `TestLowPriorityEdgeCases` - Defensive validations
- `TestNewlineHandlingBugs` - Specific bug fixes

## Performance Regression Checks

The read/readline/iteration paths in `_binary.py` and `_text.py` are hot:
seemingly harmless changes there (an extra branch, attribute lookup, or
method call per line/chunk) have measurably cost throughput before. When
touching them, benchmark before and after:

Check out the baseline *source* in a worktree, but run both sides with the
**same venv and interpreter** by shadowing the editable install via
PYTHONPATH (aiogzip is pure Python, so no build step is needed):

```bash
git worktree add /tmp/aiogzip-baseline main

# Baseline source, current venv (PYTHONPATH shadows the editable install)
PYTHONPATH=/tmp/aiogzip-baseline/src AIOGZIP_ENGINE=stdlib \
    uv run python benchmarks/run_benchmarks.py \
    --category io,micro --output /tmp/bench-before.json

# Current branch source
AIOGZIP_ENGINE=stdlib uv run python benchmarks/run_benchmarks.py \
    --category io,micro --output /tmp/bench-after.json

# Compare
uv run python benchmarks/bench_compare.py /tmp/bench-before.json /tmp/bench-after.json

git worktree remove /tmp/aiogzip-baseline
```

Notes:

- **Never `uv run` from inside the baseline worktree** — it creates a fresh
  venv that can resolve a *different Python version* (interpreter speed
  differences of ±10% masquerade as code regressions) and may lack the
  `fast` extra (zlib-ng vs stdlib skews read benchmarks several-fold).
  Verify the source swap with
  `PYTHONPATH=... python -c "import aiogzip; print(aiogzip.__file__)"`.
- Pin the codec with `AIOGZIP_ENGINE=stdlib` on both sides.
- Run on a quiet machine — background load skews results badly. Interleave
  several before/after rounds and compare per-benchmark *minimum* times;
  single-run deltas are noise.
- `io,micro` covers the hot paths; use `--all` for changes to compression,
  concurrency, or memory behavior.
- Treat deltas that survive interleaved min-of-N comparison as real; chase
  anything above ~5% with a targeted timeit-style micro-test before
  concluding either way.

## Known Issues & Gotchas

### Newline Handling

- CRLF sequences can split across chunk boundaries
- Must track `_trailing_cr` state to prevent `\r\n` → `\n\n`
- Use `_find_line_terminator()` helper for newline-aware searching

### Unicode Handling

- Multibyte characters can split across buffers
- Decoding uses an incremental codec (`codecs.getincrementaldecoder`) that
  retains incomplete trailing bytes between chunks
- Different encodings have different max incomplete byte counts

### Error Handling

- Always wrap zlib errors in OSError with descriptive messages
- Use `from e` for proper exception chaining
- Test both expected (zlib.error) and unexpected (RuntimeError) error paths

## CI/CD Notes

The project uses GitHub Actions which tests against Python 3.11 through 3.14.
Linux runs the full version sweep; Windows and macOS each run one version to
guard platform-specific paths (e.g. `os.linesep` newline translation).

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

Code in the 2.0 line may use Python 3.11 syntax. Avoid broad syntax-only
modernization of untouched modules; keep changes focused and reviewable.

## Useful Commands

```bash
# Run tests with coverage
pytest --cov --cov-report=term-missing --cov-report=html

# Run specific test class
pytest tests/test_aiogzip.py::TestNewlineHandlingBugs -v

# Check typing with mypy (if configured)
mypy src/aiogzip.py
```

## Commit Message Format

Use conventional commit style:

```
Fix/Add/Update: Short description

Detailed description of what changed and why.

Fixes: #123
```

Always include:

- 🤖 Generated with [Claude Code](https://claude.com/claude-code)
- Co-Authored-By: Claude <noreply@anthropic.com>

## Version History

- **0.3** - Major refactoring, binary/text separation
- **2.0.0a1 (current)** - Requires Python 3.11+ and adds the public synchronous
  sans-I/O `GzipEncoder` and `GzipDecoder`. File, iterable-streaming, inspection,
  and verification paths now share that one gzip state machine. The codec API
  remains provisional through the alpha series; established asyncio APIs keep
  their compatibility contract.

---

**Last Updated:** 2026-07-22
**Maintainer Notes:** Keep this file updated with new gotchas and best practices!
