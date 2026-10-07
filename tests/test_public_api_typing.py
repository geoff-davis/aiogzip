from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from _typing_contract import expected, reported, version

ROOT = Path(__file__).parents[1]
POSITIVE = ROOT / "tests" / "typing" / "public_api_positive.py"
NEGATIVE = ROOT / "tests" / "typing" / "public_api_negative.py"
POSITIVE_ARGUMENT = str(POSITIVE.relative_to(ROOT))
NEGATIVE_ARGUMENT = str(NEGATIVE.relative_to(ROOT))


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=ROOT, capture_output=True, text=True)


@pytest.mark.parametrize(
    ("name", "command"),
    [
        (
            "mypy",
            [sys.executable, "-m", "mypy", "--strict", POSITIVE_ARGUMENT],
        ),
        (
            "ty",
            [
                sys.executable,
                "-m",
                "ty",
                "check",
                "--python-version",
                "3.11",
                "--output-format",
                "concise",
                "--no-progress",
                POSITIVE_ARGUMENT,
            ],
        ),
    ],
)
def test_positive_public_api_typing(name: str, command: list[str]):
    result = _run(command)
    assert result.returncode == 0, f"{name}:\n{result.stdout}{result.stderr}"


@pytest.mark.parametrize(
    ("name", "command"),
    [
        (
            "mypy",
            [
                sys.executable,
                "-m",
                "mypy",
                "--strict",
                "--no-error-summary",
                NEGATIVE_ARGUMENT,
            ],
        ),
        (
            "ty",
            [
                sys.executable,
                "-m",
                "ty",
                "check",
                "--python-version",
                "3.11",
                "--output-format",
                "concise",
                "--no-progress",
                NEGATIVE_ARGUMENT,
            ],
        ),
    ],
)
def test_negative_public_api_typing(name: str, command: list[str]):
    result = _run(command)
    output = result.stdout + result.stderr
    assert result.returncode != 0, f"{name} unexpectedly accepted negative fixture"
    want = expected(NEGATIVE, name)
    assert len(want) == 7
    got = reported(output, name, NEGATIVE_ARGUMENT)
    assert got == want, f"{version(name)}:\n{output}"
