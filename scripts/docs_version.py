#!/usr/bin/env python3
"""Print the mike docs version and deploy kind for an aiogzip version.

Prints ``<major.minor> <kind>``, where kind is ``stable``, ``prerelease`` or
``dev``. The docs workflow deploys a stable or prerelease version on ``main``
to its ``major.minor`` docs version, and a development version to the single
``dev`` docs version, so ``latest`` never serves development builds.
Maintenance branches deploy every version to its ``major.minor``.
"""

from __future__ import annotations

import sys

from packaging.version import Version


def docs_version(version: str) -> tuple[str, str]:
    parsed = Version(version)
    major, minor = (parsed.release + (0,))[:2]
    if parsed.is_devrelease:
        kind = "dev"
    elif parsed.is_prerelease:
        kind = "prerelease"
    else:
        kind = "stable"
    return f"{major}.{minor}", kind


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: docs_version.py VERSION", file=sys.stderr)
        return 2
    print(*docs_version(argv[0]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
