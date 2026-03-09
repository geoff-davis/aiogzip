# Test Suite Refactor Plan

## Goals

- Reduce the maintenance cost of the current monolithic test layout.
- Make stdlib-parity coverage easier to review and extend.
- Preserve behavior while moving tests into smaller, coherent modules.
- Keep the suite green after each step so regressions are isolated quickly.

## Current State

- `tests/test_aiogzip.py` is the primary problem area at roughly 4,000 lines.
- Multiple classes define overlapping fixtures such as `temp_file`, `sample_data`, and `large_data`.
- Historical regression coverage exists, but it is mixed into broad feature files, which makes future parity reviews harder.
- The suite is fast today, so this should remain a structure-only refactor with no intentional behavior changes.

## Target Layout

- `tests/conftest.py`
  - shared fixtures and small test helpers
- `tests/test_factory_api.py`
  - `AsyncGzipFile` factory behavior and top-level mode mapping
- `tests/test_binary_io.py`
  - binary read/write, buffering, seeking, line APIs, new methods
- `tests/test_text_io.py`
  - text read/write, newline handling, text cookies, readline iteration
- `tests/test_fileobj.py`
  - `fileobj`, `closefd`, resource ownership, non-seekable wrappers
- `tests/test_interop.py`
  - stdlib gzip interop, tarfile patterns, metadata compatibility
- `tests/test_aiocsv.py`
  - aiocsv integration coverage
- `tests/test_protocols_and_paths.py`
  - protocols, pathlib, names, public compatibility flags
- `tests/test_regressions.py`
  - focused historical bug reproducers and parity edge cases
- `tests/test_edge_cases_and_errors.py`
  - keep as the narrow error-path file, but trim overlap where needed

## Execution Steps

1. Introduce `tests/conftest.py`
   - Move shared fixtures and `_parse_gzip_header_bytes`.
   - Update imports/fixture references and verify the full suite still passes.

2. Split the factory and binary coverage
   - Move `TestAsyncGzipFile` and `TestAsyncGzipBinaryFile` into dedicated files.
   - Keep imports local to the new files; remove moved content from `tests/test_aiogzip.py`.
   - Run targeted tests, then the full suite.

3. Split text-mode coverage
   - Move `TestAsyncGzipTextFile`, newline behavior, text error behavior, and cookie/seek tests.
   - Keep text-specific regression cases together so text parity is reviewable in one place.

4. Split file object, ownership, and cleanup coverage
   - Move `TestFileobjSupport`, `TestClosefdParameter`, and `TestResourceCleanup`.
   - Keep async-wrapper and ownership semantics together.

5. Split integration and compatibility coverage
   - Move aiocsv, tarfile, stdlib interop, pathlib, names, and protocols into focused files.

6. Consolidate regressions
   - Move narrow historical bug reproducers out of generic “priority” classes into `tests/test_regressions.py`.
   - Keep error-path tests in `tests/test_edge_cases_and_errors.py` where they remain genuinely error-focused.

7. Final cleanup
   - Delete or greatly reduce `tests/test_aiogzip.py`.
   - Run the full suite, fix any fixture/import fallout, and update contributor docs if the new layout needs a note.

## Guardrails

- Do not intentionally change runtime behavior as part of the refactor.
- Prefer moving whole test classes first; only split within a class when the grouping is already mixed.
- After each step:
  - run the relevant targeted tests
  - run the full suite
  - commit the refactor step independently

## Success Criteria

- The suite remains green after every step.
- No test coverage is lost.
- New contributors can find binary, text, fileobj, and regression coverage without searching a 4,000-line file.
