"""
Real-world scenario benchmarks for aiogzip.

Tests practical use cases and workflows.
"""

import gzip
import json
import time

from bench_common import BenchmarkBase, format_speedup, write_comparison_fixture

from aiogzip import AsyncGzipTextFile


class ScenariosBenchmarks(BenchmarkBase):
    """Real-world scenario benchmarks."""

    async def benchmark_jsonl_processing(self):
        """Benchmark read-only JSONL parsing from one identical fixture."""
        jsonl_data = self.data_gen.generate_jsonl(self.data_size_mb)
        fixture = self.temp_mgr.get_path("data.jsonl.gz")
        write_comparison_fixture(fixture, jsonl_data.encode("utf-8"))

        start = time.perf_counter()
        aiogzip_count = 0
        aiogzip_id_sum = 0
        async with AsyncGzipTextFile(
            fixture,
            "rt",
            encoding="utf-8",
            newline="\n",
            chunk_size=512 * 1024,
        ) as f:
            async for line in f:
                record = json.loads(line)
                aiogzip_count += 1
                aiogzip_id_sum += record["id"]
        aiogzip_time = time.perf_counter() - start

        start = time.perf_counter()
        batched_count = 0
        batched_id_sum = 0
        async with AsyncGzipTextFile(
            fixture,
            "rt",
            encoding="utf-8",
            newline="\n",
            chunk_size=512 * 1024,
        ) as f:
            while True:
                lines = await f.readlines(1024 * 1024)
                if not lines:
                    break
                for line in lines:
                    record = json.loads(line)
                    batched_count += 1
                    batched_id_sum += record["id"]
        batched_time = time.perf_counter() - start

        start = time.perf_counter()
        gzip_count = 0
        gzip_id_sum = 0
        with gzip.open(fixture, "rt", encoding="utf-8", newline="\n") as f:
            for line in f:
                record = json.loads(line)
                gzip_count += 1
                gzip_id_sum += record["id"]
        gzip_time = time.perf_counter() - start

        assert aiogzip_count == gzip_count
        assert aiogzip_id_sum == gzip_id_sum
        assert batched_count == gzip_count
        assert batched_id_sum == gzip_id_sum

        self.add_result(
            "JSONL read and parse (identical fixture)",
            "scenarios",
            aiogzip_time,
            aiogzip_time=f"{aiogzip_time:.4f}s",
            gzip_time=f"{gzip_time:.4f}s",
            records=aiogzip_count,
            speedup=format_speedup(aiogzip_time, gzip_time),
            tuning='newline="\\n", chunk_size=512 KiB',
        )
        self.add_result(
            "JSONL batched readlines and parse (identical fixture)",
            "scenarios",
            batched_time,
            aiogzip_time=f"{batched_time:.4f}s",
            gzip_time=f"{gzip_time:.4f}s",
            records=batched_count,
            speedup=format_speedup(batched_time, gzip_time),
            tuning='newline="\\n", chunk_size=512 KiB, readlines=1 MiB',
        )

    async def run_all(self):
        """Run all scenario benchmarks."""
        await self.benchmark_jsonl_processing()
