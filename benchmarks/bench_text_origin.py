"""
Text replay-origin benchmarks for aiogzip.

Targets the text paths that read or replace the replay origin, which the io
and micro categories do not isolate: tell()/seek(cookie) round trips,
line reading with periodic tell(), and small-hint readlines() calls, each
of which captures the origin's fields for rollback. Buffer compaction is not
reached by these public paths; tests drive it directly. Public API only, so one runner can
time any source root.
"""

import time

from bench_common import BenchmarkBase

from aiogzip import AsyncGzipTextFile

# Multibyte text keeps the decoder state non-trivial, so cookies are packed.
_LINES = "".join(f"行 {i:06d} 日本語のテキスト\n" for i in range(20_000))


class TextOriginBenchmarks(BenchmarkBase):
    """Cookie, compaction and rollback-capture paths of the text reader."""

    async def _timed(self, iterations, operation):
        total = 0.0
        for _ in range(iterations):
            start = time.perf_counter()
            await operation()
            total += time.perf_counter() - start
        return total / iterations

    def _record(self, name, avg_time, iterations):
        self.add_result(
            name,
            "text_origin",
            avg_time,
            iterations=iterations,
            avg_time_ms=f"{avg_time * 1000:.3f}ms",
        )

    async def _write(self, name):
        path = self.temp_mgr.get_path(name)
        async with AsyncGzipTextFile(path, "wt", encoding="utf-8") as f:
            await f.write(_LINES)
        return path

    async def benchmark_cookie_round_trips(self):
        """tell(), read a line, seek back to the cookie and re-read it."""
        path = await self._write("origin_cookies.gz")
        trips = 200
        iterations = 5

        async def operation():
            async with AsyncGzipTextFile(path, "rt", encoding="utf-8") as f:
                for _ in range(trips):
                    cookie = await f.tell()
                    line = await f.readline()
                    await f.seek(cookie)
                    assert await f.readline() == line

        avg = await self._timed(iterations, operation)
        self._record("tell/seek cookie round trip x200", avg, iterations)

    async def benchmark_readline_with_periodic_tell(self):
        """Read line by line with a tell() every 50 lines (fast line path)."""
        path = await self._write("origin_periodic_tell.gz")
        iterations = 10

        async def operation():
            async with AsyncGzipTextFile(
                path, "rt", encoding="utf-8", chunk_size=4096
            ) as f:
                count = 0
                while await f.readline():
                    count += 1
                    if count % 50 == 0:
                        await f.tell()

        avg = await self._timed(iterations, operation)
        self._record("readline + tell every 50 lines - 20K lines", avg, iterations)

    async def benchmark_small_hint_readlines(self):
        """readlines(hint) in a loop: one rollback capture per call."""
        path = await self._write("origin_readlines.gz")
        iterations = 10

        async def operation():
            async with AsyncGzipTextFile(path, "rt", encoding="utf-8") as f:
                while await f.readlines(64):
                    pass

        avg = await self._timed(iterations, operation)
        self._record("readlines(64) loop - 20K lines", avg, iterations)

    async def run_all(self):
        """Run all text-origin benchmarks."""
        await self.benchmark_cookie_round_trips()
        await self.benchmark_readline_with_periodic_tell()
        await self.benchmark_small_hint_readlines()
