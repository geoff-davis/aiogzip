"""The CI runtime attestation's exact-floor and unpinned (--latest) modes."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

import aiogzip

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "report_runtime_versions.py"


@pytest.fixture
def runtime_report(monkeypatch):
    spec = importlib.util.spec_from_file_location("report_runtime_versions", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    installed = {"aiogzip": aiogzip.__version__}
    monkeypatch.setattr(module, "_version", installed.get)
    monkeypatch.setattr(
        aiogzip,
        "engine_info",
        lambda: aiogzip.EngineInfo(
            compression="stdlib-zlib", decompression="stdlib-zlib", crc32="stdlib-zlib"
        ),
    )
    return module, installed


def test_latest_accepts_any_installed_version(runtime_report):
    module, installed = runtime_report
    installed.update({"aiofiles": "99.0", "aiocsv": "99.0"})
    result = module.report("csv", require_installed_artifact=False, latest=True)
    assert result["latest"] is True
    assert result["versions"]["aiofiles"] == "99.0"


def test_floor_mode_still_pins_exact_versions(runtime_report):
    module, installed = runtime_report
    installed.update({"aiofiles": "99.0", "aiocsv": "99.0"})
    with pytest.raises(RuntimeError, match="aiofiles version mismatch"):
        module.report("csv", require_installed_artifact=False)


def test_latest_requires_each_mode_distribution(runtime_report):
    module, installed = runtime_report
    installed["aiofiles"] = "99.0"
    with pytest.raises(RuntimeError, match="aiocsv must be installed"):
        module.report("csv", require_installed_artifact=False, latest=True)


def test_latest_allows_aiocsv_outside_csv_mode(runtime_report):
    module, installed = runtime_report
    installed.update({"aiofiles": "99.0", "aiocsv": "99.0"})
    module.report("base", require_installed_artifact=False, latest=True)
    installed["aiofiles"] = "23.2.1"
    with pytest.raises(RuntimeError, match="aiocsv must be absent"):
        module.report("base", require_installed_artifact=False)


def test_latest_still_forbids_zlib_ng_outside_fast_modes(runtime_report):
    module, installed = runtime_report
    installed.update({"aiofiles": "99.0", "aiocsv": "99.0", "zlib-ng": "1.0"})
    with pytest.raises(RuntimeError, match="zlib-ng must be absent"):
        module.report("csv", require_installed_artifact=False, latest=True)


def test_latest_still_checks_the_engine(runtime_report):
    module, installed = runtime_report
    installed.update({"aiofiles": "99.0", "zlib-ng": "1.0"})
    with pytest.raises(RuntimeError, match="decompression engine mismatch"):
        module.report("fast", require_installed_artifact=False, latest=True)
