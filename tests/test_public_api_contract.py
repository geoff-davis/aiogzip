from __future__ import annotations

import gzip
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
MANIFEST = ROOT / "tests" / "data" / "public_api_2_0.json"


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
