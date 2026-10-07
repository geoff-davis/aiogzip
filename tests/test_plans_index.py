"""The plans index links every committed record, and plan links resolve (G18).

``plans/`` is not part of the docs site, so the strict mkdocs build does not
check it. The documents checked and every link target must be paths git
tracks, so an untracked local file cannot satisfy a link; contents are read
from the working tree. The tests skip outside a checkout (for example, from
an sdist).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PLANS = REPO_ROOT / "plans"
INDEX = PLANS / "README.md"
LINK = re.compile(r"\]\(([^)\s]+)\)")
FENCE = re.compile(r"```.*?```", re.DOTALL)


def _tracked() -> set[Path]:
    """Every committed path and every directory that contains one."""
    if shutil.which("git") is None or not (REPO_ROOT / ".git").exists():
        pytest.skip("needs a git checkout")
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
        text=True,
    )
    files = {REPO_ROOT / name for name in result.stdout.split("\0") if name}
    return files | {parent for path in files for parent in path.parents}


def _tracked_markdown() -> list[Path]:
    files = sorted(
        path
        for path in _tracked()
        if path.suffix == ".md" and path.is_relative_to(PLANS) and path.is_file()
    )
    assert INDEX in files
    return files


def _relative_links(document: Path) -> list[str]:
    text = FENCE.sub("", document.read_text(encoding="utf-8"))
    return [
        target
        for target in LINK.findall(text)
        if not re.match(r"[A-Za-z][\w+.-]*:", target) and not target.startswith("#")
    ]


def _anchor(heading: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", heading.strip().lower())
    return re.sub(r"\s", "-", slug)


def test_every_relative_link_in_plans_resolves():
    """Links resolve to committed paths, not to local untracked files."""
    tracked = _tracked()
    broken = []
    for document in _tracked_markdown():
        for target in _relative_links(document):
            name, _, fragment = target.partition("#")
            linked = (document.parent / name).resolve()
            if linked not in tracked:
                broken.append(f"{document.relative_to(REPO_ROOT)}: {target}")
            elif fragment and linked.suffix == ".md":
                headings = re.findall(
                    r"^#+\s+(.*)$", linked.read_text(encoding="utf-8"), re.MULTILINE
                )
                if fragment not in {_anchor(heading) for heading in headings}:
                    broken.append(f"{document.relative_to(REPO_ROOT)}: {target}")
    assert broken == []


def test_index_links_every_committed_plan_record():
    linked = {
        (INDEX.parent / target.partition("#")[0]).resolve()
        for target in _relative_links(INDEX)
    }
    missing = [
        str(document.relative_to(REPO_ROOT))
        for document in _tracked_markdown()
        if document != INDEX and document.resolve() not in linked
    ]
    assert missing == []
