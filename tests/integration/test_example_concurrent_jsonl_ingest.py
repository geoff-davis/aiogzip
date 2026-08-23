"""Integration coverage for concurrent staged JSONL ingest."""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[2]
EXAMPLE_PATH = REPO_ROOT / "examples" / "concurrent_jsonl_ingest.py"


def _load_example():
    spec = importlib.util.spec_from_file_location(
        "aiogzip_example_concurrent_jsonl_ingest",
        EXAMPLE_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


example = _load_example()


def _inputs(directory):
    return sorted(directory.glob("*.jsonl.gz"))


def _partial_directories(destination):
    return list(destination.parent.glob(f".{destination.name}.partial-*"))


async def _ingest(inputs, destination, **overrides):
    options = {
        "concurrency": 2,
        "per_shard_limit": 1024 * 1024,
        "dataset_limit": 4 * 1024 * 1024,
        "batch_hint": 128,
    }
    options.update(overrides)
    return await example.ingest_dataset(inputs, destination, **options)


@pytest.mark.parametrize(
    ("parameter", "value", "error"),
    [
        ("concurrency", True, TypeError),
        ("concurrency", 0, ValueError),
        ("per_shard_limit", False, TypeError),
        ("per_shard_limit", -1, ValueError),
        ("dataset_limit", True, TypeError),
        ("dataset_limit", 0, ValueError),
        ("batch_hint", False, TypeError),
        ("batch_hint", 0, ValueError),
    ],
)
async def test_integer_options_validate_before_staging(
    tmp_path, parameter, value, error
):
    fixtures = tmp_path / "fixtures"
    example.generate_fixtures(fixtures)
    destination = tmp_path / "published"

    with pytest.raises(error, match=parameter):
        await _ingest(_inputs(fixtures), destination, **{parameter: value})

    assert not destination.exists()
    assert _partial_directories(destination) == []


async def test_input_and_destination_preconditions(tmp_path):
    fixtures = tmp_path / "fixtures"
    example.generate_fixtures(fixtures)
    inputs = _inputs(fixtures)
    destination = tmp_path / "published"
    destination.mkdir()

    with pytest.raises(FileExistsError, match="destination already exists"):
        await _ingest(inputs, destination)
    with pytest.raises(ValueError, match="duplicate input paths"):
        await _ingest([inputs[0], inputs[0]], tmp_path / "other")
    with pytest.raises(ValueError, match="at least one input"):
        await _ingest([], tmp_path / "empty")


async def test_valid_ingest_publishes_once_with_exact_manifest(tmp_path):
    fixtures = tmp_path / "fixtures"
    expected = example.generate_fixtures(fixtures, rows_per_shard=17)
    inputs = _inputs(fixtures)
    destination = tmp_path / "published"

    manifest = await _ingest(inputs, destination, batch_hint=137)

    assert destination.is_dir()
    assert _partial_directories(destination) == []
    assert len(manifest.shards) == 3
    assert manifest.max_active_handles == 2
    expected_by_name = {shard.source_name: shard for shard in expected.shards}
    combined = hashlib.sha256()
    for shard in manifest.shards:
        expected_shard = expected_by_name[shard.source_name]
        output = (destination / "partitions" / shard.output_name).read_bytes()
        combined.update(output)
        assert shard.row_count == expected_shard.row_count
        assert shard.byte_count == expected_shard.byte_count == len(output)
        assert shard.sha256 == expected_shard.sha256
        assert hashlib.sha256(output).hexdigest() == shard.sha256
        assert all(json.loads(line) for line in output.splitlines())
        max_line = max(map(len, output.splitlines(keepends=True)))
        assert shard.max_batch_chars <= 137 + max_line
        assert (
            gzip.decompress(fixtures.joinpath(shard.source_name).read_bytes()) == output
        )
    assert manifest.row_count == sum(shard.row_count for shard in expected.shards)
    assert manifest.byte_count == sum(shard.byte_count for shard in expected.shards)
    assert manifest.sha256 == combined.hexdigest()
    disk_manifest = json.loads((destination / "manifest.json").read_text())
    assert disk_manifest["sha256"] == manifest.sha256
    assert disk_manifest["row_count"] == manifest.row_count


async def test_corrupt_crc_identifies_shard_and_cleans_staging(tmp_path, monkeypatch):
    fixtures = tmp_path / "fixtures"
    example.generate_fixtures(fixtures, rows_per_shard=50)
    inputs = _inputs(fixtures)
    damaged = inputs[1]
    wire = bytearray(damaged.read_bytes())
    wire[-8] ^= 1
    damaged.write_bytes(wire)
    destination = tmp_path / "published"
    writers_with_progress = set()
    original_write = example._write_staged_bytes

    async def recording_write(writer, data):
        written = await original_write(writer, data)
        writers_with_progress.add(Path(writer.name).name)
        return written

    monkeypatch.setattr(example, "_write_staged_bytes", recording_write)

    with pytest.raises(example.ShardIngestError, match=damaged.name) as exc_info:
        await _ingest(inputs, destination)

    assert "CRC" in str(exc_info.value)
    assert any(name != "events-001.jsonl" for name in writers_with_progress)
    assert not destination.exists()
    assert _partial_directories(destination) == []


@pytest.mark.parametrize("cut", [3, 12, -1], ids=["header", "body", "trailer"])
async def test_truncated_stream_never_publishes_or_leaks(tmp_path, cut):
    fixtures = tmp_path / "fixtures"
    example.generate_fixtures(fixtures)
    inputs = _inputs(fixtures)
    damaged = inputs[0]
    wire = damaged.read_bytes()
    damaged.write_bytes(wire[:cut])
    destination = tmp_path / "published"

    with pytest.raises(example.ShardIngestError, match=damaged.name):
        await _ingest(inputs, destination)

    assert not destination.exists()
    assert _partial_directories(destination) == []


async def test_per_shard_limit_aborts_without_publishing(tmp_path):
    fixtures = tmp_path / "fixtures"
    expected = example.generate_fixtures(fixtures)
    destination = tmp_path / "published"
    limit = min(shard.byte_count for shard in expected.shards) - 1

    with pytest.raises(example.ShardIngestError, match="max_decompressed_size"):
        await _ingest(
            _inputs(fixtures),
            destination,
            per_shard_limit=limit,
        )

    assert not destination.exists()
    assert _partial_directories(destination) == []


async def test_dataset_limit_has_one_primary_budget_failure(tmp_path, monkeypatch):
    fixtures = tmp_path / "fixtures"
    expected = example.generate_fixtures(fixtures)
    destination = tmp_path / "published"
    total = sum(shard.byte_count for shard in expected.shards)
    failures = 0
    original_add = example.DatasetBudget.add

    async def recording_add(budget, amount):
        nonlocal failures
        try:
            return await original_add(budget, amount)
        except example.DatasetLimitError:
            failures += 1
            raise

    monkeypatch.setattr(example.DatasetBudget, "add", recording_add)

    with pytest.raises(example.ShardIngestError) as exc_info:
        await _ingest(
            _inputs(fixtures),
            destination,
            dataset_limit=total - 1,
        )

    assert isinstance(exc_info.value.original_error, example.DatasetLimitError)
    assert failures == 1
    assert not destination.exists()
    assert _partial_directories(destination) == []


async def test_two_budget_tasks_racing_near_limit_produce_one_failure():
    budget = example.DatasetBudget(10)
    assert await budget.add(8) == 8
    start = asyncio.Event()

    async def contender():
        await start.wait()
        return await budget.add(3)

    tasks = [asyncio.create_task(contender()) for _ in range(2)]
    start.set()
    results = await asyncio.gather(*tasks, return_exceptions=True)

    assert sum(isinstance(result, example.DatasetLimitError) for result in results) == 1
    assert sum(isinstance(result, asyncio.CancelledError) for result in results) == 1
    assert budget.used == 8


async def test_slow_shard_does_not_block_healthy_completion_or_publish_early(
    tmp_path, monkeypatch
):
    fixtures = tmp_path / "fixtures"
    example.generate_fixtures(fixtures)
    inputs = _inputs(fixtures)
    destination = tmp_path / "published"
    slow_started = asyncio.Event()
    healthy_completed = asyncio.Event()
    resume = asyncio.Event()
    original = example._ingest_shard

    async def controlled(source, output, **kwargs):
        if source.name == inputs[0].name:
            slow_started.set()
            await resume.wait()
        result = await original(source, output, **kwargs)
        if source.name != inputs[0].name:
            healthy_completed.set()
        return result

    monkeypatch.setattr(example, "_ingest_shard", controlled)
    task = asyncio.create_task(_ingest(inputs, destination))
    await slow_started.wait()
    await asyncio.wait_for(healthy_completed.wait(), timeout=2)

    assert not destination.exists()
    resume.set()
    await task
    assert destination.exists()


async def test_top_level_cancellation_closes_handles_and_removes_staging(
    tmp_path, monkeypatch
):
    fixtures = tmp_path / "fixtures"
    example.generate_fixtures(fixtures, rows_per_shard=100)
    destination = tmp_path / "published"
    staged_write = asyncio.Event()
    never_resume = asyncio.Event()
    trackers = []
    original_tracker = example._ConcurrencyTracker
    original_write = example._write_staged_bytes

    class CapturedTracker(original_tracker):
        def __init__(self):
            super().__init__()
            trackers.append(self)

    async def blocking_write(writer, data):
        written = await original_write(writer, data)
        staged_write.set()
        await never_resume.wait()
        return written

    monkeypatch.setattr(example, "_ConcurrencyTracker", CapturedTracker)
    monkeypatch.setattr(example, "_write_staged_bytes", blocking_write)
    task = asyncio.create_task(_ingest(_inputs(fixtures), destination))
    await staged_write.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert trackers and trackers[0].active == 0
    assert not destination.exists()
    assert _partial_directories(destination) == []


async def test_staged_write_failure_is_primary_and_cleanup_is_attempted(
    tmp_path, monkeypatch
):
    fixtures = tmp_path / "fixtures"
    example.generate_fixtures(fixtures, rows_per_shard=100)
    destination = tmp_path / "published"
    original_write = example._write_staged_bytes
    written = 0

    async def failing_write(writer, data):
        nonlocal written
        name = Path(writer.name).name
        if name == "events-001.jsonl" and written >= 128:
            raise OSError("injected staged write failure")
        accepted = await original_write(writer, data)
        if name == "events-001.jsonl":
            written += accepted
        return accepted

    monkeypatch.setattr(example, "_write_staged_bytes", failing_write)

    with pytest.raises(example.ShardIngestError, match="injected staged write"):
        await _ingest(_inputs(fixtures), destination, batch_hint=64)

    assert written >= 128
    assert not destination.exists()
    assert _partial_directories(destination) == []


async def test_cleanup_error_does_not_replace_primary_failure(tmp_path, monkeypatch):
    fixtures = tmp_path / "fixtures"
    example.generate_fixtures(fixtures)
    destination = tmp_path / "published"

    async def failing_write(writer, data):
        raise OSError("primary staged write failure")

    async def failing_cleanup(staging):
        raise OSError("secondary cleanup failure")

    monkeypatch.setattr(example, "_write_staged_bytes", failing_write)
    monkeypatch.setattr(example, "_cleanup_staging", failing_cleanup)

    with pytest.raises(example.ShardIngestError, match="primary staged") as exc_info:
        await _ingest(_inputs(fixtures), destination)

    assert any("secondary cleanup failure" in note for note in exc_info.value.__notes__)
    for partial in _partial_directories(destination):
        shutil.rmtree(partial)


async def test_valid_gzip_with_invalid_json_is_application_failure(tmp_path):
    fixtures = tmp_path / "fixtures"
    example.generate_fixtures(fixtures)
    inputs = _inputs(fixtures)
    damaged = inputs[2]
    payload = gzip.decompress(damaged.read_bytes())
    first_line, remainder = payload.split(b"\n", 1)
    invalid_payload = first_line + b"\nnot-json\n" + remainder
    damaged.write_bytes(gzip.compress(invalid_payload, mtime=0))
    assert gzip.decompress(damaged.read_bytes()) == invalid_payload
    destination = tmp_path / "published"

    with pytest.raises(example.ShardIngestError, match="InvalidJsonError"):
        await _ingest(inputs, destination)

    assert not destination.exists()
    assert _partial_directories(destination) == []


async def test_cleanup_is_idempotent(tmp_path):
    missing = tmp_path / "missing-staging"

    await example._cleanup_staging(missing)
    await example._cleanup_staging(missing)


def test_help_exits_without_creating_files(tmp_path):
    result = subprocess.run(
        [sys.executable, str(EXAMPLE_PATH), "--help"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert "validated dataset" in result.stdout
    assert list(tmp_path.iterdir()) == []


def test_example_uses_only_public_aiogzip_imports():
    source = EXAMPLE_PATH.read_text(encoding="utf-8")

    assert "src.aiogzip" not in source
    assert "aiogzip._" not in source
