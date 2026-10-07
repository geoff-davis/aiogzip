"""Helpers of the clean-worktree release build script."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import tarfile
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_release_artifacts.py"


@pytest.fixture(scope="module")
def release():
    spec = importlib.util.spec_from_file_location("build_release_artifacts", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _wheel(tmp_path, wheel_text):
    target = tmp_path / "pkg-1.0-py3-none-any.whl"
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("pkg/__init__.py", "")
        archive.writestr("pkg-1.0.dist-info/WHEEL", wheel_text)
    return target


def test_inventory_records_size_digest_and_members(release, tmp_path):
    wheel = _wheel(tmp_path, "Wheel-Version: 1.0\nGenerator: flit 4.1.0\n")
    entry = release._inventory_entry(wheel)
    assert entry["name"] == wheel.name
    assert entry["size"] == wheel.stat().st_size
    assert entry["sha256"] == hashlib.sha256(wheel.read_bytes()).hexdigest()
    assert entry["members"] == ["pkg-1.0.dist-info/WHEEL", "pkg/__init__.py"]
    assert release._wheel_generator(wheel) == "flit 4.1.0"


def test_sdist_members_are_listed(release, tmp_path):
    sdist = tmp_path / "pkg-1.0.tar.gz"
    with tarfile.open(sdist, "w:gz") as archive:
        data = b"x"
        info = tarfile.TarInfo("pkg-1.0/PKG-INFO")
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
    assert release._members(sdist) == ["pkg-1.0/PKG-INFO"]


def test_wheel_without_generator_fails(release, tmp_path):
    wheel = _wheel(tmp_path, "Wheel-Version: 1.0\n")
    with pytest.raises(RuntimeError, match="records no Generator"):
        release._wheel_generator(wheel)


def test_evidence_inside_repository_is_refused(release):
    with pytest.raises(RuntimeError, match="inside the repository"):
        release.main(["--evidence-dir", str(release.REPOSITORY / "evidence")])
