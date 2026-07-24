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


def test_transport_wrappers_do_not_own_gzip_or_raw_engine_state():
    """Keep framing, validation, and raw inflate confined to the codec."""
    forbidden_calls = {
        "_build_gzip_header",
        "_build_gzip_trailer",
        "compressobj",
        "crc32",
        "decompressobj",
        "inflate_step",
    }
    wrapper_modules = (
        aiogzip._binary,
        aiogzip._inspection,
        aiogzip._streaming,
    )

    for module in wrapper_modules:
        tree = ast.parse(Path(module.__file__).read_text())
        calls = {
            node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, (ast.Attribute, ast.Name))
        }
        assert calls.isdisjoint(forbidden_calls), module.__name__

    codec_tree = ast.parse(Path(aiogzip.codec.__file__).read_text())
    codec_calls = {
        node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        for node in ast.walk(codec_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Attribute, ast.Name))
    }
    assert forbidden_calls <= codec_calls
