"""Exact diagnostics for the negative typing fixtures (G15).

Each ``EXPECT_ERROR`` marker names the error code each release checker must
report on that line, as ``# EXPECT_ERROR[mypy=<code>, ty=<code>]``. A fixture
passes only when the checker reports exactly that set of (line, code) pairs:
a missing error, an extra or unexpected one, a different code, or a
diagnostic in another file fails. A malformed marker, or an error or warning
line that cannot be parsed, fails rather than being skipped.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

CHECKERS = ("mypy", "ty")
MARKER = re.compile(r"#\s*EXPECT_ERROR\[(?P<codes>[^\]]*)\]")
# An error or warning line from either checker's concise output. The path may
# start with a Windows drive (``D:\a\...``); ``rest`` follows the position.
DIAGNOSTIC = re.compile(
    r"^(?P<path>(?:[A-Za-z]:)?[^:\n]+):(?P<line>\d+):(?:\d+:)?"
    r"(?P<rest> (?:error|warning)\b.*)$"
)
# What any error or warning line looks like, parsed or not.
SEVERITY = re.compile(r"(?:^|:\s)(?:error|warning)\b")
CODE = {
    "mypy": re.compile(r"\s\s\[(?P<code>[\w-]+)\]$"),
    "ty": re.compile(r"^ (?:error|warning)\[(?P<code>[\w-]+)\]"),
}


def _codes(text: str) -> dict[str, str] | None:
    """The marker's checker codes, or None unless each checker has exactly
    one non-empty code and nothing else is named."""
    pairs = [[part.strip() for part in item.split("=", 1)] for item in text.split(",")]
    names = [pair[0] for pair in pairs]
    if sorted(names) != sorted(CHECKERS):
        return None
    if not all(len(pair) == 2 and pair[1] for pair in pairs):
        return None
    return {name: code for name, code in pairs}


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
        codes = _codes(match["codes"])
        if codes is None:
            raise AssertionError(f"{path.name}:{number}: need one code per checker")
        found.add((number, codes[checker]))
    return found


def reported(output: str, checker: str, path_argument: str) -> set[tuple[int, str]]:
    """Every diagnostic in ``output`` as (line, code); any diagnostic outside
    ``path_argument`` (compared resolved from the working directory, which
    must be the checker's), without a code, or unparsed fails."""
    found = set()
    for text in output.splitlines():
        match = DIAGNOSTIC.match(text)
        if match is None:
            assert SEVERITY.search(text) is None, f"{checker}: unparsed: {text}"
            continue
        same = Path(match["path"]).resolve() == Path(path_argument).resolve()
        assert same, f"{checker}: other file: {text}"
        code = CODE[checker].search(match["rest"])
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
