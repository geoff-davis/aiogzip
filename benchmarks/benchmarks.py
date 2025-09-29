#!/usr/bin/env python3
"""
Consolidated benchmark suite for aiogzip.

This module provides comprehensive benchmarks comparing aiogzip against standard gzip
and other I/O approaches. It includes the most informative benchmarks from all previous
benchmark modules, organized by category.

Benchmark Categories:
1. Basic Operations - Core read/write performance
2. Memory Efficiency - Memory usage patterns and limits
3. Concurrent Processing - Async I/O advantages
4. Real-world Scenarios - Practical use cases
5. Compression Analysis - Compression ratios and efficiency
6. Error Handling - Robustness testing
"""

import asyncio
import gzip
import json
import os
import random
import shutil
import string
import tempfile
import time
from typing import Dict

from aiogzip import AsyncGzipBinaryFile, AsyncGzipTextFile

try:
    import psutil

    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    print("Warning: psutil not available, memory benchmarks will be skipped")


class ConsolidatedBenchmarkSuite:
    """Consolidated benchmark suite with the most informative benchmarks."""

    def __init__(self, data_size_mb: int = 1):
        self.data_size_mb = data_size_mb
        self.data_size_bytes = int(data_size_mb * 1024 * 1024)
        self.temp_dir: str | None = None
        self.results: Dict[str, Dict] = {}

    def setup(self):
        """Create temporary directory and test data files."""
        self.temp_dir = tempfile.mkdtemp(prefix="aiogzip_consolidated_benchmark_")
        print(f"Created temporary directory: {self.temp_dir}")

        # Create test data
        self.binary_data = os.urandom(self.data_size_bytes)
        self.text_data = self._generate_text_data()
        self.jsonl_data = self._generate_jsonl_data()
        self.highly_compressible_data = b"A" * self.data_size_bytes

        print(
            f"Created test data: {self.data_size_mb}MB binary, text, JSONL, and highly compressible"
        )

    def cleanup(self):
        """Clean up temporary files and directory."""
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
            print(f"Cleaned up temporary directory: {self.temp_dir}")

    def _generate_text_data(self) -> str:
        """Generate realistic text data."""
        words = [
            "hello",
            "world",
            "python",
            "async",
            "gzip",
            "compression",
            "data",
            "file",
            "test",
            "benchmark",
        ]
        lines: list[str] = []
        for _ in range(self.data_size_bytes // 50):  # Approximate line count
            line = " ".join(random.choices(words, k=random.randint(5, 15)))
            lines.append(line)
        return "\n".join(lines)

    def _generate_jsonl_data(self) -> str:
        """Generate JSONL data."""
        lines: list[str] = []
        for i in range(self.data_size_bytes // 100):  # Approximate record count
            record = {
                "id": i,
                "name": f"item_{i}",
                "value": random.randint(1, 1000),
                "description": " ".join(random.choices(string.ascii_letters, k=20)),
            }
            lines.append(json.dumps(record))
        return "\n".join(lines)

    # ============================================================================
    # 1. BASIC OPERATIONS BENCHMARKS
    # ============================================================================

    async def benchmark_basic_binary_operations(self) -> Dict[str, float]:
        """
        Measures: Binary file read/write performance with small chunks

        What it tests:
        - Sequential read/write operations with 10-byte chunks
        - Fair comparison: both aiogzip and gzip use same chunking strategy
        - Performance impact of async/await overhead on small operations
        """
        print("\n=== Basic Binary Operations Benchmark ===")

        # Test files
        assert self.temp_dir is not None
        aiogzip_file = os.path.join(self.temp_dir, "aiogzip_binary.gz")
        gzip_file = os.path.join(self.temp_dir, "gzip_binary.gz")

        results = {}

        # aiogzip write
        start_time = time.time()
        async with AsyncGzipBinaryFile(aiogzip_file, "wb") as f:
            for i in range(0, len(self.binary_data), 10):
                chunk = self.binary_data[i : i + 10]
                await f.write(chunk)
        aiogzip_write_time = time.time() - start_time

        # aiogzip read
        start_time = time.time()
        read_data = b""
        async with AsyncGzipBinaryFile(aiogzip_file, "rb") as f:
            while True:
                chunk = await f.read(10)
                if not chunk:
                    break
                read_data += chunk
        aiogzip_read_time = time.time() - start_time

        # gzip write
        start_time = time.time()
        with gzip.open(gzip_file, "wb") as f:
            for i in range(0, len(self.binary_data), 10):
                chunk = self.binary_data[i : i + 10]
                f.write(chunk)
        gzip_write_time = time.time() - start_time

        # gzip read (fair comparison - also read in 10-byte chunks)
        start_time = time.time()
        read_data_gzip = b""
        with gzip.open(gzip_file, "rb") as f:
            while True:
                chunk = f.read(10)
                if not chunk:
                    break
                read_data_gzip += chunk
        gzip_read_time = time.time() - start_time

        # Verify data integrity
        assert read_data == self.binary_data, "aiogzip data integrity failed"
        assert read_data_gzip == self.binary_data, "gzip data integrity failed"

        results = {
            "aiogzip_write_time": aiogzip_write_time,
            "aiogzip_read_time": aiogzip_read_time,
            "gzip_write_time": gzip_write_time,
            "gzip_read_time": gzip_read_time,
            "aiogzip_total_time": aiogzip_write_time + aiogzip_read_time,
            "gzip_total_time": gzip_write_time + gzip_read_time,
            "aiogzip_vs_gzip_ratio": (aiogzip_write_time + aiogzip_read_time)
            / (gzip_write_time + gzip_read_time),
        }

        print(
            f"aiogzip write: {aiogzip_write_time:.3f}s, read: {aiogzip_read_time:.3f}s"
        )
        print(f"gzip write: {gzip_write_time:.3f}s, read: {gzip_read_time:.3f}s")
        print(f"aiogzip vs gzip ratio: {results['aiogzip_vs_gzip_ratio']:.2f}x")

        return results

    async def benchmark_realistic_binary_operations(self) -> Dict[str, float]:
        """
        Measures: Realistic binary file operations with reasonable chunk sizes

        What it tests:
        - More realistic chunk sizes (1KB instead of 10 bytes)
        - Both read and write operations with same chunking strategy
        - Performance closer to real-world usage patterns
        """
        print("\n=== Realistic Binary Operations Benchmark ===")

        # Test files
        assert self.temp_dir is not None
        aiogzip_file = os.path.join(self.temp_dir, "aiogzip_realistic.gz")
        gzip_file = os.path.join(self.temp_dir, "gzip_realistic.gz")

        chunk_size = 1024  # 1KB chunks - more realistic

        # aiogzip write
        start_time = time.time()
        async with AsyncGzipBinaryFile(aiogzip_file, "wb") as f:
            for i in range(0, len(self.binary_data), chunk_size):
                chunk = self.binary_data[i : i + chunk_size]
                await f.write(chunk)
        aiogzip_write_time = time.time() - start_time

        # aiogzip read
        start_time = time.time()
        read_data = b""
        async with AsyncGzipBinaryFile(aiogzip_file, "rb") as f:
            while True:
                chunk = await f.read(chunk_size)
                if not chunk:
                    break
                read_data += chunk
        aiogzip_read_time = time.time() - start_time

        # gzip write
        start_time = time.time()
        with gzip.open(gzip_file, "wb") as f:
            for i in range(0, len(self.binary_data), chunk_size):
                chunk = self.binary_data[i : i + chunk_size]
                f.write(chunk)
        gzip_write_time = time.time() - start_time

        # gzip read (fair comparison - same chunking)
        start_time = time.time()
        read_data_gzip = b""
        with gzip.open(gzip_file, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                read_data_gzip += chunk
        gzip_read_time = time.time() - start_time

        # Verify data integrity
        assert read_data == self.binary_data, "aiogzip data integrity failed"
        assert read_data_gzip == self.binary_data, "gzip data integrity failed"

        results = {
            "aiogzip_write_time": aiogzip_write_time,
            "aiogzip_read_time": aiogzip_read_time,
            "gzip_write_time": gzip_write_time,
            "gzip_read_time": gzip_read_time,
            "aiogzip_total_time": aiogzip_write_time + aiogzip_read_time,
            "gzip_total_time": gzip_write_time + gzip_read_time,
            "aiogzip_vs_gzip_ratio": (aiogzip_write_time + aiogzip_read_time)
            / (gzip_write_time + gzip_read_time),
            "chunk_size": chunk_size,
        }

        print(
            f"aiogzip write: {aiogzip_write_time:.3f}s, read: {aiogzip_read_time:.3f}s"
        )
        print(f"gzip write: {gzip_write_time:.3f}s, read: {gzip_read_time:.3f}s")
        print(f"aiogzip vs gzip ratio: {results['aiogzip_vs_gzip_ratio']:.2f}x")
        print(f"Chunk size: {chunk_size} bytes")

        return results

    async def benchmark_basic_text_operations(self) -> Dict[str, float]:
        """
        Measures: Basic text file read/write performance

        What it tests:
        - Text mode operations with UTF-8 encoding
        - Line-by-line processing
        - Text data compression efficiency
        """
        print("\n=== Basic Text Operations Benchmark ===")

        # Test files
        assert self.temp_dir is not None
        aiogzip_file = os.path.join(self.temp_dir, "aiogzip_text.gz")
        gzip_file = os.path.join(self.temp_dir, "gzip_text.gz")

        # aiogzip write
        start_time = time.time()
        async with AsyncGzipTextFile(aiogzip_file, "wt") as f:
            await f.write(self.text_data)
        aiogzip_write_time = time.time() - start_time

        # aiogzip read
        start_time = time.time()
        async with AsyncGzipTextFile(aiogzip_file, "rt") as f:
            read_data = await f.read()
        aiogzip_read_time = time.time() - start_time

        # gzip write
        start_time = time.time()
        with gzip.open(gzip_file, "wt") as f:
            f.write(self.text_data)
        gzip_write_time = time.time() - start_time

        # gzip read
        start_time = time.time()
        with gzip.open(gzip_file, "rt") as f:
            read_data_gzip = f.read()
        gzip_read_time = time.time() - start_time

        # Verify data integrity
        assert read_data == self.text_data, "aiogzip text data integrity failed"
        assert read_data_gzip == self.text_data, "gzip text data integrity failed"

        results = {
            "aiogzip_write_time": aiogzip_write_time,
            "aiogzip_read_time": aiogzip_read_time,
            "gzip_write_time": gzip_write_time,
            "gzip_read_time": gzip_read_time,
            "aiogzip_total_time": aiogzip_write_time + aiogzip_read_time,
            "gzip_total_time": gzip_write_time + gzip_read_time,
            "aiogzip_vs_gzip_ratio": (aiogzip_write_time + aiogzip_read_time)
            / (gzip_write_time + gzip_read_time),
        }

        print(
            f"aiogzip write: {aiogzip_write_time:.3f}s, read: {aiogzip_read_time:.3f}s"
        )
        print(f"gzip write: {gzip_write_time:.3f}s, read: {gzip_read_time:.3f}s")
        print(f"aiogzip vs gzip ratio: {results['aiogzip_vs_gzip_ratio']:.2f}x")

        return results

    # ============================================================================
    # 2. MEMORY EFFICIENCY BENCHMARKS
    # ============================================================================

    async def benchmark_memory_efficiency(self) -> Dict[str, float]:
        """
        Measures: Memory usage patterns during file operations

        What it tests:
        - Memory consumption during large file processing
        - Memory efficiency with highly compressible data
        - Peak memory usage vs data size ratios
        """
        if not PSUTIL_AVAILABLE:
            print(
                "\n=== Memory Efficiency Benchmark (skipped - psutil not available) ==="
            )
            return {"skipped": True}

        print("\n=== Memory Efficiency Benchmark ===")

        process = psutil.Process()
        initial_memory = process.memory_info().rss

        # Test with highly compressible data (worst case for memory)
        test_data = b"A" * (5 * 1024 * 1024)  # 5MB of 'A's

        assert self.temp_dir is not None
        test_file = os.path.join(self.temp_dir, "memory_test.gz")

        # Write data
        async with AsyncGzipBinaryFile(test_file, "wb") as f:
            await f.write(test_data)

        write_memory = process.memory_info().rss

        # Read data in chunks (memory-efficient approach)
        max_memory = write_memory
        chunk_size = 8192

        async with AsyncGzipBinaryFile(test_file, "rb", chunk_size=chunk_size) as f:
            total_read = 0
            while True:
                chunk = await f.read(chunk_size)
                if not chunk:
                    break
                total_read += len(chunk)
                current_memory = process.memory_info().rss
                max_memory = max(max_memory, current_memory)

        memory_increase = max_memory - initial_memory
        memory_ratio = memory_increase / len(test_data) if len(test_data) > 0 else 0

        results = {
            "initial_memory_mb": initial_memory / 1024 / 1024,
            "max_memory_mb": max_memory / 1024 / 1024,
            "memory_increase_mb": memory_increase / 1024 / 1024,
            "data_size_mb": len(test_data) / 1024 / 1024,
            "memory_ratio": memory_ratio,
            "total_read_bytes": total_read,
        }

        print(f"Memory increase: {memory_increase / 1024 / 1024:.1f} MB")
        print(f"Data size: {len(test_data) / 1024 / 1024:.1f} MB")
        print(f"Memory ratio: {memory_ratio:.2f}")
        print(f"Data integrity: {'OK' if total_read == len(test_data) else 'FAILED'}")

        return results

    # ============================================================================
    # 3. CONCURRENT PROCESSING BENCHMARKS
    # ============================================================================

    async def benchmark_concurrent_processing(self) -> Dict[str, float]:
        """
        Measures: Performance advantages of async I/O in concurrent scenarios

        What it tests:
        - Parallel file processing capabilities
        - Async I/O benefits over synchronous operations
        - Scalability with multiple concurrent operations
        """
        print("\n=== Concurrent Processing Benchmark ===")

        num_files = 5
        file_size = self.data_size_bytes // num_files

        # Create test files
        assert self.temp_dir is not None
        test_files = []
        for i in range(num_files):
            file_path = os.path.join(self.temp_dir, f"concurrent_test_{i}.gz")
            test_files.append(file_path)

            # Write test data
            test_data = os.urandom(file_size)
            async with AsyncGzipBinaryFile(file_path, "wb") as f:
                await f.write(test_data)

        # Async concurrent processing
        async def process_file_async(file_path: str) -> int:
            total_read = 0
            async with AsyncGzipBinaryFile(file_path, "rb") as f:
                while True:
                    chunk = await f.read(1024)
                    if not chunk:
                        break
                    total_read += len(chunk)
            return total_read

        start_time = time.time()
        results_async = await asyncio.gather(
            *[process_file_async(f) for f in test_files]
        )
        async_time = time.time() - start_time

        # Sync sequential processing
        def process_file_sync(file_path: str) -> int:
            total_read = 0
            with gzip.open(file_path, "rb") as f:
                while True:
                    chunk = f.read(1024)
                    if not chunk:
                        break
                    total_read += len(chunk)
            return total_read

        start_time = time.time()
        results_sync = [process_file_sync(f) for f in test_files]
        sync_time = time.time() - start_time

        # Verify data integrity
        assert all(r > 0 for r in results_async), "Async processing failed"
        assert all(r > 0 for r in results_sync), "Sync processing failed"

        results = {
            "async_time": async_time,
            "sync_time": sync_time,
            "async_vs_sync_ratio": async_time / sync_time,
            "speedup": sync_time / async_time,
            "files_processed": num_files,
        }

        print(f"Async processing: {async_time:.3f}s")
        print(f"Sync processing: {sync_time:.3f}s")
        print(f"Speedup: {results['speedup']:.2f}x")

        return results

    # ============================================================================
    # 4. REAL-WORLD SCENARIOS BENCHMARKS
    # ============================================================================

    async def benchmark_jsonl_processing(self) -> Dict[str, float]:
        """
        Measures: JSONL file processing performance (common in data pipelines)

        What it tests:
        - Line-by-line JSON processing
        - Text compression efficiency
        - Real-world data processing patterns
        """
        print("\n=== JSONL Processing Benchmark ===")

        assert self.temp_dir is not None
        aiogzip_file = os.path.join(self.temp_dir, "aiogzip_jsonl.gz")
        gzip_file = os.path.join(self.temp_dir, "gzip_jsonl.gz")

        # aiogzip processing
        start_time = time.time()
        async with AsyncGzipTextFile(aiogzip_file, "wt") as f:
            await f.write(self.jsonl_data)

        records_processed = 0
        async with AsyncGzipTextFile(aiogzip_file, "rt") as f:
            async for line in f:
                if line.strip():
                    json.loads(line.strip())
                    records_processed += 1
        aiogzip_time = time.time() - start_time

        # gzip processing
        start_time = time.time()
        with gzip.open(gzip_file, "wt") as f:
            f.write(self.jsonl_data)

        records_processed_gzip = 0
        with gzip.open(gzip_file, "rt") as f:
            for line in f:
                if line.strip():
                    json.loads(line.strip())
                    records_processed_gzip += 1
        gzip_time = time.time() - start_time

        results = {
            "aiogzip_time": aiogzip_time,
            "gzip_time": gzip_time,
            "aiogzip_vs_gzip_ratio": aiogzip_time / gzip_time,
            "records_processed": records_processed,
            "records_per_second_aiogzip": (
                records_processed / aiogzip_time if aiogzip_time > 0 else 0
            ),
            "records_per_second_gzip": (
                records_processed_gzip / gzip_time if gzip_time > 0 else 0
            ),
        }

        print(f"aiogzip: {aiogzip_time:.3f}s, {records_processed} records")
        print(f"gzip: {gzip_time:.3f}s, {records_processed_gzip} records")
        print(f"aiogzip vs gzip ratio: {results['aiogzip_vs_gzip_ratio']:.2f}x")

        return results

    # ============================================================================
    # 5. COMPRESSION ANALYSIS BENCHMARKS
    # ============================================================================

    async def benchmark_compression_analysis(self) -> Dict[str, float]:
        """
        Measures: Compression efficiency and ratios

        What it tests:
        - Compression ratios for different data types
        - Compression speed vs decompression speed
        - File size reduction effectiveness
        """
        print("\n=== Compression Analysis Benchmark ===")

        assert self.temp_dir is not None

        # Test different data types
        test_cases = {
            "random_binary": self.binary_data,
            "highly_compressible": self.highly_compressible_data,
            "text_data": self.text_data.encode("utf-8"),
            "jsonl_data": self.jsonl_data.encode("utf-8"),
        }

        results = {}

        for data_type, data in test_cases.items():
            # aiogzip compression
            aiogzip_file = os.path.join(self.temp_dir, f"aiogzip_{data_type}.gz")
            start_time = time.time()
            async with AsyncGzipBinaryFile(aiogzip_file, "wb") as f:
                await f.write(data)
            aiogzip_compress_time = time.time() - start_time

            # Get compressed file size
            aiogzip_size = os.path.getsize(aiogzip_file)

            # gzip compression
            gzip_file = os.path.join(self.temp_dir, f"gzip_{data_type}.gz")
            start_time = time.time()
            with gzip.open(gzip_file, "wb") as f:
                f.write(data)
            gzip_compress_time = time.time() - start_time

            # Get compressed file size
            gzip_size = os.path.getsize(gzip_file)

            # Calculate compression ratios
            original_size = len(data)
            aiogzip_ratio = original_size / aiogzip_size if aiogzip_size > 0 else 0
            gzip_ratio = original_size / gzip_size if gzip_size > 0 else 0

            results[data_type] = {
                "original_size": original_size,
                "aiogzip_compressed_size": aiogzip_size,
                "gzip_compressed_size": gzip_size,
                "aiogzip_compression_ratio": aiogzip_ratio,
                "gzip_compression_ratio": gzip_ratio,
                "aiogzip_compress_time": aiogzip_compress_time,
                "gzip_compress_time": gzip_compress_time,
                "size_difference_bytes": abs(aiogzip_size - gzip_size),
            }

        # Print summary
        for data_type, data_results in results.items():
            print(f"{data_type}:")
            print(f"  Original: {data_results['original_size']:,} bytes")
            print(
                f"  aiogzip: {data_results['aiogzip_compressed_size']:,} bytes ({data_results['aiogzip_compression_ratio']:.2f}x)"
            )
            print(
                f"  gzip: {data_results['gzip_compressed_size']:,} bytes ({data_results['gzip_compression_ratio']:.2f}x)"
            )
            print(f"  Size diff: {data_results['size_difference_bytes']} bytes")

        return results

    # ============================================================================
    # 6. ERROR HANDLING BENCHMARKS
    # ============================================================================

    async def benchmark_error_handling(self) -> Dict[str, float]:
        """
        Measures: Error handling robustness and performance impact

        What it tests:
        - Performance with corrupted data
        - Error recovery mechanisms
        - Graceful degradation under error conditions
        """
        print("\n=== Error Handling Benchmark ===")

        assert self.temp_dir is not None

        # Create corrupted file
        corrupted_file = os.path.join(self.temp_dir, "corrupted.gz")
        with open(corrupted_file, "wb") as f:
            f.write(b"This is not a valid gzip file")

        # Test error handling performance
        start_time = time.time()
        error_count = 0

        for _ in range(10):  # Test multiple attempts
            try:
                async with AsyncGzipBinaryFile(corrupted_file, "rb") as f:
                    await f.read(1024)
            except OSError:
                error_count += 1
            except Exception:
                error_count += 1

        error_handling_time = time.time() - start_time

        results = {
            "error_handling_time": error_handling_time,
            "errors_caught": error_count,
            "error_handling_rate": (
                error_count / error_handling_time if error_handling_time > 0 else 0
            ),
        }

        print(f"Error handling time: {error_handling_time:.3f}s")
        print(f"Errors caught: {error_count}/10")
        print(f"Error handling rate: {results['error_handling_rate']:.1f} errors/sec")

        return results

    # ============================================================================
    # MAIN BENCHMARK RUNNER
    # ============================================================================

    async def run_all_benchmarks(self) -> Dict[str, Dict]:
        """Run all benchmarks and return consolidated results."""
        print("=" * 60)
        print("CONSOLIDATED AIOGZIP BENCHMARK SUITE")
        print("=" * 60)

        self.setup()

        try:
            # Run all benchmarks
            self.results["basic_binary"] = (
                await self.benchmark_basic_binary_operations()
            )
            self.results["realistic_binary"] = (
                await self.benchmark_realistic_binary_operations()
            )
            self.results["basic_text"] = await self.benchmark_basic_text_operations()
            self.results["memory_efficiency"] = await self.benchmark_memory_efficiency()
            self.results["concurrent_processing"] = (
                await self.benchmark_concurrent_processing()
            )
            self.results["jsonl_processing"] = await self.benchmark_jsonl_processing()
            self.results["compression_analysis"] = (
                await self.benchmark_compression_analysis()
            )
            self.results["error_handling"] = await self.benchmark_error_handling()

            # Generate summary
            self._print_summary()

        finally:
            self.cleanup()

        return self.results

    def _print_summary(self):
        """Print a summary of all benchmark results."""
        print("\n" + "=" * 60)
        print("BENCHMARK SUMMARY")
        print("=" * 60)

        # Basic operations summary
        if "basic_binary" in self.results:
            binary_ratio = self.results["basic_binary"]["aiogzip_vs_gzip_ratio"]
            print(
                f"Binary Operations (10-byte chunks): aiogzip is {binary_ratio:.2f}x {'slower' if binary_ratio > 1 else 'faster'} than gzip"
            )

        if "realistic_binary" in self.results:
            realistic_ratio = self.results["realistic_binary"]["aiogzip_vs_gzip_ratio"]
            print(
                f"Binary Operations (1KB chunks): aiogzip is {realistic_ratio:.2f}x {'slower' if realistic_ratio > 1 else 'faster'} than gzip"
            )

        if "basic_text" in self.results:
            text_ratio = self.results["basic_text"]["aiogzip_vs_gzip_ratio"]
            print(
                f"Text Operations: aiogzip is {text_ratio:.2f}x {'slower' if text_ratio > 1 else 'faster'} than gzip"
            )

        # Concurrent processing summary
        if "concurrent_processing" in self.results:
            speedup = self.results["concurrent_processing"]["speedup"]
            print(f"Concurrent Processing: {speedup:.2f}x speedup with async I/O")

        # Memory efficiency summary
        if "memory_efficiency" in self.results and not self.results[
            "memory_efficiency"
        ].get("skipped", False):
            memory_ratio = self.results["memory_efficiency"]["memory_ratio"]
            print(f"Memory Efficiency: {memory_ratio:.2f}x memory usage vs data size")

        # JSONL processing summary
        if "jsonl_processing" in self.results:
            jsonl_ratio = self.results["jsonl_processing"]["aiogzip_vs_gzip_ratio"]
            print(
                f"JSONL Processing: aiogzip is {jsonl_ratio:.2f}x {'slower' if jsonl_ratio > 1 else 'faster'} than gzip"
            )

        print("=" * 60)


async def main():
    """Run the consolidated benchmark suite."""
    suite = ConsolidatedBenchmarkSuite(data_size_mb=1)
    results = await suite.run_all_benchmarks()
    return results


if __name__ == "__main__":
    asyncio.run(main())
