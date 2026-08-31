from __future__ import annotations

import importlib.util
import io
import tarfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


def _load_script(name):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


smoke = _load_script("smoke_installed_artifact")
example_runner = _load_script("run_maintained_examples")


def test_candidate_metadata_has_exact_runtime_dependency_floors():
    requirements = smoke.validate_declared_requirements()

    assert requirements == smoke.declared_requirements()


def test_maintained_examples_import_only_public_aiogzip_modules():
    example_runner.validate_public_imports(
        [
            ROOT / "examples/fragmented_transport.py",
            ROOT / "examples/concurrent_jsonl_ingest.py",
        ]
    )


def test_public_import_validation_rejects_private_module(tmp_path):
    example = tmp_path / "private_example.py"
    example.write_text("from aiogzip._binary import AsyncGzipBinaryFile\n")

    with pytest.raises(RuntimeError, match="imports private aiogzip module"):
        example_runner.validate_public_imports([example])


def test_wheel_layout_rejects_an_examples_namespace(tmp_path):
    valid = tmp_path / "valid.whl"
    with zipfile.ZipFile(valid, "w") as archive:
        archive.writestr("aiogzip/__init__.py", "")
        archive.writestr("aiogzip/codec.py", "")
    assert "aiogzip/__init__.py" in smoke.validate_artifact_layout(valid, "wheel")

    invalid = tmp_path / "invalid.whl"
    with zipfile.ZipFile(invalid, "w") as archive:
        archive.writestr("aiogzip/__init__.py", "")
        archive.writestr("aiogzip/examples/demo.py", "")
    with pytest.raises(RuntimeError, match="unexpectedly installs example files"):
        smoke.validate_artifact_layout(invalid, "wheel")


def test_sdist_layout_requires_all_maintained_examples(tmp_path):
    valid = tmp_path / "valid.tar.gz"
    with tarfile.open(valid, "w:gz") as archive:
        for name in (
            "aiogzip-2/examples/README.md",
            "aiogzip-2/examples/fragmented_transport.py",
            "aiogzip-2/examples/concurrent_jsonl_ingest.py",
        ):
            info = tarfile.TarInfo(name)
            archive.addfile(info, io.BytesIO())
    inventory = smoke.validate_artifact_layout(valid, "sdist")
    assert len(inventory) == 3

    invalid = tmp_path / "invalid.tar.gz"
    with tarfile.open(invalid, "w:gz") as archive:
        info = tarfile.TarInfo("aiogzip-2/examples/README.md")
        archive.addfile(info, io.BytesIO())
    with pytest.raises(RuntimeError, match="fragmented_transport.py"):
        smoke.validate_artifact_layout(invalid, "sdist")
