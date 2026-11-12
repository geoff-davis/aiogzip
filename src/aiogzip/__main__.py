"""Command-line entry point: ``python -m aiogzip {inspect,verify} FILE``.

Thin argparse wrapper over the public :func:`aiogzip.inspect` and
:func:`aiogzip.verify` APIs. Exit codes: 0 on success, 1 when the stream is
invalid (or unreadable), 2 for usage errors (argparse's convention) and for
any other failure, which is reported in the same form (``--json`` stays JSON).

Writing the report is separate from reading the file, so an output failure is
never reported as a problem with the gzip file. A closed standard output (for
example ``| head -1``) ends the command quietly with status 141, the status a
shell reports for a process ended by ``SIGPIPE``. Any other output failure is
reported on standard error with status 2.
"""

import argparse
import asyncio
import contextlib
import dataclasses
import json
import os
import sys
from typing import Any, List, Optional, TextIO, Tuple

from . import __version__, inspect, verify

# 128 + SIGPIPE (13): what a shell reports for a command ended by a closed
# pipe. Distinct from 1 (invalid file) and 2 (usage or other failure).
_EXIT_CLOSED_STDOUT = 141


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


def _run(args: argparse.Namespace) -> Tuple[int, str, str]:
    """Read the file and return (exit status, stdout text, stderr text).

    Nothing is written here, so the handlers below only ever see failures of
    the scan itself.
    """
    try:
        if args.command == "inspect":
            info = asyncio.run(inspect(args.path))
            if args.json:
                out = json.dumps(
                    {"ok": True, **dataclasses.asdict(info)}, default=_json_default
                )
            else:
                lines = [
                    f"{args.path}: {info.member_count} member(s), "
                    f"{info.compressed_size} bytes compressed, "
                    f"{info.uncompressed_size} bytes uncompressed"
                ]
                for m in info.members:
                    # The name comes from the file's header: repr() keeps
                    # terminal escapes and line breaks in it away from the
                    # terminal.
                    name = repr(m.original_filename) if m.original_filename else "-"
                    lines.append(
                        f"  member {m.index}: offset={m.compressed_offset} "
                        f"compressed={m.compressed_size} "
                        f"uncompressed={m.uncompressed_size} mtime={m.mtime} "
                        f"crc32={m.crc32:#010x} name={name}"
                    )
                out = "\n".join(lines)
        else:
            result = asyncio.run(verify(args.path))
            if args.json:
                out = json.dumps({"ok": True, **dataclasses.asdict(result)})
            else:
                out = (
                    f"OK: {args.path}: {result.member_count} member(s), "
                    f"{result.compressed_size} bytes compressed, "
                    f"{result.uncompressed_size} bytes uncompressed"
                )
        return 0, out, ""
    except (OSError, EOFError) as exc:
        if args.json:
            return 1, json.dumps({"ok": False, "error": str(exc)}), ""
        return 1, "", f"FAILED: {args.path}: {exc}"
    except Exception as exc:
        # Anything else (an internal error) is reported in the same form, so
        # --json output stays parseable, with usage status.
        error = f"{type(exc).__name__}: {exc}"
        if args.json:
            return 2, json.dumps({"ok": False, "error": error}), ""
        return 2, "", f"ERROR: {args.path}: {error}"


def _encodable(text: str, stream: TextIO) -> str:
    """Backslash-escape the characters ``stream`` cannot encode."""
    encoding = getattr(stream, "encoding", None)
    if not encoding:
        return text
    try:
        return text.encode(encoding, "backslashreplace").decode(encoding)
    except (LookupError, UnicodeError):
        return text


def _discard_stdout() -> None:
    """Point stdout at devnull after a failed write.

    The failed text is still buffered, so the flush at interpreter exit would
    fail again, print "Exception ignored" and change the exit status to 120.
    This is the remedy in the Python documentation's note on SIGPIPE.
    """
    with contextlib.suppress(OSError, ValueError):
        devnull = os.open(os.devnull, os.O_WRONLY)
        try:
            os.dup2(devnull, sys.stdout.fileno())
        finally:
            os.close(devnull)


def _emit(status: int, out: str, err: str) -> int:
    """Write the report and return ``status``, unless the output itself fails."""
    if err:
        with contextlib.suppress(OSError, ValueError):
            print(err, file=sys.stderr)
    if not out:
        return status
    try:
        stdout = sys.stdout
        stdout.write(_encodable(out, stdout) + "\n")
        # Flush here, so a closed pipe is seen now and not at interpreter exit.
        stdout.flush()
    except BrokenPipeError:
        # The reader went away: end quietly.
        _discard_stdout()
        return _EXIT_CLOSED_STDOUT
    except (OSError, ValueError) as exc:
        # ValueError covers UnicodeEncodeError and a closed stream object.
        _discard_stdout()
        with contextlib.suppress(OSError, ValueError):
            print(
                f"ERROR: cannot write output: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
        return 2
    return status


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    status, out, err = _run(args)
    return _emit(status, out, err)


if __name__ == "__main__":
    sys.exit(main())
