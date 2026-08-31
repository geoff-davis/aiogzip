#!/usr/bin/env python3
"""Exercise an installed aiogzip wheel or sdist-built installation."""

from __future__ import annotations

import argparse
import asyncio
import gzip
import hashlib
import importlib.metadata
import importlib.util
import json
import platform
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from collections.abc import AsyncIterator, Sequence
from pathlib import Path, PurePath
from typing import Any

import aiogzip


def _require(condition: bool, message: str) -> None:
    """Fail the smoke even when Python runs with optimization enabled."""
    if not condition:
        raise RuntimeError(message)


def _is_source_checkout(module_path: PurePath) -> bool:
    parts = tuple(part.casefold() for part in module_path.parts)
    return any(
        parts[index : index + 2] == ("src", "aiogzip")
        for index in range(len(parts) - 1)
    )


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _compact_requirement(requirement: str) -> str:
    return "".join(requirement.split()).replace('"', "'")


def declared_requirements() -> tuple[str, ...]:
    requirements = importlib.metadata.requires("aiogzip") or []
    return tuple(sorted(_compact_requirement(item) for item in requirements))


def validate_declared_requirements() -> tuple[str, ...]:
    requirements = declared_requirements()
    mandatory = tuple(item for item in requirements if ";" not in item)
    _require(
        mandatory == ("aiofiles>=23.2.1",),
        f"unexpected mandatory requirements: {mandatory!r}",
    )
    for expected in (
        "aiocsv>=1.2.3;extra=='csv'",
        "zlib-ng>=0.4.0;extra=='fast'",
    ):
        _require(expected in requirements, f"missing declared requirement: {expected}")
    return requirements


def artifact_inventory(path: Path, kind: str) -> tuple[str, ...]:
    if kind == "wheel":
        with zipfile.ZipFile(path) as archive:
            return tuple(sorted(archive.namelist()))
    if kind == "sdist":
        with tarfile.open(path, "r:gz") as archive:
            return tuple(sorted(member.name for member in archive.getmembers()))
    raise ValueError(f"unsupported artifact kind: {kind}")


def validate_artifact_layout(path: Path, kind: str) -> tuple[str, ...]:
    inventory = artifact_inventory(path, kind)
    if kind == "wheel":
        unexpected = [
            name
            for name in inventory
            if name.startswith("examples/") or "/examples/" in name.casefold()
        ]
        _require(
            not unexpected,
            f"wheel unexpectedly installs example files: {unexpected!r}",
        )
        _require(
            any(name == "aiogzip/__init__.py" for name in inventory),
            "wheel does not contain aiogzip/__init__.py",
        )
    else:
        required_suffixes = (
            "/examples/README.md",
            "/examples/fragmented_transport.py",
            "/examples/concurrent_jsonl_ingest.py",
        )
        for suffix in required_suffixes:
            _require(
                any(name.endswith(suffix) for name in inventory),
                f"sdist is missing {suffix.removeprefix('/')}",
            )
    return inventory


async def _items(*values: bytes) -> AsyncIterator[bytes]:
    for value in values:
        yield value


async def _expect_corrupt(path: Path) -> None:
    for operation in (aiogzip.inspect, aiogzip.verify):
        try:
            await operation(path)
        except gzip.BadGzipFile:
            continue
        raise RuntimeError(f"{operation.__name__} accepted a corrupt gzip stream")


async def _smoke_aiocsv(path: Path) -> None:
    try:
        import aiocsv
    except ImportError as error:
        raise RuntimeError("--require-aiocsv requested but aiocsv is absent") from error

    rows = [
        {"name": "Ada", "value": "1"},
        {"name": "Grace", "value": "2"},
    ]
    async with aiogzip.open(path, "wt", newline="") as stream:
        writer = aiocsv.AsyncDictWriter(stream, fieldnames=["name", "value"])
        await writer.writeheader()
        await writer.writerows(rows)
    async with aiogzip.open(path, "rt", newline="") as stream:
        restored = [row async for row in aiocsv.AsyncDictReader(stream)]
    _require(restored == rows, "aiocsv installed-artifact round-trip mismatch")


