# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

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
