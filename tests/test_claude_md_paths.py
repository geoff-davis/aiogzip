"""Paths and test classes quoted in CLAUDE.md must exist.

CLAUDE.md's "Useful Commands" named ``tests/test_aiogzip.py`` and
``src/aiogzip.py`` long after both were gone. ``test_doc_examples.py``
checks fenced ``python`` blocks only, and those commands are in ``bash``
blocks, so nothing failed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"

# A repository-relative path under a top-level directory of this project.
# The lookbehind skips a path that is the tail of a longer one, such as
# ``/tmp/aiogzip-baseline/src``.
_PATH = re.compile(
    r"(?<![\w./-])(?:src|tests|scripts|benchmarks|plans|docs|examples)"
    r"/[\w./-]*[\w/]"
)
_TEST_CLASS = re.compile(r"(?<![\w./-])(tests/[\w./-]+\.py)::(\w+)")


def quoted_paths(text: str) -> list[str]:
    return sorted(set(_PATH.findall(text)))


def quoted_test_classes(text: str) -> list[tuple[str, str]]:
    return sorted(set(_TEST_CLASS.findall(text)))


pytestmark = pytest.mark.skipif(
    not CLAUDE_MD.exists(), reason="CLAUDE.md is not part of this tree"
)

_TEXT = CLAUDE_MD.read_text(encoding="utf-8") if CLAUDE_MD.exists() else ""


@pytest.mark.parametrize("path", quoted_paths(_TEXT))
def test_quoted_path_exists(path: str) -> None:
    assert (REPO_ROOT / path).exists(), f"CLAUDE.md names {path}, which does not exist"


@pytest.mark.parametrize(("path", "name"), quoted_test_classes(_TEXT))
def test_quoted_test_class_exists(path: str, name: str) -> None:
    source = (REPO_ROOT / path).read_text(encoding="utf-8")
    assert re.search(rf"^class {name}\b", source, re.MULTILINE), (
        f"CLAUDE.md names {path}::{name}, which is not defined there"
    )


def test_paths_were_found() -> None:
    assert "src/aiogzip/codec.py" in quoted_paths(_TEXT)
    assert quoted_test_classes(_TEXT)


def test_checker_catches_the_stale_commands() -> None:
    stale = "pytest tests/test_aiogzip.py::TestNewlineHandlingBugs -v\nmypy src/aiogzip.py\n"
    assert quoted_paths(stale) == ["src/aiogzip.py", "tests/test_aiogzip.py"]
    assert quoted_test_classes(stale) == [
        ("tests/test_aiogzip.py", "TestNewlineHandlingBugs")
    ]
    assert not (REPO_ROOT / "tests/test_aiogzip.py").exists()
    assert not (REPO_ROOT / "src/aiogzip.py").exists()


def test_checker_ignores_paths_outside_the_repository() -> None:
    assert quoted_paths("git worktree add /tmp/aiogzip-baseline/src main") == []
    outside = (
        "pytest /tmp/other/tests/test_external.py::External\n"
        "https://example.com/tests/test_remote.py::Remote\n"
    )
    assert quoted_paths(outside) == []
    assert quoted_test_classes(outside) == []
