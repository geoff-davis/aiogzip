"""The docs workflow's version routing (scripts/docs_version.py)."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "docs_version.py"


@pytest.fixture(scope="module")
def docs_version():
    spec = importlib.util.spec_from_file_location("docs_version", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.docs_version


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("1.11.0", ("1.11", "stable")),
        ("2.0.0", ("2.0", "stable")),
        ("2.0.0rc2", ("2.0", "prerelease")),
        ("2.0.0rc3.dev0", ("2.0", "dev")),
        ("2.0.1.dev0", ("2.0", "dev")),
        ("2.1.0.dev0", ("2.1", "dev")),
        ("3", ("3.0", "stable")),
    ],
)
def test_docs_version_routing(docs_version, version, expected):
    assert docs_version(version) == expected


def test_cli_prints_version_and_kind():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "2.0.1.dev0"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout == "2.0 dev\n"


def test_workflow_routes_main_dev_builds_to_dev():
    workflow = (ROOT / ".github" / "workflows" / "docs.yml").read_text()
    assert "scripts/docs_version.py" in workflow
    assert '"${VERSION%.*}"' not in workflow
    assert 'mike deploy --push --title "$VERSION" dev' in workflow
