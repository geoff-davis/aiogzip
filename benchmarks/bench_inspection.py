"""Benchmarks for complete-stream gzip inspection and verification."""

import gzip
import time
import tracemalloc

from bench_common import BenchmarkBase

import aiogzip


class InspectionBenchmarks(BenchmarkBase):
    """Compare scan time and Python allocation peaks with full reads."""

    def setup(self):
        super().setup()
        size = max(self.data_size_bytes, 1)
        fixtures = {
            "compressible": b"A" * size,
            "incompressible": self.data_gen.generate_binary(self.data_size_mb),
            "many-members": b"member payload\n" * max(1, size // 15),
        }
        self.paths = {}
        for name, payload in fixtures.items():
            path = self.temp_mgr.get_path(f"{name}.gz")
            if name == "many-members":
                member_size = max(1, len(payload) // 1000)
                raw = b"".join(
                    gzip.compress(payload[offset : offset + member_size], mtime=0)
                    for offset in range(0, len(payload), member_size)
                )
            else:
                raw = gzip.compress(payload, mtime=0)
            path.write_bytes(raw)
            self.paths[name] = path

    async def _measure(self, name, operation):
        tracemalloc.start()
        start = time.perf_counter()
        await operation(self.paths[name])
        duration = time.perf_counter() - start
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        self.add_result(
            f"{operation.__name__} ({name})",
            "inspection",
            duration,
            peak_python_mb=peak / (1024 * 1024),
            engine=aiogzip.engine_info().decompression,
        )

    async def _read_discard(self, path):
        await aiogzip.read(path)

    async def run_all(self):
        """Benchmark verification, inspection, and full read-and-discard."""
        for name in self.paths:
            await self._measure(name, aiogzip.verify)
            await self._measure(name, aiogzip.inspect)
            await self._measure(name, self._read_discard)
