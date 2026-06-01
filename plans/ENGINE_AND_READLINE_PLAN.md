# Engine Abstraction + zlib-ng + Batched Readline Plan

## Context

A benchmark/profiling spike (2026-06-01) asked whether aiogzip's throughput
could be raised via a faster codec (zlib-ng / isal) or a native (Rust/Cython)
rewrite. Findings:

- **Bulk binary compress/decompress is ~99% native zlib C time** — the Python
  orchestration is a rounding error, so a native rewrite of those paths gains
  nothing. The only lever is a faster codec.
- **zlib-ng** gives ~1.2–1.4x compress and ~1.6–2x decompress on realistic
  data at level 6, with output-size parity. Decompressed bytes are
  **byte-identical** across engines; compressed bytes are **not**.
- **isal** is faster still but worse ratio and capped at level ≤3 → shelved.
- **Text line-iteration is ~90% Python** (per-line function-call overhead), and
  a batched `splitlines`-style approach measured **~2.8x** (153 → 430 MB/s) on
  16 MiB, in pure Python with no new dependency. Realistically ~2–2.5x once
  full incremental decode + newline translation are preserved.

This plan implements three changes that share one engine-abstraction
foundation:

1. **zlib-ng for decompression, automatic when installed** (lossless, no output
   change — decompressed bytes are identical regardless of engine).
2. **zlib-ng for compression, explicit opt-in** via an `aiogzip[fast]` extra +
   per-file flag (compressed bytes differ, so never silent).
3. **Pure-Python batched readline** for the text path (~2–2.5x line iteration).

Goal: keep aiogzip pure-Python-installable (zlib-ng is a *soft* dependency,
never required), keep default `.gz` output byte-stable, and preserve all
existing newline / Unicode / error-handling guarantees (see `CLAUDE.md`).

## Critical gotcha (applies to 1 & 2)

`zlib_ng.error` and `isal_zlib.error` are **not** `zlib.error` and **not**
subclasses of it (verified). The library wraps `except zlib.error` → `OSError`
at `_binary.py:658, 832, 885, 1071`. If decompression silently uses zlib-ng,
a corrupt stream would raise `zlib_ng.error`, bypass those handlers, and leak
an unwrapped foreign exception instead of the documented `OSError`. **Every**
`except zlib.error` site must catch a tuple that includes the active engine's
error type. Corrupt-input tests must run against the zlib-ng path.

---

## Phase 1 — Engine abstraction + zlib-ng decompression (default when present)

### New module: `src/aiogzip/_engine.py`

Single source of truth for codec selection. Soft-detects zlib-ng at import:

```python
import os
import zlib
from typing import Optional, Tuple

try:
    from zlib_ng import zlib_ng as _zng  # type: ignore
except ImportError:  # pragma: no cover - exercised by env without the extra
    _zng = None

# Escape hatch: AIOGZIP_ENGINE=stdlib forces stdlib everywhere (repro/debug).
_FORCE_STDLIB = os.environ.get("AIOGZIP_ENGINE", "").lower() == "stdlib"
_HAVE_ZNG = _zng is not None and not _FORCE_STDLIB

# Errors to catch around decompress/compress/flush calls.
ZLIB_ERRORS: Tuple[type, ...] = (
    (zlib.error,) + ((_zng.error,) if _zng is not None else ())
)

# crc32 stays on stdlib: engine-independent result, avoids any surprise.
crc32 = zlib.crc32
MAX_WBITS = zlib.MAX_WBITS
Z_SYNC_FLUSH = zlib.Z_SYNC_FLUSH


def decompressobj(wbits: int):
    """zlib-ng when available (identical output), else stdlib."""
    return (_zng if _HAVE_ZNG else zlib).decompressobj(wbits=wbits)


def compressobj(level: int, wbits: int, fast: bool = False):
    """stdlib by default; zlib-ng only when fast=True AND available.

    Installing the [fast] extra alone must NOT change compressed output, so
    compression stays on stdlib unless the caller explicitly opts in.
    """
    engine = _zng if (fast and _HAVE_ZNG) else zlib
    return engine.compressobj(level=level, wbits=wbits)


def decompress_engine_name() -> str:
    return "zlib-ng" if _HAVE_ZNG else "stdlib"
```

