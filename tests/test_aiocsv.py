# pyrefly: ignore
# pyrefly: disable=all
import aiocsv
import pytest

from aiogzip import AsyncGzipFile


class TestAiocsvIntegration:
    """Test integration with aiocsv."""

    @pytest.mark.asyncio
    async def test_csv_read_write_roundtrip(self, temp_file):
        """Test CSV read/write roundtrip with aiocsv."""
        test_data = [
            {"name": "Alice", "age": "30", "city": "New York"},
            {"name": "Bob", "age": "25", "city": "London"},
            {"name": "Charlie", "age": "35", "city": "Paris"},
        ]

        async with AsyncGzipFile(temp_file, "wt") as f:
            writer = aiocsv.AsyncDictWriter(
                f, fieldnames=["name", "age", "city"]
            )  # pyrefly: ignore
            for row in test_data:
                await writer.writerow(row)

        async with AsyncGzipFile(temp_file, "rt") as f:
            reader = aiocsv.AsyncDictReader(
                f, fieldnames=["name", "age", "city"]
            )  # pyrefly: ignore
            rows = []
            async for row in reader:
                rows.append(row)
            assert rows == test_data

    @pytest.mark.asyncio
    async def test_csv_large_data(self, temp_file):
        """Test CSV with large data."""
        test_data = []
        for i in range(1000):
            test_data.append(
                {
                    "id": str(i),
                    "name": f"Person {i}",
                    "email": f"person{i}@example.com",
                    "age": str(20 + (i % 50)),
                }
            )

        async with AsyncGzipFile(temp_file, "wt") as f:
            writer = aiocsv.AsyncDictWriter(
                f,
                fieldnames=["id", "name", "email", "age"],  # pyrefly: ignore
            )
            for row in test_data:
                await writer.writerow(row)

        async with AsyncGzipFile(temp_file, "rt") as f:
            reader = aiocsv.AsyncDictReader(
                f,
                fieldnames=["id", "name", "email", "age"],  # pyrefly: ignore
            )
            rows = []
            async for row in reader:
                rows.append(row)
            assert len(rows) == 1000
            assert rows[0] == test_data[0]
            assert rows[-1] == test_data[-1]
