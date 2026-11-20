"""Tests for the opt-in fast_compress flag (zlib-ng compression).

Decompression auto-uses zlib-ng (covered in test_engine.py); compression only
uses it when the caller passes fast_compress=True AND zlib-ng is available.
Installing the extra alone must not change default compressed output.
"""

import asyncio
import gzip
import linecache
import os
import subprocess
import sys
import warnings

import pytest

import aiogzip
from aiogzip import AsyncGzipBinaryFile, AsyncGzipFile, AsyncGzipTextFile, _engine

ZNG_AVAILABLE = _engine._zng is not None

PAYLOAD = b"the quick brown fox jumps over the lazy dog " * 5000


async def _read_back(path):
    async with AsyncGzipBinaryFile(path, "rb") as f:
        return await f.read()


class TestDefaultCompressionUnchanged:
    async def test_installing_extra_does_not_change_default_output(
        self, monkeypatch, tmp_path
    ):
        """fast_compress defaults to False, so output must be byte-identical
        whether or not zlib-ng is available."""

        # Same path/name both times: the gzip header embeds the original
        # filename, so differing names would mask a true body comparison.
        path = tmp_path / "default.gz"

        async def write_with(have_zng):
            monkeypatch.setattr(_engine, "_HAVE_ZNG", have_zng)
            async with AsyncGzipBinaryFile(path, "wb", mtime=0) as f:
                await f.write(PAYLOAD)
            return path.read_bytes()

        with_zng = await write_with(True)
        without_zng = await write_with(False)
        assert with_zng == without_zng


@pytest.mark.skipif(not ZNG_AVAILABLE, reason="zlib-ng not installed")
class TestFastCompressEnabled:
    async def test_roundtrip_binary(self, monkeypatch, tmp_path):
        monkeypatch.setattr(_engine, "_HAVE_ZNG", True)
        path = tmp_path / "fast.gz"
        async with AsyncGzipBinaryFile(path, "wb", fast_compress=True) as f:
            await f.write(PAYLOAD)
        assert await _read_back(path) == PAYLOAD

    async def test_readable_by_stdlib_gzip(self, monkeypatch, tmp_path):
        monkeypatch.setattr(_engine, "_HAVE_ZNG", True)
        path = tmp_path / "fast_interop.gz"
        async with AsyncGzipBinaryFile(path, "wb", fast_compress=True) as f:
            await f.write(PAYLOAD)
        with gzip.open(path, "rb") as f:
            assert f.read() == PAYLOAD

    async def test_fast_output_differs_from_default(self, monkeypatch, tmp_path):
        monkeypatch.setattr(_engine, "_HAVE_ZNG", True)
        # Same path/name and mtime so only the deflate body can differ.
        path = tmp_path / "same.gz"
        async with AsyncGzipBinaryFile(path, "wb", mtime=0) as f:
            await f.write(PAYLOAD)
        default_bytes = path.read_bytes()
        async with AsyncGzipBinaryFile(path, "wb", mtime=0, fast_compress=True) as f:
            await f.write(PAYLOAD)
        fast_bytes = path.read_bytes()
        # Identical header (same name + mtime); body differs because a
        # different deflate implementation produced it.
        assert default_bytes != fast_bytes

    async def test_roundtrip_text(self, monkeypatch, tmp_path):
        monkeypatch.setattr(_engine, "_HAVE_ZNG", True)
        path = tmp_path / "fast.txt.gz"
        text = "héllo wörld\nsecond line\n" * 5000
        async with AsyncGzipTextFile(path, "wt", fast_compress=True) as f:
            await f.write(text)
        async with AsyncGzipTextFile(path, "rt") as f:
            assert await f.read() == text

    async def test_factory_threads_flag(self, monkeypatch, tmp_path):
        monkeypatch.setattr(_engine, "_HAVE_ZNG", True)
        path = tmp_path / "factory.gz"
        async with AsyncGzipFile(path, "wb", fast_compress=True) as f:
            await f.write(PAYLOAD)
        assert await _read_back(path) == PAYLOAD


