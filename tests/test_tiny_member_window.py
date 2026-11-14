"""The decoder's inflate window shrinks behind small members (issue #192).

Work is measured by counting the bytes handed to the inflate engine, never by
timing.
"""

import gzip
import random

import pytest

import aiogzip
from aiogzip import GzipDecoder, _engine
from aiogzip import codec as codec_module


@pytest.fixture
def handed(monkeypatch):
    """Record the size of every input span handed to the inflate engine."""
    sizes: list[int] = []
    real = _engine.inflate_step

    def counting(engine, data, **kwargs):
        sizes.append(len(data))
        return real(engine, data, **kwargs)

    monkeypatch.setattr(_engine, "inflate_step", counting)
    return sizes


MINIMUM = codec_module._INFLATE_INPUT_MIN_WINDOW
FULL = codec_module._INFLATE_INPUT_WINDOW
# The window loses a quarter per member on its way down from the full size,
# so the windows above the minimum sum to under four full windows.
DECAY_ALLOWANCE = 4 * FULL


def _decode(blob: bytes, chunk: int, **options) -> tuple[bytes, GzipDecoder]:
    decoder = GzipDecoder(**options)
    output = bytearray()
    for start in range(0, len(blob), chunk):
        for item in decoder.feed(blob[start : start + chunk]):
            output += item
    for item in decoder.finish():
        output += item
    return bytes(output), decoder


class TestHighPriorityEdgeCases:
    def test_many_empty_members_in_one_feed_cost_linear_work(self, handed):
        member = gzip.compress(b"", mtime=0)
        blob = member * 11_397
        output, decoder = _decode(blob, len(blob))
        assert output == b""
        assert decoder.member_count == 11_397
        # Full windows handed about 5,700 times the input to the engine.
        assert sum(handed) <= 11_397 * MINIMUM + DECAY_ALLOWANCE
        assert sum(handed) <= 250 * len(blob)

    def test_many_tiny_members_in_one_feed_cost_linear_work(self, handed):
        member = gzip.compress(b"x" * 20, mtime=0)
        blob = member * 5_000
        output, _ = _decode(blob, len(blob))
        assert output == b"x" * 100_000
        assert sum(handed) <= 5_000 * MINIMUM + DECAY_ALLOWANCE

    def test_alternating_tiny_and_small_members_stay_proportional(self, handed):
        rng = random.Random(192)
        payloads = [
            b"x" * 20 if index % 2 else rng.randbytes(3000) for index in range(2000)
        ]
        blob = b"".join(gzip.compress(payload, mtime=0) for payload in payloads)
        output, _ = _decode(blob, len(blob))
        assert output == b"".join(payloads)
        # Full windows handed about 165 times the input to the engine.
        assert sum(handed) <= 4 * len(blob)
        # The small members do not split the larger ones between them.
        assert len(handed) == 2000

    def test_block_sized_members_are_not_handed_whole_windows(self, handed):
        rng = random.Random(193)
        payloads = [rng.randbytes(40_000) for _ in range(40)]
        blob = b"".join(gzip.compress(payload, mtime=0) for payload in payloads)
        output, _ = _decode(blob, len(blob))
        assert output == b"".join(payloads)
        assert sum(handed) <= 3 * len(blob)