Notes:

- Keep `Tuple` from `typing` (Python 3.8 — see `CLAUDE.md`).
- `crc32`/`MAX_WBITS`/`Z_SYNC_FLUSH` re-exported so `_binary.py` has a single
  import surface.

### Edits to `src/aiogzip/_binary.py`

- Replace `import zlib` usage with `from . import _engine` (keep `import zlib`
  only if still needed for bare constants; prefer routing through `_engine`).
- `_binary.py:239, 874, 957` (`zlib.decompressobj(wbits=GZIP_WBITS)`)
  → `_engine.decompressobj(GZIP_WBITS)`.
- `_binary.py:225-226` (compressobj) → `_engine.compressobj(self._compresslevel,
  -_engine.MAX_WBITS, fast=self._fast_compress)` — `_fast_compress` wired in
  Phase 2; default `False` so Phase 1 is behavior-neutral for compression.
- `_binary.py:658, 832, 885, 1071` (`except zlib.error`) →
  `except _engine.ZLIB_ERRORS`. Preserve the `raise OSError(...) from e`
  chaining (CLAUDE.md).
- `_binary.py:675` `zlib.crc32` → `_engine.crc32`.
- `_binary.py:1061` `zlib.Z_SYNC_FLUSH` → `_engine.Z_SYNC_FLUSH`.

### Tests (`tests/`)

- New `tests/test_engine.py`: engine selection (present/absent/forced),
  `ZLIB_ERRORS` membership, cross-engine inflate equals stdlib output.
- Parametrize existing decompression + corrupt-stream tests over engine using
  `AIOGZIP_ENGINE` (or by monkeypatching `_engine._HAVE_ZNG`) so the zlib-ng
  decode path and its error wrapping are both exercised. Especially the
  decompression-bomb / `max_decompressed_size` / `strict_size` paths — they
  operate on output bytes so should be engine-independent; assert that.

### Packaging (`pyproject.toml`)

- Add optional extra: `[project.optional-dependencies] fast = ["zlib-ng>=0.4"]`.
  Core install stays pure-Python (no new required deps).

---

## Phase 2 — Opt-in zlib-ng compression (`aiogzip[fast]`)

Builds directly on Phase 1's `_engine.compressobj(..., fast=...)`.

### Opt-in mechanism

- Add `fast_compress: bool = False` to `AsyncGzipBinaryFile.__init__`
  (`_binary.py:133`) and `AsyncGzipTextFile.__init__` (`_text.py:104`), and
  thread it through the `AsyncGzipFile` factory `**kwargs` (already pass-through
  at `__init__.py:25`). Store as `self._fast_compress`.
- Only consulted in write/append modes; ignored for read modes.
- If `fast_compress=True` but zlib-ng is absent, fall back to stdlib silently
  and emit a one-time `warnings.warn(...)` (so behavior stays correct without
  the extra; the warning tells users to `pip install aiogzip[fast]`).

### Why a flag and not just "use zlib-ng if installed"

Decompression auto-uses zlib-ng because output is identical. Compression must
stay opt-in because compressed bytes differ from stdlib — anyone hashing or
content-addressing `.gz` output must get byte-stable defaults unless they ask
otherwise.

### Tests

- Round-trip with `fast_compress=True` under zlib-ng → `gzip.decompress` reads
  it back identically (interop holds; bytes need not match stdlib).
- `fast_compress=True` without zlib-ng → falls back, warns once, still correct.
- Confirm default (`fast_compress=False`) output is byte-identical to current
  stdlib output (regression guard on determinism).

### Docs

- README/CHANGELOG: document the extra, the ~1.2–1.4x expectation (not "4x"),
  and the explicit non-byte-identical-output caveat.

---

## Phase 3 — Batched pure-Python readline (text path)

Most delicate; **no new dependency**, gated behind the full text suite.

### Current shape (`src/aiogzip/_text.py`)

