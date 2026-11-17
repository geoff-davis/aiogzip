"""The ``max_members`` limit on every entry point that decodes gzip (#231)."""

import gzip
import io
import tracemalloc
from typing import AsyncIterator, Optional

import pytest

import aiogzip
import aiogzip.codec
from aiogzip import GzipDecoder

MEMBER = gzip.compress(b"x")
EMPTY_MEMBER = gzip.compress(b"")
PREFIX = "gzip stream exceeded max_members"


class _Source:
    """A minimal asynchronous reader over bytes."""

    def __init__(self, data: bytes) -> None:
        self._stream = io.BytesIO(data)

    async def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)


async def _chunks(data: bytes, size: int = 7) -> AsyncIterator[bytes]:
    for start in range(0, len(data), size):
        yield data[start : start + size]


def _decode(decoder: GzipDecoder, data: bytes) -> bytes:
    output = b"".join(decoder.feed(data))
    return output + b"".join(decoder.finish())


class TestDecoderLimit:
    def test_a_stream_at_the_limit_decodes(self) -> None:
        decoder = GzipDecoder(max_members=3)
        assert _decode(decoder, MEMBER * 3) == b"xxx"
        assert decoder.member_count == 3
        assert decoder.finished

    def test_one_member_over_raises_plain_oserror(self) -> None:
        decoder = GzipDecoder(max_members=3)
        with pytest.raises(OSError) as raised:
            _decode(decoder, MEMBER * 4)
        assert type(raised.value) is OSError
        assert str(raised.value) == (
            f"{PREFIX} (3): input continues at compressed offset {3 * len(MEMBER)}"
        )
        assert decoder.member_count == 3

    def test_trailing_zero_padding_is_not_a_member(self) -> None:
        decoder = GzipDecoder(max_members=2)
        assert _decode(decoder, MEMBER * 2 + b"\0" * 64) == b"xx"

    def test_padding_between_members_does_not_hide_the_next(self) -> None:
        decoder = GzipDecoder(max_members=1)
        with pytest.raises(OSError, match=PREFIX) as raised:
            _decode(decoder, MEMBER + b"\0" * 5 + MEMBER)
        assert str(raised.value).endswith(f"offset {len(MEMBER) + 5}")

    def test_the_limit_is_checked_before_the_next_header_is_parsed(self) -> None:
        # One byte of a further member is enough: nothing of its header,
        # which may carry a large file name or comment, is buffered first.
        decoder = GzipDecoder(max_members=1, collect_member_info=True)
        with pytest.raises(OSError, match=PREFIX):
            _decode(decoder, MEMBER + MEMBER[:1])
        assert len(decoder.members) == 1

    def test_no_record_is_kept_for_the_member_past_the_limit(self) -> None:
        decoder = GzipDecoder(max_members=2, collect_member_info=True)
        with pytest.raises(OSError, match=PREFIX):
            _decode(decoder, MEMBER * 5)
        assert [member.index for member in decoder.members] == [0, 1]

    def test_the_limit_holds_when_members_arrive_byte_by_byte(self) -> None:
        decoder = GzipDecoder(max_members=2)
        data = MEMBER * 3
        with pytest.raises(OSError, match=PREFIX):
            for index in range(len(data)):
                for _ in decoder.feed(data[index : index + 1]):
                    pass

    def test_a_failed_decoder_stays_failed(self) -> None:
        decoder = GzipDecoder(max_members=1)
        with pytest.raises(OSError, match=PREFIX):
            _decode(decoder, MEMBER * 2)
        with pytest.raises(OSError, match="unusable after a prior failure"):
            decoder.feed(b"")

    def test_default_sets_no_limit(self) -> None:
        assert _decode(GzipDecoder(), EMPTY_MEMBER * 5000) == b""

    @pytest.mark.parametrize("value", [0, -1])
    def test_a_limit_below_one_is_a_value_error(self, value: int) -> None:
        with pytest.raises(ValueError, match="max_members"):
            GzipDecoder(max_members=value)

    @pytest.mark.parametrize("value", [1.0, "1", True])
    def test_a_limit_of_the_wrong_type_is_a_type_error(self, value: object) -> None:
        with pytest.raises(TypeError, match="max_members"):
            GzipDecoder(max_members=value)  # type: ignore[arg-type]


class TestSynchronousDecompress:
    def test_at_and_over_the_limit(self) -> None:
        assert aiogzip.codec.decompress(MEMBER * 2, max_members=2) == b"xx"
        with pytest.raises(OSError, match=PREFIX):
            aiogzip.codec.decompress(MEMBER * 3, max_members=2)


