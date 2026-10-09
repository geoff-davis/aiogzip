#!/usr/bin/env python3
"""Build, check, inventory and smoke the release artifacts from a clean tree.

The wheel and sdist are built with ``uv build`` from a detached worktree of
one commit, so local edits and untracked files cannot leak into them.
``twine check`` validates both. The evidence directory receives the
artifacts, an inventory (each artifact's size, sha256 and member list, and
the exact uv, twine, build backend and interpreter versions), and, for each
artifact, the reports of ``smoke_installed_artifact.py`` and
``run_maintained_examples.py`` run from a fresh venv outside the repository.
Those scripts assert that ``aiogzip`` imports from that venv, then run the
manifest check, the codec, file, streaming, inspect, verify, CLI and aiocsv
smokes, and both maintained examples with their integration tests. For the
sdist, the examples and integration tests run from the extracted sdist,
after its packaged ``examples/`` and ``tests/integration/`` are checked to
match the commit byte for byte; the wheel ships no examples, so its run
uses the worktree copies.

The build backend and twine are pinned by ``scripts/release-constraints.txt``
in the commit being built. Requires ``uv`` on PATH and network access to
install the latest runtime dependencies and the pinned tools.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from collections.abc import Sequence
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
# Exact build backend and twine versions, read from the commit being built.
CONSTRAINTS = Path("scripts") / "release-constraints.txt"
RUNTIME = ("aiofiles", "aiocsv")
TEST_TOOLS = ("pytest", "pytest-asyncio", "pytest-timeout")
# Packaged application code the sdist must carry unchanged.
PACKAGED_TREES = ("examples", "tests/integration")


def _run(
    command: Sequence[str], *, cwd: Path, capture: bool = False
) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(command), flush=True)
    return subprocess.run(
        command, cwd=cwd, check=True, text=True, capture_output=capture
    )


def _output(command: Sequence[str], *, cwd: Path) -> str:
    return _run(command, cwd=cwd, capture=True).stdout.strip()


def _source_version(source: Path) -> str:
    """Read ``__version__`` from the source tree without importing the package.

    Importing ``aiogzip`` needs its runtime dependencies, which the release
    build environment deliberately does not install.
    """
    init = source / "src" / "aiogzip" / "__init__.py"
    match = re.search(
        r'^__version__ = "([^"]+)"$', init.read_text(encoding="utf-8"), re.MULTILINE
    )
    if match is None:
        raise SystemExit(f"no __version__ assignment in {init}")
    return match.group(1)


def _members(artifact: Path) -> list[str]:
    if artifact.suffix == ".whl":
        with zipfile.ZipFile(artifact) as archive:
            return sorted(archive.namelist())
    with tarfile.open(artifact) as archive:
        return sorted(archive.getnames())


def _wheel_generator(wheel: Path) -> str:
    """The build backend and version recorded in the wheel's WHEEL file."""
    with zipfile.ZipFile(wheel) as archive:
        (name,) = [n for n in archive.namelist() if n.endswith(".dist-info/WHEEL")]
        for line in archive.read(name).decode("utf-8").splitlines():
            if line.startswith("Generator:"):
                return line.split(":", 1)[1].strip()
    raise RuntimeError(f"{wheel.name} records no Generator")


def _inventory_entry(artifact: Path) -> dict[str, object]:
    return {
        "name": artifact.name,
        "size": artifact.stat().st_size,
        "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "members": _members(artifact),
    }


def _extract_sdist(sdist: Path, destination: Path) -> Path:
    """Extract the sdist and return its single top-level directory."""
    with tarfile.open(sdist) as archive:
        if sys.version_info >= (3, 12):
            archive.extractall(destination, filter="data")
        else:
            archive.extractall(destination)
    (root,) = [path for path in destination.iterdir() if path.is_dir()]
    return root


def _tree_digests(root: Path, relative: str) -> dict[str, str]:
    base = root / relative
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(base.rglob("*"))
        if path.is_file()
    }


def _require_packaged_trees(packaged: Path, source: Path) -> dict[str, str]:
    """The sdist's examples and integration tests equal the commit's."""
    expected: dict[str, str] = {}
    for relative in PACKAGED_TREES:
        want = _tree_digests(source, relative)
        got = _tree_digests(packaged, relative)
        if not want or got != want:
            raise RuntimeError(
                f"sdist {relative}/ differs from the commit: "
                f"missing {sorted(want.keys() - got.keys())}, "
                f"extra {sorted(got.keys() - want.keys())}, "
                f"changed {sorted(k for k in want.keys() & got.keys() if want[k] != got[k])}"
            )
        expected.update(want)
    return expected


def _venv_python(root: Path) -> Path:
    if sys.platform == "win32":
        return root / "Scripts" / "python.exe"
    return root / "bin" / "python"


