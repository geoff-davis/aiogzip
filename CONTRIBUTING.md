# Contributing to aiogzip

Thanks for your interest in contributing. The full guide is the
[contributing page](https://geoff-davis.github.io/aiogzip/dev/contributing/) in
the documentation, kept in this repository as
[`docs/contributing.md`](docs/contributing.md). It covers setup, tests,
code quality, the rules for behavior changes, benchmarks and the package
layout.

## Quick start

```bash
git clone https://github.com/<your-username>/aiogzip.git
cd aiogzip
uv sync --all-extras        # needs https://docs.astral.sh/uv/
uv run prek install         # lint and type-check hooks
git checkout -b my-change   # commits directly on main are refused
# make your change, then:
uv run prek run --all-files
uv run pytest
```

## Before opening a pull request

- Comment on the issue you are working on so that it can be assigned to you.
  [Good first issues](https://github.com/geoff-davis/aiogzip/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22)
  are a good place to start.
- Keep the pull request to one concern, add tests for behavior changes, and
  add a `CHANGELOG.md` entry under `[Unreleased]` for user-visible changes.
- Use a conventional commit title such as `Fix: Short description`, and write
  "Fixes #123" in the pull request description.
- The public API follows the [stability policy](docs/stability.md); discuss
  API changes in an issue first.

A maintainer approves CI for a first-time contributor's pull request, and
every required check must pass before it merges.

Report security problems privately, as described in [SECURITY.md](SECURITY.md),
not in a public issue.
