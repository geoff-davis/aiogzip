"""Static-typing test: the AsyncGzipFile factory narrows its return by mode.

Runs ``mypy --strict`` over ``tests/typing/check_factory_overloads.py``, whose
``assert_type`` calls fail the type check unless the overloads resolve a text
mode to ``AsyncGzipTextFile`` (``read() -> str``) and a binary mode to
``AsyncGzipBinaryFile`` (``read() -> bytes``).
"""

import subprocess
import sys
from pathlib import Path

import pytest

CHECK_FILE = Path(__file__).parent / "typing" / "check_factory_overloads.py"


def _mypy_available() -> bool:
    try:
        import mypy  # noqa: F401
    except ImportError:
        return False
    return True


@pytest.mark.skipif(not _mypy_available(), reason="mypy is not installed")
def test_factory_overloads_typecheck():
    result = subprocess.run(
        [sys.executable, "-m", "mypy", "--strict", str(CHECK_FILE)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "mypy --strict reported errors on the factory-overload assertions:\n"
        + result.stdout
        + result.stderr
    )
