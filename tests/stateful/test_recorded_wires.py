"""The recorded-trace replays must not skip silently off Windows."""

import sys

import pytest
from recorded_wires import REPRODUCED


@pytest.mark.skipif(sys.platform == "win32", reason="Windows may bundle zlib-ng")
def test_recorded_wires_are_reproduced():
    # test_differential.py skips entirely where this fails. Only Windows
    # (whose Python 3.14 build emits different gzip.compress() streams) may.
    assert REPRODUCED
