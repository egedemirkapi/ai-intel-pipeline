from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class RawItem:
    url: str
    title: str
    published_at: datetime
    body: str | None = None
    author: str | None = None
    raw: dict[str, Any] | None = None


class Collector(ABC):
    name: str = "base"

    @abstractmethod
    async def fetch_since(self, since: datetime) -> list[RawItem]:
        """Fetch items published after `since`."""
        ...
