"""Keep the parameter reference in docs/api.md in step with the signatures.

The "Parameters" section of docs/api.md documents every parameter of the two
file classes under its own heading and lists it in a summary table. A
parameter added to a constructor without documentation, or a default changed
without the table, fails here.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

import aiogzip

API_MD = Path(__file__).parent.parent / "docs" / "api.md"


def _parameters_section() -> str:
    text = API_MD.read_text(encoding="utf-8")
    start = text.index("\n## Parameters\n")
    end = text.index("\n## ", start + 1)
    return text[start:end]


SECTION = _parameters_section()
HEADINGS = set(re.findall(r"^### `(\w+)`$", SECTION, flags=re.MULTILINE))
TABLE_ROWS = {
    name: default
    for name, default in re.findall(
        r"^\| \[`(\w+)`\]\(#\w+\) \| ([^|]+) \|", SECTION, flags=re.MULTILINE
    )
}
HELPER_ROWS = {
    name: set(re.findall(r"`(\w+)`", keywords))
    for name, keywords in re.findall(
        r"^\| `(\w+)\([^)]*\)` \| ([^|]+) \|", SECTION, flags=re.MULTILINE
    )
}


def _init_parameters(cls: type) -> dict[str, inspect.Parameter]:
    return dict(inspect.signature(cls).parameters)


CLASS_PARAMETERS = {
    **_init_parameters(aiogzip.AsyncGzipBinaryFile),
    **_init_parameters(aiogzip.AsyncGzipTextFile),
}


@pytest.mark.parametrize(
    "cls", [aiogzip.AsyncGzipBinaryFile, aiogzip.AsyncGzipTextFile]
)
def test_every_constructor_parameter_is_documented(cls: type) -> None:
    names = set(_init_parameters(cls))
    assert names - HEADINGS == set(), "parameters without a heading in docs/api.md"
    assert names - set(TABLE_ROWS) == set(), "parameters missing from the table"


def test_no_documented_parameter_is_stale() -> None:
    assert HEADINGS == set(CLASS_PARAMETERS)
    assert set(TABLE_ROWS) == set(CLASS_PARAMETERS)


def test_classes_differ_only_by_the_text_parameters() -> None:
    binary = _init_parameters(aiogzip.AsyncGzipBinaryFile)
    text = _init_parameters(aiogzip.AsyncGzipTextFile)
    assert set(text) - set(binary) == {"encoding", "errors", "newline"}
    assert set(binary) - set(text) == set()
    for name, parameter in binary.items():
        if name != "mode":
            assert parameter.default == text[name].default, name


@pytest.mark.parametrize("name", sorted(CLASS_PARAMETERS))
def test_documented_default_matches_signature(name: str) -> None:
    default = CLASS_PARAMETERS[name].default
    documented = TABLE_ROWS[name]
    if default is inspect.Parameter.empty:
        assert documented.strip() == "required"
    elif name == "mode":
        binary = _init_parameters(aiogzip.AsyncGzipBinaryFile)["mode"].default
        text = _init_parameters(aiogzip.AsyncGzipTextFile)["mode"].default
        assert f'`"{binary}"`' in documented
        assert f'`"{text}"`' in documented
    elif isinstance(default, str):
        assert documented.startswith(f'`"{default}"`')
    else:
        assert documented.startswith(f"`{default!r}`")


@pytest.mark.parametrize("name", ["read", "write", "inspect", "verify"])
def test_helper_keyword_parameters_are_listed(name: str) -> None:
    keyword_only = {
        parameter.name
        for parameter in inspect.signature(getattr(aiogzip, name)).parameters.values()
        if parameter.kind is inspect.Parameter.KEYWORD_ONLY
    }
    assert HELPER_ROWS[name] == keyword_only
    assert keyword_only <= HEADINGS
