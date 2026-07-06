"""Validate code snippets in the documentation against the real API.

Every fenced ``python`` block in README.md, CLAUDE.md, and docs/*.md is
checked three ways:

1. It parses as Python (top-level ``await``/``async with`` allowed, with
   fallback fixups for common documentation fragments).
2. Any ``import aiogzip`` / ``from aiogzip import X`` resolves against
   the real package, so renamed or removed exports fail CI.
3. Any ``aiogzip.X`` attribute reference (including via import aliases)
   resolves, so docs can't reference API that no longer exists.

Snippet code is never executed — blocks are compiled to AST only, and
the import check only ever imports the ``aiogzip`` package itself.

CHANGELOG.md is deliberately excluded (it records old APIs). Individual
blocks can opt out by putting ``<!-- doc-snippet: skip -->`` on its own
line directly above the fence.
"""

from __future__ import annotations

import ast
import importlib
import re
from pathlib import Path

import pytest

import aiogzip

REPO_ROOT = Path(__file__).parent.parent

DOC_FILES = sorted(
    {
        REPO_ROOT / "README.md",
        REPO_ROOT / "CLAUDE.md",
        *(REPO_ROOT / "docs").glob("*.md"),
    }
)

SKIP_MARKER = "<!-- doc-snippet: skip -->"

FENCE_RE = re.compile(r"^```python\s*$")
FENCE_END_RE = re.compile(r"^```\s*$")


class Snippet:
    def __init__(self, path: Path, line: int, source: str) -> None:
        self.path = path
        self.line = line  # 1-indexed line of the opening fence
        self.source = source

    @property
    def label(self) -> str:
        return f"{self.path.relative_to(REPO_ROOT).as_posix()}:{self.line}"


def extract_snippets(path: Path) -> list[Snippet]:
    snippets = []
    lines = path.read_text(encoding="utf-8").splitlines()
    i = 0
    while i < len(lines):
        if FENCE_RE.match(lines[i]):
            skipped = i > 0 and lines[i - 1].strip() == SKIP_MARKER
            start = i + 1
            j = start
            while j < len(lines) and not FENCE_END_RE.match(lines[j]):
                j += 1
            if not skipped:
                snippets.append(Snippet(path, i + 1, "\n".join(lines[start:j])))
            i = j
        i += 1
    return snippets


ALL_SNIPPETS = [s for path in DOC_FILES for s in extract_snippets(path)]


def _fragment_fixups(source: str) -> str:
    """Rewrite common doc-fragment idioms into parseable Python.

    Only used as a fallback when the raw snippet doesn't parse, so these
    can't corrupt valid code.
    """
    # Signature displays: a def with no body, ending either on its own
    # dedented ")" line or with ")" at the end of the def line.
    source = re.sub(r"^(\s*)\)\s*$", r"\1): ...", source, flags=re.MULTILINE)
    source = re.sub(
        r"^(\s*(?:async )?def .+\))\s*$", r"\1: ...", source, flags=re.MULTILINE
    )
    # Elided-arguments idiom: call(kwarg=1, ...)
    source = re.sub(r",\s*\.\.\.\s*\)", ")", source)
    return source


def parse_snippet(source: str) -> ast.AST | None:
    for candidate in (source, _fragment_fixups(source)):
        try:
            return compile(
                candidate,
                "<doc-snippet>",
                "exec",
                flags=ast.PyCF_ONLY_AST | ast.PyCF_ALLOW_TOP_LEVEL_AWAIT,
            )
        except SyntaxError:
            continue
    return None


def _is_aiogzip_module(name: str) -> bool:
    # Exact-prefix match: importing executes module code, so only ever
    # import this package itself (not e.g. an aiogzip_x typosquat).
    return name == "aiogzip" or name.startswith("aiogzip.")


def aiogzip_aliases(tree: ast.AST) -> set[str]:
    """Names a snippet binds to the aiogzip package (import aiogzip [as x])."""
    aliases = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "aiogzip":
                    aliases.add(alias.asname or alias.name)
    return aliases


@pytest.mark.parametrize("snippet", ALL_SNIPPETS, ids=lambda s: s.label)
def test_doc_snippet_parses(snippet: Snippet) -> None:
    """Every fenced python block in the docs must be valid Python."""
    assert parse_snippet(snippet.source) is not None, (
        f"{snippet.label}: python code block does not parse. Fix the snippet, or mark an "
        f"intentional fragment with {SKIP_MARKER!r} on the line above the fence."
    )


@pytest.mark.parametrize("snippet", ALL_SNIPPETS, ids=lambda s: s.label)
def test_doc_imports_resolve(snippet: Snippet) -> None:
    """Every aiogzip import in a doc snippet must exist."""
    tree = parse_snippet(snippet.source)
    if tree is None:  # reported by test_doc_snippet_parses
        pytest.skip("snippet does not parse")

    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.level:
            continue
        module_name = node.module or ""
        if not _is_aiogzip_module(module_name):
            continue
        module = importlib.import_module(module_name)
        for alias in node.names:
            assert hasattr(module, alias.name), (
                f"{snippet.label}: `from {module_name} import {alias.name}` — {alias.name!r} does not exist in {module_name}"
            )


@pytest.mark.parametrize("snippet", ALL_SNIPPETS, ids=lambda s: s.label)
def test_doc_attribute_references_resolve(snippet: Snippet) -> None:
    """Every `aiogzip.X` reference in a doc snippet must exist.

    Docs use the module-level API (`aiogzip.open`, `aiogzip.AsyncGzipTextFile`,
    ...); a rename in the package must fail these references in CI.
    """
    tree = parse_snippet(snippet.source)
    if tree is None:
        pytest.skip("snippet does not parse")

    aliases = aiogzip_aliases(tree)
    if not aliases:
        return

    problems = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in aliases
            and not hasattr(aiogzip, node.attr)
        ):
            problems.append(f"aiogzip.{node.attr} does not exist")

    assert not problems, "{}:\n  {}".format(snippet.label, "\n  ".join(problems))


# --- self-tests: prove the checkers catch what they exist to catch ---


def test_checker_catches_missing_export() -> None:
    tree = parse_snippet("from aiogzip import definitely_not_a_real_name")
    assert tree is not None
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom))
    assert _is_aiogzip_module(node.module or "")
    assert not hasattr(aiogzip, node.names[0].name)


def test_checker_catches_missing_attribute() -> None:
    tree = parse_snippet("import aiogzip\naiogzip.definitely_not_a_real_name()")
    assert tree is not None
    assert aiogzip_aliases(tree) == {"aiogzip"}
    attrs = [
        n.attr
        for n in ast.walk(tree)
        if isinstance(n, ast.Attribute)
        and isinstance(n.value, ast.Name)
        and n.value.id == "aiogzip"
    ]
    assert attrs == ["definitely_not_a_real_name"]
    assert not hasattr(aiogzip, attrs[0])


def test_checker_ignores_typosquat_modules() -> None:
    assert not _is_aiogzip_module("aiogzip_evil")
    assert _is_aiogzip_module("aiogzip")
    assert _is_aiogzip_module("aiogzip._common")


def test_docs_were_discovered() -> None:
    """Guard against the glob silently matching nothing."""
    assert len(DOC_FILES) >= 5
    assert len(ALL_SNIPPETS) >= 15
    assert any(s.path.name == "README.md" for s in ALL_SNIPPETS)
