#!/usr/bin/env python3
"""Run maintained examples and their failure suites against installed aiogzip."""

from __future__ import annotations

import argparse
import ast
import importlib.metadata
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

import aiogzip

EXAMPLE_NAMES = ("fragmented_transport.py", "concurrent_jsonl_ingest.py")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def validate_public_imports(paths: Sequence[Path]) -> None:
    """Reject examples that import an aiogzip private module directly."""
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                modules.append(node.module)
            for module in modules:
                _require(
                    not module.startswith("aiogzip._")
                    and module not in {"src.aiogzip", "src.aiogzip.codec"},
                    f"{path} imports private aiogzip module {module!r}",
                )


def _run(command: Sequence[str], *, cwd: Path, environment: dict[str, str]) -> None:
    subprocess.run(command, cwd=cwd, env=environment, check=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--report-output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    repository = args.repository_root.resolve()
    examples = tuple(repository / "examples" / name for name in EXAMPLE_NAMES)
    for example in examples:
        _require(example.is_file(), f"maintained example is missing: {example}")
    validate_public_imports(examples)

    package_path = Path(aiogzip.__file__).resolve()
    environment_root = Path(sys.prefix).resolve()
    _require(
        _is_relative_to(package_path, environment_root),
        f"aiogzip is outside the clean environment: {package_path}",
    )
    _require(
        not _is_relative_to(package_path, repository),
        f"maintained examples imported aiogzip from the repository: {package_path}",
    )

    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    with tempfile.TemporaryDirectory(prefix="aiogzip-example-run-") as directory:
        workdir = Path(directory)
        _require(
            not _is_relative_to(workdir.resolve(), repository),
            f"example working directory is inside repository: {workdir}",
        )
        _run(
            [sys.executable, str(examples[0]), "--self-test"],
            cwd=workdir,
            environment=environment,
        )
        _run(
            [
                sys.executable,
                str(examples[1]),
                "--generate-fixtures",
                str(workdir / "input"),
                "--output",
                str(workdir / "output"),
            ],
            cwd=workdir,
            environment=environment,
        )
        _run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                str(
                    repository
                    / "tests/integration/test_example_fragmented_transport.py"
                ),
                str(
                    repository
                    / "tests/integration/test_example_concurrent_jsonl_ingest.py"
                ),
            ],
            cwd=workdir,
            environment=environment,
        )

    report = {
        "version": aiogzip.__version__,
        "metadata_version": importlib.metadata.version("aiogzip"),
        "python": sys.version.split()[0],
        "package_path": str(package_path),
        "examples": [str(path) for path in examples],
        "scenarios": [
            "success",
            "corruption",
            "truncation",
            "cancellation",
            "limits",
            "cleanup",
        ],
    }
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    print(rendered, end="")
    if args.report_output is not None:
        args.report_output.parent.mkdir(parents=True, exist_ok=True)
        args.report_output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
