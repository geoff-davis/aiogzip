# Contributing

Contributions are welcome! This project uses `flit_core` for packaging and modern tooling for quality assurance.

Development and the 2.0 release line require Python 3.11 or newer. The 1.x
maintenance branch retains compatibility with older supported interpreters.

## Development Setup

1. **Clone the repository**:

    ```bash
    git clone https://github.com/geoff-davis/aiogzip.git
    cd aiogzip
    ```

2. **Install dependencies**:

    We recommend using a virtual environment.

    ```bash
    python -m venv .venv
    source .venv/bin/activate
    pip install -e ".[dev,csv,docs]"
    ```

3. **Install Pre-commit Hooks**:

    This project uses `prek` (a drop-in replacement for `pre-commit`) to
    ensure code quality.

    ```bash
    prek install
    ```

## Running Tests

Run the full test suite using `pytest`:

```bash
pytest
```

## Code Quality

We use `ruff` for linting and formatting, and both `mypy` and `ty` for static type checking. These are run automatically by prek, but you can run them manually:

```bash
ruff check .
ruff format .
mypy src
ty check src
```

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

Development and CI target Python 3.11 through 3.14. Code in the 2.0 line may
use Python 3.11 syntax, while compatibility fixes for older interpreters belong
on the `1.x` maintenance branch.

When adding new internals, prefer one of the focused modules and keep
`__init__.py` as the stable public API surface.

## Documentation

To build the documentation locally:

```bash
mkdocs serve
```

Then open [http://localhost:8000](http://localhost:8000) in your browser.
