"""A ``bytes`` subclass cannot substitute the data the codec sees (BC27).

``docs/codec.md`` promises that a subclass is copied from its raw storage
without invoking its overridable methods. On Python 3.12 and newer
``memoryview()`` calls a ``__buffer__`` override (PEP 688), so the snapshot
must not go through it.
"""

import gzip

from aiogzip import (
    AsyncGzipBinaryFile,
    GzipDecoder,
    GzipEncoder,
    compress_chunks,
    decompress_chunks,
)

PAYLOAD = b"the real payload " * 64
called = []


class Hostile(bytes):
    def __buffer__(self, flags):
        called.append("__buffer__")
        return memoryview(b"SUBSTITUTED")

    def __getitem__(self, key):
        called.append("__getitem__")
        return b"SUBSTITUTED"

    def __len__(self):
        called.append("__len__")
        return 3

    def __bytes__(self):
        called.append("__bytes__")
        return b"SUBSTITUTED"

    def __iter__(self):
        called.append("__iter__")
        return iter(b"SUBSTITUTED")


def test_encoder_reads_a_subclass_from_its_raw_storage():
    called.clear()
    encoder = GzipEncoder()
    wire = b"".join(encoder.start())
    wire += b"".join(encoder.feed(Hostile(PAYLOAD)))
    wire += b"".join(encoder.finish())
    assert gzip.decompress(wire) == PAYLOAD
    assert encoder.input_size == len(PAYLOAD)
    assert called == []


def test_decoder_reads_a_subclass_from_its_raw_storage():
    called.clear()
    decoder = GzipDecoder()
    out = b"".join(decoder.feed(Hostile(gzip.compress(PAYLOAD))))
    out += b"".join(decoder.finish())
    assert out == PAYLOAD
    assert called == []


async def test_chunk_streams_read_a_subclass_from_its_raw_storage():
    called.clear()

    async def source(data):
        yield Hostile(data)

    wire = b"".join([chunk async for chunk in compress_chunks(source(PAYLOAD))])
    assert gzip.decompress(wire) == PAYLOAD
    out = b"".join([chunk async for chunk in decompress_chunks(source(wire))])
    assert out == PAYLOAD
    assert called == []


async def test_file_write_reads_a_subclass_from_its_raw_storage(tmp_path):
    called.clear()
    path = tmp_path / "subclass.gz"
    async with AsyncGzipBinaryFile(path, "wb") as handle:
        assert await handle.write(Hostile(PAYLOAD)) == len(PAYLOAD)
        assert await handle.tell() == len(PAYLOAD)
    assert gzip.decompress(path.read_bytes()) == PAYLOAD
    assert called == []


async def test_custom_source_chunks_are_read_from_their_raw_storage():
    called.clear()

    class Source:
        def __init__(self, data):
            self.data = data

        async def read(self, size=-1):
            data, self.data = self.data, b""
            return Hostile(data) if data else b""

    async with AsyncGzipBinaryFile(
        None, "rb", fileobj=Source(gzip.compress(PAYLOAD))
    ) as handle:
        assert await handle.read() == PAYLOAD
        # The rewind replays the cached compressed bytes.
        await handle.seek(0)
        assert await handle.read() == PAYLOAD
    assert called == []
