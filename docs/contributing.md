# Contributing

Contributions are welcome! This project uses `flit_core` for packaging and modern tooling for quality assurance.

Development and the 2.0 release line require Python 3.11 or newer. The 1.x
maintenance branch retains compatibility with older supported interpreters.

## Development Setup

1. **Fork and clone the repository**:

    Fork [geoff-davis/aiogzip](https://github.com/geoff-davis/aiogzip) on
    GitHub, then clone your fork and add the main repository as `upstream`:

    ```bash
    git clone https://github.com/<your-username>/aiogzip.git
    cd aiogzip
    git remote add upstream https://github.com/geoff-davis/aiogzip.git
    ```

2. **Install dependencies**:

    The project uses [uv](https://docs.astral.sh/uv/), and `uv.lock` pins the
    development tools so every contributor runs the same versions:

    ```bash
    uv sync --all-extras
    ```

    Prefix commands with `uv run` (for example `uv run pytest`), or activate
    `.venv`. Without uv, `pip install -e ".[dev,csv,fast,docs]"` in a virtual
    environment also works, but resolves unpinned tool versions.

3. **Install the Git hooks**:

    This project uses `prek` (a drop-in replacement for `pre-commit`). It
    runs ruff, mypy, ty and markdownlint on each commit:

    ```bash
    uv run prek install
    ```

    Two hooks may surprise you. `no-commit-to-branch` refuses commits made
    directly on `main`, so work on a branch. The pre-push hook
    `check-branch-fresh` refuses a push when your branch is missing commits
    from `origin/main`; rebase onto it, as the message suggests.

    In a fork, `origin` is your fork, so also keep your branch current with
    the main repository: `git fetch upstream && git rebase upstream/main`.

## Running Tests

Run the full test suite using `pytest`:

```bash
uv run pytest
```

The suite has more than 7,000 tests and takes a couple of minutes. While
iterating, run the module you are working on, for example
`uv run pytest tests/test_inspection.py`, then the full suite before opening
a pull request.

## Code Quality

We use `ruff` for linting and formatting, and both `mypy` and `ty` for static type checking. These are run automatically by prek, but you can run them manually:

```bash
uv run prek run --all-files   # everything the hooks run
uv run ruff check .
uv run ruff format .
uv run mypy src
uv run ty check src
```

## Making a Change

### Before you start

- Issues labeled
  [good first issue](https://github.com/geoff-davis/aiogzip/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22)
  are small, self-contained starting points.
- Comment on an issue before starting so that it can be assigned to you and
  two people do not work on the same thing. For anything larger than a small
  fix, describe your approach first.
- Report security problems privately as described in the
  [security policy](https://github.com/geoff-davis/aiogzip/security/policy),
  not in a public issue.

### Rules that shape a change

- **The public API is stable.** aiogzip 2.0 follows the
  [stability policy](stability.md). Public signatures, exception types and
  documented behavior do not change in a patch release; new public names wait
  for a minor release. Discuss any API change in an issue first.
- **Behavior changes need a record.** The file handles' lifecycle,
  cancellation, ownership and recovery rules are specified in
  [`plans/design/v2.0.0b2-file-state-model.md`](https://github.com/geoff-davis/aiogzip/blob/main/plans/design/v2.0.0b2-file-state-model.md),
  and every approved behavior difference is listed in the
  [behavior-exception ledger](https://github.com/geoff-davis/aiogzip/blob/main/plans/reviews/v2.0.0b2-behavior-exceptions.md).
  Read both before changing `_binary.py`, `_text.py` or `_source_io.py`. A
  change to observable behavior there needs a model or ledger update, not just
  an edited test.
- **Keep gzip logic in the codec.** See [Package Layout](#package-layout)
  below.
- **Test what you change.** Add or update tests for any behavior change or
  bug fix. Tests that write arbitrary text and expect a byte-exact round trip
  must pass `newline=""`; otherwise the default newline translation breaks
  them on Windows CI.

### Commits and the changelog

Use conventional commit titles, with a short body explaining why:

```text
Fix: Short description of the change

What changed and why.

Fixes: #123
```

Common prefixes are `Fix:`, `Add:` and `Update:`. Add an entry under
`[Unreleased]` in `CHANGELOG.md` for any user-visible change, in the section
that fits (Added, Changed, Fixed, Documentation, and so on). Internal changes
such as a docstring, a test or a refactor need no entry.

### Opening the pull request

1. Push your branch to your fork and open a pull request against `main`.
2. Write "Fixes #123" in the description so that the issue closes when the
   pull request merges, and summarize what you changed and how you tested it.
3. Keep each pull request to one concern; separate fixes are easier to review
   as separate pull requests.

GitHub Actions does not run automatically for a first-time contributor's pull
request; a maintainer approves the run. CI then runs the suite on Python
3.11 through 3.15 on Linux and on selected versions on Windows and macOS, with
and without the optional zlib-ng engine, and checks linting, the
documentation build, the minimum dependency versions and the installed
artifacts. Every required check must pass before a pull request can merge.

## Performance-Sensitive Changes

Capture benchmark results before changing codec calls, buffering, text
decoding, line iteration, executor offloading, or parser hot paths. Comparable
captures require clean committed source roots; use the current checkout's venv
and runner for both worktrees so Python, engine, filesystem, data, and repeat
count stay fixed:

```bash
git worktree add /tmp/aiogzip-before <baseline-commit>
git worktree add /tmp/aiogzip-after <candidate-commit>

uv run python benchmarks/run_benchmarks.py \
  --category io,scenarios,concurrency --size 8 --repeat 5 \
  --engine stdlib --source-root /tmp/aiogzip-before \
  --output /tmp/aiogzip-before.json

uv run python benchmarks/run_benchmarks.py \
  --category io,scenarios,concurrency --size 8 --repeat 5 \
  --engine stdlib --source-root /tmp/aiogzip-after \
  --output /tmp/aiogzip-after.json

uv run python benchmarks/bench_compare.py \
  /tmp/aiogzip-before.json /tmp/aiogzip-after.json
```

Repeat with `--engine zlib-ng` when zlib-ng may be affected. Captures made
without `--source-root` are exploratory and the comparator rejects them by
design. Include the
commands and any material wins or regressions in the pull request. The
[benchmark guide](https://github.com/geoff-davis/aiogzip/tree/main/benchmarks)
documents the comparison methodology and focused categories.

### Hot-path duplication map

A few hot paths deliberately duplicate a slower reference path, because
removing the duplication measurably cost throughput. Each duplicate carries a
`Parity:` comment naming the parametrized test module that pins it to its
reference. Change both paths together, keep the parity module passing, and
re-run the constraining benchmark before merging either path into the other.

| Duplicated path | Reference path | Why it is duplicated | Constraining benchmark | Parity module |
| --- | --- | --- | --- | --- |
| `_Operation.__next__` (`codec.py`) | `_Operation._advance_raw` | Avoids a helper frame on every public advancement | `regressions` codec rows, `micro` Small writes | `test_parity_operation.py` |
| `GzipEncoder._feed_snapshot` | `GzipEncoder.feed` | The file writer's per-call path; avoids three helper frames per tiny write | `micro` Small writes, `io` Text write | `test_parity_encoder_feed.py` |
| Inline reservation in `AsyncGzipBinaryFile.write` | `_BinaryWriteReservation` (`writelines`, `flush`, writer `seek`) | The context manager exceeded the small-write budget | `micro` Small writes | `test_parity_binary_write.py` |
| Inline encoder/sink body in `AsyncGzipTextFile.write` | `_write_batch_reserved` under `_write_call` | The reservation context manager and helper both exceeded 5% on small writes | `micro` Text writelines batching, `io` Text write | `test_parity_text_inline.py` |
| Inline origin capture in `_read_chunk_and_decode` | `_capture_buffer_origin` | Avoids a helper frame per refill | `io` Text line iteration, `text_origin` | `test_parity_text_inline.py` |
| `_decode_next_chunk` | `_read_chunk_and_decode` | Returns text for local accumulation, avoiding quadratic `str +=` | `io` Text large reads, Text read (bulk) | `test_parity_text_inline.py` |
| Pending-line consumption inline in `__anext__` | `readline()` | A helper call per line lowers iteration throughput | `micro` Line iteration, `io` Text line iteration | `test_parity_text_inline.py` |
| Bounded fast path inline in `readline()` | `_take_buffered_line` | Avoids a helper frame and a second buffered-length computation | `micro` readline() loop | `test_parity_text_inline.py` |

## Package Layout

Core implementation is split across focused modules in `src/aiogzip`:

- `codec.py`: the only production gzip state machine; owns framing, raw
  DEFLATE, CRC/ISIZE, members, padding, metadata, and limits
- `_engine.py`: normalized engine selection and input-consumption accounting
- `_common.py`: shared constants, validation helpers, and protocols
- `_binary.py`: `AsyncGzipBinaryFile` transport and buffering
- `_streaming.py`, `_inspection.py`: thin async drivers around the codec
- `_text.py`: `AsyncGzipTextFile` implementation
- `__init__.py`: public API exports, recommended `open()` entry point, and the
  compatibility `AsyncGzipFile` factory

Do not add gzip framing, trailer, CRC/ISIZE, raw-engine, or member-loop logic to
a transport wrapper. Codec operations are lazy: a wrapper must exhaust or
explicitly close each returned iterator before another state change, preserve
the primary error during cleanup, and avoid reading ahead from an async source.
The codec itself performs no I/O and no executor offload; wrappers own those
policies.

Development and CI target Python 3.11 through 3.15. Code in the 2.0 line may
use Python 3.11 syntax, while compatibility fixes for older interpreters belong
on the `1.x` maintenance branch.

When adding new internals, prefer one of the focused modules and keep
`__init__.py` as the stable public API surface.

## Documentation

To build the documentation locally:

```bash
uv run mkdocs serve
```

Then open [http://localhost:8000](http://localhost:8000) in your browser.
