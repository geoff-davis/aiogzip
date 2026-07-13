"""Codec engine selection for aiogzip.

Single source of truth for which deflate implementation backs compression and
decompression. ``zlib-ng`` is a *soft* dependency: when the ``aiogzip[fast]``
extra is installed it is used automatically for **decompression** (its output
is byte-identical to stdlib ``zlib``, so this is transparent) and, only when a
caller explicitly opts in, for **compression** (its compressed bytes differ
from stdlib, so it is never selected silently). When ``zlib-ng`` is not
installed every path falls back to stdlib ``zlib`` and aiogzip stays
pure-Python.

Set ``AIOGZIP_ENGINE=stdlib`` to force stdlib everywhere (useful for
reproducible error behaviour or debugging).
"""

import importlib
import os
import zlib
from dataclasses import dataclass
from typing import Any, Tuple, Type

from ._common import ZlibEngine


def _load_zng() -> Any:
    """Return the zlib-ng module, or None if the extra is not installed.

    Imported dynamically and typed as Any so neither mypy nor ty objects to the
    stub-less module; behaviour is identical to ``from zlib_ng import zlib_ng``.
    """
    try:
        return importlib.import_module("zlib_ng.zlib_ng")
    except ImportError:  # pragma: no cover - exercised in environments without it
        return None


_zng: Any = _load_zng()

# Whether stdlib has been forced via the environment escape hatch.
_FORCE_STDLIB = os.environ.get("AIOGZIP_ENGINE", "").strip().lower() == "stdlib"

# Whether zlib-ng is available *and* permitted as the active engine.
_HAVE_ZNG = _zng is not None and not _FORCE_STDLIB


@dataclass(frozen=True)
class EngineInfo:
    """Human-readable codec selections used by aiogzip by default."""

    compression: str
    decompression: str


# Errors raised by the deflate engines. zlib-ng's (and isal's) error type is
# NOT zlib.error nor a subclass of it, so callers that mean to catch decode
# failures must catch this tuple — otherwise a corrupt stream decoded by
# zlib-ng would leak an unwrapped foreign exception. zlib-ng's error is
# included whenever the module is importable (regardless of the force flag),
# since including an extra type in an ``except`` is harmless.
ZLIB_ERRORS: Tuple[Type[BaseException], ...]
if _zng is not None:
    ZLIB_ERRORS = (zlib.error, _zng.error)
else:
    ZLIB_ERRORS = (zlib.error,)

# crc32 stays on stdlib: the result is engine-independent, and pinning it
# avoids any surprise from a divergent implementation.
crc32 = zlib.crc32

# Re-export the constants _binary.py needs so it has a single import surface.
MAX_WBITS = zlib.MAX_WBITS
Z_SYNC_FLUSH = zlib.Z_SYNC_FLUSH


def decompressobj(wbits: int) -> ZlibEngine:
    """Return a decompressor: zlib-ng when available, else stdlib zlib.

    Decompressed output is byte-identical across engines, so this selection is
    transparent to callers.
    """
    if _HAVE_ZNG:
        return _zng.decompressobj(wbits=wbits)
    return zlib.decompressobj(wbits=wbits)


def compressobj(level: int, wbits: int, fast: bool = False) -> ZlibEngine:
    """Return a compressor.

    Stdlib ``zlib`` by default. ``zlib-ng`` is used only when ``fast`` is True
    *and* it is available, because its compressed output is not byte-identical
    to stdlib — installing the extra alone must not change produced ``.gz``
    bytes.
    """
    if fast and _HAVE_ZNG:
        return _zng.compressobj(level=level, wbits=wbits)
    return zlib.compressobj(level=level, wbits=wbits)


def have_fast_engine() -> bool:
    """True when zlib-ng is available and not disabled via the env escape hatch."""
    return _HAVE_ZNG


def decompress_engine_name() -> str:
    """Name of the engine backing decompression: ``"zlib-ng"`` or ``"stdlib"``."""
    return "zlib-ng" if _HAVE_ZNG else "stdlib"


def engine_info() -> EngineInfo:
    """Return the default compression and active decompression engines.

    Compression remains on stdlib zlib unless a writer opts into zlib-ng with
    ``fast_compress=True``. The returned strings are intended for diagnostics,
    not machine-readable feature detection.
    """
    return EngineInfo(
        compression="stdlib-zlib",
        decompression="zlib-ng" if _HAVE_ZNG else "stdlib-zlib",
    )
