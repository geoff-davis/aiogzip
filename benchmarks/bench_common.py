"""
Common infrastructure for aiogzip benchmarks.

This module provides shared utilities, base classes, and data generators
used across all benchmark modules.
"""

import json
import os
import random
import shutil
import string
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Dict, Callable, Optional


@dataclass
class BenchmarkResults:
    """Store and format benchmark results."""

    name: str
    category: str
    duration: float
    metrics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "category": self.category,
            "duration": self.duration,
            "metrics": self.metrics,
        }

    def __str__(self) -> str:
        """Format for display."""
        lines = [f"{self.name}: {self.duration:.3f}s"]
        for key, value in self.metrics.items():
            if isinstance(value, float):
                lines.append(f"  {key}: {value:.2f}")
            else:
                lines.append(f"  {key}: {value}")
        return "\n".join(lines)


class TempFileManager:
    """Manage temporary files and directories for benchmarks."""

    def __init__(self, prefix: str = "aiogzip_bench_"):
        self.prefix = prefix
        self.temp_dir: Optional[Path] = None

    def setup(self) -> Path:
        """Create temporary directory."""
        self.temp_dir = Path(tempfile.mkdtemp(prefix=self.prefix))
        return self.temp_dir

    def cleanup(self):
        """Remove temporary directory and all contents."""
        if self.temp_dir and self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
            self.temp_dir = None

    def get_path(self, filename: str) -> Path:
        """Get path within temp directory."""
        if not self.temp_dir:
            raise RuntimeError("TempFileManager not set up. Call setup() first.")
        return self.temp_dir / filename


class DataGenerator:
    """Generate test data for benchmarks."""

    @staticmethod
    def generate_binary(size_mb: int) -> bytes:
        """Generate random binary data."""
        return os.urandom(int(size_mb * 1024 * 1024))

    @staticmethod
    def generate_text(size_mb: int) -> str:
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
            "performance",
            "optimize",
            "stream",
            "buffer",
            "memory",
            "speed",
            "efficient",
            "process",
        ]
        lines: List[str] = []
        target_size = size_mb * 1024 * 1024
        current_size = 0

        while current_size < target_size:
            line = " ".join(random.choices(words, k=random.randint(5, 15)))
            lines.append(line)
            current_size += len(line) + 1  # +1 for newline

        return "\n".join(lines)

    @staticmethod
    def generate_jsonl(size_mb: int) -> str:
        """Generate JSONL (JSON Lines) data."""
        lines: List[str] = []
        target_size = size_mb * 1024 * 1024
        current_size = 0
        record_id = 0

        while current_size < target_size:
            record = {
                "id": record_id,
                "name": f"item_{record_id}",
                "value": random.randint(1, 1000),
                "description": "".join(random.choices(string.ascii_letters, k=20)),
                "timestamp": time.time(),
            }
            line = json.dumps(record)
            lines.append(line)
            current_size += len(line) + 1
            record_id += 1

        return "\n".join(lines)

    @staticmethod
    def generate_compressible(size_mb: int, pattern: str = "A") -> bytes:
        """Generate highly compressible data."""
        return pattern.encode() * (size_mb * 1024 * 1024)


class BenchmarkBase:
    """Base class for benchmark suites."""

    def __init__(self, data_size_mb: int = 1):
        self.data_size_mb = data_size_mb
        self.data_size_bytes = int(data_size_mb * 1024 * 1024)
        self.temp_mgr = TempFileManager()
        self.results: List[BenchmarkResults] = []
        self.data_gen = DataGenerator()

    def setup(self):
        """Set up benchmark environment."""
        self.temp_mgr.setup()

    def cleanup(self):
        """Clean up benchmark environment."""
        self.temp_mgr.cleanup()

    def add_result(self, name: str, category: str, duration: float, **metrics):
        """Add a benchmark result."""
        result = BenchmarkResults(
            name=name, category=category, duration=duration, metrics=metrics
        )
        self.results.append(result)
        return result

    def get_results(self) -> List[BenchmarkResults]:
        """Get all results."""
        return self.results

    def save_results(self, filepath: Path):
        """Save results to JSON file."""
        data = {
            "timestamp": time.time(),
            "data_size_mb": self.data_size_mb,
            "results": [r.to_dict() for r in self.results],
        }
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)


def benchmark_timer(func: Callable) -> Callable:
    """Decorator to time async functions."""

    async def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = await func(*args, **kwargs)
        duration = time.perf_counter() - start
        return result, duration

    return wrapper


def format_speedup(aiogzip_time: float, gzip_time: float) -> str:
    """Format speedup comparison."""
    if gzip_time == 0:
        return "N/A"
    speedup = gzip_time / aiogzip_time
    if speedup >= 1.0:
        return f"{speedup:.2f}x faster"
    else:
        return f"{1/speedup:.2f}x slower"


def format_size(bytes_size: int) -> str:
    """Format bytes as human-readable size."""
    for unit in ["B", "KB", "MB", "GB"]:
        if bytes_size < 1024:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024
    return f"{bytes_size:.1f} TB"
