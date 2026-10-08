#!/usr/bin/env python3
"""Check that a directory holds exactly the release artifacts a record names.

The record is a ``sha256sum``-style file (``<sha256>  <filename>`` per line,
``#`` comments allowed) committed during release preparation as
``plans/releases/v<version>.sha256``. The directory must contain every named
file with the recorded SHA-256 and nothing else, so an altered, missing,
renamed or extra artifact can never reach the upload step.

``--write`` instead records the directory's files, for release preparation.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from collections.abc import Sequence
from pathlib import Path

_LINE = re.compile(r"^(?P<digest>[0-9a-f]{64}) [ *](?P<name>[^/\\\s][^/\\]*)$")


class RecordError(Exception):
    """The artifacts do not match the release record."""


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_record(record: Path) -> dict[str, str]:
    """Parse a record into ``{filename: sha256}``; reject anything malformed."""
    entries: dict[str, str] = {}
    for number, line in enumerate(record.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = _LINE.match(line)
        if match is None:
            raise RecordError(f"{record}:{number}: malformed record line: {line!r}")
        name = match["name"]
        if name in entries:
            raise RecordError(f"{record}:{number}: duplicate entry for {name}")
        entries[name] = match["digest"]
    if not entries:
        raise RecordError(f"{record}: no artifacts recorded")
    return entries


def _artifacts(directory: Path) -> dict[str, Path]:
    if not directory.is_dir():
        raise RecordError(f"{directory}: not a directory")
    found: dict[str, Path] = {}
    for path in sorted(directory.iterdir()):
        if path.is_symlink() or not path.is_file():
            raise RecordError(f"{path}: not a regular file")
        found[path.name] = path
    return found


def verify(directory: Path, record: Path) -> dict[str, str]:
    """Return the verified ``{filename: sha256}`` or raise ``RecordError``."""
    expected = read_record(record)
    found = _artifacts(directory)
    problems = [f"missing: {name}" for name in sorted(expected.keys() - found)]
    problems += [f"unrecorded: {name}" for name in sorted(found.keys() - expected)]
    for name in sorted(expected.keys() & found.keys()):
        actual = _digest(found[name])
        if actual != expected[name]:
            problems.append(f"sha256 mismatch: {name}: {actual} != {expected[name]}")
    if problems:
        raise RecordError(
            f"{directory} does not match {record}:\n  " + "\n  ".join(problems)
        )
    return expected


def write_record(directory: Path, record: Path) -> None:
    lines = [f"{_digest(path)}  {name}" for name, path in _artifacts(directory).items()]
    if not lines:
        raise RecordError(f"{directory}: no artifacts to record")
    record.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="directory of artifacts")
    parser.add_argument("record", type=Path, help="sha256sum-style release record")
    parser.add_argument(
        "--write", action="store_true", help="write the record instead of checking"
    )
    args = parser.parse_args(argv)
    try:
        if args.write:
            write_record(args.directory, args.record)
            print(f"recorded {args.directory} in {args.record}")
        else:
            for name, digest in verify(args.directory, args.record).items():
                print(f"verified {digest}  {name}")
    except (OSError, RecordError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
