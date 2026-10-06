#!/usr/bin/env python3
"""Count text replay-origin objects by category for representative workloads.

WP7 evidence: the live origin is updated in place (no object per refill or
line), rollback keeps an immutable field tuple (no object), and an
unpublished-read pending origin is one object per such read. Counts are of
_TextBufferOrigin constructions attributed to the method that requested them.

    uv run python scripts/measure_text_origin_allocations.py [--output FILE]
"""

import argparse
import asyncio
import collections
import gzip
import io
import json
import sys

import aiogzip._text as text_module
from aiogzip import AsyncGzipTextFile

CATEGORY = {
    "__init__": "live-origin",
    "_read_sized_reserved": "pending-origin",
    "_next_fast_line": "pending-origin",
    "_readline_buffered_reserved": "pending-origin",
}
LINES = 20_000
CHUNK = 4096  # small chunks: many refills per scenario


class _Source:
    def __init__(self, data):
        self._data = io.BytesIO(data)
        self.reads = 0

    async def read(self, size=-1):
        self.reads += 1
        return self._data.read(size)


def _count_refills(counter):
    """Count the text layer's decode refills; return a restore callback."""
    cls = AsyncGzipTextFile
    originals = {
        name: getattr(cls, name)
        for name in ("_read_chunk_and_decode", "_decode_next_chunk")
    }

    def wrap(method):
        async def counted(self, *args, **kwargs):
            counter["refills"] += 1
            return await method(self, *args, **kwargs)

        return counted

    for name, method in originals.items():
        setattr(cls, name, wrap(method))

    def restore():
        for name, method in originals.items():
            setattr(cls, name, method)

    return restore


def _install(counts):
    original = text_module._TextBufferOrigin

    class Counting(original):
        __slots__ = ()

        def __init__(self, *args, **kwargs):
            frame = sys._getframe(1)  # the code that constructed the origin
            counts[CATEGORY.get(frame.f_code.co_name, frame.f_code.co_name)] += 1
            super().__init__(*args, **kwargs)

    text_module._TextBufferOrigin = Counting
    return original


async def _scenario(name, newline, ending, action):
    counts = collections.Counter()
    data = gzip.compress("".join(f"row {i}{ending}" for i in range(LINES)).encode())
    original = _install(counts)
    refills = collections.Counter()
    restore_refills = _count_refills(refills)
    try:
        source = _Source(data)
        stream = AsyncGzipTextFile(
            None, "rt", fileobj=source, newline=newline, chunk_size=CHUNK
        )
        await stream.open()
        operations = await action(stream)
        await stream.close()
    finally:
        text_module._TextBufferOrigin = original
        restore_refills()
    return dict(
        scenario=name,
        lines=LINES,
        operations=operations,
        source_reads=source.reads,
        text_refills=refills["refills"],
        counts=dict(sorted(counts.items())),
    )


async def _iterate(stream):
    count = 0
    async for _ in stream:
        count += 1
    return count


async def _readlines_small_hint(stream):
    calls = 0
    while await stream.readlines(64):
        calls += 1
    return calls + 1


async def _sized_reads(stream):
    calls = 0
    while await stream.read(1000):
        calls += 1
    return calls + 1


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output")
    args = parser.parse_args()
    rows = [
        await _scenario("iterate fast (newline='\\n')", "\n", "\n", _iterate),
        await _scenario("iterate generic (newline='')", "", "\n", _iterate),
        await _scenario("iterate generic (newline='\\r\\n')", "\r\n", "\r\n", _iterate),
        await _scenario("readlines(64) loop, fast", "\n", "\n", _readlines_small_hint),
        await _scenario("readlines(64) loop, generic", "", "\n", _readlines_small_hint),
        await _scenario("read(1000) loop", "\n", "\n", _sized_reads),
    ]
    text = json.dumps(rows, indent=2)
    print(text)
    if args.output:
        with open(args.output, "x", encoding="utf-8") as stream:
            stream.write(text + "\n")


if __name__ == "__main__":
    asyncio.run(main())
