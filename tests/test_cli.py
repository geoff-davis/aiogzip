"""Tests for the ``python -m aiogzip`` command-line interface."""

import gzip
import json
import subprocess
import sys

import pytest

from aiogzip import __version__
from aiogzip.__main__ import main

PAYLOAD = b"hello world\n" * 100


@pytest.fixture
def good_gz(tmp_path):
    path = tmp_path / "good.gz"
    with gzip.open(path, "wb") as f:
        f.write(PAYLOAD)
    return path


@pytest.fixture
def corrupt_gz(tmp_path, good_gz):
    path = tmp_path / "bad.gz"
    raw = good_gz.read_bytes()
    # Zero out the trailer (CRC32 + ISIZE) so the payload decodes but fails
    # integrity validation.
    path.write_bytes(raw[:-8] + b"\x00" * 8)
    return path


class TestVerifyCommand:
    def test_ok_exit_zero_and_summary(self, good_gz, capsys):
        assert main(["verify", str(good_gz)]) == 0
        out = capsys.readouterr().out
        assert out.startswith("OK: ")
        assert "1 member(s)" in out
        assert f"{len(PAYLOAD)} bytes uncompressed" in out

    def test_ok_json_shape(self, good_gz, capsys):
        assert main(["verify", str(good_gz), "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data == {
            "ok": True,
            "member_count": 1,
            "compressed_size": good_gz.stat().st_size,
            "uncompressed_size": len(PAYLOAD),
        }

    def test_corrupt_exit_one_and_stderr(self, corrupt_gz, capsys):
        assert main(["verify", str(corrupt_gz)]) == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err.startswith("FAILED: ")
        assert "CRC" in captured.err

    def test_corrupt_json_reports_error(self, corrupt_gz, capsys):
        assert main(["verify", str(corrupt_gz), "--json"]) == 1
        data = json.loads(capsys.readouterr().out)
        assert data["ok"] is False
        assert "CRC" in data["error"]

    def test_missing_file_exit_one(self, tmp_path, capsys):
        assert main(["verify", str(tmp_path / "missing.gz")]) == 1
        assert "FAILED" in capsys.readouterr().err


class TestInspectCommand:
    def test_human_output_lists_members(self, good_gz, capsys):
        assert main(["inspect", str(good_gz)]) == 0
        out = capsys.readouterr().out
        assert "1 member(s)" in out
        assert "member 0:" in out
        assert f"uncompressed={len(PAYLOAD)}" in out

    def test_json_matches_inspect_dataclass(self, good_gz, capsys):
        assert main(["inspect", str(good_gz), "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["uncompressed_size"] == len(PAYLOAD)
        assert len(data["members"]) == 1
        member = data["members"][0]
        assert member["index"] == 0
        assert member["trailer_isize"] == len(PAYLOAD)

    def test_json_encodes_extra_bytes_as_hex(self, tmp_path, capsys):
        # Hand-build a member with an FEXTRA field (FLG bit 2).
        payload = b"x"
        body = gzip.compress(payload)
        extra = b"\xde\xad"
        xlen = len(extra).to_bytes(2, "little")
        raw = body[:3] + b"\x04" + body[4:10] + xlen + extra + body[10:]
        path = tmp_path / "extra.gz"
        path.write_bytes(raw)
        assert main(["inspect", str(path), "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["members"][0]["extra"] == "dead"

    def test_corrupt_exit_one(self, corrupt_gz, capsys):
        assert main(["inspect", str(corrupt_gz)]) == 1
        assert "FAILED" in capsys.readouterr().err


class TestUsage:
    def test_no_command_is_usage_error(self, capsys):
        with pytest.raises(SystemExit) as excinfo:
            main([])
        assert excinfo.value.code == 2

    def test_unknown_command_is_usage_error(self, capsys):
        with pytest.raises(SystemExit) as excinfo:
            main(["bogus"])
        assert excinfo.value.code == 2

    def test_version_flag(self, capsys):
        with pytest.raises(SystemExit) as excinfo:
            main(["--version"])
        assert excinfo.value.code == 0
        assert capsys.readouterr().out.strip() == __version__

    def test_module_entry_point_runs(self, good_gz):
        proc = subprocess.run(
            [sys.executable, "-m", "aiogzip", "verify", str(good_gz)],
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0
        assert proc.stdout.startswith("OK: ")
