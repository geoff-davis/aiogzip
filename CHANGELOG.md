# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

## [1.11.0] - 2026-07-19

### Documentation

- New "Migrating from `gzip.open`" page: the exactly-three differences
  (`async with`, `async for`, `await` on reads/writes) with a before/after
  pair.
- New "Error handling" page documenting the exception taxonomy:
  `gzip.BadGzipFile` for corrupt data (normalized across engines), `OSError`
  for I/O failures, and a plain `OSError` — deliberately not `BadGzipFile`,
  and thus distinguishable by type — with a stable message prefix when
  `max_decompressed_size` is exceeded.
- New ADR recording the ISA-L (python-isal) evaluation and why it was not
  adopted, with revisit criteria.
- New "Gzip over S3 / fsspec" recipe for streaming via async `fileobj`s; the
  JSONL batching recipes and performance guide now use `iter_batches()`; new
  "When stdlib gzip is fine" section in the performance guide.

### Added

- `AsyncGzipTextFile.iter_batches(hint)`: first-class batched line iteration —
  `async for batch in f.iter_batches():` yields non-empty lists of complete
  lines, ending naturally at EOF. Implemented as a thin wrapper over the same
  internal drain as `readlines(hint)` so the two can never diverge; batching
  amortizes the per-line `await` of `async for line in f` (roughly 2x on
  line-dense files in the repo harness). The default hint is 1 MiB, chosen by
  interleaved min-of-N benchmark: throughput was flat from 256 KiB to ~1 MiB
  and slightly worse above 2 MiB. `hint` must be a positive integer,
  validated eagerly at the call.