class TestMediumPriorityEdgeCases:
    def test_single_member_keeps_full_windows(self, handed):
        payload = random.Random(194).randbytes(2_000_000)
        blob = gzip.compress(payload, mtime=0)
        output, _ = _decode(blob, len(blob))
        assert output == payload
        assert sum(handed) == len(blob) - 10  # all but the header
        assert max(handed) == codec_module._INFLATE_INPUT_WINDOW

    def test_first_member_starts_with_the_full_window(self, handed):
        blob = gzip.compress(b"payload", mtime=0)
        _decode(blob + blob, 2 * len(blob))
        assert handed[0] == 2 * len(blob) - 10

    def test_window_shrinks_by_a_quarter_per_small_member(self, handed):
        member = gzip.compress(b"", mtime=0)
        blob = member * 40_000
        _decode(blob, len(blob))
        windows = [FULL]
        while windows[-1] > MINIMUM:
            windows.append(max(MINIMUM, windows[-1] - windows[-1] // 4))
        assert handed[: len(windows)] == windows
        assert set(handed[len(windows) : 1000]) == {MINIMUM}

    def test_one_small_member_does_not_split_the_next_large_one(self, handed):
        rng = random.Random(197)
        large = [rng.randbytes(100_000) for _ in range(8)]
        blob = b"".join(
            gzip.compress(b"x" * 20, mtime=0) + gzip.compress(payload, mtime=0)
            for payload in large
        )
        output, _ = _decode(blob, len(blob))
        assert output == b"".join(b"x" * 20 + payload for payload in large)
        # One step per member: 16 members, 16 windows.
        assert len(handed) == 16
        assert sum(handed) <= 4 * len(blob)

    def test_large_member_after_many_tiny_ones_grows_its_window(self, handed):
        payload = random.Random(195).randbytes(1_500_000)
        lead = 60
        blob = gzip.compress(b"", mtime=0) * lead + gzip.compress(payload, mtime=0)
        output, _ = _decode(blob, len(blob))
        assert output == payload
        growth = codec_module._INFLATE_INPUT_WINDOW_GROWTH
        expected = [MINIMUM]
        while expected[-1] < FULL:
            expected.append(min(FULL, expected[-1] * growth))
        assert handed[lead : lead + len(expected)] == expected
        assert max(handed[lead:]) == FULL
        assert sum(handed[lead:]) == len(blob) - 20 * lead - 10

    @pytest.mark.parametrize("chunk", [1, 7, 1024, 4096, 1 << 20])
    def test_mixed_member_sizes_decode_identically_at_any_chunking(self, chunk):
        rng = random.Random(196)
        sizes = [0, 1, 20, 900, 1100, 5000, 70_000, 3, 300_000, 0, 2048, 40]
        if chunk == 1:
            sizes = [0, 1, 20, 900, 1100, 5000, 3, 0, 2048, 40]
        payloads = [rng.randbytes(size) for size in sizes]
        blob = b"".join(gzip.compress(payload, mtime=0) for payload in payloads)
        output, decoder = _decode(blob, chunk, collect_member_info=True)
        assert output == b"".join(payloads)
        assert [member.uncompressed_size for member in decoder.members] == sizes
        offsets = [member.compressed_offset for member in decoder.members]
        assert offsets == sorted(offsets)
        assert sum(member.compressed_size for member in decoder.members) == len(blob)

    def test_output_limit_still_trips_inside_a_small_window(self):
        blob = gzip.compress(b"", mtime=0) + gzip.compress(b"\0" * 5_000_000, mtime=0)
        with pytest.raises(OSError, match="max_decompressed_size"):
            _decode(blob, len(blob), max_decompressed_size=1_000_000)


# The stored block ends exactly where the second window behind small members
# ends (4 KiB, then 16 KiB, less the 5-byte block header), so the invalid
# block type is the first byte of the third.
BLOCK = 5 * MINIMUM - 5
LIMIT = BLOCK - 1
# Enough empty members to bring the window down to its minimum.
LEAD = 60


def _corrupt_after_stored_block(lead: int = LEAD) -> bytes:
    """*lead* empty members, then a member whose valid stored block of BLOCK
    bytes is followed by an invalid block type."""
    header = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\xff"
    stored = (
        b"\x00" + BLOCK.to_bytes(2, "little") + (BLOCK ^ 0xFFFF).to_bytes(2, "little")
    )
    empty = gzip.compress(b"", mtime=0)
    return empty * lead + header + stored + b"a" * BLOCK + b"\x06"


def _outcome(blob: bytes, chunk: int, **options) -> tuple[int, type, str]:
    decoder = GzipDecoder(**options)
    published = 0
    try:
        for start in range(0, len(blob), chunk):
            for item in decoder.feed(blob[start : start + chunk]):
                published += len(item)
        for item in decoder.finish():
            published += len(item)
    except OSError as error:
        return published, type(error), str(error)
    raise AssertionError("the corrupt stream decoded")


class TestCorruptStreamOrdering:
    """BC31: behind small members, a failure is found as it is for
    fragmented input, because the engine no longer sees the whole window."""

    def test_valid_bytes_before_corrupt_deflate_are_published(self):
        blob = _corrupt_after_stored_block()
        published, kind, _ = _outcome(blob, len(blob))
        assert kind is gzip.BadGzipFile
        assert 0 < published <= BLOCK

    def test_limit_is_reported_before_later_corruption(self):
        blob = _corrupt_after_stored_block()
        published, kind, message = _outcome(
            blob, len(blob), max_decompressed_size=LIMIT
        )
        assert kind is OSError
        assert "max_decompressed_size" in message
        assert published == LIMIT

    @pytest.mark.parametrize("lead", [0, 1])
    def test_corruption_in_a_full_window_is_found_as_before(self, lead):
        # The first member has the full window, and one small member before
        # it takes only a quarter off: the corruption is in the same window.
        blob = _corrupt_after_stored_block(lead)
        _, kind, _ = _outcome(blob, len(blob), max_decompressed_size=LIMIT)
        assert kind is gzip.BadGzipFile

    @pytest.mark.asyncio
    async def test_file_reader_reports_the_limit_and_refuses_salvage(self, tmp_path):
        path = tmp_path / "corrupt.gz"
        path.write_bytes(_corrupt_after_stored_block())
        async with aiogzip.AsyncGzipBinaryFile(
            path, "rb", max_decompressed_size=LIMIT
        ) as handle:
            with pytest.raises(OSError, match="max_decompressed_size"):
                await handle.read()
            assert handle._read_health.name == "BROKEN"
            with pytest.raises(OSError):
                await handle.read()
