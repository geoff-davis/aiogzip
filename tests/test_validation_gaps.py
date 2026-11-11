"""Small validation gaps from the 2.0.0 code review (behavior exception BC28)."""

import io
import os
import subprocess
import sys
import warnings

import pytest

import aiogzip
from aiogzip import _engine

LINES = b"one\ntwo\nthree\n"


class TestReadlinesNone:
    @pytest.mark.asyncio
    async def test_binary_readlines_none_reads_every_line(self, tmp_path):
        path = tmp_path / "lines.gz"
        async with aiogzip.open(path, "wb") as f:
            await f.write(LINES)
        async with aiogzip.open(path, "rb") as f:
            assert await f.readlines(None) == LINES.splitlines(keepends=True)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("newline", [None, ""])
    async def test_text_readlines_none_reads_every_line(self, tmp_path, newline):
        path = tmp_path / "lines.gz"
        async with aiogzip.open(path, "wb") as f:
            await f.write(LINES)
        async with aiogzip.open(path, "rt", newline=newline) as f:
            assert await f.readlines(None) == ["one\n", "two\n", "three\n"]


class TestMtimeValidation:
    @pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
    def test_non_finite_mtime_is_a_value_error(self, value):
        with pytest.raises(ValueError, match="mtime must be a finite number"):
            aiogzip.GzipEncoder(mtime=value)

    @pytest.mark.parametrize("value", [True, False])
    def test_bool_mtime_is_a_type_error(self, value, tmp_path):
        with pytest.raises(TypeError, match="mtime must be an int or float"):
            aiogzip.GzipEncoder(mtime=value)
        with pytest.raises(TypeError, match="mtime must be an int or float"):
            aiogzip.AsyncGzipBinaryFile(tmp_path / "x.gz", "wb", mtime=value)

    def test_ordinary_mtime_values_still_accepted(self):
        aiogzip.GzipEncoder(mtime=0)
        aiogzip.GzipEncoder(mtime=1.9)
        aiogzip.GzipEncoder(mtime=2**32 - 1)


class TestEngineEnvironmentValue:
    @staticmethod
    def _import_with(value):
        env = dict(os.environ)
        env["AIOGZIP_ENGINE"] = value
        return subprocess.run(
            [
                sys.executable,
                "-W",
                "error::RuntimeWarning",
                "-c",
                "import aiogzip; print(aiogzip.engine_info().decompression)",
            ],
            env=env,
            capture_output=True,
            text=True,
        )

    @pytest.mark.parametrize("value", ["", "stdlib", "STDLIB ", "zlib-ng"])
    def test_recognized_values_do_not_warn(self, value):
        result = self._import_with(value)
        assert result.returncode == 0, result.stderr

    @pytest.mark.parametrize("value", ["std", "zlib", "bogus"])
    def test_unrecognized_value_warns(self, value):
        result = self._import_with(value)
        assert result.returncode != 0
        assert "Ignoring unrecognized AIOGZIP_ENGINE value" in result.stderr
        assert repr(value) in result.stderr


class TestTextTellWideDecoderState:
    @pytest.mark.asyncio
    async def test_iso2022_kr_tell_round_trips(self, tmp_path):
        text = "한국어 텍스트 " * 40
        path = tmp_path / "kr.gz"
        async with aiogzip.open(path, "wb") as f:
            await f.write(text.encode("iso2022_kr"))
        async with aiogzip.open(
            path, "rt", encoding="iso2022_kr", newline="", chunk_size=3
        ) as f:
            seen = []
            cookies = []
            while True:
                cookies.append(await f.tell())
                char = await f.read(1)
                if not char:
                    break
                seen.append(char)
            assert "".join(seen) == text
            for index in (1, 2, 7, len(text) - 1):
                assert await f.seek(cookies[index]) == cookies[index]
                assert await f.read() == text[index:]

    @pytest.mark.asyncio
    async def test_wide_state_was_actually_exercised(self, tmp_path):
        import codecs

        decoder = codecs.getincrementaldecoder("iso2022_kr")()
        decoder.decode("한".encode("iso2022_kr")[:-1])
        assert decoder.getstate()[1].bit_length() > 31


class TestUnopenedTextHandle:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("newline", [None, "", "\n", "\r", "\r\n"])
    async def test_readline_reports_not_opened(self, tmp_path, newline):
        f = aiogzip.AsyncGzipTextFile(tmp_path / "x.gz", "rt", newline=newline)
        for call in (lambda: f.readline(), lambda: f.readline(5), f.__anext__):
            with pytest.raises(ValueError, match="File not opened"):
                await call()


class TestTextWriteModeSeek:
    @pytest.mark.asyncio
    async def test_only_the_current_position_is_seekable(self, tmp_path):
        path = tmp_path / "w.gz"
        async with aiogzip.open(path, "wt") as f:
            assert await f.seek(0) == 0
            await f.write("abc")
            assert await f.seek(3) == 3
            assert await f.seek(await f.tell()) == 3
            for target in (0, 2, 10):
                with pytest.raises(io.UnsupportedOperation, match="write mode"):
                    await f.seek(target)
            assert await f.seek(0, os.SEEK_END) == 3
            assert await f.seek(0, os.SEEK_CUR) == 3
            with pytest.raises(io.UnsupportedOperation):
                await f.seek(1, os.SEEK_END)
            await f.write("def")
            assert await f.seek(0, os.SEEK_END) == 6
        async with aiogzip.open(path, "rt") as f:
            assert await f.read() == "abcdef"


class TestFastCompressFallbackWarning:
    @pytest.mark.asyncio
    async def test_warning_is_deduplicated_and_leaves_other_registries(
        self, monkeypatch
    ):
        monkeypatch.setattr(_engine, "have_fast_engine", lambda: False)

        async def source():
            yield b"payload"

        async def compress():
            return b"".join(
                [c async for c in aiogzip.compress_chunks(source(), fast_compress=True)]
            )

        def other():
            warnings.warn("unrelated", DeprecationWarning, stacklevel=1)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("default")
            for _ in range(3):
                other()
                data = await compress()
        messages = [str(w.message) for w in caught]
        assert messages.count("unrelated") == 1
        assert sum("zlib-ng is not available" in m for m in messages) == 1
        assert caught[1].filename == __file__
        import gzip

        assert gzip.decompress(data) == b"payload"
