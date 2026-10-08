"""R05: only the exact recorded release artifacts can reach the upload step."""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_release_artifacts.py"
WHEEL = "aiogzip-9.9.9-py3-none-any.whl"
SDIST = "aiogzip-9.9.9.tar.gz"


@pytest.fixture(scope="module")
def verifier():
    spec = importlib.util.spec_from_file_location("verify_release_artifacts", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def dist(tmp_path):
    directory = tmp_path / "dist"
    directory.mkdir()
    (directory / WHEEL).write_bytes(b"wheel bytes")
    (directory / SDIST).write_bytes(b"sdist bytes")
    return directory


def _record(tmp_path, lines):
    record = tmp_path / "v9.9.9.sha256"
    record.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    return record


def _line(name, data):
    return f"{hashlib.sha256(data).hexdigest()}  {name}"


@pytest.fixture
def record(tmp_path):
    return _record(
        tmp_path,
        ["# aiogzip 9.9.9", _line(WHEEL, b"wheel bytes"), _line(SDIST, b"sdist bytes")],
    )


def test_exact_artifacts_verify(verifier, dist, record):
    assert verifier.verify(dist, record) == {
        WHEEL: hashlib.sha256(b"wheel bytes").hexdigest(),
        SDIST: hashlib.sha256(b"sdist bytes").hexdigest(),
    }
    assert verifier.main([str(dist), str(record)]) == 0


def test_an_altered_artifact_is_refused(verifier, dist, record, capsys):
    path = dist / SDIST
    data = bytearray(path.read_bytes())
    data[0] ^= 0x01
    path.write_bytes(bytes(data))
    with pytest.raises(verifier.RecordError, match=f"sha256 mismatch: {SDIST}"):
        verifier.verify(dist, record)
    assert verifier.main([str(dist), str(record)]) == 1
    assert "sha256 mismatch" in capsys.readouterr().err


def test_a_missing_artifact_is_refused(verifier, dist, record):
    (dist / WHEEL).unlink()
    with pytest.raises(verifier.RecordError, match=f"missing: {WHEEL}"):
        verifier.verify(dist, record)


@pytest.mark.parametrize("extra", ["aiogzip-9.9.9-1-py3-none-any.whl", ".hidden"])
def test_an_unrecorded_file_is_refused(verifier, dist, record, extra):
    (dist / extra).write_bytes(b"wheel bytes")
    with pytest.raises(verifier.RecordError, match=f"unrecorded: {extra}"):
        verifier.verify(dist, record)


def test_a_renamed_artifact_is_refused(verifier, dist, record):
    (dist / SDIST).rename(dist / "aiogzip-9.9.8.tar.gz")
    with pytest.raises(verifier.RecordError) as caught:
        verifier.verify(dist, record)
    assert f"missing: {SDIST}" in str(caught.value)
    assert "unrecorded: aiogzip-9.9.8.tar.gz" in str(caught.value)


def test_a_symlinked_artifact_is_refused(verifier, dist, record, tmp_path):
    target = tmp_path / "elsewhere"
    target.write_bytes(b"wheel bytes")
    (dist / WHEEL).unlink()
    (dist / WHEEL).symlink_to(target)
    with pytest.raises(verifier.RecordError, match="not a regular file"):
        verifier.verify(dist, record)


@pytest.mark.parametrize(
    "lines, message",
    [
        ([], "no artifacts recorded"),
        (["# only a comment"], "no artifacts recorded"),
        ([f"{'0' * 63}  {WHEEL}"], "malformed"),
        ([f"{'A' * 64}  {WHEEL}"], "malformed"),
        ([f"{'0' * 64} {WHEEL}"], "malformed"),
        ([f"{'0' * 64}  ../{WHEEL}"], "malformed"),
        ([f"{'0' * 64}  sub/{WHEEL}"], "malformed"),
        ([_line(WHEEL, b"x"), _line(WHEEL, b"y")], "duplicate"),
    ],
)
def test_a_malformed_record_is_refused(verifier, dist, tmp_path, lines, message):
    with pytest.raises(verifier.RecordError, match=message):
        verifier.verify(dist, _record(tmp_path, lines))


def test_a_binary_mode_marker_is_accepted(verifier, dist, tmp_path):
    record = _record(
        tmp_path,
        [
            _line(WHEEL, b"wheel bytes").replace("  ", " *"),
            _line(SDIST, b"sdist bytes"),
        ],
    )
    verifier.verify(dist, record)


def test_write_then_verify_round_trips(verifier, dist, tmp_path):
    record = tmp_path / "written.sha256"
    assert verifier.main([str(dist), str(record), "--write"]) == 0
    assert record.read_text(encoding="utf-8") == (
        _line(WHEEL, b"wheel bytes") + "\n" + _line(SDIST, b"sdist bytes") + "\n"
    )
    verifier.verify(dist, record)


def test_a_missing_record_fails_cleanly(verifier, dist, tmp_path, capsys):
    assert verifier.main([str(dist), str(tmp_path / "absent.sha256")]) == 1
    assert "error:" in capsys.readouterr().err


def test_release_records_are_not_packaged():
    # A record inside the sdist would change the sdist hash it records.
    import tomllib

    root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    included = pyproject["tool"]["flit"]["sdist"]["include"]
    assert not [entry for entry in included if entry.startswith("plans")]
    assert (root / "plans" / "releases" / "README.md").is_file()
