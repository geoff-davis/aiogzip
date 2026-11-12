"""Tests for the ``python -m aiogzip`` command-line interface."""

import dataclasses
import errno
import gzip
import json
import os
import subprocess
import sys

import pytest

from aiogzip import GzipInfo, __version__
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


def _named_gz(path, name: bytes, payload: bytes = b"x"):
    """Write a one-member gzip file whose FNAME field (FLG bit 3) is ``name``."""
    body = gzip.compress(payload)
    path.write_bytes(body[:3] + b"\x08" + body[4:10] + name + b"\x00" + body[10:])
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
        # 2.0.2 (review C8): success carries "ok": true, as verify --json
        # does, next to every field of the inspect dataclass.
        assert data["ok"] is True
        assert set(data) == {"ok"} | {f.name for f in dataclasses.fields(GzipInfo)}
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

    def test_corrupt_json_reports_error(self, corrupt_gz, capsys):
        assert main(["inspect", str(corrupt_gz), "--json"]) == 1
        data = json.loads(capsys.readouterr().out)
        assert data["ok"] is False
        assert "CRC" in data["error"]

    def test_human_output_escapes_header_name(self, tmp_path, capsys):
        # A header name with a terminal escape and a forged second line.
        path = _named_gz(tmp_path / "esc.gz", b"\x1b[31mred\nFAILED: forged")
        assert main(["inspect", str(path)]) == 0
        out = capsys.readouterr().out
        assert "\x1b" not in out
        assert len(out.splitlines()) == 2
        assert out.endswith("name='\\x1b[31mred\\nFAILED: forged'\n")

    def test_human_output_without_name_prints_dash(self, good_gz, capsys):
        raw = good_gz.read_bytes()
        assert raw[3] & 0x08  # gzip.open stored a name; drop it
        end = raw.index(b"\x00", 10) + 1
        good_gz.write_bytes(raw[:3] + b"\x00" + raw[4:10] + raw[end:])
        assert main(["inspect", str(good_gz)]) == 0
        assert capsys.readouterr().out.endswith("name=-\n")


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


class TestUnexpectedFailures:
    """RC1 R09: non-OSError failures keep the output form, with exit 2."""

    @pytest.fixture(params=["verify", "inspect"])
    def failing(self, request, monkeypatch):
        async def boom(*args, **kwargs):
            raise RuntimeError("internal failure")

        monkeypatch.setattr(f"aiogzip.__main__.{request.param}", boom)
        return request.param

    def test_json_stays_json(self, failing, good_gz, capsys):
        assert main([failing, "--json", str(good_gz)]) == 2
        captured = capsys.readouterr()
        assert json.loads(captured.out) == {
            "ok": False,
            "error": "RuntimeError: internal failure",
        }
        assert "Traceback" not in captured.err

    def test_human_output_has_no_traceback(self, failing, good_gz, capsys):
        assert main([failing, str(good_gz)]) == 2
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == f"ERROR: {good_gz}: RuntimeError: internal failure\n"

    def test_oserror_keeps_exit_one(self, monkeypatch, good_gz, capsys):
        async def unreadable(*args, **kwargs):
            raise OSError("unreadable")

        monkeypatch.setattr("aiogzip.__main__.verify", unreadable)
        assert main(["verify", "--json", str(good_gz)]) == 1
        assert json.loads(capsys.readouterr().out) == {
            "ok": False,
            "error": "unreadable",
        }

    def test_interrupt_is_not_reported(self, monkeypatch, good_gz):
        async def interrupted(*args, **kwargs):
            raise KeyboardInterrupt

        monkeypatch.setattr("aiogzip.__main__.verify", interrupted)
        with pytest.raises(KeyboardInterrupt):
            main(["verify", str(good_gz)])


class _FailingStdout:
    """A stdout whose writes fail; it has no file descriptor."""

    encoding = "utf-8"

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    def write(self, text: str) -> int:
        raise self._exc

    def flush(self) -> None:
        raise self._exc

    def fileno(self) -> int:
        raise OSError("no file descriptor")


