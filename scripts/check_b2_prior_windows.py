#!/usr/bin/env python3
"""Allow a fallback timing window only if no earlier window started a series.

Used as a systemd ExecCondition. Exit 0 permits the fallback; exit 1 skips it.
A fallback may run only when every earlier window either never initialized or
ended deferred with all block slots unstarted. Anything else, including a
started, failed, running or unreadable window, needs review instead.
"""

import argparse
import json
import sys
from pathlib import Path


def blocker(directory):
    """Return why this earlier window prevents a fallback, or None."""
    if not directory.exists():
        # The runner creates its output before any command, so no series exists.
        return None
    try:
        state = json.loads((directory / "status.json").read_text(encoding="utf-8"))
        if state["status"] != "deferred":
            return f"status is {state['status']!r}, not 'deferred'"
        # Every declared slot must be present; a truncated record proves nothing.
        declared = [block["id"] for block in state["manifest"]["blocks"]]
        slots = state["blocks"]
        if (
            not declared
            or type(slots) is not list
            or [slot["id"] for slot in slots] != declared
        ):
            return "block slots do not match the embedded manifest"
        if any(
            slot["status"] != "unstarted" or slot["captures"] != [] for slot in slots
        ):
            return "a measurement block started"
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return f"unreadable status: {type(exc).__name__}: {exc}"
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("earlier", type=Path, nargs="+")
    args = parser.parse_args()
    for directory in args.earlier:
        if not directory.is_absolute():
            parser.error("earlier window outputs must be absolute paths")
        reason = blocker(directory)
        if reason is not None:
            print(f"Skipping fallback: {directory}: {reason}", flush=True)
            return 1
    print("No earlier window started a series; fallback permitted.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
