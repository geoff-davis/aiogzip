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
`uv.lock`) so new dependency releases are exercised across 3.8-3.14 before
users hit them. Dependabot's `uv` ecosystem keeps `uv.lock` current.

The lockfile also only resolves for Python >= 3.10
(`tool.uv.environments` in pyproject.toml): the 3.8/3.9 branches carried
urllib3/wheel pins frozen on known CVEs because the fixes dropped old
Pythons. `uv sync`/`uv run` under 3.8/3.9 is therefore refused — for a
local old-Python check use pip/pyenv (see the 3.8 checklist below).

Why this matters: a stale checkout here once produced a full package review
and a 21-commit branch built on v1.7.0 while origin was already at v1.8.0 —
two commits duplicated already-shipped work, the PR opened conflicting, and
everything had to be rebased. The git status snapshot at session start only
reflects the local clone; it says nothing about freshness relative to origin.

A pre-push hook (`scripts/check_branch_fresh.sh`, wired up as the
`check-branch-fresh` pre-commit hook) backstops this: it refuses a push when
`origin/main` has commits missing from the branch's history, which also
catches main moving *mid-session*. It requires the pre-push hook type to be
installed — `pre-commit install` handles it via `default_install_hook_types`,
but run it once on each machine/clone. Intentionally-behind pushes:
`SKIP=check-branch-fresh git push`. The hook fails open when offline.

## Python 3.8 Compatibility Checklist

**IMPORTANT:** This library supports Python 3.8+. Always check for PEP 585 compatibility before committing!

### Type Hints - Python 3.8 Compatibility

Python 3.8 does NOT support PEP 585 (using built-in types for generics). Always use `typing` module imports:

#### ❌ DON'T (Python 3.9+ only)

```python
def function() -> tuple[int, int]:
    pass

def function() -> list[str]:
    pass

def function() -> dict[str, int]:
    pass
```

#### ✅ DO (Python 3.8+ compatible)

```python
from typing import Tuple, List, Dict

def function() -> Tuple[int, int]:
    pass

def function() -> List[str]:
    pass

def function() -> Dict[str, int]:
    pass
```

### Pre-commit Checklist

Before committing code changes, verify:

1. **Type hints compatibility:**

   ```bash
   grep -r "tuple\[" src/
   grep -r "list\[" src/
   grep -r "dict\[" src/
   grep -r "set\[" src/
   grep -r "PathLike\[" src/
   ```

   All should return no results! Use `Tuple`, `List`, `Dict`, `Set` from `typing` instead.
   For PathLike, use plain `os.PathLike` (not `os.PathLike[str]`).

2. **Run tests locally:**

   ```bash
   pytest --cov --cov-report=term-missing
   ```

   Ensure all 850+ tests pass with good coverage.

3. **Check imports:**

   ```python
   from typing import Tuple, List, Dict, Set, Optional, Union, Any
   ```

   Make sure these are imported if used.

4. **Test with Python 3.8 (optional but recommended):**

   The pre-commit `python38-compat` hook (`scripts/check_py38_compat.py`)
   catches syntax-level incompatibilities. For a runtime check with pyenv:

   ```bash
   pyenv install 3.8.18  # One-time setup
   pyenv exec python3.8 -c "import aiogzip"  # Quick import test
   ```

## Test Coverage Best Practices

- **Current coverage:** ~92% (850+ tests)
- **Target:** Maintain or improve coverage. CI enforces a floor via
  `--cov-fail-under=85`.
- Always add tests for new features
- Document edge cases with descriptive test names

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

The project uses GitHub Actions which tests against Python 3.8 through 3.14.
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
lint-only tooling). mypy/types-aiofiles/typing_extensions belong to
`[test]` because `test_factory_typing.py` shells out to `mypy --strict`
and silently skips when mypy is absent.

`astral-sh/setup-uv` publishes no moving major tag from v8 on — pin the
exact version (e.g. `@v8.3.0`); a bare `@v8` fails to resolve. Dependabot's
github-actions ecosystem keeps the pin current.

**Any Python 3.9+ only syntax will fail CI!**

Common causes of CI failures:

- PEP 585 type hints (most common)
- PEP 604 union operator (`X | Y` instead of `Union[X, Y]`)
- Match statements (Python 3.10+)
- Dictionary merge operators (`|` for dicts, Python 3.9+)

## Useful Commands

```bash
# Run tests with coverage
pytest --cov --cov-report=term-missing --cov-report=html

# Check for Python 3.8 incompatibilities
grep -rn "tuple\[" src/
grep -rn "list\[" src/
grep -rn "dict\[" src/

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
- **1.10.0 (current)** - See `CHANGELOG.md` for the full release history. Recent
  work adds package-level `open()`, whole-file helpers, engine diagnostics,
  gzip inspection and verification, and bounded async-iterable compression and
  decompression. It also expands migration, recipe, streaming, operational, and
  benchmark documentation.

---

**Last Updated:** 2026-07-09
**Maintainer Notes:** Keep this file updated with new gotchas and best practices!
