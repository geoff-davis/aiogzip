from __future__ import annotations

import importlib
import tomllib
from pathlib import Path

import aiogzip


def test_version_consistency():
    """Ensure project version is synchronized across metadata locations."""
    root = Path(__file__).resolve().parents[1]
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))

    project = data["project"]
    assert "version" not in project, (
        "Static version should be removed when using dynamic versioning"
    )
    assert "version" in project.get("dynamic", []), "Version must be declared dynamic"

    build_system = data["build-system"]
    assert build_system["build-backend"] == "flit_core.buildapi"
    assert any(
        requirement.startswith("flit_core>=3.11")
        for requirement in build_system["requires"]
    )

    module = importlib.import_module("aiogzip")
    assert module.__version__ == aiogzip.__version__, (
        "aiogzip exposes inconsistent __version__ values"
    )


def test_pep639_license_metadata():
    """License metadata should use the modern PEP 639 representation."""
    root = Path(__file__).resolve().parents[1]
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))

    project = data["project"]
    assert project["license"] == "MIT"
    assert project["license-files"] == ["LICENSE"]
    assert not any(
        classifier.startswith("License ::") for classifier in project["classifiers"]
    )


def test_py_typed_marker_shipped():
    """py.typed should be installed alongside the aiogzip package."""
    module_path = Path(aiogzip.__file__)
    marker = module_path.with_name("py.typed")
    assert marker.exists(), "py.typed marker missing from installed package"
