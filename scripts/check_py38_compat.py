#!/usr/bin/env python3
"""Fail if source files use PEP 585 generics or PEP 604 unions.

Those syntaxes are Python 3.9+/3.10+ only and break the library's
declared support for Python 3.8.
"""

from __future__ import annotations

import re
import sys
import tokenize
from pathlib import Path

# Builtin generic subscripts: tuple[...], list[...], dict[...], set[...],
# frozenset[...], type[...], PathLike[...]
_PEP585 = re.compile(
    r"(?<![A-Za-z_.])"
    r"(?:tuple|list|dict|set|frozenset|type|PathLike)"
    r"\s*\["
)

# Union operator on common builtins: `int | None`, `str | bytes`, etc.
# This is a heuristic; it only catches the most common forms.
_PEP604 = re.compile(
    r"(?<![A-Za-z_.])"
    r"(?:int|str|bytes|float|bool|bytearray|memoryview|dict|list|tuple|set)"
    r"\s*\|\s*"
    r"(?:None|int|str|bytes|float|bool|bytearray|memoryview|dict|list|tuple|set)"
    r"(?![A-Za-z_])"
)


def _scan(path: Path) -> list[tuple[int, str, str]]:
    """Return (lineno, rule, line) for offending lines in *path*."""
    # Use tokenize to skip string literals and comments.
    problems: list[tuple[int, str, str]] = []
    with path.open("rb") as fh:
        try:
            tokens = list(tokenize.tokenize(fh.readline))
        except tokenize.TokenizeError:
            return problems

    lines = path.read_text(encoding="utf-8").splitlines()
    scrubbed = list(lines)
    for tok in tokens:
        if tok.type in (tokenize.STRING, tokenize.COMMENT):
            start_row, start_col = tok.start
            end_row, end_col = tok.end
            for row in range(start_row, end_row + 1):
                line = scrubbed[row - 1]
                left = start_col if row == start_row else 0
                right = end_col if row == end_row else len(line)
                scrubbed[row - 1] = line[:left] + (" " * (right - left)) + line[right:]

    for idx, line in enumerate(scrubbed, start=1):
        if _PEP585.search(line):
            problems.append((idx, "PEP 585 generic", lines[idx - 1].rstrip()))
        if _PEP604.search(line):
            problems.append((idx, "PEP 604 union", lines[idx - 1].rstrip()))
    return problems


def main(argv: list[str]) -> int:
    bad = 0
    for arg in argv:
        path = Path(arg)
        if not path.is_file():
            continue
        for lineno, rule, line in _scan(path):
            print(f"{path}:{lineno}: {rule} (Python 3.9+): {line}")
            bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
