"""Error messages for the common mistakes (#199).

Exception types are frozen and stay as they were; these tests pin the
message fragments and the ``__notes__`` that make three mistakes
diagnosable: a synchronous file object, a corrupt file among many, and
input that is not gzip at all.
"""

from __future__ import annotations

import gzip
import io
from pathlib import Path
from typing import Any

import aiofiles
import pytest

import aiogzip
from aiogzip._common import _NOT_AWAITABLE, _sync_fileobj_message

GZIP_HELLO = gzip.compress(b"hello")

NOT_GZIP = [
    pytest.param(
        b"\x28\xb5\x2f\xfd" + b"\0" * 32, "(b'(\\xb5'): looks like Zstandard", id="zstd"
    ),
    pytest.param(b"BZh91AY&SY" + b"\0" * 32, "(b'BZ'): looks like bzip2", id="bzip2"),
    pytest.param(b"\xfd7zXZ\x00" + b"\0" * 32, "(b'\\xfd7'): looks like xz", id="xz"),
    pytest.param(b"PK\x03\x04" + b"\0" * 32, "(b'PK'): looks like zip", id="zip"),
    pytest.param(b"not gzip, just some text\n", "(b'no')", id="text"),
]


class AsyncReader:
    """An async reader with no ``name``."""

    def __init__(self, data: bytes) -> None:
        self._buffer = io.BytesIO(data)

    async def read(self, size: int = -1) -> bytes:
        return self._buffer.read(size)


def _decode(pieces: list[bytes]) -> gzip.BadGzipFile:
    decoder = aiogzip.GzipDecoder()
    with pytest.raises(gzip.BadGzipFile) as caught:
        for piece in pieces:
            for _ in decoder.feed(piece):
                pass
        for _ in decoder.finish():
            pass
    return caught.value


class TestNotGzipInput:
    @pytest.mark.parametrize(("data", "detail"), NOT_GZIP)
    def test_codec_shows_the_magic_bytes_and_a_format_hint(
        self, data: bytes, detail: str
    ) -> None:
        error = _decode([data])
        assert str(error) == f"Not a gzipped file {detail}"
        # The sans-I/O codec has no filename and adds no note.
        assert not hasattr(error, "__notes__")

    @pytest.mark.parametrize(("data", "detail"), NOT_GZIP)
    def test_message_is_the_same_for_a_fragmented_header(
        self, data: bytes, detail: str
    ) -> None:
        whole = str(_decode([data]))
        assert str(_decode([data[:1], data[1:]])) == whole
        assert str(_decode([bytes([b]) for b in data])) == whole

    def test_text_without_a_known_signature_has_no_hint(self) -> None:
        assert "looks like" not in str(_decode([b"hello world"]))

    def test_trailing_garbage_shows_its_first_bytes(self) -> None:
        error = _decode([GZIP_HELLO + b"garbage"])
        assert "Not a gzipped file (b'ga')" in str(error)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("data", "detail"), NOT_GZIP)
    async def test_file_reader_keeps_its_prefix_and_adds_the_detail(
        self, tmp_path: Path, data: bytes, detail: str
    ) -> None:
        path = tmp_path / "input.gz"
        path.write_bytes(data)
        async with aiogzip.open(path, "rb") as f:
            with pytest.raises(gzip.BadGzipFile) as caught:
                await f.read()
        assert str(caught.value) == (
            f"Error decompressing gzip data: Not a gzipped file {detail}"
        )


