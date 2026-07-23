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
decoding, line iteration, executor offloading, or parser hot paths. Run the
same command afterward so the comparison uses the same Python, engine,
filesystem, data, and repeat count:

```bash
AIOGZIP_ENGINE=stdlib uv run python benchmarks/run_benchmarks.py \
  --category io,scenarios,concurrency --size 8 --repeat 5 \
  --output /tmp/aiogzip-before.json

# Make the change, then repeat with --output /tmp/aiogzip-after.json.

uv run python benchmarks/bench_compare.py \
  /tmp/aiogzip-before.json /tmp/aiogzip-after.json
```

Repeat with the default engine when zlib-ng may be affected. Include the
commands and any material wins or regressions in the pull request. The
[benchmark guide](https://github.com/geoff-davis/aiogzip/tree/main/benchmarks)
documents the comparison methodology and focused categories.

## Package Layout

Core implementation is split across focused modules in `src/aiogzip`:

- `_common.py`: shared constants, validation helpers, and protocols
- `_binary.py`: `AsyncGzipBinaryFile` implementation
- `_text.py`: `AsyncGzipTextFile` implementation
- `__init__.py`: public API exports, recommended `open()` entry point, and the
  compatibility `AsyncGzipFile` factory

When adding new internals, prefer one of the focused modules and keep `__init__.py` as the stable public API surface.

## Documentation

To build the documentation locally:

```bash
mkdocs serve
```

Then open [http://localhost:8000](http://localhost:8000) in your browser.
