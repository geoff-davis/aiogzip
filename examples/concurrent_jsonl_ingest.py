#!/usr/bin/env python3
"""Bounded concurrent JSONL ingest with validation and atomic publication."""

from __future__ import annotations

import argparse
import asyncio
import gzip
import hashlib
import json
import shutil
import tempfile
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol, cast

import aiofiles

import aiogzip


class DatasetLimitError(OSError):
    """Raised when staged decoded bytes cross the dataset-wide limit."""


class InvalidJsonError(ValueError):
    """Raised when a validated gzip payload is not valid JSON Lines."""


class ShardIngestError(OSError):
    """Attach a deterministic source name to one shard's primary failure."""

    def __init__(self, source_name: str, error: Exception) -> None:
        self.source_name = source_name
        self.original_error = error
        super().__init__(f"{source_name}: {type(error).__name__}: {error}")


class _AsyncByteWriter(Protocol):
    async def write(self, data: bytes, /) -> int: ...


@dataclass(frozen=True)
class FixtureShard:
    source_name: str
    partition: str
    row_count: int
    byte_count: int
    sha256: str


@dataclass(frozen=True)
class FixtureManifest:
    shards: tuple[FixtureShard, ...]


@dataclass(frozen=True)
class ShardManifest:
    source_name: str
    output_name: str
    partition: str
    row_count: int
    byte_count: int
    sha256: str
    max_batch_chars: int


@dataclass(frozen=True)
class DatasetManifest:
    shards: tuple[ShardManifest, ...]
    row_count: int
    byte_count: int
    sha256: str
    max_active_handles: int