async def _smoke_tarfile_style(directory: Path) -> None:
    contents = {"first.txt": b"first\nline\n", "second.txt": b"second\n"}
    tar_path = directory / "archive.tar.gz"
    source_paths: list[Path] = []
    for name, content in contents.items():
        source = directory / name
        source.write_bytes(content)
        source_paths.append(source)
    with tarfile.open(tar_path, "w:gz") as archive:
        for source in source_paths:
            archive.add(source, arcname=source.name)

    restored: dict[str, bytes] = {}
    async with aiogzip.open(tar_path, "rb") as stream:
        while True:
            header = await stream.read(512)
            if not header or header == b"\x00" * 512:
                break
            info = tarfile.TarInfo.frombuf(
                header, encoding="utf-8", errors="surrogateescape"
            )
            data = await stream.read(info.size)
            if info.name in contents:
                restored[info.name] = data
            padding = (-info.size) % 512
            if padding:
                await stream.seek(await stream.tell() + padding)
    _require(restored == contents, "tarfile-style installed-artifact read mismatch")


async def _smoke_async(directory: Path, *, require_aiocsv: bool) -> tuple[Path, Path]:
    payload = ("installed artifact — β\n" * 100).encode()
    binary_path = directory / "binary.gz"
    text_path = directory / "text.gz"

    await aiogzip.write(binary_path, payload, mtime=0)
    _require(await aiogzip.read(binary_path) == payload, "binary round-trip mismatch")

    text = "first\nΚαλημέρα 🌍\nlast\n"
    async with aiogzip.open(text_path, "wt", encoding="utf-8", newline="") as stream:
        count = await stream.write(text)
    _require(count == len(text), "text write returned an incorrect character count")
    async with aiogzip.open(text_path, "rt", encoding="utf-8", newline="") as stream:
        _require(await stream.read() == text, "text round-trip mismatch")

    compressed = b"".join(
        [
            chunk
            async for chunk in aiogzip.compress_chunks(
                _items(payload[:31], b"", payload[31:]),
                mtime=0,
                output_chunk_size=17,
            )
        ]
    )
    restored = b"".join(
        [
            chunk
            async for chunk in aiogzip.decompress_chunks(
                _items(compressed[:7], compressed[7:19], compressed[19:]),
                output_chunk_size=23,
            )
        ]
    )
    _require(restored == payload, "chunk API round-trip mismatch")

    info = await aiogzip.inspect(binary_path)
    verified = await aiogzip.verify(binary_path)
    _require(info.member_count == verified.member_count == 1, "member-count mismatch")
    _require(
        info.uncompressed_size == verified.uncompressed_size == len(payload),
        "uncompressed-size mismatch",
    )

    corrupt_path = directory / "corrupt.gz"
    corrupt = bytearray(binary_path.read_bytes())
    corrupt[-8] ^= 1
    corrupt_path.write_bytes(corrupt)
    await _expect_corrupt(corrupt_path)

    if require_aiocsv:
        await _smoke_aiocsv(directory / "rows.csv.gz")
    await _smoke_tarfile_style(directory)
    return binary_path, corrupt_path


