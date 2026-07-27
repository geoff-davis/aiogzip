#!/usr/bin/env python3
"""Smoke an installed aiogzip wheel without importing the source checkout."""

from __future__ import annotations

import argparse
import asyncio
import gzip
import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path, PurePath

import aiogzip


def _require(condition: bool, message: str) -> None:
    """Fail the release smoke even when Python runs with optimization enabled."""
    if not condition:
        raise RuntimeError(message)


def _is_source_checkout(module_path: PurePath) -> bool:
    parts = tuple(part.casefold() for part in module_path.parts)
    return any(
        parts[index : index + 2] == ("src", "aiogzip")
        for index in range(len(parts) - 1)
    )


async def _items(*values: bytes):
    for value in values:
        yield value


async def _smoke_async(path: Path, payload: bytes) -> None:
    compressed = b"".join(
        [
            chunk
            async for chunk in aiogzip.compress_chunks(
                _items(payload[:17], payload[17:]),
                mtime=0,
                output_chunk_size=11,
            )
        ]
    )
    restored = b"".join(
        [
            chunk
            async for chunk in aiogzip.decompress_chunks(
                _items(compressed[:7], compressed[7:]),
                output_chunk_size=13,
            )
        ]
    )
    _require(restored == payload, "async chunk round-trip mismatch")

    await aiogzip.write(path, payload, mtime=0)
    _require(await aiogzip.read(path) == payload, "async file round-trip mismatch")
    info = await aiogzip.inspect(path)
    verified = await aiogzip.verify(path)
    _require(
        info.member_count == verified.member_count == 1,
        "inspect/verify member-count mismatch",
    )
    _require(
        info.uncompressed_size == verified.uncompressed_size == len(payload),
        "inspect/verify uncompressed-size mismatch",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--expect-fast", action="store_true")
    args = parser.parse_args()

    _require(
        aiogzip.__version__ == args.expected_version,
        f"version mismatch: {aiogzip.__version__!r} != {args.expected_version!r}",
    )
    package_path = Path(aiogzip.__file__).resolve()
    _require(
        not _is_source_checkout(package_path),
        f"imported aiogzip from source checkout: {package_path}",
    )
    _require(
        importlib.util.find_spec("bench_common") is None,
        "benchmark module bench_common is importable from the wheel environment",
    )

    payload = b"wheel smoke payload\n" * 100
    encoder = aiogzip.GzipEncoder(mtime=0, output_chunk_size=17)
    compressed = b"".join(encoder.start())
    compressed += b"".join(encoder.feed(payload))
    compressed += b"".join(encoder.finish())
    _require(gzip.decompress(compressed) == payload, "sync encoder round-trip mismatch")

    decoder = aiogzip.GzipDecoder(output_chunk_size=19)
    restored = b"".join(decoder.feed(compressed)) + b"".join(decoder.finish())
    _require(restored == payload, "sync decoder round-trip mismatch")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "smoke.gz"
        asyncio.run(_smoke_async(path, payload))
        subprocess.run(
            [sys.executable, "-m", "aiogzip", "verify", str(path)],
            check=True,
        )
    version = subprocess.run(
        [sys.executable, "-m", "aiogzip", "--version"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    _require(
        version == args.expected_version,
        f"CLI version mismatch: {version!r} != {args.expected_version!r}",
    )

    engine = aiogzip.engine_info()
    if args.expect_fast:
        _require(
            engine.decompression == "zlib-ng",
            f"expected zlib-ng decompression, got {engine.decompression!r}",
        )
    print(
        f"aiogzip {aiogzip.__version__} smoke passed on "
        f"Python {sys.version_info.major}.{sys.version_info.minor} "
        f"with {engine.decompression}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