def _smoke(
    artifact: Path,
    kind: str,
    *,
    source: Path,
    examples_root: Path,
    version: str,
    python: str,
    scratch: Path,
    evidence: Path,
) -> None:
    """Install one artifact into a fresh venv and run both smoke scripts;
    the maintained examples run from ``examples_root``."""
    environment = scratch / f"venv-{kind}"
    _run(["uv", "venv", "--python", python, str(environment)], cwd=scratch)
    interpreter = str(_venv_python(environment))
    _run(
        ["uv", "pip", "install", "--python", interpreter, *RUNTIME, *TEST_TOOLS],
        cwd=scratch,
    )
    _run(
        ["uv", "pip", "install", "--python", interpreter, "--no-deps", str(artifact)],
        cwd=scratch,
    )
    run_directory = scratch / f"run-{kind}"
    run_directory.mkdir()
    _run(
        [
            interpreter,
            str(source / "scripts" / "smoke_installed_artifact.py"),
            "--expected-version",
            version,
            "--expected-engine",
            "stdlib-zlib",
            "--require-aiocsv",
            "--artifact",
            str(artifact),
            "--artifact-kind",
            kind,
            "--repository-root",
            str(source),
            "--api-script",
            str(source / "scripts" / "capture_public_api.py"),
            "--api-manifest",
            str(source / "tests" / "data" / "public_api_2_0.json"),
            "--report-output",
            str(evidence / f"smoke-{kind}.json"),
        ],
        cwd=run_directory,
    )
    _run(
        [
            interpreter,
            str(source / "scripts" / "run_maintained_examples.py"),
            "--repository-root",
            str(examples_root),
            "--report-output",
            str(evidence / f"examples-{kind}.json"),
        ],
        cwd=run_directory,
    )


def build(ref: str, evidence: Path, python: str) -> dict[str, object]:
    commit = _output(
        ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"], cwd=REPOSITORY
    )
    evidence.mkdir(parents=True, exist_ok=False)
    dist = evidence / "dist"
    with tempfile.TemporaryDirectory(prefix="aiogzip-release-") as directory:
        scratch = Path(directory).resolve()
        source = scratch / "source"
        _run(
            ["git", "worktree", "add", "--detach", str(source), commit],
            cwd=REPOSITORY,
        )
        try:
            _require_clean(source)
            constraints = source / CONSTRAINTS
            if not constraints.is_file():
                raise RuntimeError(f"release build needs {CONSTRAINTS} at {commit}")
            _run(
                [
                    "uv",
                    "build",
                    "--wheel",
                    "--sdist",
                    "--build-constraints",
                    str(constraints),
                    "--out-dir",
                    str(dist),
                    # The release record names every file in dist, and the
                    # publish job's artifact upload drops hidden files.
                    "--no-create-gitignore",
                ],
                cwd=source,
            )
            wheel, sdist = _release_artifacts(dist)
            twine = [
                "uv",
                "tool",
                "run",
                "--constraints",
                str(constraints),
                "--from",
                "twine",
                "twine",
            ]
            _run(
                [*twine, "check", "--strict", str(wheel), str(sdist)],
                cwd=scratch,
            )
            version = _source_version(source)
            packaged = _extract_sdist(sdist, scratch / "sdist")
            packaged_digests = _require_packaged_trees(packaged, source)
            for artifact, kind, examples_root in (
                (wheel, "wheel", source),
                (sdist, "sdist", packaged),
            ):
                _smoke(
                    artifact,
                    kind,
                    source=source,
                    examples_root=examples_root,
                    version=version,
                    python=python,
                    scratch=scratch,
                    evidence=evidence,
                )
            inventory = {
                "commit": commit,
                "version": version,
                "tools": {
                    "uv": _output(["uv", "--version"], cwd=scratch),
                    "twine": " ".join(
                        _output([*twine, "--version"], cwd=scratch).split()
                    ),
                    "backend": _wheel_generator(wheel),
                    "python": _output([python, "--version"], cwd=scratch),
                    "platform": platform.platform(),
                },
                "artifacts": [_inventory_entry(wheel), _inventory_entry(sdist)],
                "sdist_packaged_files": packaged_digests,
                "reports": sorted(
                    path.name for path in evidence.glob("*.json") if path.is_file()
                ),
            }
        finally:
            _run(["git", "worktree", "remove", "--force", str(source)], cwd=REPOSITORY)
    (evidence / "inventory.json").write_text(
        json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return inventory


def _release_artifacts(dist: Path) -> tuple[Path, Path]:
    """The one wheel and one sdist in ``dist``; anything else there fails.

    Every file in ``dist`` is recorded and published, so a stray file (uv's
    ``.gitignore``, say) would either enter the release record or fail it.
    """
    names = sorted(path.name for path in dist.iterdir())
    wheels = [name for name in names if name.endswith(".whl")]
    sdists = [name for name in names if name.endswith(".tar.gz")]
    if len(wheels) != 1 or len(sdists) != 1 or len(names) != 2:
        raise RuntimeError(f"expected exactly one wheel and one sdist: {names}")
    return dist / wheels[0], dist / sdists[0]


def _require_clean(source: Path) -> None:
    status = _output(["git", "status", "--porcelain", "--ignored"], cwd=source)
    if status:
        raise RuntimeError(f"release worktree is not clean:\n{status}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", default="HEAD", help="commit to build (default HEAD)")
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        required=True,
        help="new directory for artifacts, inventory and smoke reports",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="interpreter for the smoke venvs (default: this one)",
    )
    args = parser.parse_args(argv)
    if shutil.which("uv") is None:
        raise RuntimeError("uv is required on PATH")
    evidence = args.evidence_dir.resolve()
    if evidence.is_relative_to(REPOSITORY):
        raise RuntimeError(f"evidence directory is inside the repository: {evidence}")
    inventory = build(args.ref, evidence, args.python)
    print(
        json.dumps({k: inventory[k] for k in ("commit", "version", "tools")}, indent=2)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
