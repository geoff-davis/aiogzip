# Contributing

Contributions are welcome! This project uses `setuptools` for packaging and modern tooling for quality assurance.

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

    This project uses `pre-commit` to ensure code quality.

    ```bash
    pre-commit install
    ```

## Running Tests

Run the full test suite using `pytest`:

```bash
pytest
```

## Code Quality

We use `ruff` for linting and formatting, and both `mypy` and `ty` for static type checking. These are run automatically by pre-commit, but you can run them manually:

```bash
ruff check .
ruff format .
mypy src
ty check src
```

## Package Layout

Core implementation is split across focused modules in `src/aiogzip`:

- `_common.py`: shared constants, validation helpers, and protocols
- `_binary.py`: `AsyncGzipBinaryFile` implementation
- `_text.py`: `AsyncGzipTextFile` implementation
- `__init__.py`: public API exports and `AsyncGzipFile` factory

When adding new internals, prefer one of the focused modules and keep `__init__.py` as the stable public API surface.

## Documentation

To build the documentation locally:

```bash
mkdocs serve
```

Then open [http://localhost:8000](http://localhost:8000) in your browser.
