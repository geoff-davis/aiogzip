# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

## [1.3.2] - 2026-04-14

### Documentation

- Add JSONL performance tips to README, examples guide, and performance guide.
- Recommend `newline="\n"` and larger `chunk_size` for efficient gzipped JSONL reads.

## [1.3.1] - 2026-04-01

### Performance

- Replace character-by-character Python loop in text newline decoding with C-speed string operations (`str.find`, `in`, `str.replace`), with a fast path that skips translation entirely when no `\r` is present.
- Eliminate per-line string slice copies in `readline()` and `async for` iteration by searching directly in the text buffer with an offset instead of creating a slice copy.
- Track already-scanned buffer positions in `readline()` / `__anext__()` to avoid O(n²) re-scanning when lines span multiple chunks.
- Dedicated `read(-1)` fast path that bypasses per-chunk buffer append/consume overhead, performing a single binary read and decode instead.
- Use `memoryview` for zero-copy buffer slicing in binary `read()`, `read1()`, and `readline()`, eliminating an intermediate `bytearray` allocation per call.
- Add binary `readline()` fast path for the common case where the line fits in the current buffer, avoiding list allocation and `b"".join()`.
- Add binary `read(size)` early exit when the buffer already satisfies the request.
- Make text `_capture_buffer_origin()` synchronous by accessing binary position directly, eliminating coroutine creation overhead per chunk.
- Inline small helper methods (`_buffered_text_len`, `_capture_buffer_origin`, `_finalize_pending_newline_state`, `_at_stream_eof`) in hot paths to eliminate method call overhead.
- Pre-compute `_universal_newlines` flag at init to replace per-chunk set membership tests.
- Defer text buffer compaction until dead space exceeds a threshold, matching the binary layer's strategy.
- Inline `isinstance` check in binary `write()` for the common `bytes` input case, skipping static method dispatch.
- Cache class-attribute and instance-attribute lookups as locals in tight loops.

## [1.3.0] - 2026-03-09

### Fixed

- Make `AsyncGzipTextFile.tell()` cookies unique per call to avoid collisions that could restore the wrong text position when using `seek(cookie)`.
- Align binary `read1()` and `readinto1()` with `gzip.GzipFile`, including zero-length requests that must not trigger underlying reads.
- Add read-mode binary `seek(..., SEEK_END)` support to match `gzip.GzipFile`.
- Support backward seeks on non-seekable binary `fileobj` inputs by replaying cached compressed input when a rewind is needed.
- Clean up internally opened resources when `AsyncGzipBinaryFile.__aenter__()` or `AsyncGzipTextFile.__aenter__()` fails partway through setup.
- Validate that gzip header `mtime` values fit in the 32-bit field before opening the stream.
- Make text-mode newline tracking match stdlib behavior by reporting observed newline types and preserving that state across `seek(tell())` round trips.
- Rework text `seek()` / `tell()` handling to use self-contained cookies plus stdlib-compatible plain positions, fixing multibyte, translated-newline, and exact-EOF edge cases without retaining per-cookie cache state indefinitely.
- Fall back to `fileobj.name` for `.name` when no explicit filename was provided, matching `gzip.GzipFile`.

### Documentation

- Clarify that text `tell()` values are opaque cookies intended only for `seek(cookie)` on the same open stream.

### Changed

- Narrow GitHub Actions write permissions so only the coverage-comment job gets elevated access.
- Ignore local `mise.toml` tool configuration files in git status.

### Refactor

- Split the test suite into focused modules for factory, binary, text, file-object, lifecycle, interop, regression, and performance coverage.
- Add contributor guidance to run `uv run pre-commit run --all-files` before committing so formatting and type-check issues are caught locally.

## [1.2.2] - 2026-02-11

### Added

- Add Python 3.14 support metadata: include the `Programming Language :: Python :: 3.14` classifier and expand the documented support badge to `3.8-3.14`.

### Changed

- Expand CI test matrix to include Python 3.14.
- Bump `aiogzip.__version__` to `1.2.2` to align source version metadata with the new release tag.

## [1.2.1] - 2026-02-11

### Fixed

- Restore `project.license` to table form (`{ text = "MIT" }`) for compatibility with older setuptools used in Python 3.8 editable-install CI jobs.

## [1.2.0] - 2026-02-10

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
- Ignore trailing zero padding between/after gzip members while continuing to read valid member payloads.

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
- Added `ty` as an additional static type checker in development tooling and CI, alongside existing `mypy` checks.
- Binary parity additions:
  - `closed` and `mtime` properties on `AsyncGzipBinaryFile`
  - `readline`, `readlines`, and `writelines` for binary streams
  - `isatty`, `detach`, and `truncate` methods for binary compatibility
  - async line iteration support for binary reads (`__aiter__` / `__anext__`)
- Text parity additions:
  - `encoding`, `errors`, `newlines`, and `buffer` properties on `AsyncGzipTextFile`
- New compatibility smoke tests for top-level exports and `__all__` stability.
- New micro-benchmark case for binary long-line `readline` under tiny chunk sizes.

### Changed

- Optimized binary `readline` internals to avoid repeated full-buffer copies in long-line/small-chunk scenarios.

### Refactor

- Split the core implementation into focused internal modules:
  - `aiogzip._common` (shared constants/helpers/protocols)
  - `aiogzip._binary` (`AsyncGzipBinaryFile`)
  - `aiogzip._text` (`AsyncGzipTextFile`)
- Kept `aiogzip.__init__` as the public API facade and explicit re-export surface.
- Removed unused internal text state and stale constants no longer used by the implementation.
- Added explicit internal export list (`__all__`) for `aiogzip._common`.

### Documentation

- Updated contributor docs with the new internal module layout and public API facade guidance.
- Clarified public-vs-internal module boundaries in the API reference docs.

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
