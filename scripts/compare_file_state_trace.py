#!/usr/bin/env python3
"""Compare semantic traces; exceptions match exact scenario-specific before/after values."""

import argparse
import json
from pathlib import Path


def compare(before, after, exceptions=None):
    exceptions = exceptions or {}
    if before["fixture_sha256"] != after["fixture_sha256"]:
        raise ValueError("trace fixtures differ")
    differences = []
    for name in sorted(before["semantic"].keys() | after["semantic"].keys()):
        old, new = before["semantic"].get(name), after["semantic"].get(name)
        if old == new:
            continue
        allowed = exceptions.get(name, {})
        exception_id = (
            allowed.get("exception_id")
            if (allowed.get("before") == old and allowed.get("after") == new)
            else None
        )
        differences.append(
            {
                "scenario": name,
                "before": old,
                "after": new,
                "exception_id": exception_id,
            }
        )
    return {
        "passed": all(row["exception_id"] for row in differences),
        "differences": differences,
        "diagnostics_equal": before.get("diagnostic") == after.get("diagnostic"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("--exceptions", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    def read(path):
        return json.loads(path.read_text(encoding="utf-8"))

    result = compare(
        read(args.before),
        read(args.after),
        read(args.exceptions) if args.exceptions else None,
    )
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(result, output, indent=2)
        output.write("\n")
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