class TestEntryPoints:
    async def test_decompress(self) -> None:
        assert await aiogzip.decompress(MEMBER * 2, max_members=2) == b"xx"
        with pytest.raises(OSError, match=PREFIX):
            await aiogzip.decompress(MEMBER * 3, max_members=2)

    async def test_decompress_validates_when_awaited(self) -> None:
        with pytest.raises(ValueError, match="max_members"):
            await aiogzip.decompress(MEMBER, max_members=0)

    async def test_decompress_chunks(self) -> None:
        output = [
            chunk
            async for chunk in aiogzip.decompress_chunks(
                _chunks(MEMBER * 2), max_members=2
            )
        ]
        assert b"".join(output) == b"xx"
        with pytest.raises(OSError, match=PREFIX):
            async for _ in aiogzip.decompress_chunks(
                _chunks(MEMBER * 3), max_members=2
            ):
                pass

    def test_decompress_chunks_validates_at_the_call(self) -> None:
        with pytest.raises(ValueError, match="max_members"):
            aiogzip.decompress_chunks(_chunks(MEMBER), max_members=0)
        with pytest.raises(TypeError, match="max_members"):
            aiogzip.decompress_chunks(
                _chunks(MEMBER),
                max_members="2",  # type: ignore[arg-type]
            )

    async def test_verify(self) -> None:
        result = await aiogzip.verify(None, fileobj=_Source(MEMBER * 2), max_members=2)
        assert result.member_count == 2
        with pytest.raises(OSError, match=PREFIX):
            await aiogzip.verify(None, fileobj=_Source(MEMBER * 3), max_members=2)

    async def test_inspect(self) -> None:
        info = await aiogzip.inspect(None, fileobj=_Source(MEMBER * 2), max_members=2)
        assert len(info.members) == 2
        with pytest.raises(OSError, match=PREFIX):
            await aiogzip.inspect(None, fileobj=_Source(MEMBER * 3), max_members=2)

    async def test_scan_validates_before_touching_the_source(self) -> None:
        source = _Source(MEMBER)
        with pytest.raises(ValueError, match="max_members"):
            await aiogzip.inspect(None, fileobj=source, max_members=0)
        with pytest.raises(TypeError, match="max_members"):
            await aiogzip.verify(
                None,
                fileobj=source,
                max_members=1.5,  # type: ignore[arg-type]
            )
        assert source._stream.tell() == 0

    async def test_read(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        path = tmp_path / "members.gz"
        path.write_bytes(MEMBER * 3)
        assert await aiogzip.read(path, max_members=3) == b"xxx"
        with pytest.raises(OSError, match=PREFIX):
            await aiogzip.read(path, max_members=2)


class TestFileHandles:
    async def test_binary_handle(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        path = tmp_path / "members.gz"
        path.write_bytes(MEMBER * 3)
        async with aiogzip.open(path, "rb", max_members=3) as stream:
            assert await stream.read() == b"xxx"
        async with aiogzip.open(path, "rb", max_members=2) as stream:
            with pytest.raises(OSError, match=PREFIX):
                await stream.read()

    async def test_text_handle(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        path = tmp_path / "members.gz"
        path.write_bytes(gzip.compress(b"a\n") * 3)
        async with aiogzip.open(path, "rt", max_members=3) as stream:
            assert [line async for line in stream] == ["a\n"] * 3
        async with aiogzip.open(path, "rt", max_members=2) as stream:
            with pytest.raises(OSError, match=PREFIX):
                await stream.read()

    async def test_a_rewind_starts_the_count_again(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        path = tmp_path / "members.gz"
        path.write_bytes(MEMBER * 3)
        async with aiogzip.open(path, "rb", max_members=3) as stream:
            assert await stream.read() == b"xxx"
            await stream.seek(0)
            assert await stream.read() == b"xxx"

    async def test_factory_and_classes_take_the_limit(self) -> None:
        for handle in (
            aiogzip.AsyncGzipFile(
                None, "rb", fileobj=_Source(MEMBER * 2), max_members=1
            ),
            aiogzip.AsyncGzipBinaryFile(
                None, "rb", fileobj=_Source(MEMBER * 2), max_members=1
            ),
            aiogzip.AsyncGzipTextFile(
                None, "rt", fileobj=_Source(MEMBER * 2), max_members=1
            ),
        ):
            async with handle as stream:
                with pytest.raises(OSError, match=PREFIX):
                    await stream.read()

    @pytest.mark.parametrize("mode", ["rb", "rt", "wb"])
    def test_handles_validate_at_construction(self, mode: str) -> None:
        with pytest.raises(ValueError, match="max_members"):
            aiogzip.open("unused.gz", mode, max_members=0)
        with pytest.raises(TypeError, match="max_members"):
            aiogzip.open("unused.gz", mode, max_members="1")  # type: ignore[call-overload]


async def _inspect_peak(blob: bytes, max_members: Optional[int]) -> int:
    source = _Source(blob)
    tracemalloc.start()
    try:
        try:
            # A small read size keeps the source chunk out of the peak.
            await aiogzip.inspect(
                None, fileobj=source, max_members=max_members, chunk_size=4096
            )
        except OSError as error:
            assert str(error).startswith(PREFIX)
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


class TestInspectMemory:
    async def test_the_limit_bounds_inspect_memory_on_many_empty_members(self) -> None:
        # 10,000 empty members are 200 kB of input. Unbounded, inspect() keeps
        # a record for each one, about twelve times the input. With the limit
        # it stops at the 101st member, inside the first chunk it read. The
        # count is kept small because tracing allocations under coverage is
        # slow on the Windows runners.
        count = 10_000
        blob = EMPTY_MEMBER * count
        assert len(blob) == 20 * count

        unbounded = await _inspect_peak(blob, None)
        bounded = await _inspect_peak(blob, 100)

        assert unbounded > 8 * len(blob)
        assert bounded < len(blob)
        assert bounded * 10 < unbounded
