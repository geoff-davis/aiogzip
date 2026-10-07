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
smokes, and both maintained examples with their integration tests.

Requires ``uv`` on PATH and network access to install the latest runtime
dependencies and twine.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from collections.abc import Sequence
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
RUNTIME = ("aiofiles", "aiocsv")
TEST_TOOLS = ("pytest", "pytest-asyncio", "pytest-timeout")


def _run(
    command: Sequence[str], *, cwd: Path, capture: bool = False
) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(command), flush=True)
    return subprocess.run(
        command, cwd=cwd, check=True, text=True, capture_output=capture
    )


def _output(command: Sequence[str], *, cwd: Path) -> str:
    return _run(command, cwd=cwd, capture=True).stdout.strip()


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


def _venv_python(root: Path) -> Path:
    if sys.platform == "win32":
        return root / "Scripts" / "python.exe"
    return root / "bin" / "python"


def _smoke(
    artifact: Path,
    kind: str,
    *,
    source: Path,
    version: str,
    python: str,
    scratch: Path,
    evidence: Path,
) -> None:
    """Install one artifact into a fresh venv and run both smoke scripts."""
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
            str(source),
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
            _run(
                ["uv", "build", "--wheel", "--sdist", "--out-dir", str(dist)],
                cwd=source,
            )
            wheels = sorted(dist.glob("*.whl"))
            sdists = sorted(dist.glob("*.tar.gz"))
            if len(wheels) != 1 or len(sdists) != 1:
                raise RuntimeError(
                    f"expected one wheel and one sdist: {wheels + sdists}"
                )
            twine = ["uv", "tool", "run", "--from", "twine", "twine"]
            _run(
                [*twine, "check", "--strict", str(wheels[0]), str(sdists[0])],
                cwd=scratch,
            )
            version = _output(
                [
                    python,
                    "-c",
                    "import sys; sys.path.insert(0, 'src'); "
                    "import aiogzip; print(aiogzip.__version__)",
                ],
                cwd=source,
            )
            for artifact, kind in ((wheels[0], "wheel"), (sdists[0], "sdist")):
                _smoke(
                    artifact,
                    kind,
                    source=source,
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
                    "backend": _wheel_generator(wheels[0]),
                    "python": _output([python, "--version"], cwd=scratch),
                    "platform": platform.platform(),
                },
                "artifacts": [_inventory_entry(wheels[0]), _inventory_entry(sdists[0])],
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
