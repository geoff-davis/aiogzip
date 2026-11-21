from __future__ import annotations

import gzip
import hashlib
import importlib.metadata
import importlib.util
import json
import subprocess
import sys
import types
import typing
from pathlib import Path

import pytest

import aiogzip

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "capture_public_api.py"
MANIFEST = ROOT / "tests" / "data" / "public_api_2_1.json"
BASELINE = ROOT / "tests" / "data" / "public_api_2_0.json"
# The frozen 2.0 contract as released. A later line adds to it and never
# edits it.
BASELINE_SHA256 = "e0168ae90bf4f265da9255a6d0bfc3e27cf6f0282861ac6c5f253da67e9d8951"


def _removed_or_altered(baseline: object, current: object, path: str) -> list[str]:
    """List every baseline entry that ``current`` lacks or holds differently.

    A mapping may gain keys and an export list may gain names. Everything
    else, down to each parameter of each signature, must be equal.
    """
    if isinstance(baseline, dict):
        if not isinstance(current, dict):
            return [path]
        problems = []
        for key, value in baseline.items():
            if key not in current:
                problems.append(f"{path}.{key}")
            else:
                problems.extend(
                    _removed_or_altered(value, current[key], f"{path}.{key}")
                )
        return problems
    if path.endswith(".exports"):
        assert isinstance(baseline, list) and isinstance(current, list)
        return [f"{path}: {name}" for name in baseline if name not in current]
    return [] if baseline == current else [path]


def test_frozen_2_0_baseline_is_unchanged():
    # A Windows checkout may convert line endings; the content is what counts.
    content = BASELINE.read_bytes().replace(b"\r\n", b"\n")
    digest = hashlib.sha256(content).hexdigest()
    assert digest == BASELINE_SHA256


def test_current_manifest_contains_the_2_0_contract_unaltered():
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    current = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert baseline.pop("release_line") == "2.0"
    assert current.pop("release_line") == "2.1"
    assert _removed_or_altered(baseline, current, "api") == []


def test_baseline_comparison_reports_removals_and_changes():
    baseline = {"functions": {"f": {"default": 1}}, "m": {"exports": ["a", "b"]}}
    assert _removed_or_altered(baseline, baseline, "api") == []
    grown = {
        "functions": {"f": {"default": 1}, "g": {}},
        "m": {"exports": ["a", "b", "c"]},
        "new": 1,
    }
    assert _removed_or_altered(baseline, grown, "api") == []
    broken = {"functions": {"f": {"default": 2}}, "m": {"exports": ["b"]}}
    assert _removed_or_altered(baseline, broken, "api") == [
        "api.functions.f.default",
        "api.m.exports: a",
    ]
    assert _removed_or_altered(baseline, {"m": baseline["m"]}, "api") == [
        "api.functions"
    ]


def _capture_module():
    spec = importlib.util.spec_from_file_location("capture_public_api", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_public_api_manifest_matches_runtime():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--check", str(MANIFEST)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_public_api_capture_is_deterministic():
    module = _capture_module()
    first = module.render(module.capture())
    second = module.render(module.capture())
    assert first == second
    assert first.endswith("\n")
    assert json.loads(first)["schema_version"] == 1


def test_public_api_annotations_are_interpreter_neutral():
    module = _capture_module()

    assert module._annotation_name(Path) == "pathlib.Path"
    assert module._annotation_name(typing.Optional[int]) == "Optional[int]"
    assert (
        module._annotation_name(typing.Union[int, float, None])
        == "Union[int, float, NoneType]"
    )
    assert (
        module._annotation_name(typing.Union[str, bytes, Path, None])
        == "Union[str, bytes, pathlib.Path, NoneType]"
    )
    assert (
        module._annotation_name(typing.AsyncIterable[typing.Union[bytes, bytearray]])
        == "AsyncIterable[Union[bytes, bytearray]]"
    )
    assert module._annotation_name(typing.AsyncIterable[bytes]) == (
        "AsyncIterable[bytes]"
    )


def test_public_api_capture_rejects_duplicate_exports():
    module = _capture_module()
    fake = types.ModuleType("duplicate_exports")
    fake.__all__ = ["value", "value"]
    fake.value = object()
    with pytest.raises(ValueError, match="contains duplicates: value"):
        module._exports(fake)


def test_public_api_capture_rejects_missing_exports():
    module = _capture_module()
    fake = types.ModuleType("missing_exports")
    fake.__all__ = ["missing"]
    with pytest.raises(ValueError, match="contains missing names: missing"):
        module._exports(fake)


def test_version_is_public_string_synchronized_with_metadata():
    assert isinstance(aiogzip.__version__, str)
    assert aiogzip.__version__ == importlib.metadata.version("aiogzip")


def test_engine_info_shape_without_freezing_diagnostic_values():
    # Engine-selection tests reload the private engine module. Verify public
    # class identity in a clean interpreter so this contract is order-neutral.
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import aiogzip; "
                "info = aiogzip.engine_info(); "
                "assert isinstance(info, aiogzip.EngineInfo); "
                "assert all(isinstance(value, str) for value in "
                "(info.compression, info.decompression, info.crc32))"
            ),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_documented_decompression_limit_message_prefix():
    decoder = aiogzip.GzipDecoder(max_decompressed_size=3)
    operation = decoder.feed(gzip.compress(b"four", mtime=0))
    with pytest.raises(OSError) as caught:
        b"".join(operation)
    assert str(caught.value).startswith(
        "decompressed output exceeded max_decompressed_size"
    )
