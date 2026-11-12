"""The decoder's inflate window follows member sizes (issue #192).

Work is measured by counting the bytes handed to the inflate engine, never by
timing.
"""

import gzip
import random

import pytest

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
        assert sum(handed) <= 40 * len(blob)

    def test_many_tiny_members_in_one_feed_cost_linear_work(self, handed):
        member = gzip.compress(b"x" * 20, mtime=0)
        blob = member * 5_000
        output, _ = _decode(blob, len(blob))
        assert output == b"x" * 100_000
        assert sum(handed) <= 40 * len(blob)

    def test_alternating_tiny_and_small_members_stay_proportional(self, handed):
        rng = random.Random(192)
        payloads = [
            b"x" * 20 if index % 2 else rng.randbytes(3000) for index in range(2000)
        ]
        blob = b"".join(gzip.compress(payload, mtime=0) for payload in payloads)
        output, _ = _decode(blob, len(blob))
        assert output == b"".join(payloads)
        # Full windows handed about 165 times the input to the engine.
        assert sum(handed) <= 8 * len(blob)

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

    def test_large_member_after_a_tiny_one_grows_its_window(self, handed):
        payload = random.Random(195).randbytes(1_500_000)
        blob = gzip.compress(b"", mtime=0) + gzip.compress(payload, mtime=0)
        output, _ = _decode(blob, len(blob))
        assert output == payload
        growth = codec_module._INFLATE_INPUT_WINDOW_GROWTH
        minimum = codec_module._INFLATE_INPUT_MIN_WINDOW
        full = codec_module._INFLATE_INPUT_WINDOW
        expected = [minimum]
        while expected[-1] < full:
            expected.append(min(full, expected[-1] * growth))
        # The last step up may be cut short by the end of the requeued span.
        assert handed[1 : len(expected)] == expected[:-1]
        assert handed[len(expected)] <= full
        assert sum(handed) <= 2 * len(blob)

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
