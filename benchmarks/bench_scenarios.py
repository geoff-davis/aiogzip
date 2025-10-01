"""
Real-world scenario benchmarks for aiogzip.

Tests practical use cases and workflows.
"""

import gzip
import json
import time

from aiogzip import AsyncGzipTextFile
from bench_common import BenchmarkBase


class ScenariosBenchmarks(BenchmarkBase):
    """Real-world scenario benchmarks."""

    async def benchmark_jsonl_processing(self):
        """Benchmark JSONL file processing."""
        jsonl_data = self.data_gen.generate_jsonl(1)
        aiogzip_file = self.temp_mgr.get_path("data_aiogzip.jsonl.gz")
        gzip_file = self.temp_mgr.get_path("data_gzip.jsonl.gz")

        # aiogzip: Write and read JSONL
        start = time.perf_counter()
        async with AsyncGzipTextFile(aiogzip_file, "wt") as f:
            await f.write(jsonl_data)

        records_aiogzip = []
        async with AsyncGzipTextFile(aiogzip_file, "rt") as f:
            async for line in f:
                records_aiogzip.append(json.loads(line))
        aiogzip_time = time.perf_counter() - start

        # gzip: Write and read JSONL
        start = time.perf_counter()
        with gzip.open(gzip_file, "wt") as f:
            f.write(jsonl_data)

        records_gzip = []
        with gzip.open(gzip_file, "rt") as f:
            for line in f:
                records_gzip.append(json.loads(line))
        gzip_time = time.perf_counter() - start

        speedup = gzip_time / aiogzip_time if aiogzip_time > 0 else 0

        self.add_result(
            "JSONL processing",
            "scenarios",
            aiogzip_time,
            aiogzip_time=f"{aiogzip_time:.3f}s",
            gzip_time=f"{gzip_time:.3f}s",
            records=len(records_aiogzip),
            speedup=f"{speedup:.2f}x"
        )

    async def run_all(self):
        """Run all scenario benchmarks."""
        await self.benchmark_jsonl_processing()
