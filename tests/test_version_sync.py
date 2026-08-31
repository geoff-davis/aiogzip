from __future__ import annotations

import importlib
import importlib.util
import re
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


def test_release_metadata_is_synchronized():
    """The version, changelog, and packaging posture must agree.

    A ``.devN`` version means the release is not cut yet, so its base version
    must not appear as a released changelog heading. A plain version means the
    release is cut, so the newest changelog heading must match it exactly.
    This holds across release-prep and next-dev-version bumps without pinning
    either state.
    """
    root = Path(__file__).resolve().parents[1]
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    project = data["project"]

    assert "## [Unreleased]" in changelog
    newest = re.search(
        r"^## \[([^]]+)\] - (\d{4}-\d{2}-\d{2})$", changelog, re.MULTILINE
    )
    assert newest is not None, "changelog has no dated release heading"

    version = aiogzip.__version__
    dev = re.fullmatch(r"(?P<base>.+?)\.dev\d+", version)
    if dev is not None:
        assert f"## [{dev.group('base')}]" not in changelog, (
            "development version's release already has a changelog heading"
        )
    else:
        assert newest.group(1) == version, (
            "released version must match the newest changelog heading"
        )

    assert project["requires-python"] == ">=3.11"
    assert "Development Status :: 3 - Alpha" in project["classifiers"]
    assert any(
        dependency.startswith("aiofiles") for dependency in project["dependencies"]
    )


def test_minimum_runtime_dependencies_are_synchronized():
    """Metadata, the assertion script, and CI must use the proven floors."""
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]
    assert project["dependencies"] == ["aiofiles>=23.2.1"]
    assert project["optional-dependencies"]["csv"] == ["aiocsv>=1.2.3"]
    assert project["optional-dependencies"]["fast"] == ["zlib-ng>=0.4.0"]

    script = root / "scripts" / "report_runtime_versions.py"
    spec = importlib.util.spec_from_file_location("report_runtime_versions", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module._EXPECTED_VERSIONS == {
        "base": {"aiofiles": "23.2.1"},
        "csv": {"aiofiles": "23.2.1", "aiocsv": "1.2.3"},
        "fast": {"aiofiles": "23.2.1", "zlib-ng": "0.4.0"},
        "fast-forced-stdlib": {"aiofiles": "23.2.1", "zlib-ng": "0.4.0"},
    }

    workflow = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    for exact_pin in (
        "aiofiles==23.2.1",
        "aiocsv==1.2.3",
        "zlib-ng==0.4.0",
    ):
        assert exact_pin in workflow
