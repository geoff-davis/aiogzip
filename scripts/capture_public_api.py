#!/usr/bin/env python3
"""Capture the deliberately curated aiogzip 2.0 public runtime contract."""

from __future__ import annotations

import argparse
import dataclasses
import difflib
import importlib
import inspect
import json
import types
import typing
from pathlib import Path

import aiogzip
import aiogzip.codec

SCHEMA_VERSION = 1
DEFAULT_MANIFEST = Path("tests/data/public_api_2_0.json")

_FUNCTIONS = (
    "AsyncGzipFile",
    "open",
    "read",
    "write",
    "engine_info",
    "inspect",
    "verify",
    "decompress_chunks",
    "compress_chunks",
)

_CLASS_MEMBERS = {
    "AsyncGzipBinaryFile": (
        "open",
        "tell",
        "seek",
        "raw",
        "name",
        "closed",
        "mtime",
        "fileno",
        "isatty",
        "detach",
        "truncate",
        "peek",
        "readinto",
        "read1",
        "readinto1",
        "readline",
        "readlines",
        "writelines",
        "readable",
        "writable",
        "seekable",
        "rewind",
        "write",
        "read",
        "flush",
        "close",
        "__aenter__",
        "__aexit__",
        "__aiter__",
        "__anext__",
    ),
    "AsyncGzipTextFile": (
        "open",
        "tell",
        "seek",
        "fileno",
        "isatty",
        "detach",
        "truncate",
        "raw",
        "name",
        "closed",
        "encoding",
        "errors",
        "newlines",
        "buffer",
        "mtime",
        "readable",
        "writable",
        "seekable",
        "write",
        "read",
        "readline",
        "readlines",
        "iter_batches",
        "writelines",
        "flush",
        "close",
        "__aenter__",
        "__aexit__",
        "__aiter__",
        "__anext__",
    ),
    "GzipEncoder": (
        "discard",
        "input_size",
        "crc32",
        "started",
        "finished",
        "start",
        "feed",
        "flush",
        "finish",
    ),
    "GzipDecoder": (
        "discard",
        "members",
        "member_count",
        "compressed_size",
        "uncompressed_size",
        "finished",
        "feed",
        "finish",
    ),
    "GzipInfo": ("member_count",),
}

_DATACLASSES = (
    "EngineInfo",
    "GzipMemberInfo",
    "GzipInfo",
    "VerificationResult",
)

_PROTOCOLS = {
    "CodecOperation": ("__iter__", "__next__", "close"),
    "WithAsyncRead": ("read",),
    "WithAsyncWrite": ("write",),
    "WithAsyncReadWrite": ("read", "write", "close"),
}

_CONSTANTS = (
    "GZIP_WBITS",
    "GZIP_FLAG_FNAME",
    "GZIP_FLAG_FHCRC",
    "GZIP_FLAG_FEXTRA",
    "GZIP_FLAG_FCOMMENT",
    "GZIP_METHOD_DEFLATE",
    "GZIP_OS_UNKNOWN",
)


def _source_annotations(obj: object) -> dict[str, str]:
    """Return source-spelled annotations when the interpreter exposes them."""
    try:
        annotationlib = importlib.import_module("annotationlib")
    except ImportError:
        return {}
    return annotationlib.get_annotations(obj, format=annotationlib.Format.STRING)


