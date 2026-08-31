from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
POSITIVE = ROOT / "tests" / "typing" / "public_api_positive.py"
NEGATIVE = ROOT / "tests" / "typing" / "public_api_negative.py"
POSITIVE_ARGUMENT = str(POSITIVE.relative_to(ROOT))
NEGATIVE_ARGUMENT = str(NEGATIVE.relative_to(ROOT))


def _expected_error_lines() -> set[int]:
    return {
        number
        for number, line in enumerate(
            NEGATIVE.read_text(encoding="utf-8").splitlines(), start=1
        )
        if "EXPECT_ERROR" in line
    }


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
    reported_path = NEGATIVE_ARGUMENT
    for line in _expected_error_lines():
        assert re.search(rf"{re.escape(reported_path)}:{line}(?::|\b)", output), (
            f"{name} did not report expected line {line}:\n{output}"
        )