class TestFileNameNote:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("mode", ["rb", "rt"])
    async def test_reader_names_the_corrupt_file_in_a_note(
        self, tmp_path: Path, mode: str
    ) -> None:
        path = tmp_path / "shard-0042.gz"
        path.write_bytes(GZIP_HELLO[:-8] + b"\0" * 8)
        async with aiogzip.open(path, mode) as f:
            with pytest.raises(gzip.BadGzipFile) as caught:
                await f.read()
        assert caught.value.__notes__ == [f"while reading {str(path)!r}"]
        # The message itself is unchanged, so matching on it keeps working.
        assert "shard-0042" not in str(caught.value)
        assert "CRC check failed" in str(caught.value)

    @pytest.mark.asyncio
    async def test_reader_names_a_bytes_path_as_given(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.gz"
        path.write_bytes(b"not gzip")
        raw = str(path).encode()
        async with aiogzip.open(raw, "rb") as f:
            with pytest.raises(gzip.BadGzipFile) as caught:
                await f.read()
        assert caught.value.__notes__ == [f"while reading {raw!r}"]

    @pytest.mark.asyncio
    async def test_reader_uses_the_name_of_a_named_fileobj(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "named.gz"
        path.write_bytes(b"not gzip")
        async with aiofiles.open(path, "rb") as raw:
            async with aiogzip.open(None, "rb", fileobj=raw) as f:
                with pytest.raises(gzip.BadGzipFile) as caught:
                    await f.read()
        assert caught.value.__notes__ == [f"while reading {str(path)!r}"]

    @pytest.mark.asyncio
    async def test_no_note_without_a_name(self) -> None:
        async with aiogzip.open(None, "rb", fileobj=AsyncReader(b"not gzip")) as f:
            with pytest.raises(gzip.BadGzipFile) as caught:
                await f.read()
        assert not hasattr(caught.value, "__notes__")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("scan", [aiogzip.verify, aiogzip.inspect])
    async def test_scans_name_the_file(self, tmp_path: Path, scan: Any) -> None:
        path = tmp_path / "scan.gz"
        path.write_bytes(GZIP_HELLO[:-8] + b"\0" * 8)
        with pytest.raises(gzip.BadGzipFile) as caught:
            await scan(path)
        assert caught.value.__notes__ == [f"while reading {str(path)!r}"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("scan", [aiogzip.verify, aiogzip.inspect])
    async def test_scans_add_no_note_without_a_name(self, scan: Any) -> None:
        with pytest.raises(gzip.BadGzipFile) as caught:
            await scan(None, fileobj=AsyncReader(b"not gzip"))
        assert not hasattr(caught.value, "__notes__")

    @pytest.mark.asyncio
    async def test_a_missing_file_gets_no_note(self, tmp_path: Path) -> None:
        # The operating system's message already names the path.
        with pytest.raises(FileNotFoundError) as caught:
            await aiogzip.verify(tmp_path / "absent.gz")
        assert not hasattr(caught.value, "__notes__")


class TestSynchronousFileObject:
    EXPLANATION = (
        "not an awaitable; aiogzip needs an async file object. Wrap a sync "
        "file with aiofiles.threadpool.wrap(f), or use gzip.open()."
    )

    @pytest.mark.asyncio
    async def test_read_mode_explains_the_first_read(self) -> None:
        async with aiogzip.open(None, "rb", fileobj=io.BytesIO(GZIP_HELLO)) as f:
            with pytest.raises(OSError) as caught:
                await f.read()
        assert str(caught.value) == f"fileobj.read() returned bytes, {self.EXPLANATION}"
        assert isinstance(caught.value.__cause__, TypeError)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("scan", [aiogzip.verify, aiogzip.inspect])
    async def test_scans_explain_the_first_read(self, scan: Any) -> None:
        with pytest.raises(OSError) as caught:
            await scan(None, fileobj=io.BytesIO(GZIP_HELLO))
        assert str(caught.value) == f"fileobj.read() returned bytes, {self.EXPLANATION}"

    @pytest.mark.asyncio
    async def test_write_mode_explains_the_header_write(self) -> None:
        with pytest.raises(TypeError) as caught:
            async with aiogzip.open(None, "wb", fileobj=io.BytesIO()):
                pass
        assert str(caught.value) == f"fileobj.write() returned int, {self.EXPLANATION}"
        # The original exception with a clearer message: no cause is added.
        assert caught.value.__cause__ is None
        assert caught.value.__context__ is None

    @pytest.mark.asyncio
    async def test_the_suggested_wrapper_works(self) -> None:
        import aiofiles.threadpool

        wrapped = aiofiles.threadpool.wrap(io.BytesIO(GZIP_HELLO))
        async with aiogzip.open(None, "rb", fileobj=wrapped) as f:
            assert await f.read() == b"hello"

    @pytest.mark.asyncio
    async def test_another_type_error_from_an_async_read_is_not_rewritten(
        self,
    ) -> None:
        class Broken:
            async def read(self, size: int = -1) -> bytes:
                raise TypeError("boom")

        async with aiogzip.open(None, "rb", fileobj=Broken()) as f:
            with pytest.raises(OSError, match="^Error reading from file: boom$"):
                await f.read()

    @pytest.mark.parametrize(
        "text",
        [
            "'bytes' object can't be awaited",
            "object bytes can't be used in 'await' expression",
        ],
    )
    def test_both_interpreter_phrasings_are_recognized(self, text: str) -> None:
        match = _NOT_AWAITABLE.search(text)
        assert match is not None
        assert (match.group(1) or match.group(2)) == "bytes"

    def test_other_errors_are_not_recognized(self) -> None:
        assert _sync_fileobj_message(TypeError("boom"), "read") is None
        assert _sync_fileobj_message(ValueError("can't be awaited"), "read") is None
        # Without a traceback there is no evidence of where the await failed.
        untraced = TypeError("'bytes' object can't be awaited")
        assert _sync_fileobj_message(untraced, "read") is None

    @pytest.mark.asyncio
    async def test_an_await_that_fails_inside_an_async_read_is_not_relabelled(
        self,
    ) -> None:
        class Internal:
            async def read(self, size: int = -1) -> bytes:
                return await b"internal mistake"  # type: ignore[misc]

        async with aiogzip.open(None, "rb", fileobj=Internal()) as f:
            with pytest.raises(OSError) as caught:
                await f.read()
        assert str(caught.value).startswith("Error reading from file: ")
        assert "fileobj.read() returned" not in str(caught.value)
        for scan in (aiogzip.verify, aiogzip.inspect):
            with pytest.raises(OSError) as caught:
                await scan(None, fileobj=Internal())
            assert str(caught.value).startswith("Error reading from file: ")

    @pytest.mark.asyncio
    async def test_an_await_that_fails_inside_an_async_write_is_not_relabelled(
        self,
    ) -> None:
        class Internal:
            async def write(self, data: bytes) -> int:
                return await 5  # type: ignore[misc]

        with pytest.raises(TypeError) as caught:
            async with aiogzip.open(None, "wb", fileobj=Internal()):
                pass
        assert "fileobj.write() returned" not in str(caught.value)
        assert "await" in str(caught.value)


class TestPositionalFileObject:
    @pytest.mark.parametrize("mode", ["rb", "wb", "rt"])
    def test_a_file_object_as_filename_points_at_fileobj(self, mode: str) -> None:
        with pytest.raises(TypeError) as caught:
            aiogzip.open(io.BytesIO(), mode)  # type: ignore[call-overload]
        assert str(caught.value) == (
            "Filename must be a string, bytes, or PathLike object, not BytesIO; "
            "pass a file object as fileobj=..."
        )

    def test_another_wrong_type_keeps_the_short_message(self) -> None:
        with pytest.raises(TypeError) as caught:
            aiogzip.open(3, "rb")  # type: ignore[call-overload]
        assert str(caught.value) == (
            "Filename must be a string, bytes, or PathLike object"
        )

    @pytest.mark.asyncio
    async def test_scans_give_the_same_pointer(self) -> None:
        with pytest.raises(TypeError, match="pass a file object as fileobj="):
            await aiogzip.verify(io.BytesIO())  # type: ignore[arg-type]


class TestRepr:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("mode", ["rb", "rt"])
    async def test_file_repr_tells_unopened_from_open(
        self, tmp_path: Path, mode: str
    ) -> None:
        path = tmp_path / "repr.gz"
        path.write_bytes(GZIP_HELLO)
        f = aiogzip.open(str(path), mode)
        prefix = f"<aiogzip.{type(f).__name__} name={str(path)!r} mode={mode!r} "
        assert repr(f) == prefix + "unopened>"
        assert f.closed is False
        await f.open()
        assert repr(f) == prefix + "closed=False>"
        await f.close()
        assert repr(f) == prefix + "closed=True>"

    @pytest.mark.asyncio
    async def test_file_closed_before_open_reports_closed(self, tmp_path: Path) -> None:
        f = aiogzip.open(tmp_path / "never.gz", "rb")
        await f.close()
        assert repr(f).endswith("closed=True>")

    def test_encoder_repr_shows_its_progress(self) -> None:
        encoder = aiogzip.GzipEncoder()
        assert repr(encoder) == (
            "<aiogzip.GzipEncoder started=False finished=False input_size=0>"
        )
        for _ in encoder.start():
            pass
        for _ in encoder.feed(b"hello"):
            pass
        for _ in encoder.finish():
            pass
        assert repr(encoder) == (
            "<aiogzip.GzipEncoder started=True finished=True input_size=5>"
        )

    def test_decoder_repr_shows_its_progress(self) -> None:
        decoder = aiogzip.GzipDecoder()
        assert repr(decoder) == (
            "<aiogzip.GzipDecoder finished=False member_count=0 "
            "compressed_size=0 uncompressed_size=0>"
        )
        for _ in decoder.feed(GZIP_HELLO):
            pass
        for _ in decoder.finish():
            pass
        assert repr(decoder) == (
            f"<aiogzip.GzipDecoder finished=True member_count=1 "
            f"compressed_size={len(GZIP_HELLO)} uncompressed_size=5>"
        )

    def test_codec_repr_tolerates_a_half_built_instance(self) -> None:
        for cls in (aiogzip.GzipEncoder, aiogzip.GzipDecoder):
            assert repr(cls.__new__(cls)) == f"<aiogzip.{cls.__name__} [uninitialized]>"


class TestDiagnosticsNeverReplaceTheError:
    """A note or hint that cannot be built must leave the real error alone."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("scan", [aiogzip.verify, aiogzip.inspect])
    async def test_scan_survives_a_name_property_that_raises(self, scan: Any) -> None:
        class Reader(AsyncReader):
            @property
            def name(self) -> str:
                raise RuntimeError("no name for you")

        with pytest.raises(gzip.BadGzipFile, match="Not a gzipped file") as caught:
            await scan(None, fileobj=Reader(b"not gzip"))
        assert not hasattr(caught.value, "__notes__")

    @pytest.mark.asyncio
    async def test_reader_survives_a_name_property_that_raises(self) -> None:
        class Reader(AsyncReader):
            @property
            def name(self) -> str:
                raise RuntimeError("no name for you")

        async with aiogzip.open(None, "rb", fileobj=Reader(b"not gzip")) as f:
            with pytest.raises(gzip.BadGzipFile, match="Not a gzipped file") as caught:
                await f.read()
        assert not hasattr(caught.value, "__notes__")

    @pytest.mark.asyncio
    async def test_a_name_whose_repr_raises_is_not_noted(self, tmp_path: Path) -> None:
        class Unprintable(str):
            def __repr__(self) -> str:
                raise RuntimeError("no repr for you")

        path = tmp_path / "bad.gz"
        path.write_bytes(b"not gzip")
        name = Unprintable(path)
        with pytest.raises(gzip.BadGzipFile, match="Not a gzipped file") as caught:
            await aiogzip.verify(name)
        assert not hasattr(caught.value, "__notes__")
        async with aiogzip.open(name, "rb") as f:
            with pytest.raises(gzip.BadGzipFile, match="Not a gzipped file") as caught:
                await f.read()
        assert not hasattr(caught.value, "__notes__")

    def test_a_filename_whose_read_attribute_raises_keeps_its_type_error(
        self,
    ) -> None:
        class Hostile:
            @property
            def read(self) -> Any:
                raise RuntimeError("no read for you")

        with pytest.raises(TypeError) as caught:
            aiogzip.open(Hostile(), "rb")  # type: ignore[call-overload]
        assert str(caught.value) == (
            "Filename must be a string, bytes, or PathLike object"
        )
