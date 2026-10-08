"""Helpers of the clean-worktree release build script."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import subprocess
import sys
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


def _tree(root, files):
    for name, text in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


FILES = {
    "examples/a.py": "a",
    "examples/README.md": "r",
    "tests/integration/test_a.py": "t",
}


def test_packaged_trees_must_match_the_commit(release, tmp_path):
    source = _tree(tmp_path / "source", FILES)
    packaged = _tree(tmp_path / "packaged", FILES)
    digests = release._require_packaged_trees(packaged, source)
    assert set(digests) == set(FILES)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"examples/a.py": "stale"}, "changed \\['examples/a.py'\\]"),
        ({"examples/extra.py": "x"}, "extra \\['examples/extra.py'\\]"),
        (
            {"examples/__pycache__/a.cpython-314.pyc": "x"},
            "extra \\['examples/__pycache__/a.cpython-314.pyc'\\]",
        ),
    ],
    ids=["changed", "extra", "bytecode-cache"],
)
def test_packaged_tree_differences_fail(release, tmp_path, change, message):
    source = _tree(tmp_path / "source", FILES)
    packaged = _tree(tmp_path / "packaged", {**FILES, **change})
    with pytest.raises(RuntimeError, match=message):
        release._require_packaged_trees(packaged, source)


def test_missing_packaged_file_fails(release, tmp_path):
    source = _tree(tmp_path / "source", FILES)
    packaged = _tree(
        tmp_path / "packaged",
        {k: v for k, v in FILES.items() if k != "tests/integration/test_a.py"},
    )
    with pytest.raises(RuntimeError, match="missing"):
        release._require_packaged_trees(packaged, source)


def test_source_version_is_read_without_importing(release, tmp_path):
    package = tmp_path / "src" / "aiogzip"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        'raise ImportError("must not be imported")\n__version__ = "9.9.9rc1"\n',
        encoding="utf-8",
    )
    assert release._source_version(tmp_path) == "9.9.9rc1"


def test_source_version_without_assignment_fails(release, tmp_path):
    package = tmp_path / "src" / "aiogzip"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("VERSION = '1'\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="no __version__"):
        release._source_version(tmp_path)


def test_source_version_needs_no_site_packages():
    # The publish build job installs neither aiogzip nor its dependencies, so
    # reading the version must work in an interpreter without site-packages.
    root = SCRIPT.parents[1]
    code = (
        "import importlib.util, sys; "
        f"spec = importlib.util.spec_from_file_location('b', {str(SCRIPT)!r}); "
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); "
        f"print(m._source_version(__import__('pathlib').Path({str(root)!r}))); "
        "assert 'aiofiles' not in sys.modules and 'aiogzip' not in sys.modules"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-c", code],
        capture_output=True,
        text=True,
        check=True,
    )
    init = (root / "src" / "aiogzip" / "__init__.py").read_text(encoding="utf-8")
    assert f'__version__ = "{result.stdout.strip()}"' in init
