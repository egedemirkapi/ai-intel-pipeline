from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from ai_intel.collectors.base import Collector, RawItem
from ai_intel.collectors.runner import run_all_collectors
from ai_intel.db.session import get_engine, init_db


class FakeCollector(Collector):
    name = "fake"

    async def fetch_since(self, since: datetime) -> list[RawItem]:
        return [
            RawItem(
                url="https://fake.example.com/item-1",
                title="Fake AI item",
                published_at=datetime.now(timezone.utc),
            )
        ]


class FailingCollector(Collector):
    name = "failing"

    async def fetch_since(self, since: datetime) -> list[RawItem]:
        raise RuntimeError("simulated network failure")


@pytest.mark.asyncio
async def test_runner_returns_counts_and_isolates_failures(tmp_path: Path):
    engine = get_engine(tmp_path / "runner_test.db")
    init_db(engine)

    collectors = [FakeCollector(), FailingCollector()]
    since = datetime.now(timezone.utc) - timedelta(hours=1)

    result = await run_all_collectors(engine, collectors, since)

    assert result["fake"] == 1
    assert "failing" in result["failures"]


@pytest.mark.asyncio
async def test_runner_deduplicates_across_runs(tmp_path: Path):
    engine = get_engine(tmp_path / "dedup_test.db")
    init_db(engine)

    collectors = [FakeCollector()]
    since = datetime.now(timezone.utc) - timedelta(hours=1)

    result1 = await run_all_collectors(engine, collectors, since)
    result2 = await run_all_collectors(engine, collectors, since)

    assert result1["fake"] == 1
    assert result2["fake"] == 0  # deduped on second run