class TestFastCompressFallback:
    def test_warns_when_unavailable(self, monkeypatch, tmp_path):
        """fast_compress=True without zlib-ng warns once at construction."""
        monkeypatch.setattr(_engine, "_HAVE_ZNG", False)
        with pytest.warns(UserWarning, match="zlib-ng is not available"):
            AsyncGzipBinaryFile(tmp_path / "x.gz", "wb", fast_compress=True)

    async def test_falls_back_and_roundtrips(self, monkeypatch, tmp_path):
        monkeypatch.setattr(_engine, "_HAVE_ZNG", False)
        path = tmp_path / "fallback.gz"
        with pytest.warns(UserWarning):
            cm = AsyncGzipBinaryFile(path, "wb", fast_compress=True)
        async with cm as f:
            await f.write(PAYLOAD)
        assert await _read_back(path) == PAYLOAD

    def test_no_warning_in_read_mode(self, monkeypatch, tmp_path):
        """fast_compress is meaningless for reads and must not warn there."""
        monkeypatch.setattr(_engine, "_HAVE_ZNG", False)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            AsyncGzipBinaryFile(tmp_path / "r.gz", "rb", fast_compress=True)

    def test_no_warning_when_not_requested(self, monkeypatch, tmp_path):
        monkeypatch.setattr(_engine, "_HAVE_ZNG", False)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            AsyncGzipBinaryFile(tmp_path / "n.gz", "wb")


FALLBACK = "zlib-ng is not available"


def _fallbacks(caught):
    return [w for w in caught if FALLBACK in str(w.message)]


def _source_line(warning):
    return linecache.getline(warning.filename, warning.lineno)


async def _items():
    yield b"payload"


