"""Engine-matched raw DEFLATE references for the stateful model.

Malformed DEFLATE has no cross-engine output bound, so a body-corruption
scenario is checked against the raw decompressor of the engine the leg
actually uses. A single ``decompress(body)`` call is not a reference: it
raises at the bad code and discards everything it inflated in that call. The
``raw-1in-1out/v1`` schedule instead feeds one compressed byte at a time and
drains with ``max_length=1``, so every byte the engine can inflate before the
bad code is captured.
"""

from __future__ import annotations

import importlib.util
import zlib
from types import ModuleType
from typing import Any

SCHEDULE = "raw-1in-1out/v1"


def engine_modules() -> dict[str, ModuleType]:
    """Raw decompressor modules available here, keyed by engine_info name."""
    modules: dict[str, ModuleType] = {"stdlib-zlib": zlib}
    if importlib.util.find_spec("zlib_ng") is not None:
        from zlib_ng import zlib_ng

        modules["zlib-ng"] = zlib_ng
    return modules


def raw_reference(module: ModuleType, body: bytes) -> dict[str, Any]:
    """Apply ``raw-1in-1out/v1`` to a raw DEFLATE ``body``.

    Returns the output of every successful call, the compressed offset of the
    byte whose feed raised (``None`` if no engine error) and the error text.
    """
    decompressor = module.decompressobj(-15)
    output = bytearray()
    for offset in range(len(body)):
        data = body[offset : offset + 1]
        try:
            while True:
                chunk = decompressor.decompress(data, 1)
                output += chunk
                data = decompressor.unconsumed_tail
                if not chunk and not data:
                    break
        except module.error as error:
            return {
                "schedule": SCHEDULE,
                "output": bytes(output),
                "error_offset": offset,
                "error": str(error),
            }
        if decompressor.eof:
            break
    return {
        "schedule": SCHEDULE,
        "output": bytes(output),
        "error_offset": None,
        "error": None,
    }
