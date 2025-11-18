"""
Compression benchmarks for aiogzip.

Tests compression ratios and format compatibility.
"""

import gzip

from bench_common import BenchmarkBase, format_size

from aiogzip import AsyncGzipBinaryFile


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

    async def run_all(self):
        """Run all compression benchmarks."""
        await self.benchmark_compression_ratios()
