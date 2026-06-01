"""
Compression benchmarks for aiogzip.

Tests compression ratios and format compatibility.
"""

import gzip
import time

from bench_common import BenchmarkBase, format_size

from aiogzip import AsyncGzipBinaryFile, _engine


class CompressionBenchmarks(BenchmarkBase):
    """Compression analysis benchmarks."""

    async def benchmark_compression_ratios(self):
        """Analyze compression ratios for different data types."""
        test_cases = {
            "random": self.data_gen.generate_binary(1),
            "compressible": self.data_gen.generate_compressible(1, "A"),
            "text": self.data_gen.generate_text(1).encode(),
        }

        for name, data in test_cases.items():
            aiogzip_file = self.temp_mgr.get_path(f"{name}_aiogzip.gz")
            gzip_file = self.temp_mgr.get_path(f"{name}_gzip.gz")

            # Write with aiogzip
            async with AsyncGzipBinaryFile(aiogzip_file, "wb") as f:
                await f.write(data)

            # Write with gzip
            with gzip.open(gzip_file, "wb") as f:
                f.write(data)

            # Compare sizes
            original_size = len(data)
            aiogzip_size = aiogzip_file.stat().st_size
            gzip_size = gzip_file.stat().st_size

            aiogzip_ratio = original_size / aiogzip_size if aiogzip_size > 0 else 0
            gzip_ratio = original_size / gzip_size if gzip_size > 0 else 0

            self.add_result(
                f"Compression: {name}",
                "compression",
                0.0,
                original=format_size(original_size),
                aiogzip_size=format_size(aiogzip_size),
                gzip_size=format_size(gzip_size),
                aiogzip_ratio=f"{aiogzip_ratio:.2f}x",
                gzip_ratio=f"{gzip_ratio:.2f}x",
            )

    async def _time_compress(self, data, fast, reps=5):
        """Return (best_seconds, output_size) for compressing ``data``."""
        best = float("inf")
        size = 0
        for _ in range(reps):
            path = self.temp_mgr.get_path(f"fc_{fast}.gz")
            start = time.perf_counter()
            async with AsyncGzipBinaryFile(
                path, "wb", mtime=0, fast_compress=fast
            ) as f:
                await f.write(data)
            best = min(best, time.perf_counter() - start)
            size = path.stat().st_size
        return best, size

    async def benchmark_fast_compress(self):
        """Compare default (stdlib) compression to fast_compress=True (zlib-ng).

        Exercises the Phase 2 opt-in path: throughput gain plus the output-size
        delta (zlib-ng's compressed bytes differ from stdlib's).
        """
        if not _engine.have_fast_engine():
            self.add_result(
                "Compression: fast_compress",
                "compression",
                0.0,
                status="skipped (install aiogzip[fast] / unset AIOGZIP_ENGINE)",
            )
            return

        data = self.data_gen.generate_text(self.data_size_mb).encode()
        mb = len(data) / (1024 * 1024)
        std_t, std_sz = await self._time_compress(data, fast=False)
        fast_t, fast_sz = await self._time_compress(data, fast=True)

        self.add_result(
            "Compression: fast_compress (text)",
            "compression",
            fast_t,
            stdlib_throughput=f"{mb / std_t:.1f} MB/s",
            fast_throughput=f"{mb / fast_t:.1f} MB/s",
            speedup=f"{std_t / fast_t:.2f}x",
            stdlib_size=format_size(std_sz),
            fast_size=format_size(fast_sz),
            size_vs_stdlib=f"{100 * fast_sz / std_sz:.1f}%",
        )

    async def run_all(self):
        """Run all compression benchmarks."""
        await self.benchmark_compression_ratios()
        await self.benchmark_fast_compress()
