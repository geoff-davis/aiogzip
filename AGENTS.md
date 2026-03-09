# Repository Instructions

## Commit Checks

- Before creating a commit, run `uv run pre-commit run --all-files` and fix any issues it reports.
- Do not create a commit while `pre-commit` is failing unless the user explicitly asks for it.
- Treat `ruff format --check` failures as blocking, even if `ruff check` and tests pass.
