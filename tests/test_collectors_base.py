from datetime import datetime, timezone

from ai_intel.collectors.base import Collector, RawItem


class DummyCollector(Collector):
    name = "dummy"

    async def fetch_since(self, since: datetime) -> list[RawItem]:
        return [
            RawItem(
                url="https://example.com/x",
                title="x",
                published_at=datetime.now(timezone.utc),
                body=None,
                author=None,
                raw={"source": "dummy"},
            )
        ]


async def test_dummy_collector():
    c = DummyCollector()
    items = await c.fetch_since(datetime.now(timezone.utc))
    assert len(items) == 1
    assert items[0].url == "https://example.com/x"