def _positive_integer(value: object, name: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{name} must be a positive integer")
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


class DatasetBudget:
    """Example-local atomic accounting for bytes already staged on disk."""

    def __init__(self, limit: int) -> None:
        self._limit = _positive_integer(limit, "dataset_limit")
        self._used = 0
        self._failed = False
        self._lock = asyncio.Lock()

    @property
    def used(self) -> int:
        return self._used

    async def add(self, amount: int) -> int:
        amount = _positive_integer(amount, "staged byte count")
        async with self._lock:
            if self._failed:
                raise asyncio.CancelledError
            next_value = self._used + amount
            if next_value > self._limit:
                self._failed = True
                raise DatasetLimitError(
                    f"decoded dataset would exceed dataset_limit "
                    f"({next_value} > {self._limit} bytes)"
                )
            self._used = next_value
            return next_value


class _ConcurrencyTracker:
    def __init__(self) -> None:
        self.active = 0
        self.maximum = 0
        self._lock = asyncio.Lock()

    async def enter(self) -> None:
        async with self._lock:
            self.active += 1
            self.maximum = max(self.maximum, self.active)

    async def leave(self) -> None:
        async with self._lock:
            self.active -= 1


def _fixture_records(partition: int, row_count: int) -> list[dict[str, object]]:
    return [
        {
            "partition": partition,
            "sequence": sequence,
            "value": f"event-{partition:03d}-{sequence:04d}",
        }
        for sequence in range(row_count)
    ]


def _encode_jsonl(records: Sequence[dict[str, object]]) -> bytes:
    return b"".join(
        (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
        for record in records
    )


def generate_fixtures(
    directory: Path,
    *,
    shard_count: int = 3,
    rows_per_shard: int = 40,
) -> FixtureManifest:
    """Generate small deterministic gzip fixtures with the standard library."""
    shard_count = _positive_integer(shard_count, "shard_count")
    rows_per_shard = _positive_integer(rows_per_shard, "rows_per_shard")
    directory = Path(directory)
    if directory.exists():
        raise FileExistsError(f"fixture directory already exists: {directory}")
    directory.mkdir(parents=True)
    shards: list[FixtureShard] = []
    for partition_index in range(shard_count):
        source_name = f"events-{partition_index:03d}.jsonl.gz"
        records = _fixture_records(partition_index, rows_per_shard)
        payload = _encode_jsonl(records)
        (directory / source_name).write_bytes(gzip.compress(payload, mtime=0))
        shards.append(
            FixtureShard(
                source_name=source_name,
                partition=f"events-{partition_index:03d}",
                row_count=len(records),
                byte_count=len(payload),
                sha256=hashlib.sha256(payload).hexdigest(),
            )
        )
    manifest = FixtureManifest(tuple(shards))
    manifest_json = {
        "schema_version": 1,
        "shards": [asdict(shard) for shard in manifest.shards],
    }
    (directory / "fixtures-manifest.json").write_text(
        json.dumps(manifest_json, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def _output_name(source: Path) -> str:
    return source.name[:-3] if source.name.endswith(".gz") else f"{source.name}.jsonl"


def _partition_name(source: Path) -> str:
    output = _output_name(source)
    return output[:-6] if output.endswith(".jsonl") else output


def _validated_inputs(inputs: Sequence[Path]) -> tuple[Path, ...]:
    if not inputs:
        raise ValueError("at least one input is required")
    paths = tuple(Path(path) for path in inputs)
    resolved = tuple(path.resolve() for path in paths)
    if len(set(resolved)) != len(paths):
        raise ValueError("duplicate input paths are not allowed")
    names = [path.name for path in paths]
    if len(set(names)) != len(names):
        raise ValueError("duplicate input names are not allowed")
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(f"input is not a file: {path}")
    return tuple(sorted(paths, key=lambda path: (path.name, path.as_posix())))


async def _write_staged_bytes(writer: _AsyncByteWriter, data: bytes) -> int:
    written = await writer.write(data)
    if written != len(data):
        raise OSError(f"staged write accepted {written} of {len(data)} bytes")
    return written


async def _ingest_shard(
    source: Path,
    output: Path,
    *,
    semaphore: asyncio.Semaphore,
    tracker: _ConcurrencyTracker,
    budget: DatasetBudget,
    per_shard_limit: int,
    batch_hint: int,
) -> ShardManifest:
    async with semaphore:
        await tracker.enter()
        try:
            digest = hashlib.sha256()
            row_count = 0
            byte_count = 0
            max_batch_chars = 0
            try:
                async with aiogzip.open(
                    source,
                    "rt",
                    encoding="utf-8",
                    errors="strict",
                    newline="\n",
                    max_decompressed_size=per_shard_limit,
                ) as stream:
                    async with aiofiles.open(output, "wb") as staged:
                        async for batch in stream.iter_batches(hint=batch_hint):
                            batch_chars = sum(len(line) for line in batch)
                            max_batch_chars = max(max_batch_chars, batch_chars)
                            for index, line in enumerate(batch, start=row_count + 1):
                                try:
                                    cast(dict[str, object], json.loads(line))
                                except json.JSONDecodeError as error:
                                    raise InvalidJsonError(
                                        f"invalid JSON at line {index}"
                                    ) from error
                            encoded = "".join(batch).encode("utf-8")
                            written = await _write_staged_bytes(staged, encoded)
                            await budget.add(written)
                            digest.update(encoded)
                            row_count += len(batch)
                            byte_count += written
            except asyncio.CancelledError:
                raise
            except Exception as error:
                raise ShardIngestError(source.name, error) from error
            return ShardManifest(
                source_name=source.name,
                output_name=output.name,
                partition=_partition_name(source),
                row_count=row_count,
                byte_count=byte_count,
                sha256=digest.hexdigest(),
                max_batch_chars=max_batch_chars,
            )
        finally:
            await tracker.leave()


def _first_exception(group: ExceptionGroup[Exception]) -> Exception:
    for error in group.exceptions:
        if isinstance(error, ExceptionGroup):
            return _first_exception(error)
        return error
    return RuntimeError("TaskGroup failed without an exception")


async def _dataset_digest(staging: Path, shards: Sequence[ShardManifest]) -> str:
    digest = hashlib.sha256()
    for shard in shards:
        async with aiofiles.open(
            staging / "partitions" / shard.output_name, "rb"
        ) as file:
            while chunk := await file.read(64 * 1024):
                digest.update(chunk)
    return digest.hexdigest()


async def _write_manifest(staging: Path, manifest: DatasetManifest) -> None:
    payload = {
        "schema_version": 1,
        "row_count": manifest.row_count,
        "byte_count": manifest.byte_count,
        "sha256": manifest.sha256,
        "max_active_handles": manifest.max_active_handles,
        "shards": [asdict(shard) for shard in manifest.shards],
    }
    async with aiofiles.open(staging / "manifest.json", "w", encoding="utf-8") as file:
        await file.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")


async def _cleanup_staging(staging: Path) -> None:
    if staging.exists():
        await asyncio.to_thread(shutil.rmtree, staging)


async def ingest_dataset(
    inputs: Sequence[Path],
    destination: Path,
    *,
    concurrency: int,
    per_shard_limit: int,
    dataset_limit: int,
    batch_hint: int = 64 * 1024,
) -> DatasetManifest:
    """Validate shards concurrently, then atomically publish one dataset."""
    concurrency = _positive_integer(concurrency, "concurrency")
    per_shard_limit = _positive_integer(per_shard_limit, "per_shard_limit")
    dataset_limit = _positive_integer(dataset_limit, "dataset_limit")
    batch_hint = _positive_integer(batch_hint, "batch_hint")
    sources = _validated_inputs(inputs)
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(f"destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}.partial-",
            dir=destination.parent,
        )
    )
    (staging / "partitions").mkdir()
    semaphore = asyncio.Semaphore(concurrency)
    tracker = _ConcurrencyTracker()
    budget = DatasetBudget(dataset_limit)
    tasks: list[asyncio.Task[ShardManifest]] = []
    try:
        try:
            async with asyncio.TaskGroup() as group:
                for source in sources:
                    tasks.append(
                        group.create_task(
                            _ingest_shard(
                                source,
                                staging / "partitions" / _output_name(source),
                                semaphore=semaphore,
                                tracker=tracker,
                                budget=budget,
                                per_shard_limit=per_shard_limit,
                                batch_hint=batch_hint,
                            )
                        )
                    )
        except ExceptionGroup as group:
            raise _first_exception(group) from group

        shards = tuple(
            sorted((task.result() for task in tasks), key=lambda x: x.source_name)
        )
        manifest = DatasetManifest(
            shards=shards,
            row_count=sum(shard.row_count for shard in shards),
            byte_count=sum(shard.byte_count for shard in shards),
            sha256=await _dataset_digest(staging, shards),
            max_active_handles=tracker.maximum,
        )
        await _write_manifest(staging, manifest)
        if destination.exists():
            raise FileExistsError(f"destination appeared during ingest: {destination}")
        staging.rename(destination)
        return manifest
    except BaseException as primary:
        try:
            await asyncio.shield(_cleanup_staging(staging))
        except BaseException as cleanup_error:
            primary.add_note(
                f"staging cleanup also failed: {type(cleanup_error).__name__}: "
                f"{cleanup_error}"
            )
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate gzip JSONL shards and publish a validated dataset."
    )
    parser.add_argument("--generate-fixtures", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--shards", type=int, default=3)
    parser.add_argument("--rows-per-shard", type=int, default=40)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--per-shard-limit", type=int, default=4 * 1024 * 1024)
    parser.add_argument("--dataset-limit", type=int, default=12 * 1024 * 1024)
    parser.add_argument("--batch-hint", type=int, default=64 * 1024)
    return parser


async def _main(args: argparse.Namespace) -> DatasetManifest:
    generate_fixtures(
        args.generate_fixtures,
        shard_count=args.shards,
        rows_per_shard=args.rows_per_shard,
    )
    inputs = sorted(args.generate_fixtures.glob("*.jsonl.gz"))
    return await ingest_dataset(
        inputs,
        args.output,
        concurrency=args.concurrency,
        per_shard_limit=args.per_shard_limit,
        dataset_limit=args.dataset_limit,
        batch_hint=args.batch_hint,
    )


def main() -> int:
    args = _parser().parse_args()
    manifest = asyncio.run(_main(args))
    print(
        f"published={args.output} shards={len(manifest.shards)} "
        f"rows={manifest.row_count} bytes={manifest.byte_count} "
        f"sha256={manifest.sha256}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