class TestFallbackWarningLocation:
    """The fallback warning names the caller and is shown once per line (#234)."""

    @pytest.fixture(autouse=True)
    def _no_zlib_ng(self, monkeypatch):
        monkeypatch.setattr(_engine, "_HAVE_ZNG", False)

    @pytest.mark.parametrize("mode", ["wb", "wt", "ab", "at", "xb", "xt"])
    async def test_open_warns_once_per_line_at_the_caller(self, mode, tmp_path):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("default")
            for index in range(3):
                path = tmp_path / f"{index}.gz"
                async with aiogzip.open(path, mode, fast_compress=True) as f:
                    await f.write("x" if "t" in mode else b"x")
        (warning,) = _fallbacks(caught)
        assert warning.category is UserWarning
        assert warning.filename == __file__
        assert "aiogzip.open(path, mode, fast_compress=True)" in _source_line(warning)

    @pytest.mark.parametrize(
        ("factory", "mode"),
        [
            (AsyncGzipBinaryFile, "wb"),
            (AsyncGzipTextFile, "wt"),
            (AsyncGzipFile, "wb"),
            (AsyncGzipFile, "wt"),
        ],
    )
    def test_constructor_warns_once_per_line_at_the_caller(
        self, factory, mode, tmp_path
    ):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("default")
            for _ in range(3):
                factory(tmp_path / "c.gz", mode, fast_compress=True)
        (warning,) = _fallbacks(caught)
        assert warning.filename == __file__
        assert "factory(tmp_path" in _source_line(warning)
        assert not (tmp_path / "c.gz").exists()

    async def test_write_helper_warns_once_per_line_at_the_caller(self, tmp_path):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("default")
            for _ in range(3):
                await aiogzip.write(tmp_path / "w.gz", b"x", fast_compress=True)
        (warning,) = _fallbacks(caught)
        assert warning.filename == __file__
        assert "aiogzip.write(" in _source_line(warning)

    async def test_encoder_and_stream_are_attributed_to_the_caller(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("default")
            for _ in range(3):
                aiogzip.GzipEncoder(fast_compress=True)
            for _ in range(3):
                stream = aiogzip.compress_chunks(_items(), fast_compress=True)
                assert gzip.decompress(b"".join([c async for c in stream]))
        first, second = _fallbacks(caught)
        assert first.filename == second.filename == __file__
        assert "aiogzip.GzipEncoder(" in _source_line(first)
        assert "aiogzip.compress_chunks(" in _source_line(second)

    async def test_two_lines_warn_separately(self, tmp_path):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("default")
            aiogzip.open(tmp_path / "a.gz", "wb", fast_compress=True)
            aiogzip.open(tmp_path / "b.gz", "wb", fast_compress=True)
        first, second = _fallbacks(caught)
        assert second.lineno == first.lineno + 1

    @pytest.mark.parametrize("mode", ["wb", "wt"])
    async def test_each_handle_warns_exactly_once_under_always(self, mode, tmp_path):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            for index in range(3):
                handle = aiogzip.open(
                    tmp_path / f"{index}.gz", mode, fast_compress=True
                )
                assert len(_fallbacks(caught)) == index + 1
                async with handle as f:
                    await f.write("x" if "t" in mode else b"x")
                assert len(_fallbacks(caught)) == index + 1

    @pytest.mark.parametrize("mode", ["wb", "wt"])
    def test_error_filter_raises_from_the_constructor(self, mode, tmp_path):
        path = tmp_path / "e.gz"
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            with pytest.raises(UserWarning, match=FALLBACK):
                aiogzip.open(path, mode, fast_compress=True)
        assert not path.exists()

    @pytest.mark.parametrize("mode", ["rb", "rt"])
    async def test_read_modes_do_not_warn(self, mode, tmp_path):
        path = tmp_path / "r.gz"
        path.write_bytes(gzip.compress(b"x"))
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            async with aiogzip.open(path, mode, fast_compress=True) as f:
                await f.read()

    @pytest.mark.parametrize("mode", ["wb", "wt"])
    async def test_opening_does_not_reset_other_warning_registries(
        self, mode, tmp_path
    ):
        def other():
            warnings.warn("unrelated", DeprecationWarning, stacklevel=1)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("default")
            for index in range(3):
                other()
                path = tmp_path / f"{index}.gz"
                async with aiogzip.open(path, mode, fast_compress=True) as f:
                    await f.write("x" if "t" in mode else b"x")
        assert [str(w.message) for w in caught].count("unrelated") == 1
        assert len(_fallbacks(caught)) == 1

    @pytest.mark.parametrize("mode", ["wb", "wt"])
    async def test_unrelated_construction_during_a_handle_still_warns(
        self, mode, tmp_path
    ):
        """Only the handle's own inner objects are silent.

        Nothing ambient silences the warning, so an unrelated encoder built
        while a handle is being constructed or opened warns as usual. An
        ``int`` subclass is accepted as ``chunk_size``; its comparisons run
        inside the constructors, which is where an eagerly started task or
        any other callback would run.
        """
        independent = []

        class Chunk(int):
            def _hook(self):
                with warnings.catch_warnings(record=True) as inner:
                    warnings.simplefilter("always")
                    aiogzip.GzipEncoder(fast_compress=True)
                independent.append(len(_fallbacks(inner)))

            def __lt__(self, other):
                self._hook()
                return int(self) < other

            def __gt__(self, other):
                self._hook()
                return int(self) > other

            def __le__(self, other):
                self._hook()
                return int(self) <= other

            def __ge__(self, other):
                self._hook()
                return int(self) >= other

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            handle = aiogzip.open(
                tmp_path / "u.gz", mode, chunk_size=Chunk(1024), fast_compress=True
            )
            constructed = len(independent)
            async with handle as f:
                await f.write("x" if "t" in mode else b"x")
        assert constructed > 0
        assert len(independent) > constructed
        assert independent == [1] * len(independent)
        assert len(_fallbacks(caught)) == 1

    @pytest.mark.skipif(
        not hasattr(asyncio, "eager_task_factory"), reason="needs Python 3.12"
    )
    async def test_eager_task_started_during_open_still_warns(self, tmp_path):
        loop = asyncio.get_running_loop()
        counts = []

        async def construct():
            with warnings.catch_warnings(record=True) as inner:
                warnings.simplefilter("always")
                aiogzip.GzipEncoder(fast_compress=True)
            counts.append(len(_fallbacks(inner)))

        class Chunk(int):
            def __gt__(self, other):
                tasks.append(loop.create_task(construct()))
                return int(self) > other

            __lt__ = __gt__

        tasks = []
        previous = loop.get_task_factory()
        loop.set_task_factory(asyncio.eager_task_factory)
        try:
            with warnings.catch_warnings(record=True):
                warnings.simplefilter("always")
                async with aiogzip.open(
                    tmp_path / "eager.gz",
                    "wt",
                    chunk_size=Chunk(1024),
                    fast_compress=True,
                ) as f:
                    await f.write("x")
            await asyncio.gather(*tasks)
        finally:
            loop.set_task_factory(previous)
        assert counts and counts == [1] * len(counts)

    @pytest.mark.parametrize("mode", ["wb", "wt"])
    async def test_fallback_output_equals_default_output(self, mode, tmp_path):
        """The fallback is stdlib zlib, byte for byte."""
        outputs = []
        for fast in (False, True):
            path = tmp_path / "same.gz"
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                async with aiogzip.open(path, mode, mtime=0, fast_compress=fast) as f:
                    await f.write("payload " * 500 if "t" in mode else PAYLOAD)
            outputs.append(path.read_bytes())
        assert outputs[0] == outputs[1]

    @pytest.mark.skipif(not ZNG_AVAILABLE, reason="needs zlib-ng")
    @pytest.mark.parametrize("mode", ["wb", "wt"])
    async def test_available_engine_is_still_requested(
        self, mode, monkeypatch, tmp_path
    ):
        monkeypatch.setattr(_engine, "_HAVE_ZNG", True)
        calls = []
        real = _engine.compressobj

        def recording(level, wbits, fast=False):
            calls.append(fast)
            return real(level, wbits, fast=fast)

        monkeypatch.setattr(_engine, "compressobj", recording)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            async with aiogzip.open(tmp_path / "z.gz", mode, fast_compress=True) as f:
                await f.write("x" if "t" in mode else b"x")
        assert calls == [True]

    async def test_text_handle_buffer_is_a_plain_binary_file(self, tmp_path):
        with pytest.warns(UserWarning, match=FALLBACK):
            handle = aiogzip.open(tmp_path / "p.gz", "wt", fast_compress=True)
        async with handle as f:
            assert type(f.buffer) is AsyncGzipBinaryFile

    def test_subclass_outside_the_package_is_the_caller(self):
        class Encoder(aiogzip.GzipEncoder):
            def __init__(self):
                super().__init__(fast_compress=True)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            Encoder()
        (warning,) = _fallbacks(caught)
        assert warning.filename == __file__
        assert "super().__init__(fast_compress=True)" in _source_line(warning)

    @pytest.mark.parametrize(
        "filename",
        [
            "/app/importlib/_bootstrap_user.py",
            "/elsewhere/build/lib/aiogzip/_binary.py",
            "<string>",
        ],
    )
    def test_caller_is_identified_by_module_not_by_file_name(self, filename):
        """A caller is whatever module is outside the package.

        ``warnings.warn()`` skips frames whose file name looks like
        importlib's bootstrap while it counts ``stacklevel``, and a file name
        can look like one of aiogzip's own. Neither changes the attribution.
        """
        source = "\n\nimport aiogzip\naiogzip.GzipEncoder(fast_compress=True)\n"
        namespace = {"__name__": "user_module", "__package__": ""}
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            exec(compile(source, filename, "exec"), namespace)
        (warning,) = _fallbacks(caught)
        assert (warning.filename, warning.lineno) == (filename, 4)

    def test_package_frame_with_a_foreign_file_name_is_skipped(self):
        """Relocated bytecode keeps a build-time file name; it is still ours."""
        source = "def construct(encoder):\n    return encoder(fast_compress=True)\n"
        namespace = {"__name__": "aiogzip._relocated", "__package__": "aiogzip"}
        exec(compile(source, "/build/tmp/aiogzip/_relocated.py", "exec"), namespace)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            namespace["construct"](aiogzip.GzipEncoder)
        (warning,) = _fallbacks(caught)
        assert warning.filename == __file__
        assert 'namespace["construct"](aiogzip.GzipEncoder)' in _source_line(warning)

    def test_similarly_named_package_is_a_caller(self):
        source = "import aiogzip\naiogzip.GzipEncoder(fast_compress=True)\n"
        namespace = {"__name__": "aiogzip_tools.x", "__package__": "aiogzip_tools"}
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            exec(compile(source, "/app/aiogzip_tools/x.py", "exec"), namespace)
        (warning,) = _fallbacks(caught)
        assert warning.filename == "/app/aiogzip_tools/x.py"

    def test_error_filter_can_match_the_calling_module(self, tmp_path):
        """The module name given to the filter is the caller's."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            warnings.filterwarnings(
                "error", category=UserWarning, module=__name__.replace(".", r"\.")
            )
            with pytest.raises(UserWarning, match=FALLBACK):
                aiogzip.open(tmp_path / "m.gz", "wt", fast_compress=True)

    def test_script_run_as_main_gets_one_warning_at_its_own_line(self, tmp_path):
        """A plain script is the caller, and nothing else is warned about."""
        script = tmp_path / "script.py"
        script.write_text(
            "import asyncio\n"
            "import sys\n"
            "import aiogzip\n"
            "async def main():\n"
            "    for name in ('a.gz', 'b.gz'):\n"
            "        async with aiogzip.open(name, 'wt', fast_compress=True) as f:\n"
            "            await f.write('x')\n"
            "asyncio.run(main())\n"
        )
        src = os.path.dirname(os.path.dirname(aiogzip.__file__))
        result = subprocess.run(
            [sys.executable, "-W", "error::DeprecationWarning", str(script)],
            cwd=tmp_path,
            env={**os.environ, "AIOGZIP_ENGINE": "stdlib", "PYTHONPATH": src},
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stderr
        warned = [line for line in result.stderr.splitlines() if "Warning" in line]
        assert len(warned) == 1, result.stderr
        assert warned[0].startswith(f"{script}:6: UserWarning: fast_compress=True")
