#!/usr/bin/env python3
"""Smoke an installed aiogzip wheel without importing the source checkout."""

from __future__ import annotations

import argparse
import asyncio
import gzip
import subprocess
import sys
import tempfile
from pathlib import Path

import aiogzip


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
    assert restored == payload

    await aiogzip.write(path, payload, mtime=0)
    assert await aiogzip.read(path) == payload
    info = await aiogzip.inspect(path)
    verified = await aiogzip.verify(path)
    assert info.member_count == verified.member_count == 1
    assert info.uncompressed_size == verified.uncompressed_size == len(payload)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--expect-fast", action="store_true")
    args = parser.parse_args()

    assert aiogzip.__version__ == args.expected_version
    assert "/src/aiogzip/" not in str(Path(aiogzip.__file__).resolve())
    assert not any(name.startswith("bench_") for name in sys.modules)

    payload = b"wheel smoke payload\n" * 100
    encoder = aiogzip.GzipEncoder(mtime=0, output_chunk_size=17)
    compressed = b"".join(encoder.start())
    compressed += b"".join(encoder.feed(payload))
    compressed += b"".join(encoder.finish())
    assert gzip.decompress(compressed) == payload

    decoder = aiogzip.GzipDecoder(output_chunk_size=19)
    restored = b"".join(decoder.feed(compressed)) + b"".join(decoder.finish())
    assert restored == payload

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "smoke.gz"
        asyncio.run(_smoke_async(path, payload))
        subprocess.run(
            [sys.executable, "-m", "aiogzip", "verify", str(path)],
            check=True,
            capture_output=True,
            text=True,
        )
    version = subprocess.run(
        [sys.executable, "-m", "aiogzip", "--version"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert version == args.expected_version

    engine = aiogzip.engine_info()
    if args.expect_fast:
        assert engine.decompression == "zlib-ng"
    print(
        f"aiogzip {aiogzip.__version__} smoke passed on "
        f"Python {sys.version_info.major}.{sys.version_info.minor} "
        f"with {engine.decompression}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
