"""Exact diagnostics for the negative typing fixtures (G15).

Each ``EXPECT_ERROR`` marker names the error code each release checker must
report on that line, as ``# EXPECT_ERROR[mypy=<code>, ty=<code>]``. A fixture
passes only when the checker reports exactly that set of (line, code) pairs:
a missing error, an extra or unexpected one, a different code, or a
diagnostic in another file fails.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

CHECKERS = ("mypy", "ty")
MARKER = re.compile(r"#\s*EXPECT_ERROR\[(?P<codes>[^\]]*)\]")
# Any error or warning line, from either checker's concise output.
DIAGNOSTIC = re.compile(
    r"^(?P<path>[^\s:][^:\n]*):(?P<line>\d+):(?:\d+:)? (?:error|warning)\b.*$",
    re.M,
)
CODE = {
    "mypy": re.compile(r"\s\s\[(?P<code>[\w-]+)\]$"),
    "ty": re.compile(r"^\S+ (?:error|warning)\[(?P<code>[\w-]+)\]"),
}


def expected(path: Path, checker: str) -> set[tuple[int, str]]:
    """The (line, code) pairs ``checker`` must report for ``path``."""
    found = set()
    lines = path.read_text(encoding="utf-8").splitlines()
    for number, line in enumerate(lines, start=1):
        if "EXPECT_ERROR" not in line:
            continue
        match = MARKER.search(line)
        if match is None:
            raise AssertionError(f"{path.name}:{number}: EXPECT_ERROR has no codes")
        codes = dict(
            (part.strip() for part in item.split("=", 1))
            for item in match["codes"].split(",")
        )
        if set(codes) != set(CHECKERS) or not all(codes.values()):
            raise AssertionError(f"{path.name}:{number}: need a code per checker")
        found.add((number, codes[checker]))
    return found


def reported(output: str, checker: str, path_argument: str) -> set[tuple[int, str]]:
    """Every diagnostic in ``output`` as (line, code); any diagnostic outside
    ``path_argument`` (compared resolved from the working directory, which
    must be the checker's) or without a code fails."""
    found = set()
    for match in DIAGNOSTIC.finditer(output):
        text = match.group(0)
        same = Path(match["path"]).resolve() == Path(path_argument).resolve()
        assert same, f"{checker}: other file: {text}"
        code = CODE[checker].search(text)
        assert code is not None, f"{checker}: no error code: {text}"
        found.add((int(match["line"]), code["code"]))
    return found


def version(checker: str) -> str:
    result = subprocess.run(
        [sys.executable, "-m", checker, "--version"],
        capture_output=True,
        text=True,
    )
    return (result.stdout or result.stderr).strip()