- Using `with` or `for` on `AsyncGzipBinaryFile`/`AsyncGzipTextFile` now
  raises a corrective `TypeError` (e.g. "must be used with 'async with', not
  'with'") instead of the generic protocol errors, via `__enter__`/`__exit__`
  and `__iter__` stubs.

- `python -m aiogzip {inspect,verify} FILE`: a minimal command-line interface
  over the existing `inspect()`/`verify()` APIs. Human-readable output by
  default, `--json` for machine use (bytes fields hex-encoded); exit code 0
  on success, 1 for invalid or unreadable streams, 2 for usage errors.

- `EngineInfo` gained a `crc32` field reporting which engine backs the crc32
  selection (`"zlib-ng"` except on macOS or under `AIOGZIP_ENGINE=stdlib`,
  where it is `"stdlib-zlib"`). The field is defaulted so existing
  two-argument `EngineInfo(...)` construction keeps working.

### Changed

- Switched the git-hook runner from `pre-commit` to `prek`, a Rust drop-in
  replacement that reads the same `.pre-commit-config.yaml`. The `[dev]`
  extra now installs `prek` instead of `pre-commit`; reinstall hooks once
  per clone with `uv run prek install`. The `ruff` hook id was updated to
  its current name `ruff-check`.

## [1.10.2] - 2026-07-16

### Documentation

- Refreshed the benchmark tables and README performance summary from
  2026-07-16 Linux x86-64 reference runs at commit `ec931cd`, covering the
  line-splitting, LF-detection, and crc32 optimizations. The README
  comparison bullets now lead with the concurrency and accelerated-read
  results.

### Changed

- `crc32` now uses zlib-ng's SIMD implementation when the `aiogzip[fast]`
  extra is installed, except on macOS where Apple's hardware-accelerated
  stdlib zlib measured ~4x faster than zlib-ng (zlib-ng measured ~3.4x
  faster than stdlib on x86-64 Linux). CRC-32 output is fully specified and
  bit-identical across engines, so this affects only speed; the write path,
  streaming encoder, and inspection/verification all share the selection,
  and `AIOGZIP_ENGINE=stdlib` still forces stdlib everywhere.

- Batched text line splitting now uses C-level `str.splitlines(keepends=True)`
  when a cheap membership probe confirms the region contains none of the extra
  break characters `splitlines` recognizes (`\v`, `\f`, `\x1c`-`\x1e`, `\x85`,
  U+2028, U+2029), falling back to the keepends regex otherwise. Differentially
  verified against the regex splitter; `readlines()` batches measured ~30%
  faster and direct line iteration ~10-15% faster on LF-only fixtures, with
  no regression for CRLF-content or mixed input.
- The LF-only universal-newline fast path now probes for CR with an early-exit
  membership scan instead of a full `str.count()` pass (~16x cheaper on
  CR-free chunks), bringing bulk text reads on LF-only files to near parity
  with synchronous `gzip` under the stdlib engine. Mixed-newline tracking,
  translation, and chunk-boundary behavior are unchanged.

## [1.10.1] - 2026-07-13

### Changed

- Text `readlines()` now drains the reader's existing bounded line batches
  directly instead of awaiting `readline()` once per line. Hinted calls retain
  complete-line and text-position semantics while substantially reducing
  coroutine overhead for batch-oriented processing.
- Universal-newline text reads now recognize LF-only decoded chunks with one
  CR scan, avoiding repeated full-string CRLF/LF/CR counts while preserving
  mixed-newline tracking, translation, and chunk-boundary behavior.
- Comparative benchmarks now use deterministic data, identical compressed
  fixtures for reads, explicit compression level 6 for both writers, separate
  read/write timings, realistic size-scaled line workloads, and median results.
- JSON Lines benchmarks now isolate read-and-parse performance instead of
  folding unequal-default compression into the reported speedup.

### Documentation

- Corrected performance claims that previously described combined text
  read/write and JSON Lines timings as read-speed improvements. The README and
  performance guide now distinguish synchronous single-file overhead, async
  concurrency, and optional zlib-ng acceleration.
- Added a required before/after benchmark workflow for performance-sensitive
  changes, including engine-controlled runs and result comparison commands.

## [1.10.0] - 2026-07-13

### Added

- Added `aiogzip.open()` as the recommended typed package-level entry point.
  The existing `AsyncGzipFile()` factory remains fully supported and has
  identical behavior.
- Added asynchronous `aiogzip.read()` and `aiogzip.write()` helpers for small
  binary payloads that fit in memory.
- Added the immutable `EngineInfo` result and `engine_info()` diagnostic API,
  which report the default compression and active decompression engines.
- Added `aiogzip.inspect()` and `aiogzip.verify()` for complete gzip integrity
  scans that discard decompressed payload data, plus immutable
  `GzipMemberInfo`, `GzipInfo`, and `VerificationResult` result types.
- Added shared bounded-memory incremental gzip decoding internals with
  concatenated-member, metadata, CRC-32, `ISIZE`, and size-limit validation.
- Added `aiogzip.decompress_chunks()` for pull-driven, bounded-output gzip
  decompression from asynchronous byte iterables, including cumulative output
  limits and complete-stream integrity validation.
- Added `aiogzip.compress_chunks()` for pull-driven, bounded-output creation of
  one gzip member from asynchronous byte iterables, with existing compression,
  metadata, reproducibility, strict-size, and optional zlib-ng controls.
- Added a shared private incremental gzip encoder alongside the incremental
  decoder so iterable streaming uses the same header, trailer, engine,
  executor-offload, CRC-32, and `ISIZE` rules as file operations.

### Documentation

- Reorganized the README around installation and immediate text/binary
  quickstarts, with detailed operational behavior moved later.
- Added a migration guide for users of standard-library `gzip` and a focused
  recipes page covering JSON Lines, untrusted input, reproducible output,
  append mode, seeking, cancellation, and external async file objects.
- Added an async-iterable streaming guide covering backpressure, validation
  timing, untrusted-input limits, reproducible compression, cancellation,
  incomplete-output handling, direct pipelines, and early exit.

### Security

- Complete-stream decompression APIs share cumulative decompressed-size limits
  that cap every inflate call to the remaining allowance plus one byte.
  Iterable compression and decompression retain bounded codec/parser state and
  do not introduce producer tasks or unbounded queues.

### Maintenance

- Dependabot now preserves compatible lower bounds for pip requirements and
  limits uv updates to `uv.lock`, preventing grouped updates from dropping
  supported Python versions or rewriting build metadata. Ruff remains a
  manual paired update with its pre-commit hook revision.

### Packaging

- Switched the build backend from setuptools to `flit_core` so source builds
  keep working on Python 3.8 while adopting modern PEP 639 metadata. The
  project now publishes an SPDX `MIT` license expression and explicit license
  file without deprecated license classifiers or build warnings.

## [1.9.1] - 2026-07-09

### Fixed

- `max_decompressed_size` now bounds each inflate call to the remaining
  allowance plus one byte instead of checking only after zlib returned its full
  output. Highly compressible untrusted input can no longer allocate its entire
  expansion before the decompression-bomb guard raises `OSError`.
- A failed write of `flush()` output now marks the compressor stream broken.
  Follow-up writes are rejected and `close()` does not append a misleading
  final block or trailer to an already torn gzip member.
- Text writers now keep one incremental encoder across `write()` calls and
  finalize it before closing the gzip member. Stateful encodings such as
  UTF-16 and ISO-2022-JP no longer emit repeated BOMs or reset sequences when a
  document is written in multiple calls.
- Cancelling a read while decompression is running in the executor now marks
  that reader unusable. The worker thread may still advance its zlib state, so
  subsequent reads and seeks raise `OSError` instead of risking skipped or
  corrupted output; close the handle and reopen the gzip file to continue.
- Short writes from external `fileobj` sinks are now retried until every gzip
  header, compressed block, flush block, and trailer byte has been accepted.
  Zero-progress and invalid write counts raise `OSError` instead of silently
  producing a truncated or malformed archive.
- `chunk_size`, `compresslevel`, `max_decompressed_size`, and
  `max_rewind_cache_size` now reject floats, strings, and booleans immediately
  with `TypeError` instead of failing later inside slicing, file I/O, or zlib.

### Performance

- Binary and text `writelines()` now combine small inputs into bounded batches
  before encoding/compression, reducing coroutine and compressor-call overhead
  while preserving streaming behavior for large inputs and failing iterators.

### Maintenance

- The fast text-line refill path now has a narrow first-line helper and asserts
  that general pending consumption already happened in the two intentionally
  inlined hot paths, removing redundant pending-state handling without adding a
  per-line function call.
- The benchmark runner now executes each category three times by default and
  reports median durations with metrics from the closest real sample. Use
  `--repeat` to tune stability versus runtime. Removed an unused mypy override
  that produced a configuration warning on every source-only type check.

### Documentation

- Clarified that `max_decompressed_size` bounds individual inflate output and
  documented continuous incremental encoding for text writers.
- Documented bounded `writelines()` batching and strict integer-only tuning
  parameters.

## [1.9.0] - 2026-07-02

### Announced

- The 1.x line is the last to support Python 3.8 and 3.9 (both past
  end-of-life; together ~0.35% of downloads over the last 180 days).
  aiogzip 2.0 will require Python 3.11+. Older interpreters keep resolving
  the latest 1.x release via the `requires-python` metadata.

### Fixed

- A task cancelled during `open()` (e.g. mid header write) left the instance
  wedged — the handle leaked and every retry raised "File is already open".
  The open-failure cleanup now runs for `BaseException`, so a cancelled open
  is retryable exactly like a failed one, in both classes.
- Operations before `open()` now say "File not opened. Call await open() or
  use async with." — the old message only mentioned the context manager.
- `readline(limit)` with a limit below -1 corrupted the read position: the binary fast path could move the buffer offset backwards and re-serve already-consumed bytes, and the text path drove the buffer offset negative so subsequent reads returned empty strings. Any negative limit now means "no limit", matching `io.IOBase`.
- Reading a zero-byte file raised `BadGzipFile` ("truncated") where `gzip.open()` returns empty output. Truncation is now reported only when a gzip member actually started. Files that end mid-member still raise.
- `seek()`, `tell()`, `rewind()`, `readinto()` and `readinto1()` on a closed file now raise `ValueError` like `read()`/`peek()`; previously `seek()` silently succeeded.
- `flush()` on a writer whose stream was broken by a prior write failure now raises `OSError` instead of silently returning as if the data were flushed.
- Cancelling a `write()` while it awaits the offloaded zlib compress now marks the stream broken — the executor thread may still consume the input, so continuing to write could silently produce a torn member.
- `fileno()` no longer leaks an un-awaited coroutine (RuntimeWarning) when the underlying file's `fileno` is async.

### Added

- `AsyncGzipTextFile` file-API parity with the binary class: `mtime`, `isatty()`, `detach()`, `truncate()`; `seekable()` now delegates to the binary layer instead of returning a constant `True`.

### Packaging

- PyPI metadata now carries the MIT license classifier, Documentation and
  Changelog URLs, and keywords; sdists have deterministic contents via
  MANIFEST.in and include CHANGELOG.md/SECURITY.md. Publishing is gated on
  a test run and a tag-vs-version check.

### Documentation

- Corrected the text `seek()`/`tell()` docs: plain-offset seeks replay only
  the forward delta when possible (not always "from the start"), and
  `tell()` returns a plain offset at clean boundaries, a cookie otherwise.

## [1.8.0] - 2026-06-10

### Added

- Public `open()` method on `AsyncGzipBinaryFile` and `AsyncGzipTextFile` for the explicit try/finally lifecycle; `__aenter__` now delegates to it. Calling `open()` on an already-open file raises `ValueError`, and a closed instance cannot be reopened (matching io objects). A failed `open()` (e.g. a transient write error on an external `fileobj`) leaves the instance retryable instead of half-open.
- `__repr__` on both file classes showing the name, mode, and closed state. The repr is safe even on partially-constructed instances, so debuggers and locals-capturing traceback formatters get a usable string instead of `AttributeError`.
- Typing overloads on the `AsyncGzipFile` factory so the return type narrows to `AsyncGzipBinaryFile` or `AsyncGzipTextFile` from the mode literal.

### Fixed

- Text-mode forward `seek()` no longer corrupts decoder state when bytes were consumed directly from the public `buffer` accessor: the fast path now tracks the decoder's byte frontier and falls back to a full replay when the binary position has moved past it (previously `UnicodeDecodeError`, or silent corruption with error-tolerant encodings).
- `readinto()`/`readinto1()` accept any writable buffer, including those with itemsize > 1 such as `array.array`, filling them and returning byte counts exactly like stdlib gzip.
- `readinto()` fills its internal buffer before consuming, so a decompression error mid-request leaves the stream position and already-decoded data intact for salvage, matching `read()`.
- `readinto1()` and `read1()` repeat fills until at least one byte decodes, so a `0`/`b""` result now means EOF (a single fill can consume compressed input, e.g. the gzip header, without producing output); `while await f.readinto1(buf): ...` loops are safe.
- `peek()` on a closed file raises `ValueError("I/O operation on closed file.")` like the other read methods, and `readinto1()`'s writable-buffer `TypeError` names the right method.

### Performance

- `readinto()`/`readinto1()` write decompressed data straight into the caller's buffer instead of allocating an intermediate `bytes` object.
- Forward plain-offset text seeks replay only the delta from the current position instead of restarting decompression from byte 0 — including when decoded read-ahead is buffered, since the buffer is discarded by the seek anyway.
- Universal-newline detection counts terminators with windowed `str.count` instead of `replace()`-based scans, eliminating two chunk-sized string allocations per chunk on CRLF streams.

### Documentation

- Documented that text `tell()` cookies are bound to the handle that minted them, and added the resumable-processing recipe: checkpoint plain decompressed-byte offsets at line boundaries via the binary layer, then resume by seeking in text mode. `docs/api.md` summarizes and links to the canonical recipe in `docs/index.md`.

### Testing

- Hypothesis property-based parity suite against stdlib gzip: randomized multi-member archives are read through both libraries in lockstep across access patterns, and single-byte corruption must be detected identically — aiogzip may be stricter than stdlib only for reserved FLG-bit flips, which zlib rejects and stdlib's header parser ignores.

## [1.7.0] - 2026-06-01

### Added

- Optional `aiogzip[fast]` extra that installs [`zlib-ng`](https://pypi.org/project/zlib-ng/). When present, **decompression** automatically uses zlib-ng, which is faster (~1.6–2x on typical data) and produces byte-identical output to stdlib `zlib`. Set the environment variable `AIOGZIP_ENGINE=stdlib` to force stdlib regardless of what is installed. When the extra is not installed, aiogzip remains pure-Python and behaves exactly as before.
- `fast_compress=True` option on `AsyncGzipBinaryFile`, `AsyncGzipTextFile`, and the `AsyncGzipFile` factory to opt into zlib-ng for **compression** (~1.2–1.4x). Compression stays on stdlib `zlib` by default because zlib-ng's compressed output is not byte-identical — installing the extra alone does not change produced `.gz` bytes. If `fast_compress=True` is requested without zlib-ng installed, it warns once and falls back to stdlib. zlib-ng output remains valid gzip readable by any decompressor.

### Performance

- Line iteration in `AsyncGzipTextFile` (`async for` / `readline()`) is faster for the single-character newline modes (`None`, `"\n"`, `"\r"`): each decoded chunk's complete lines are bulk-split in one pass and served from a batch instead of scanned one at a time. ~1.3x for `async for` and ~1.16x for `readline()` loops; the batch is capped per refill so a large `chunk_size` does not increase peak memory unboundedly.

## [1.6.0] - 2026-05-28

### Changed

- The default `chunk_size` for `AsyncGzipBinaryFile` and `AsyncGzipTextFile` is now **256 KiB** (was 64 KiB). This improves bulk-read throughput (~1.3–1.6x) and lets CPU-bound `zlib` work offload to a thread by default, at the cost of more buffer memory per open file. Pass `chunk_size=64*1024` to restore the previous footprint.
- CI now runs on Windows and macOS in addition to Linux, and enforces a coverage floor. Fixed the mypy configuration for newer mypy releases.

### Performance

- Bulk `read(-1)` no longer copies decompressed output through an intermediate buffer, speeding up full-file reads (notably for compressible data).
- Text `read(size)` and long-line `readline()`/iteration are now O(n) instead of O(n^2) for large reads.

### Documentation

- Documented that an open file is not safe for concurrent use by multiple tasks (use one file object per task).
- Refreshed the performance guide for the new 256 KiB default and current benchmark numbers.

## [1.5.0] - 2026-04-23

### Added

- Add `max_rewind_cache_size` to `AsyncGzipBinaryFile` and `AsyncGzipTextFile`. Non-seekable read streams now retain at most 128 MiB of compressed input by default for backward-seek replay; pass a byte limit to tune the cap or `None` to preserve the previous unbounded cache behavior.

### Fixed

- Ensure `AsyncGzipTextFile.close()` does not finalize partially read decoder state. Closing after a partial multibyte read no longer raises `UnicodeDecodeError` or skips closing the underlying binary stream.
- Ensure `AsyncGzipBinaryFile.close()` still closes owned or `closefd=True` file objects when final compressor flush or trailer writes fail.
- Reject embedded NUL bytes in `original_filename`, which previously produced malformed gzip headers and unreadable archives.
- Reset `max_decompressed_size` accounting when a reader rewinds, so re-reading an otherwise under-cap archive after `seek(0)` no longer trips the cap.
- Treat file objects that report `seekable() == False` as non-seekable even if they expose a `seek()` method, using replay caching instead of calling a failing seek.

### Changed

- Keep underscore-prefixed implementation helpers out of the top-level `aiogzip.__all__`; import internals from `aiogzip._common`, `aiogzip._binary`, or `aiogzip._text` only for unsupported internal testing/debugging.
- Broaden `fileobj` constructor type annotations to accept read-only objects in read mode and write-only objects in write mode.
- Use `asyncio.get_running_loop()` for executor dispatch in zlib offload paths.

### Documentation

- Document bounded rewind-cache behavior for non-seekable streams and clarify the 128 MiB `chunk_size` cap.

### Tooling

- Run the Python 3.8 syntax-compatibility guard in CI, not just pre-commit.
- Run `twine check dist/*` in the publish workflow before uploading artifacts.

## [1.4.0] - 2026-04-16

### Added

- New `max_decompressed_size` keyword on `AsyncGzipBinaryFile` and `AsyncGzipTextFile`: when set, reads abort with `OSError` once the cumulative decompressed output exceeds the cap. Intended as a decompression-bomb guard for untrusted input.
- New `strict_size` keyword on `AsyncGzipBinaryFile` and `AsyncGzipTextFile`: when true, writes that would push the uncompressed member size past the gzip `ISIZE` field's 4 GiB limit raise `OSError` instead of producing a trailer with a silently-truncated size. Default remains false so spec-compliant wrapping (matching `gzip.open()`) is preserved.

### Fixed

- Detect truncated gzip streams. A member that ended before the decompressor consumed its trailer previously caused `read()` and `seek(0, SEEK_END)` to silently return the partial bytes already emitted. Both paths now raise `gzip.BadGzipFile`. **Behavior change:** callers that were (often unknowingly) relying on silent truncation will now see an exception — this is a data-integrity fix.
- Keep write accounting consistent after a failed underlying `write()`. `_crc`, `_input_size`, and `_position` now update only after the compressed bytes are durably handed to the file object, and the CRC accumulator is explicitly masked to 32 bits. A mid-write `OSError` marks the stream broken so follow-up writes refuse rather than silently producing a torn gzip member, and `close()` skips emitting a trailer that would lie about bytes never written.
- `_cleanup_failed_enter` now nulls `_file` in a `finally` block, so a raising close during setup-failure cleanup no longer leaves a reachable handle on the instance.
- Add an upper bound (128 MiB) to `_validate_chunk_size` and to `AsyncGzipBinaryFile.peek(size=…)`, so a caller passing an unsanitized integer cannot accidentally allocate gigabytes of buffer.

### Performance

- Offload `zlib` compress/decompress calls to the default executor when the input is ≥ 256 KiB. `zlib` releases the GIL internally, so multiple gzip streams on the same event loop now run their CPU work in parallel. The repo's concurrent-I/O benchmark improves ~4x; single-stream latency is unchanged within noise.

### Documentation

- README now describes append-mode multi-member semantics, backward-seek cost, the 4 GiB `ISIZE` caveat (and `strict_size`), and `max_decompressed_size` as a decompression-bomb guard.

### Tooling

- Add a `scripts/check_py38_compat.py` pre-commit hook that rejects PEP 585 generic subscripts (`tuple[...]`, `list[...]`, `PathLike[...]`, ...) and PEP 604 union operators in `src/`. `mypy` ≥ 1.15 no longer accepts `python_version = "3.8"`, so this grep-based check guards the library's declared Python 3.8+ support.
- `/release-prep` skill now refuses to run when the current branch has commits ahead of `origin/main` that are not yet merged, preventing silent exclusion of feature work from the release.

## [1.3.3] - 2026-04-14

### Added

- Add `/release-prep` and `/release-tag` Claude Code skills to streamline the release process.

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