def _run_cli(path: Path, corrupt_path: Path, expected_version: str) -> None:
    version = subprocess.run(
        [sys.executable, "-m", "aiogzip", "--version"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    _require(version == expected_version, f"CLI version mismatch: {version!r}")

    for command in ("inspect", "verify"):
        success = subprocess.run(
            [sys.executable, "-m", "aiogzip", command, str(path), "--json"],
            check=True,
            capture_output=True,
            text=True,
        )
        parsed = json.loads(success.stdout)
        if command == "verify":
            _require(parsed["ok"] is True, "CLI verify did not report success")
        else:
            _require(len(parsed["members"]) == 1, "CLI inspect member mismatch")

        failure = subprocess.run(
            [sys.executable, "-m", "aiogzip", command, str(corrupt_path), "--json"],
            check=False,
            capture_output=True,
            text=True,
        )
        _require(failure.returncode == 1, f"CLI {command} accepted corrupt data")
        _require(json.loads(failure.stdout)["ok"] is False, "CLI failure JSON mismatch")


def _run_manifest_check(script: Path, manifest: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(script), "--check", str(manifest)],
        check=False,
        capture_output=True,
        text=True,
    )
    _require(result.returncode == 0, result.stdout + result.stderr)


def _artifact_report(path: Path, kind: str) -> dict[str, object]:
    data = path.read_bytes()
    inventory = validate_artifact_layout(path, kind)
    return {
        "kind": kind,
        "path": str(path.resolve()),
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "file_count": len(inventory),
    }


def _installed_version(distribution: str) -> str | None:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--expected-engine", choices=("stdlib-zlib", "zlib-ng"))
    parser.add_argument(
        "--expect-fast",
        action="store_true",
        help="compatibility alias for --expected-engine=zlib-ng",
    )
    parser.add_argument("--require-aiocsv", action="store_true")
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--artifact-kind", choices=("wheel", "sdist"))
    parser.add_argument("--repository-root", type=Path)
    parser.add_argument("--api-script", type=Path)
    parser.add_argument("--api-manifest", type=Path)
    parser.add_argument("--report-output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if (args.api_script is None) != (args.api_manifest is None):
        raise RuntimeError("--api-script and --api-manifest must be supplied together")
    if (args.artifact is None) != (args.artifact_kind is None):
        raise RuntimeError("--artifact and --artifact-kind must be supplied together")

    package_path = Path(aiogzip.__file__).resolve()
    environment_root = Path(sys.prefix).resolve()
    _require(
        _is_relative_to(package_path, environment_root),
        f"aiogzip is outside the clean environment: {package_path}",
    )
    _require(
        not _is_source_checkout(package_path),
        f"aiogzip imported from a source checkout: {package_path}",
    )
    if args.repository_root is not None:
        repository_root = args.repository_root.resolve()
        _require(
            not _is_relative_to(Path.cwd().resolve(), repository_root),
            f"smoke working directory is inside repository: {Path.cwd()}",
        )
        _require(
            not _is_relative_to(package_path, repository_root),
            f"aiogzip imported from repository: {package_path}",
        )

    metadata_version = importlib.metadata.version("aiogzip")
    _require(
        metadata_version == aiogzip.__version__ == args.expected_version,
        "import, distribution, and expected versions differ: "
        f"{aiogzip.__version__!r}, {metadata_version!r}, {args.expected_version!r}",
    )
    requirements = validate_declared_requirements()
    _require(
        importlib.util.find_spec("aiogzip.examples") is None,
        "wheel exposes an unexpected aiogzip.examples namespace",
    )
    _require(
        importlib.util.find_spec("bench_common") is None,
        "benchmark module is importable from the artifact environment",
    )

    from aiogzip.codec import CodecOperation, GzipDecoder, GzipEncoder

    _require(
        (CodecOperation, GzipDecoder, GzipEncoder)
        == (aiogzip.CodecOperation, aiogzip.GzipDecoder, aiogzip.GzipEncoder),
        "top-level and aiogzip.codec exports differ",
    )
    payload = b"installed codec payload\n" * 100
    encoder = GzipEncoder(mtime=0, output_chunk_size=17)
    compressed = b"".join(encoder.start())
    compressed += b"".join(encoder.feed(payload))
    compressed += b"".join(encoder.finish())
    _require(gzip.decompress(compressed) == payload, "stdlib rejected codec output")
    decoder = GzipDecoder(output_chunk_size=19)
    restored = b"".join(decoder.feed(compressed)) + b"".join(decoder.finish())
    _require(restored == payload, "codec round-trip mismatch")

    if args.api_script is not None:
        _run_manifest_check(args.api_script.resolve(), args.api_manifest.resolve())

    with tempfile.TemporaryDirectory(prefix="aiogzip-artifact-smoke-") as directory:
        valid_path, corrupt_path = asyncio.run(
            _smoke_async(Path(directory), require_aiocsv=args.require_aiocsv)
        )
        _run_cli(valid_path, corrupt_path, args.expected_version)

    engine = aiogzip.engine_info()
    expected_engine = "zlib-ng" if args.expect_fast else args.expected_engine
    if expected_engine is not None:
        _require(
            engine.decompression == expected_engine,
            f"engine mismatch: {engine.decompression!r} != {expected_engine!r}",
        )

    report: dict[str, Any] = {
        "version": aiogzip.__version__,
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "package_path": str(package_path),
        "environment_root": str(environment_root),
        "working_directory": str(Path.cwd().resolve()),
        "requirements": requirements,
        "versions": {
            name: _installed_version(name) for name in ("aiofiles", "aiocsv", "zlib-ng")
        },
        "engine": {
            "compression": engine.compression,
            "decompression": engine.decompression,
            "crc32": engine.crc32,
        },
    }
    if args.artifact is not None:
        report["artifact"] = _artifact_report(
            args.artifact.resolve(), args.artifact_kind
        )
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    print(rendered, end="")
    if args.report_output is not None:
        args.report_output.parent.mkdir(parents=True, exist_ok=True)
        args.report_output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