def _annotation_name(annotation: object, source: str | None = None) -> str | None:
    if annotation is inspect.Signature.empty:
        return None
    if annotation is None or annotation is types.NoneType:
        return "None"
    if isinstance(annotation, str):
        return annotation.replace("typing.", "")
    if annotation is typing.Any:
        return "Any"
    if isinstance(annotation, typing.ForwardRef):
        return annotation.__forward_arg__.replace("typing.", "")
    origin = typing.get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        arguments = typing.get_args(annotation)
        pep_604 = (source is not None and "|" in source) or (
            origin is types.UnionType and origin is not typing.Union
        )
        if pep_604:
            rendered_arguments = [
                "None" if item is types.NoneType else _annotation_name(item)
                for item in arguments
            ]
            return " | ".join(rendered_arguments)
        if len(arguments) == 2 and types.NoneType in arguments:
            member = next(item for item in arguments if item is not types.NoneType)
            return f"Optional[{_annotation_name(member)}]"
        rendered_arguments = [
            "NoneType" if item is types.NoneType else _annotation_name(item)
            for item in arguments
        ]
        return f"Union[{', '.join(rendered_arguments)}]"
    rendered = inspect.formatannotation(annotation).replace("typing.", "")
    rendered = rendered.replace("pathlib._local.Path", "pathlib.Path")
    for private_module in (
        "aiogzip._binary.",
        "aiogzip._common.",
        "aiogzip._engine.",
        "aiogzip._metadata.",
        "aiogzip._text.",
    ):
        rendered = rendered.replace(private_module, "aiogzip.")
    return rendered


def _default(default: object) -> dict[str, object]:
    if default is inspect.Signature.empty or default is dataclasses.MISSING:
        return {"kind": "required"}
    if default is None or isinstance(default, (bool, int, float, str)):
        return {"kind": "value", "value": default}
    if isinstance(default, bytes):
        return {"kind": "bytes", "hex": default.hex()}
    if default is Ellipsis:
        return {"kind": "ellipsis"}
    raise TypeError(f"unsupported public default value: {default!r}")


def _signature(obj: object) -> dict[str, object]:
    signature = inspect.signature(obj)
    source_annotations = _source_annotations(obj)
    parameters = []
    for parameter in signature.parameters.values():
        parameters.append(
            {
                "name": parameter.name,
                "kind": parameter.kind.name,
                "default": _default(parameter.default),
                "annotation": _annotation_name(
                    parameter.annotation, source_annotations.get(parameter.name)
                ),
            }
        )
    return {
        "parameters": parameters,
        "return": _annotation_name(
            signature.return_annotation, source_annotations.get("return")
        ),
    }


def _callable_kind(obj: object) -> str:
    if inspect.isasyncgenfunction(obj):
        return "async_generator_function"
    if inspect.iscoroutinefunction(obj):
        return "coroutine_function"
    if inspect.isclass(obj):
        return "class"
    return "function"


def _exports(module: types.ModuleType) -> list[str]:
    exports = list(module.__all__)
    duplicates = sorted({name for name in exports if exports.count(name) > 1})
    if duplicates:
        names = ", ".join(duplicates)
        raise ValueError(f"{module.__name__}.__all__ contains duplicates: {names}")
    missing = sorted(name for name in exports if not hasattr(module, name))
    if missing:
        names = ", ".join(missing)
        raise ValueError(f"{module.__name__}.__all__ contains missing names: {names}")
    return sorted(exports)


def _class_contract(name: str) -> dict[str, object]:
    cls = getattr(aiogzip, name)
    members: dict[str, object] = {}
    for member_name in _CLASS_MEMBERS[name]:
        static_member = inspect.getattr_static(cls, member_name)
        if isinstance(static_member, property):
            source_annotations = _source_annotations(static_member.fget)
            members[member_name] = {
                "kind": "property",
                "return": _annotation_name(
                    inspect.signature(static_member.fget).return_annotation,
                    source_annotations.get("return"),
                ),
            }
            continue
        member = getattr(cls, member_name)
        members[member_name] = {
            "kind": _callable_kind(member),
            "signature": _signature(member),
        }
    return {"constructor": _signature(cls), "members": members}


