"""The typing-diagnostic parser behind the negative typing fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest
from _typing_contract import expected, reported

FIXTURE = "fixture.py"


def _marked(tmp_path: Path, marker: str) -> Path:
    target = tmp_path / FIXTURE
    target.write_text(f"x: int = 'a'  # EXPECT_ERROR[{marker}]\n", encoding="utf-8")
    return target


def test_marker_codes_per_checker(tmp_path):
    target = _marked(tmp_path, "mypy=assignment, ty=invalid-assignment")
    assert expected(target, "mypy") == {(1, "assignment")}
    assert expected(target, "ty") == {(1, "invalid-assignment")}


@pytest.mark.parametrize(
    "marker",
    [
        "",
        "mypy=assignment",
        "mypy=assignment, ty=",
        "mypy=assignment, ty",
        "mypy=a, mypy=b, ty=c",
        "mypy=a, ty=b, ty=c",
        "mypy=a, ty=b, pyright=c",
    ],
)
def test_malformed_markers_fail(tmp_path, marker):
    with pytest.raises(AssertionError, match="one code per checker"):
        expected(_marked(tmp_path, marker), "mypy")


def test_marker_without_brackets_fails(tmp_path):
    target = tmp_path / FIXTURE
    target.write_text("x: int = 'a'  # EXPECT_ERROR\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="has no codes"):
        expected(target, "mypy")


@pytest.mark.parametrize(
    "shown",
    [
        "fixture.py",
        "{cwd}/fixture.py",
        "D:\\a\\repo\\fixture.py",
    ],
    ids=["relative", "absolute-posix", "absolute-windows"],
)
def test_diagnostic_paths(tmp_path, monkeypatch, shown):
    monkeypatch.chdir(tmp_path)
    argument = shown.format(cwd=tmp_path)
    mypy = f"{argument}:7: error: Incompatible types  [assignment]\n"
    ty = f"{argument}:7:10: error[invalid-assignment] Object of type\n"
    assert reported(mypy, "mypy", argument) == {(7, "assignment")}
    assert reported(ty, "ty", argument) == {(7, "invalid-assignment")}


def test_notes_and_summaries_are_not_diagnostics(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = (
        "fixture.py:7: error: Incompatible types  [assignment]\n"
        "fixture.py:7: note: See https://example.invalid\n"
        "Found 1 error in 1 file (checked 1 source file)\n"
    )
    assert reported(output, "mypy", FIXTURE) == {(7, "assignment")}


@pytest.mark.parametrize(
    ("output", "message"),
    [
        ("other.py:7: error: Incompatible types  [assignment]\n", "other file"),
        ("fixture.py:7: error: Incompatible types\n", "no error code"),
        ("fixture.py: error: cannot read file\n", "unparsed"),
        ("error: unrecognized arguments\n", "unparsed"),
    ],
    ids=["other-file", "no-code", "no-line", "bare"],
)
def test_unexpected_diagnostics_fail(tmp_path, monkeypatch, output, message):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(AssertionError, match=message):
        reported(output, "mypy", FIXTURE)