Per-line: `__anext__` (972) → `_readline_fast` (926) → `_find_line_terminator`
(789) + `_consume_buffer` (436), with `_apply_newline_decoding` (850) handling
universal-newline translation and `_trailing_cr` (CRLF-across-chunk) state.
~266k calls each per 16 MiB → the overhead the profile flagged.

### Approach

Maintain a pre-split line buffer (e.g. `self._pending_lines: List[str]` +
index, or a `collections.deque`). `_readline_fast`/`__anext__` pop from it;
when empty, decode the next chunk via the existing `_decode_next_chunk` (657)

- `_apply_newline_decoding` (850), then split the translated text into lines in
one batch and carry the trailing partial line forward.

### Correctness constraints (do NOT regress)

- **Do not use `str.splitlines()`** — it splits on the full Unicode line-
  boundary set (`\v`, `\f`, `\x1c`, `\x85`, …). Text-file readline must split
  only on the terminators `_find_line_terminator` recognizes (`\n`, and `\r` /
  `\r\n` per `newline` mode). The spike's `splitlines` ceiling matched counts
  only because the ASCII test data had no such chars. The real split must
  mirror `_find_line_terminator`'s terminator set (e.g. `text.split("\n")` with
  keepends reconstruction after universal translation, or an explicit
  terminator-aware batch splitter reusing the existing helper).
- Preserve `newline` semantics for all of `None` (universal), `""`, `"\n"`,
  `"\r"`, `"\r\n"`, and the `_trailing_cr` / `_buffer_origin_trailing_cr` state
  across chunk boundaries.
- Preserve `readline(limit=...)` and `readlines(hint=...)` semantics
  (`_text.py:1000, 1063`).
- Keep incremental UTF-8/multibyte decoding via the existing
  `codecs.getincrementaldecoder` decoder (175) so multibyte chars split across
  chunks still work.

### Tests

- The entire text suite must stay green, especially `TestNewlineHandlingBugs`
  and the text-cookie / partial-line cases.
- Add data with embedded `\v`/`\f`/`\x85` to prove we did *not* introduce
  `splitlines`-style over-splitting.
- Add a benchmark assertion-free check (or a `benchmarks/` entry) showing the
  line-iteration speedup, to document the gain.

---

## Cross-cutting

- **Python 3.8**: use `typing.Tuple/List/Optional`; no PEP 585/604. Run the
  `grep` checks from `CLAUDE.md` before committing.
- **CI**: add a job (or matrix axis) that installs `.[fast]` so both the
  stdlib and zlib-ng paths are tested. zlib-ng wheel availability across
  3.8–3.14 × {Linux, macOS, Windows} should be confirmed; the soft-dependency
  design means any version lacking a wheel simply runs on stdlib (acceptable).
- **Coverage**: keep ≥85% (`--cov-fail-under=85`). New `_engine.py` branches
  (present/absent/forced) need coverage from both real and monkeypatched runs.
- **Determinism**: a regression test asserting default compressed output equals
  the current stdlib bytes guards against accidental engine bleed-through.

## Ordering / rollout

1. **Phase 1** first — self-contained, behavior-neutral for compression, ships
   the highest-value/lowest-risk win (free decompression speedup) and lays the
   `_engine.py` plumbing. The error-tuple fix is mandatory here.
2. **Phase 2** next — small delta on top of Phase 1 (one flag + extra + docs).
3. **Phase 3** last and independently — no dependency on 1/2; highest test risk;
   ship only behind a fully green text suite. Can be deferred/dropped without
   affecting 1–2.

## Verification

- `pytest --cov --cov-report=term-missing` green at ≥85%, run **twice**: once
  with zlib-ng absent (or `AIOGZIP_ENGINE=stdlib`) and once with `.[fast]`
  installed.
- `python -c "from aiogzip._engine import decompress_engine_name; print(decompress_engine_name())"`
  reports `zlib-ng` when the extra is installed, `stdlib` otherwise.
- Interop: for both engines, `gzip.decompress(aiogzip_output) == original` and
  aiogzip reads stdlib-`gzip.compress` output back identically.
- Re-run the codec + readline benchmarks (recreate the spike scripts) to
  confirm the measured ~2x decompress and ~2–2.5x line-iteration gains land.
