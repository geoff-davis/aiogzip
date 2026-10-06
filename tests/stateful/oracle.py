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


WIRE_SCHEDULE = "wire-1in-1out/v1"
FHCRC, FEXTRA, FNAME, FCOMMENT = 0x02, 0x04, 0x08, 0x10


def _header_end(wire: bytes, start: int) -> tuple[int | None, str | None]:
    """The end of the RFC 1952 header at ``start``, or the failure stage.

    Returns ``(end, None)`` for a complete header, ``(None, "truncated")``
    when the wire ends inside it and ``(None, "invalid")`` for a header the
    decoder must refuse.
    """
    fixed = wire[start : start + 10]
    for size, valid in (
        (2, lambda: fixed[:2] == b"\x1f\x8b"),
        (3, lambda: fixed[2] == 8),
        (4, lambda: not fixed[3] & 0xE0),
    ):
        if len(fixed) < size:
            return None, "truncated"
        if not valid():
            return None, "invalid"
    if len(fixed) < 10:
        return None, "truncated"
    flags, pos = fixed[3], start + 10
    if flags & FEXTRA:
        if pos + 2 > len(wire):
            return None, "truncated"
        pos += 2 + int.from_bytes(wire[pos : pos + 2], "little")
        if pos > len(wire):
            return None, "truncated"
    for flag in (FNAME, FCOMMENT):
        if flags & flag:
            nul = wire.find(b"\0", pos)
            if nul < 0:
                return None, "truncated"
            pos = nul + 1
    if flags & FHCRC:
        if pos + 2 > len(wire):
            return None, "truncated"
        expected = int.from_bytes(wire[pos : pos + 2], "little")
        if zlib.crc32(wire[start:pos]) & 0xFFFF != expected:
            return None, "invalid"
        pos += 2
    return pos, None


def wire_reference(module: ModuleType, wire: bytes) -> dict[str, Any]:
    """Decode a whole gzip ``wire`` member by member, as ``wire-1in-1out/v1``.

    An independent model of the decoder's member loop: zero padding only
    after a completed member, an RFC 1952 header, each raw DEFLATE body
    through the engine's raw decompressor under ``raw-1in-1out/v1``, then the
    CRC32/ISIZE trailer. Returns every byte the members yield before the
    first failure, the bytes guaranteed before that failure is terminal
    (``validated``), the completed members' wire spans, and the failure stage,
    ``None`` when the wire ends cleanly.
    """
    output = bytearray()
    members: list[list[int]] = []
    pos, failure, validated = 0, None, 0
    while True:
        if members:
            while pos < len(wire) and wire[pos] == 0:
                pos += 1
        if pos == len(wire):
            break
        start = pos
        body_start, stage = _header_end(wire, start)
        if body_start is None:
            failure = f"header {stage}"
            break
        reference = raw_reference(module, wire[body_start:])
        output += reference["output"]
        if reference["error"] is not None:
            failure = "body invalid"
            break
        decompressor = module.decompressobj(-15)
        decompressor.decompress(wire[body_start:])
        if not decompressor.eof:
            failure = "body truncated"
            break
        trailer_start = len(wire) - len(decompressor.unused_data)
        trailer = wire[trailer_start : trailer_start + 8]
        if len(trailer) < 8:
            failure = "trailer truncated"
            break
        member_output = reference["output"]
        if zlib.crc32(member_output) != int.from_bytes(trailer[:4], "little"):
            failure, validated = "trailer crc", len(output)
            break
        if len(member_output) & 0xFFFFFFFF != int.from_bytes(trailer[4:], "little"):
            failure, validated = "trailer isize", len(output)
            break
        pos = trailer_start + 8
        members.append([start, pos])
        validated = len(output)
    return {
        "schedule": WIRE_SCHEDULE,
        "output": bytes(output),
        "validated": validated,
        "members": members,
        "failure": failure,
    }
