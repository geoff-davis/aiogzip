"""Static typing tests for the public codec operation lifecycle."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from _typing_contract import expected, reported, version

TYPING_DIR = Path(__file__).parent / "typing"
CHECK_FILE = TYPING_DIR / "check_codec_operation.py"
REJECT_FILE = TYPING_DIR / "reject_plain_iterator_close.py"
TY = shutil.which("ty")
if TY is None:
    sibling_ty = Path(sys.executable).with_name("ty")
    if sibling_ty.is_file():
        TY = str(sibling_ty)


def _mypy_available() -> bool:
    try:
        import mypy  # noqa: F401
    except ImportError:
        return False
    return True


@pytest.mark.skipif(not _mypy_available(), reason="mypy is not installed")
@pytest.mark.parametrize(
    ("check_file", "expected_returncode"),
    [(CHECK_FILE, 0), (REJECT_FILE, 1)],
)
def test_codec_operation_mypy_contract(check_file, expected_returncode):
    result = subprocess.run(
        [sys.executable, "-m", "mypy", "--strict", str(check_file)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == expected_returncode, result.stdout + result.stderr
    if expected_returncode:
        got = reported(result.stdout, "mypy", str(check_file))
        assert got == expected(check_file, "mypy"), (
            f"{version('mypy')}:\n{result.stdout}"
        )


@pytest.mark.skipif(TY is None, reason="ty is not installed")
@pytest.mark.parametrize(
    ("check_file", "expected_returncode"),
    [(CHECK_FILE, 0), (REJECT_FILE, 1)],
)
def test_codec_operation_ty_contract(check_file, expected_returncode):
    assert TY is not None
    result = subprocess.run(
        [TY, "check", "--output-format", "concise", "--no-progress", str(check_file)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == expected_returncode, result.stdout + result.stderr
    if expected_returncode:
        got = reported(result.stdout, "ty", str(check_file))
        assert got == expected(check_file, "ty"), f"{version('ty')}:\n{result.stdout}"
