"""
Read-health benchmarks for aiogzip.

Targets the binary paths whose health handling WP6 changed and that the io and
micro categories do not reach: seek-to-0 rewind of a healthy reader, recovery
rewind of a broken reader, and draining validation-salvage data through read()
and readline(). Public API only, so one runner can time any source root.
"""

import gzip
import random
import time

from bench_common import BenchmarkBase

from aiogzip import AsyncGzipBinaryFile

# Incompressible bytes span many source chunks, so a fresh reader returns a
# prefix without inflating the whole member at once.
_LARGE = random.Random(0).randbytes(4 * 1024 * 1024)
_LINES = b"".join(b"salvage line %06d\n" % i for i in range(50_000))


def _corrupt_crc(data: bytes) -> bytes:
    corrupt = bytearray(gzip.compress(data, mtime=0))
    corrupt[-8] ^= 1
    return bytes(corrupt)


class ReadHealthBenchmarks(BenchmarkBase):
    """Seek, recovery and validation-salvage paths of the binary reader."""

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
            "read_health",
            avg_time,
            iterations=iterations,
            avg_time_ms=f"{avg_time * 1000:.3f}ms",
        )

    async def benchmark_healthy_seek_to_zero(self):
        """Rewind a healthy reader to 0 and re-read a prefix, repeatedly."""
        path = self.temp_mgr.get_path("health_seek.gz")
        path.write_bytes(gzip.compress(_LARGE, mtime=0))
        rewinds = 50
        iterations = 20

        async def operation():
            async with AsyncGzipBinaryFile(path, "rb") as f:
                for _ in range(rewinds):
                    await f.read(65536)
                    await f.seek(0)

        avg = await self._timed(iterations, operation)
        self._record("seek(0) rewind x50 - healthy reader", avg, iterations)

    async def benchmark_broken_reader_recovery(self):
        """Break a reader at the size limit, rewind to recover, read a prefix."""
        path = self.temp_mgr.get_path("health_recover.gz")
        path.write_bytes(gzip.compress(_LARGE, mtime=0))
        limit = len(_LARGE) - 1
        recoveries = 10
        iterations = 10

        async def operation():
            async with AsyncGzipBinaryFile(
                path, "rb", max_decompressed_size=limit
            ) as f:
                for _ in range(recoveries):
                    try:
                        await f.read()
                    except OSError:
                        pass
                    await f.seek(0)
                    await f.read(65536)

        avg = await self._timed(iterations, operation)
        self._record("limit break + seek(0) recovery x10", avg, iterations)

    async def benchmark_salvage_read(self):
        """Report a CRC failure, then drain the salvage data with read()."""
        path = self.temp_mgr.get_path("health_salvage.gz")
        path.write_bytes(_corrupt_crc(_LARGE))
        iterations = 20

        async def operation():
            async with AsyncGzipBinaryFile(path, "rb") as f:
                try:
                    await f.read()
                except gzip.BadGzipFile:
                    pass
                data = await f.read()
                assert len(data) == len(_LARGE)

        avg = await self._timed(iterations, operation)
        self._record("CRC failure + salvage read() - 4MB", avg, iterations)

    async def benchmark_salvage_readline(self):
        """Report a CRC failure, then drain the salvage data line by line."""
        path = self.temp_mgr.get_path("health_salvage_lines.gz")
        path.write_bytes(_corrupt_crc(_LINES))
        iterations = 10

        async def operation():
            async with AsyncGzipBinaryFile(path, "rb") as f:
                try:
                    await f.read()
                except gzip.BadGzipFile:
                    pass
                # Salvage is never clean EOF: once drained, the next call fails.
                count = 0
                try:
                    while await f.readline():
                        count += 1
                except OSError:
                    pass
                assert count == 50_000

        avg = await self._timed(iterations, operation)
        self._record("CRC failure + salvage readline() - 50K lines", avg, iterations)

    async def run_all(self):
        """Run all read-health benchmarks."""
        await self.benchmark_healthy_seek_to_zero()
        await self.benchmark_broken_reader_recovery()
        await self.benchmark_salvage_read()
        await self.benchmark_salvage_readline()
