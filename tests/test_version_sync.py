from __future__ import annotations

import importlib
from pathlib import Path

import aiogzip

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover -- Python <3.11 fallback
    import tomli as tomllib  # type: ignore[no-redef]


def test_version_consistency():
    """Ensure project version is synchronized across metadata locations."""
    root = Path(__file__).resolve().parents[1]
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))

    project = data["project"]
    assert "version" not in project, (
        "Static version should be removed when using dynamic versioning"
    )
    assert "version" in project.get("dynamic", []), "Version must be declared dynamic"

    dynamic_cfg = data["tool"]["setuptools"]["dynamic"]["version"]
    assert dynamic_cfg["attr"] == "aiogzip.__version__", (
        "Dynamic version should reference aiogzip.__version__"
    )

    module = importlib.import_module("aiogzip")
    assert module.__version__ == aiogzip.__version__, (
        "aiogzip exposes inconsistent __version__ values"
    )


def test_py_typed_marker_shipped():
    """py.typed should be installed alongside the aiogzip package."""
    module_path = Path(aiogzip.__file__)
    marker = module_path.with_name("py.typed")
    assert marker.exists(), "py.typed marker missing from installed package"