class TestOutputErrors:
    """Review C8: an output failure is not a failure of the gzip file."""

    @pytest.mark.parametrize("command", ["inspect", "verify"])
    @pytest.mark.parametrize("json_flag", [[], ["--json"]])
    def test_closed_stdout_ends_quietly(
        self, command, json_flag, good_gz, monkeypatch, capsys
    ):
        broken = BrokenPipeError(errno.EPIPE, "Broken pipe")
        monkeypatch.setattr(sys, "stdout", _FailingStdout(broken))
        assert main([command, *json_flag, str(good_gz)]) == 141
        assert capsys.readouterr().err == ""

    def test_closed_stdout_on_failure_report_ends_quietly(
        self, corrupt_gz, monkeypatch, capsys
    ):
        broken = BrokenPipeError(errno.EPIPE, "Broken pipe")
        monkeypatch.setattr(sys, "stdout", _FailingStdout(broken))
        assert main(["verify", "--json", str(corrupt_gz)]) == 141
        assert capsys.readouterr().err == ""

    @pytest.mark.parametrize(
        "exc",
        [
            OSError(errno.ENOSPC, "No space left on device"),
            UnicodeEncodeError("ascii", "\xe9", 0, 1, "ordinal not in range(128)"),
        ],
        ids=["oserror", "unicode"],
    )
    def test_other_output_error_is_not_a_file_failure(
        self, exc, good_gz, monkeypatch, capsys
    ):
        monkeypatch.setattr(sys, "stdout", _FailingStdout(exc))
        assert main(["inspect", str(good_gz)]) == 2
        err = capsys.readouterr().err
        assert err.startswith(f"ERROR: cannot write output: {type(exc).__name__}: ")
        assert "FAILED" not in err
        assert str(good_gz) not in err

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="a closed pipe is not reported as BrokenPipeError on Windows",
    )
    def test_reader_closing_the_pipe(self, tmp_path):
        # 20,000 members: the report is far larger than a pipe buffer, so the
        # child is still writing when the reader goes away (``| head -1``).
        path = tmp_path / "many.gz"
        path.write_bytes(gzip.compress(b"") * 20_000)
        proc = subprocess.Popen(
            [sys.executable, "-m", "aiogzip", "inspect", str(path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert proc.stdout is not None and proc.stderr is not None
        try:
            first = proc.stdout.readline()
            proc.stdout.close()
            err = proc.stderr.read()
            returncode = proc.wait(timeout=60)
        finally:
            proc.kill()
            proc.stderr.close()
        assert b"20000 member(s)" in first
        assert err == b""
        assert returncode == 141

    def test_unencodable_name_is_escaped(self, tmp_path):
        # FNAME is Latin-1 on the wire: this one is "caf\xe9".
        path = _named_gz(tmp_path / "name.gz", "caf\xe9".encode("latin-1"))
        proc = subprocess.run(
            [sys.executable, "-m", "aiogzip", "inspect", str(path)],
            capture_output=True,
            env={**os.environ, "PYTHONIOENCODING": "ascii"},
        )
        assert proc.returncode == 0
        assert proc.stderr == b""
        assert proc.stdout.rstrip().endswith(b"name='caf\\xe9'")
        assert len(proc.stdout.splitlines()) == 2

    @pytest.mark.skipif(
        not os.path.exists("/dev/full"), reason="needs /dev/full (Linux)"
    )
    @pytest.mark.parametrize("json_flag", [[], ["--json"]])
    def test_full_device_exits_two_without_exit_flush_noise(self, json_flag, good_gz):
        # The failed report stays in stdout's buffer; unless stdout is
        # neutralized, the interpreter's exit flush fails again, prints
        # "Exception ignored" and turns the status into 120.
        with open("/dev/full", "wb") as full:
            proc = subprocess.run(
                [sys.executable, "-m", "aiogzip", "inspect", *json_flag, str(good_gz)],
                stdout=full,
                stderr=subprocess.PIPE,
                text=True,
            )
        assert proc.returncode == 2
        assert proc.stderr.startswith("ERROR: cannot write output: OSError: ")
        assert len(proc.stderr.splitlines()) == 1
        assert "Exception ignored" not in proc.stderr
        assert "FAILED" not in proc.stderr
