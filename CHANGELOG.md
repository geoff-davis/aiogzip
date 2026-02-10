# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Fixed

- Reject invalid `newline` values in `AsyncGzipTextFile` (e.g., `newline="bad"`) with `ValueError`, matching stdlib behavior.
- Align `fileobj` close semantics with `gzip.GzipFile`: default `closefd=False` for caller-provided `fileobj`, while preserving close-on-exit for internally opened filenames.
- Validate `AsyncGzipFile(mode=...)` type early and raise a consistent `TypeError` for non-string modes.
- In binary factory modes, reject text-only kwargs (`encoding`, `errors`, `newline`) when non-`None`, and ignore them when explicitly `None`.
- Accept `encoding=None` and `errors=None` in text mode and normalize to defaults (`utf-8`, `strict`).
- Ignore `compresslevel` validation in read modes, matching `gzip.open`.
- Allow `compresslevel=-1` (zlib default) in write modes; keep validation for values outside `[-1, 9]`.
- Support text `seek(0, SEEK_CUR)` and `seek(0, SEEK_END)`, while rejecting nonzero relative text seeks with `io.UnsupportedOperation` like stdlib.
- Prevent silent data corruption when seeking to evicted text cookies by raising `OSError` for uncached nonzero cookies.
- Make `peek(0)` behave as a real peek and fix a bug where `peek()` could incorrectly return empty bytes before EOF.
- Raise `gzip.BadGzipFile` (instead of generic `OSError`) for gzip decompression/finalization errors.

### Added

- Regression tests for all compatibility and correctness fixes listed above, including:
  - text newline validation
  - binary/text `fileobj` default close behavior
  - factory mode-type validation
  - binary factory text-kwarg handling (`None` and non-`None`)
  - text-mode `encoding=None` / `errors=None`
  - read/write `compresslevel` semantics
  - text `seek` CUR/END support and nonzero relative seek errors
  - uncached text-cookie seek failure behavior
  - `peek(0)` and non-empty pre-EOF `peek()` behavior
  - `BadGzipFile` exception type for corrupted streams

## [1.1.0] - 2025-11-25

### Added

- `readlines()` method for `AsyncGzipTextFile` for efficient bulk line reading.
- `writelines()` method for `AsyncGzipTextFile` for efficient bulk line writing.
- `name` property on both `AsyncGzipBinaryFile` and `AsyncGzipTextFile` returning the underlying filename.
- `BUFFER_COMPACTION_THRESHOLD` class constant for configurable buffer management.
- `MAX_COOKIE_CACHE_SIZE` class constant with automatic eviction to prevent unbounded memory growth.
- Made `AsyncGzipBinaryFileProtocol` and `AsyncGzipTextFileProtocol` `@runtime_checkable` for duck-typing support.
- 15 new tests in `TestAdditionalCoverage` class covering edge cases and new features.

### Changed

- Added `__slots__` to `AsyncGzipBinaryFile` and `AsyncGzipTextFile` for improved memory efficiency.
- Refactored `readline()` control flow for improved clarity and maintainability.
- Switched CI coverage reporting to py-cov-action/python-coverage-comment-action.
- Test count increased from 209 to 253 tests.
- Coverage improved from 85.13% to 87.92%.

## [1.0.0] - 2025-11-19

### Added

- Comprehensive test coverage for error conditions and edge cases in `tests/test_edge_cases_and_errors.py`.
- `pre-commit` configuration with `ruff` and `mypy` for code quality enforcement.
- Initial MkDocs documentation structure and configuration.
- Ability to set gzip header `mtime` and original filename metadata for deterministic archives.
- Async wrappers for `seek`, `tell`, `peek`, `readinto`, and `fileno` to improve drop-in compatibility with `gzip.GzipFile`.

### Changed

- Updated `pyproject.toml` with development dependencies and tooling configurations.

### Fixed

- Resolved import sorting and formatting issues across the project with Ruff v0.14.5.

### Refactor

- Modernized `AsyncGzipTextFile` to use `codecs.getincrementaldecoder` for improved memory efficiency and simplified text decoding logic.
- Removed obsolete manual buffering (`_pending_bytes`, `_text_data`, `_line_buffer`) in `AsyncGzipTextFile`, in favor of a unified `_text_buffer`.
- Simplified `read`, `readline`, and iteration logic in `AsyncGzipTextFile`.
- Cleaned up `tests/test_aiogzip.py` by removing assertions for obsolete internal state attributes.

### Performance

- Optimized `AsyncGzipBinaryFile` buffer handling by replacing `bytearray` deletion with an offset pointer to avoid excessive data movement during read operations.

## [0.4] - 2025-11-14

### Fixed

- Support gzip-compatible mode strings (e.g., `xb`, `rb+`, `xt`, `rt+`) while rejecting only invalid binary/text combinations
- Treat `newline=''` the same as CPython by keeping CRLF pairs intact when they cross chunk boundaries
- Allow arbitrary codec error handlers (e.g., `surrogatepass`, user-registered handlers) in text mode instead of rejecting unknown values
- Accept `bytes`/`Path` filenames in `AsyncGzipTextFile` by avoiding accidental stringification and add regression tests
- Restore `readline(limit)` parity with `gzip.open` by supporting the optional limit argument and buffering leftovers correctly
- Allow `AsyncGzipBinaryFile.write()` to consume any bytes-like object (bytearray/memoryview/etc.) and emit clearer `TypeError`s for unsupported inputs
- Fix `read(0)` to return empty string without draining internal buffer, conforming to TextIOBase contract
- Fix CRLF sequences split across chunk boundaries causing duplicate newlines (was converting `\r\n` to `\n\n`)
- Fix line iteration (`__anext__`) to respect newline mode parameter (`\r`, `\n`, `\r\n`, universal)
- Fix `readline()` to respect newline mode parameter, ensuring consistent behavior with iteration
- Fix Python 3.8 compatibility by using `Tuple` instead of `tuple` in type hints (PEP 585 syntax not supported in 3.8)

### Added

- Tests for exclusive-create and read/write-plus modes, newline='' boundary handling, and custom error handlers
- Tests for bytes-path support, buffer-protocol writes, and `readline(limit)` semantics
- Comprehensive test coverage improvements: 113 → 162 tests (+49 tests)
- Test coverage increased from 84.13% to 88.47%
- Tests for exception handling edge cases (unexpected errors in compression/decompression/flush)
- Tests for Unicode boundary detection (multibyte character splits across chunks)
- Tests for multi-member gzip archives (empty members, many members, partial reads)
- Tests for async flush/close on custom file objects
- Tests for unusual encodings (shift_jis, iso-8859-1, cp1252, UTF-16/32)
- Tests for closed file operations and iteration edge cases
- Tests documenting and verifying newline handling fixes

### Changed

- Refresh README developer instructions to highlight `uv sync` / `uv run pytest` workflow and correct import examples

## [0.3] - 2025-10-21

- Fix handling of negative `size` values so reads return the full remaining payload in both binary and text modes.
- Make `AsyncGzipTextFile.write()` report the number of characters written instead of encoded byte counts.
- Normalize iteration errors from `AsyncGzipBinaryFile` to `TypeError`, matching the standard file API.
- Declare project metadata dynamically via `aiogzip.__version__`, add explicit license info, and tidy packaging configuration.