def _dataclass_contract(name: str) -> dict[str, object]:
    cls = getattr(aiogzip, name)
    if not dataclasses.is_dataclass(cls):
        raise TypeError(f"aiogzip.{name} is no longer a dataclass")
    fields = []
    source_annotations = _source_annotations(cls)
    for field in dataclasses.fields(cls):
        default = field.default
        if field.default_factory is not dataclasses.MISSING:  # type: ignore[misc]
            raise TypeError(f"default factory is not supported for aiogzip.{name}")
        fields.append(
            {
                "name": field.name,
                "annotation": _annotation_name(
                    field.type, source_annotations.get(field.name)
                ),
                "default": _default(default),
            }
        )
    params = cls.__dataclass_params__
    return {
        "fields": fields,
        "frozen": params.frozen,
        "slots": "__slots__" in cls.__dict__,
    }


def _protocol_contract(name: str, members: tuple[str, ...]) -> dict[str, object]:
    protocol = getattr(aiogzip, name)
    missing = [member for member in members if not hasattr(protocol, member)]
    if missing:
        raise TypeError(f"aiogzip.{name} is missing protocol members: {missing}")
    contract: dict[str, object] = {"members": list(members)}
    if name == "CodecOperation":
        contract["runtime_checkable"] = False
    else:
        contract["runtime_checkable"] = bool(
            getattr(protocol, "_is_runtime_protocol", False)
        )
    return contract


def capture() -> dict[str, object]:
    """Return the curated contract as JSON-serializable standard types."""
    functions = {}
    for name in _FUNCTIONS:
        function = getattr(aiogzip, name)
        functions[name] = {
            "kind": _callable_kind(function),
            "signature": _signature(function),
        }

    return {
        "schema_version": SCHEMA_VERSION,
        "package": "aiogzip",
        "release_line": "2.0",
        "modules": {
            "aiogzip": {"exports": _exports(aiogzip)},
            "aiogzip.codec": {"exports": _exports(aiogzip.codec)},
        },
        "functions": functions,
        "classes": {name: _class_contract(name) for name in sorted(_CLASS_MEMBERS)},
        "dataclasses": {name: _dataclass_contract(name) for name in _DATACLASSES},
        "exceptions": {
            "ConcurrentOperationError": {
                "direct_bases": [
                    base.__name__ for base in aiogzip.ConcurrentOperationError.__bases__
                ]
            }
        },
        "protocols": {
            name: _protocol_contract(name, members)
            for name, members in _PROTOCOLS.items()
        },
        "typing_aliases": {"ZlibEngine": _annotation_name(aiogzip.ZlibEngine)},
        "constants": {name: getattr(aiogzip, name) for name in _CONSTANTS},
        "version": {
            "present": hasattr(aiogzip, "__version__"),
            "type": type(getattr(aiogzip, "__version__", None)).__name__,
        },
        "stable_message_prefixes": [
            "decompressed output exceeded max_decompressed_size"
        ],
        "non_guarantees": [
            "engine_info string values",
            "literal __version__ value",
            "private modules and members",
            "complete dynamic exception messages",
            "example CLI and output wording",
        ],
    }


def render(contract: dict[str, object]) -> str:
    """Serialize a contract deterministically with a final newline."""
    return json.dumps(contract, indent=2, sort_keys=True) + "\n"


def _check(path: Path, actual: str) -> int:
    expected = path.read_text(encoding="utf-8")
    if actual == expected:
        return 0
    diff = difflib.unified_diff(
        expected.splitlines(keepends=True),
        actual.splitlines(keepends=True),
        fromfile=str(path),
        tofile="captured public API",
    )
    print("".join(diff), end="")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--check",
        nargs="?",
        const=DEFAULT_MANIFEST,
        type=Path,
        metavar="MANIFEST",
        help="fail with a unified diff when MANIFEST differs",
    )
    group.add_argument(
        "--output", type=Path, metavar="PATH", help="write the captured JSON to PATH"
    )
    args = parser.parse_args()

    actual = render(capture())
    if args.check is not None:
        return _check(args.check, actual)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(actual, encoding="utf-8")
        return 0
    print(actual, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
