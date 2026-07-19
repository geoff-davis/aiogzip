"""Command-line entry point: ``python -m aiogzip {inspect,verify} FILE``.

Thin argparse wrapper over the public :func:`aiogzip.inspect` and
:func:`aiogzip.verify` APIs. Exit codes: 0 on success, 1 when the stream is
invalid (or unreadable), 2 for usage errors (argparse's convention).
"""

import argparse
import asyncio
import dataclasses
import gzip
import json
import sys
from typing import Any, List, Optional

from . import __version__, inspect, verify


def _json_default(value: Any) -> str:
    if isinstance(value, bytes):
        return value.hex()
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m aiogzip",
        description="Inspect or verify gzip files using aiogzip.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    inspect_parser = subparsers.add_parser(
        "inspect", help="show per-member metadata after full validation"
    )
    verify_parser = subparsers.add_parser(
        "verify", help="validate headers, payloads, CRCs, and sizes"
    )
    for subparser in (inspect_parser, verify_parser):
        subparser.add_argument("path", help="gzip file to read")
        subparser.add_argument(
            "--json", action="store_true", help="machine-readable JSON output"
        )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "inspect":
            info = asyncio.run(inspect(args.path))
            if args.json:
                print(json.dumps(dataclasses.asdict(info), default=_json_default))
            else:
                print(
                    f"{args.path}: {info.member_count} member(s), "
                    f"{info.compressed_size} bytes compressed, "
                    f"{info.uncompressed_size} bytes uncompressed"
                )
                for m in info.members:
                    name = m.original_filename or "-"
                    print(
                        f"  member {m.index}: offset={m.compressed_offset} "
                        f"compressed={m.compressed_size} "
                        f"uncompressed={m.uncompressed_size} mtime={m.mtime} "
                        f"crc32={m.crc32:#010x} name={name}"
                    )
        else:
            result = asyncio.run(verify(args.path))
            if args.json:
                print(json.dumps({"ok": True, **dataclasses.asdict(result)}))
            else:
                print(
                    f"OK: {args.path}: {result.member_count} member(s), "
                    f"{result.compressed_size} bytes compressed, "
                    f"{result.uncompressed_size} bytes uncompressed"
                )
        return 0
    except (gzip.BadGzipFile, OSError, EOFError) as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}))
        else:
            print(f"FAILED: {args.path}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
