#!/usr/bin/env python3
"""Report and enforce aiogzip's exact minimum-runtime CI environments."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
from pathlib import Path, PurePath

import aiogzip

_EXPECTED_VERSIONS = {
    "base": {"aiofiles": "23.2.1"},
    "csv": {"aiofiles": "23.2.1", "aiocsv": "1.2.3"},
    "fast": {"aiofiles": "23.2.1", "zlib-ng": "0.4.0"},
    "fast-forced-stdlib": {"aiofiles": "23.2.1", "zlib-ng": "0.4.0"},
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _version(distribution: str) -> str | None:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None


def _is_source_checkout(module_path: PurePath) -> bool:
    parts = tuple(part.casefold() for part in module_path.parts)
    return any(
        parts[index : index + 2] == ("src", "aiogzip")
        for index in range(len(parts) - 1)
    )


def report(mode: str, *, require_installed_artifact: bool) -> dict[str, object]:
    """Return the environment report after enforcing one exact floor mode."""
    expected = _EXPECTED_VERSIONS[mode]
    versions = {
        distribution: _version(distribution)
        for distribution in ("aiogzip", "aiofiles", "aiocsv", "zlib-ng")
    }

    for distribution, expected_version in expected.items():
        actual = versions[distribution]
        _require(
            actual == expected_version,
            f"{distribution} version mismatch: {actual!r} != {expected_version!r}",
        )

    for distribution in {"aiocsv", "zlib-ng"} - expected.keys():
        _require(
            versions[distribution] is None,
            f"{distribution} must be absent in {mode} mode, got "
            f"{versions[distribution]!r}",
        )

    _require(
        versions["aiogzip"] == aiogzip.__version__,
        "aiogzip import and distribution versions differ: "
        f"{aiogzip.__version__!r} != {versions['aiogzip']!r}",
    )

    package_path = Path(aiogzip.__file__).resolve()
    if require_installed_artifact:
        _require(
            not _is_source_checkout(package_path),
            f"aiogzip imported from the source checkout: {package_path}",
        )

    engine = aiogzip.engine_info()
    expected_engine = "zlib-ng" if mode == "fast" else "stdlib-zlib"
    _require(
        engine.decompression == expected_engine,
        "decompression engine mismatch: "
        f"{engine.decompression!r} != {expected_engine!r}",
    )
    if mode == "fast-forced-stdlib":
        _require(
            os.environ.get("AIOGZIP_ENGINE", "").strip().lower() == "stdlib",
            "fast-forced-stdlib mode requires AIOGZIP_ENGINE=stdlib",
        )

    return {
        "mode": mode,
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "package_path": str(package_path),
        "versions": versions,
        "engine": {
            "compression": engine.compression,
            "decompression": engine.decompression,
            "crc32": engine.crc32,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=sorted(_EXPECTED_VERSIONS), required=True)
    parser.add_argument(
        "--require-installed-artifact",
        action="store_true",
        help="fail if aiogzip resolves from a src/aiogzip checkout",
    )
    parser.add_argument("--output", type=Path, help="also write the report as JSON")
    args = parser.parse_args()

    rendered = (
        json.dumps(
            report(
                args.mode, require_installed_artifact=args.require_installed_artifact
            ),
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    print(rendered, end="")
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
