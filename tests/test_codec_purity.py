"""Architectural and export checks for the public sans-I/O codec."""

import ast
from pathlib import Path

import aiogzip
from aiogzip.codec import GzipDecoder, GzipEncoder


def test_codec_is_exported_from_both_public_paths():
    assert aiogzip.GzipEncoder is GzipEncoder
    assert aiogzip.GzipDecoder is GzipDecoder
    assert "GzipEncoder" in aiogzip.__all__
    assert "GzipDecoder" in aiogzip.__all__


def test_codec_module_has_no_async_or_io_dependencies():
    path = Path(aiogzip.codec.__file__)
    tree = ast.parse(path.read_text())
    imports = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }

    assert imports.isdisjoint({"asyncio", "aiofiles"})


def test_thread_safety_contract_is_prominent():
    assert "not thread-safe" in (aiogzip.codec.__doc__ or "")
    assert "not thread-safe" in (GzipEncoder.__doc__ or "")
    assert "not thread-safe" in (GzipDecoder.__doc__ or "")
