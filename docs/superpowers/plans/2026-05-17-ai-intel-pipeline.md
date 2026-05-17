# AI Intel Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python service that polls AI ecosystem sources every 5 min, enriches with Claude Haiku, ranks top 50 with Claude Opus every 2 hours, generates a PDF digest, and emails it to `egedemirkapi@gmail.com`.

**Architecture:** Single-process Python service orchestrated by APScheduler. Collectors (no LLM) → SQLite → Haiku enrichment → Opus master analyst (every 2h) → WeasyPrint PDF → Resend email. Deploys to Render.com, runs locally first.

**Tech Stack:** Python 3.11+, anthropic SDK (MAX OAuth via `ANTHROPIC_API_KEY` env), sqlmodel + SQLite, feedparser + httpx, APScheduler, Jinja2 + WeasyPrint, resend.

**Spec reference:** `docs/superpowers/specs/2026-05-17-ai-intel-pipeline-design.md`

---

## Phase 0: Pre-flight

### Task 0.1: Verify environment

**Files:** none

- [ ] **Step 1:** Verify Python 3.11+ is installed.

```bash
python --version
```
Expected: `Python 3.11.x` or higher. If lower, install Python 3.11+ before continuing.

- [ ] **Step 2:** Verify the Claude OAuth token is set.

```bash
echo $ANTHROPIC_API_KEY  # macOS/Linux
echo $env:ANTHROPIC_API_KEY  # PowerShell
```
Expected: a non-empty string starting with `sk-ant-oat-` (the OAuth setup-token format). If empty, run `claude setup-token` and follow the prompts.

- [ ] **Step 3:** Verify git working directory is clean.

```bash
cd C:/Users/egede/ai-intel-pipeline
git status
```
Expected: "nothing to commit, working tree clean" (the spec commits should be the only commits so far).

- [ ] **Step 4:** Get a Resend API key.

Sign up at resend.com (free tier: 100 emails/day, plenty). Create an API key. Save it — we'll add it to `.env` in Task 1.2.

---

## Phase 1: Project Skeleton

### Task 1.1: Create pyproject.toml with dependencies

**Files:**
- Create: `pyproject.toml`

- [ ] **Step 1:** Write `pyproject.toml`:

```toml
[project]
name = "ai-intel-pipeline"
version = "0.1.0"
description = "Multi-agent AI ecosystem monitor — 2h PDF digest"
requires-python = ">=3.11"
dependencies = [
    "anthropic>=0.40.0",
    "apscheduler>=3.10.0",
    "beautifulsoup4>=4.12.0",
    "fastapi>=0.110.0",
    "feedparser>=6.0.10",
    "httpx>=0.27.0",
    "jinja2>=3.1.0",
    "pydantic>=2.6.0",
    "python-dotenv>=1.0.0",
    "pyyaml>=6.0",
    "resend>=2.0.0",
    "sqlmodel>=0.0.16",
    "uvicorn>=0.27.0",
    "weasyprint>=61.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "pytest-httpx>=0.30.0",
    "ruff>=0.3.0",
]

[project.scripts]
ai-intel = "ai_intel.__main__:main"

[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

- [ ] **Step 2:** Create a virtual env and install.

```bash
cd C:/Users/egede/ai-intel-pipeline
python -m venv .venv
source .venv/Scripts/activate  # Git Bash on Windows
# OR: .venv\Scripts\activate  (cmd / PowerShell)
pip install -e ".[dev]"
```
Expected: installs cleanly. If WeasyPrint fails on Windows, see Phase 1 troubleshooting below.

**WeasyPrint Windows troubleshooting:** WeasyPrint needs GTK runtime libs. On Windows, install via: download GTK from `https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer/releases`, install, restart shell. If you can't get WeasyPrint working in 15 minutes, swap to `playwright` for PDF (HTML → PDF via headless Chromium) and document the swap.

- [ ] **Step 3:** Add `.venv/` to .gitignore if not already (it already is from spec commit).

- [ ] **Step 4:** Commit.

```bash
git add pyproject.toml
git commit -m "chore: add pyproject.toml with deps"
```

### Task 1.2: Create environment template

**Files:**
- Create: `.env.example`

- [ ] **Step 1:** Write `.env.example`:

```bash
# Anthropic OAuth token from `claude setup-token`
ANTHROPIC_API_KEY=sk-ant-oat-...

# Resend API key from resend.com dashboard
RESEND_API_KEY=re_...

# Product Hunt API token (optional — if unset, PH collector is skipped)
# Get from: https://api.producthunt.com/v2/oauth/applications
PRODUCT_HUNT_TOKEN=

# Override config defaults (optional)
EMAIL_TO=egedemirkapi@gmail.com
LOG_LEVEL=INFO
```

- [ ] **Step 2:** Copy to a real local `.env` (gitignored) and fill in real values.

```bash
cp .env.example .env
# Edit .env and paste real values
```

- [ ] **Step 3:** Commit.

```bash
git add .env.example
git commit -m "chore: add .env template"
```

### Task 1.3: Create directory structure

**Files:**
- Create: full directory tree per spec

- [ ] **Step 1:** Create all directories and `__init__.py` files:

```bash
mkdir -p src/ai_intel/{collectors,enrichment,analyst,pdf,mailer,db}
mkdir -p src/ai_intel/pdf/templates
mkdir -p src/ai_intel/db/migrations
mkdir -p config prompts data output tests
touch src/ai_intel/__init__.py
touch src/ai_intel/{collectors,enrichment,analyst,pdf,mailer,db}/__init__.py
touch data/.gitkeep output/.gitkeep
```

- [ ] **Step 2:** Verify structure.

```bash
find src config prompts -type f -o -type d | sort
```

- [ ] **Step 3:** Commit.

```bash
git add src/ config/ prompts/ data/ output/ tests/
git commit -m "chore: create directory skeleton"
```

### Task 1.4: Create config.yaml and watchlist.txt

**Files:**
- Create: `config/config.yaml`
- Create: `config/watchlist.txt`

- [ ] **Step 1:** Write `config/config.yaml` (copy verbatim from spec Configuration section).

- [ ] **Step 2:** Write `config/watchlist.txt`:

```
# One RSS URL or domain per line. Lines starting with # are ignored.
# Add companies, blogs, newsletters Ege specifically wants tracked.
mindra.ai
caretta.ai
hockeystack.com
```

- [ ] **Step 3:** Commit.

```bash
git add config/
git commit -m "chore: add default config and watchlist"
```

### Task 1.5: Set up logging

**Files:**
- Create: `src/ai_intel/logging_config.py`

- [ ] **Step 1:** Write `src/ai_intel/logging_config.py`:

```python
import logging
import os
import sys


def setup_logging() -> None:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
```

- [ ] **Step 2:** Commit.

```bash
git add src/ai_intel/logging_config.py
git commit -m "feat: structured logging setup"
```

---

## Phase 2: Database

### Task 2.1: Define data models

**Files:**
- Create: `src/ai_intel/db/models.py`
- Create: `tests/test_db_models.py`

- [ ] **Step 1: Write the failing test.**

```python
# tests/test_db_models.py
from datetime import datetime, timezone
from sqlmodel import Session, SQLModel, create_engine

from ai_intel.db.models import Item, Digest


def test_item_round_trip():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        item = Item(
            source="hn",
            url="https://example.com/1",
            url_hash="abc123",
            title="Test item",
            published_at=datetime.now(timezone.utc),
            collected_at=datetime.now(timezone.utc),
        )
        session.add(item)
        session.commit()
        session.refresh(item)
        assert item.id is not None


def test_digest_round_trip():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        digest = Digest(
            window_start=datetime.now(timezone.utc),
            window_end=datetime.now(timezone.utc),
            items_considered=100,
            items_selected=50,
        )
        session.add(digest)
        session.commit()
        session.refresh(digest)
        assert digest.id is not None
```

- [ ] **Step 2:** Run test, expect FAIL.

```bash
pytest tests/test_db_models.py -v
```
Expected: ImportError, models don't exist yet.

- [ ] **Step 3:** Write `src/ai_intel/db/models.py`:

```python
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class Item(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    source: str = Field(index=True)
    url: str = Field(unique=True)
    url_hash: str = Field(unique=True, index=True)
    title: str
    body: Optional[str] = None
    author: Optional[str] = None
    published_at: datetime = Field(index=True)
    collected_at: datetime
    classification: Optional[str] = None
    entities_json: Optional[str] = None  # JSON-encoded dict
    pre_score: Optional[int] = None
    ai_relevance: Optional[float] = None
    skip_reason: Optional[str] = None
    sent_in_digest_at: Optional[datetime] = Field(default=None, index=True)
    raw_json: Optional[str] = None


class Digest(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    window_start: datetime
    window_end: datetime
    items_considered: int
    items_selected: int
    summary: Optional[str] = None
    pdf_path: Optional[str] = None
    sent_at: Optional[datetime] = None
    sent_to: Optional[str] = None
```

- [ ] **Step 4:** Run test, expect PASS.

```bash
pytest tests/test_db_models.py -v
```

- [ ] **Step 5:** Commit.

```bash
git add src/ai_intel/db/models.py tests/test_db_models.py
git commit -m "feat(db): Item and Digest models with round-trip tests"
```

### Task 2.2: Database initialization helper

**Files:**
- Create: `src/ai_intel/db/__init__.py` (update)
- Create: `src/ai_intel/db/session.py`
- Create: `tests/test_db_session.py`

- [ ] **Step 1: Write the failing test.**

```python
# tests/test_db_session.py
from pathlib import Path

from ai_intel.db.session import get_engine, init_db


def test_init_db_creates_file(tmp_path: Path):
    db_path = tmp_path / "test.db"
    engine = get_engine(db_path)
    init_db(engine)
    assert db_path.exists()
```

- [ ] **Step 2:** Run test, expect FAIL (module not found).

- [ ] **Step 3:** Write `src/ai_intel/db/session.py`:

```python
from pathlib import Path

from sqlmodel import SQLModel, create_engine


def get_engine(db_path: Path):
    return create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )


def init_db(engine) -> None:
    # Import models so SQLModel sees them
    from ai_intel.db import models  # noqa: F401
    SQLModel.metadata.create_all(engine)
```

- [ ] **Step 4:** Run test, expect PASS.

- [ ] **Step 5:** Commit.

```bash
git add src/ai_intel/db/session.py tests/test_db_session.py
git commit -m "feat(db): engine + init_db helpers"
```

---

## Phase 3: Collectors

### Task 3.1: Base collector interface

**Files:**
- Create: `src/ai_intel/collectors/base.py`
- Create: `tests/test_collectors_base.py`

- [ ] **Step 1: Write the failing test.**

```python
# tests/test_collectors_base.py
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
```

- [ ] **Step 2:** Run test, expect FAIL.

- [ ] **Step 3:** Write `src/ai_intel/collectors/base.py`:

```python
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
```

- [ ] **Step 4:** Run test, expect PASS.

- [ ] **Step 5:** Commit.

### Task 3.2: Persist helper — store collected items

**Files:**
- Create: `src/ai_intel/collectors/persist.py`
- Create: `tests/test_collectors_persist.py`

- [ ] **Step 1: Write the failing test.**

```python
# tests/test_collectors_persist.py
import asyncio
from datetime import datetime, timezone
from pathlib import Path

from sqlmodel import Session, select

from ai_intel.collectors.base import RawItem
from ai_intel.collectors.persist import persist_items
from ai_intel.db.models import Item
from ai_intel.db.session import get_engine, init_db


async def test_persist_dedups_by_url(tmp_path: Path):
    engine = get_engine(tmp_path / "test.db")
    init_db(engine)
    items = [
        RawItem(
            url="https://example.com/a",
            title="A",
            published_at=datetime.now(timezone.utc),
        ),
        RawItem(
            url="https://example.com/a",  # duplicate
            title="A again",
            published_at=datetime.now(timezone.utc),
        ),
    ]
    inserted = await persist_items(engine, source="test", items=items)
    assert inserted == 1
    with Session(engine) as s:
        all_items = s.exec(select(Item)).all()
        assert len(all_items) == 1
```

- [ ] **Step 2:** Run test, expect FAIL.

- [ ] **Step 3:** Write `src/ai_intel/collectors/persist.py`:

```python
import hashlib
import json
from datetime import datetime, timezone

from sqlmodel import Session, select

from ai_intel.collectors.base import RawItem
from ai_intel.db.models import Item


def url_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


async def persist_items(engine, source: str, items: list[RawItem]) -> int:
    """Insert non-duplicate items. Returns count inserted."""
    inserted = 0
    now = datetime.now(timezone.utc)
    with Session(engine) as session:
        for raw in items:
            h = url_hash(raw.url)
            existing = session.exec(select(Item).where(Item.url_hash == h)).first()
            if existing:
                continue
            item = Item(
                source=source,
                url=raw.url,
                url_hash=h,
                title=raw.title,
                body=raw.body,
                author=raw.author,
                published_at=raw.published_at,
                collected_at=now,
                raw_json=json.dumps(raw.raw) if raw.raw else None,
            )
            session.add(item)
            inserted += 1
        session.commit()
    return inserted
```

- [ ] **Step 4:** Run test, expect PASS.

- [ ] **Step 5:** Commit.

### Task 3.3: Hacker News collector

**Files:**
- Create: `src/ai_intel/collectors/hn.py`
- Create: `tests/test_collectors_hn.py`

- [ ] **Step 1: Write the failing test using pytest-httpx mock.**

```python
# tests/test_collectors_hn.py
from datetime import datetime, timezone, timedelta

import pytest
from pytest_httpx import HTTPXMock

from ai_intel.collectors.hn import HackerNewsCollector


@pytest.mark.asyncio
async def test_hn_filters_ai_titles(httpx_mock: HTTPXMock):
    # Top stories endpoint
    httpx_mock.add_response(
        url="https://hacker-news.firebaseio.com/v0/topstories.json",
        json=[1, 2, 3],
    )
    # Individual story endpoints
    now_ts = int(datetime.now(timezone.utc).timestamp())
    httpx_mock.add_response(
        url="https://hacker-news.firebaseio.com/v0/item/1.json",
        json={"id": 1, "title": "Anthropic launches Claude 5", "url": "https://x.com/1", "time": now_ts, "by": "alice"},
    )
    httpx_mock.add_response(
        url="https://hacker-news.firebaseio.com/v0/item/2.json",
        json={"id": 2, "title": "Best sourdough recipe", "url": "https://x.com/2", "time": now_ts, "by": "bob"},
    )
    httpx_mock.add_response(
        url="https://hacker-news.firebaseio.com/v0/item/3.json",
        json={"id": 3, "title": "New LLM benchmark released", "url": "https://x.com/3", "time": now_ts, "by": "carol"},
    )

    c = HackerNewsCollector()
    items = await c.fetch_since(datetime.now(timezone.utc) - timedelta(hours=2))
    # Sourdough item should be filtered out
    titles = [i.title for i in items]
    assert "Anthropic launches Claude 5" in titles
    assert "New LLM benchmark released" in titles
    assert "Best sourdough recipe" not in titles
```

- [ ] **Step 2:** Run test, expect FAIL.

- [ ] **Step 3:** Write `src/ai_intel/collectors/hn.py`:

```python
import asyncio
import logging
from datetime import datetime, timezone

import httpx

from ai_intel.collectors.base import Collector, RawItem

logger = logging.getLogger(__name__)

AI_KEYWORDS = {
    "ai", "ml", "llm", "agent", "anthropic", "openai", "claude", "gpt",
    "gemini", "transformer", "deepseek", "mistral", "meta-llama", "llama",
    "rag", "embedding", "fine-tun", "diffusion", "neural", "deep learning",
    "machine learning", "artificial intelligence", "copilot", "cursor",
    "perplexity", "groq", "cerebras", "huggingface", "langchain", "vector db",
}


def _is_ai_relevant(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in AI_KEYWORDS)


class HackerNewsCollector(Collector):
    name = "hn"
    BASE = "https://hacker-news.firebaseio.com/v0"

    async def fetch_since(self, since: datetime) -> list[RawItem]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            top_ids_resp = await client.get(f"{self.BASE}/topstories.json")
            top_ids = top_ids_resp.json()[:100]  # check top 100

            items: list[RawItem] = []
            for hid in top_ids:
                try:
                    r = await client.get(f"{self.BASE}/item/{hid}.json")
                    d = r.json() or {}
                    title = d.get("title", "")
                    url = d.get("url") or f"https://news.ycombinator.com/item?id={hid}"
                    ts = d.get("time", 0)
                    pub = datetime.fromtimestamp(ts, tz=timezone.utc)
                    if pub < since:
                        continue
                    if not _is_ai_relevant(title):
                        continue
                    items.append(
                        RawItem(
                            url=url,
                            title=title,
                            published_at=pub,
                            author=d.get("by"),
                            raw=d,
                        )
                    )
                except Exception as e:
                    logger.warning(f"HN item {hid} failed: {e}")
            return items
```

- [ ] **Step 4:** Run test, expect PASS.

- [ ] **Step 5:** Commit.

### Task 3.4: RSS collector (generic, multi-source)

**Files:**
- Create: `src/ai_intel/collectors/rss.py`
- Create: `tests/test_collectors_rss.py`
- Create: `tests/fixtures/sample_feed.xml`

- [ ] **Step 1: Write a sample RSS fixture.**

`tests/fixtures/sample_feed.xml`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
  <title>Sample</title>
  <item>
    <title>Anthropic announces new model</title>
    <link>https://example.com/1</link>
    <pubDate>Mon, 17 May 2026 10:00:00 +0000</pubDate>
    <description>An AI breakthrough.</description>
  </item>
  <item>
    <title>Generic tech news</title>
    <link>https://example.com/2</link>
    <pubDate>Mon, 17 May 2026 11:00:00 +0000</pubDate>
    <description>Not AI related.</description>
  </item>
</channel>
</rss>
```

- [ ] **Step 2: Write the failing test.**

```python
# tests/test_collectors_rss.py
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

from ai_intel.collectors.rss import RSSCollector


@pytest.mark.asyncio
async def test_rss_filters_by_recency(httpx_mock: HTTPXMock):
    feed_xml = Path("tests/fixtures/sample_feed.xml").read_text()
    httpx_mock.add_response(url="https://example.com/feed.xml", text=feed_xml)

    c = RSSCollector(
        source_id="example",
        feed_url="https://example.com/feed.xml",
        filter_ai=False,  # take all
    )
    items = await c.fetch_since(datetime(2026, 5, 17, 9, 0, tzinfo=timezone.utc))
    assert len(items) == 2

    items_recent = await c.fetch_since(datetime(2026, 5, 17, 10, 30, tzinfo=timezone.utc))
    assert len(items_recent) == 1


@pytest.mark.asyncio
async def test_rss_filters_ai_keywords(httpx_mock: HTTPXMock):
    feed_xml = Path("tests/fixtures/sample_feed.xml").read_text()
    httpx_mock.add_response(url="https://example.com/feed.xml", text=feed_xml)

    c = RSSCollector(
        source_id="example",
        feed_url="https://example.com/feed.xml",
        filter_ai=True,
    )
    items = await c.fetch_since(datetime(2026, 5, 17, 9, 0, tzinfo=timezone.utc))
    titles = [i.title for i in items]
    assert "Anthropic announces new model" in titles
    assert "Generic tech news" not in titles
```

- [ ] **Step 3:** Run tests, expect FAIL.

- [ ] **Step 4:** Write `src/ai_intel/collectors/rss.py`:

```python
import logging
from datetime import datetime, timezone

import feedparser
import httpx

from ai_intel.collectors.base import Collector, RawItem
from ai_intel.collectors.hn import _is_ai_relevant

logger = logging.getLogger(__name__)


class RSSCollector(Collector):
    def __init__(self, source_id: str, feed_url: str, filter_ai: bool = False):
        self.name = f"rss:{source_id}"
        self.feed_url = feed_url
        self.filter_ai = filter_ai

    async def fetch_since(self, since: datetime) -> list[RawItem]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(self.feed_url)
                resp.raise_for_status()
                feed = feedparser.parse(resp.text)
        except Exception as e:
            logger.warning(f"RSS fetch failed for {self.feed_url}: {e}")
            return []

        items: list[RawItem] = []
        for entry in feed.entries:
            try:
                published = entry.get("published_parsed") or entry.get("updated_parsed")
                if not published:
                    continue
                pub_dt = datetime(*published[:6], tzinfo=timezone.utc)
                if pub_dt < since:
                    continue
                title = entry.get("title", "")
                if self.filter_ai and not _is_ai_relevant(title):
                    continue
                items.append(
                    RawItem(
                        url=entry.get("link", ""),
                        title=title,
                        published_at=pub_dt,
                        body=entry.get("summary"),
                        author=entry.get("author"),
                        raw=dict(entry),
                    )
                )
            except Exception as e:
                logger.warning(f"RSS entry parse failed: {e}")
        return items
```

- [ ] **Step 5:** Run tests, expect PASS.

- [ ] **Step 6:** Commit.

### Task 3.5: Product Hunt collector

**Files:**
- Create: `src/ai_intel/collectors/product_hunt.py`
- Create: `tests/test_collectors_ph.py`

- [ ] **Step 1: Get a Product Hunt API token.**

Go to `https://api.producthunt.com/v2/oauth/applications`, create an app, get the developer token. Add to `.env` as `PRODUCT_HUNT_TOKEN=...`.

- [ ] **Step 2: Write the failing test with a mocked GraphQL response.**

```python
# tests/test_collectors_ph.py
from datetime import datetime, timezone, timedelta

import pytest
from pytest_httpx import HTTPXMock

from ai_intel.collectors.product_hunt import ProductHuntCollector


@pytest.mark.asyncio
async def test_ph_collects(httpx_mock: HTTPXMock, monkeypatch):
    monkeypatch.setenv("PRODUCT_HUNT_TOKEN", "test-token")
    now_iso = datetime.now(timezone.utc).isoformat()
    httpx_mock.add_response(
        url="https://api.producthunt.com/v2/api/graphql",
        json={
            "data": {
                "posts": {
                    "edges": [
                        {"node": {
                            "id": "1",
                            "name": "AI Notes",
                            "tagline": "AI-powered note taker",
                            "url": "https://www.producthunt.com/posts/ai-notes",
                            "createdAt": now_iso,
                            "user": {"name": "Alice"},
                        }}
                    ]
                }
            }
        },
    )
    c = ProductHuntCollector()
    items = await c.fetch_since(datetime.now(timezone.utc) - timedelta(hours=2))
    assert len(items) == 1
    assert items[0].title == "AI Notes — AI-powered note taker"
```

- [ ] **Step 3:** Run test, expect FAIL.

- [ ] **Step 4:** Write `src/ai_intel/collectors/product_hunt.py`:

```python
import logging
import os
from datetime import datetime, timezone

import httpx

from ai_intel.collectors.base import Collector, RawItem

logger = logging.getLogger(__name__)

GRAPHQL_QUERY = """
query RecentPosts($postedAfter: DateTime!) {
  posts(postedAfter: $postedAfter, order: NEWEST) {
    edges {
      node {
        id
        name
        tagline
        url
        createdAt
        user { name }
      }
    }
  }
}
"""


class ProductHuntCollector(Collector):
    name = "product_hunt"
    URL = "https://api.producthunt.com/v2/api/graphql"

    async def fetch_since(self, since: datetime) -> list[RawItem]:
        token = os.getenv("PRODUCT_HUNT_TOKEN")
        if not token:
            logger.warning("PRODUCT_HUNT_TOKEN not set; skipping PH collection")
            return []
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    self.URL,
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "query": GRAPHQL_QUERY,
                        "variables": {"postedAfter": since.isoformat()},
                    },
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            logger.warning(f"Product Hunt fetch failed: {e}")
            return []

        items: list[RawItem] = []
        for edge in data.get("data", {}).get("posts", {}).get("edges", []):
            node = edge.get("node", {})
            try:
                pub_dt = datetime.fromisoformat(node["createdAt"].replace("Z", "+00:00"))
                items.append(
                    RawItem(
                        url=node["url"],
                        title=f"{node['name']} — {node['tagline']}",
                        published_at=pub_dt,
                        author=node.get("user", {}).get("name"),
                        raw=node,
                    )
                )
            except Exception as e:
                logger.warning(f"PH entry parse failed: {e}")
        return items
```

- [ ] **Step 5:** Run test, expect PASS.

- [ ] **Step 6:** Commit.

### Task 3.6: Watchlist collector

**Files:**
- Create: `src/ai_intel/collectors/watchlist.py`
- Create: `tests/test_collectors_watchlist.py`

- [ ] **Step 1: Write the failing test.**

```python
# tests/test_collectors_watchlist.py
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

from ai_intel.collectors.watchlist import WatchlistCollector


@pytest.mark.asyncio
async def test_watchlist_resolves_rss_urls(tmp_path: Path, httpx_mock: HTTPXMock):
    watch = tmp_path / "watchlist.txt"
    watch.write_text("# comment\nhttps://example.com/feed.xml\n")

    feed_xml = Path("tests/fixtures/sample_feed.xml").read_text()
    httpx_mock.add_response(url="https://example.com/feed.xml", text=feed_xml)

    c = WatchlistCollector(watchlist_path=watch)
    items = await c.fetch_since(datetime(2026, 5, 17, 9, 0, tzinfo=timezone.utc))
    assert len(items) >= 1
```

- [ ] **Step 2:** Run, expect FAIL.

- [ ] **Step 3:** Write `src/ai_intel/collectors/watchlist.py`:

```python
import logging
from datetime import datetime
from pathlib import Path

from ai_intel.collectors.base import Collector, RawItem
from ai_intel.collectors.rss import RSSCollector

logger = logging.getLogger(__name__)


class WatchlistCollector(Collector):
    name = "watchlist"

    def __init__(self, watchlist_path: Path):
        self.path = watchlist_path

    async def fetch_since(self, since: datetime) -> list[RawItem]:
        if not self.path.exists():
            return []
        urls: list[str] = []
        for line in self.path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # If it doesn't look like an RSS URL, skip — for v1 we only support direct feed URLs
            if line.startswith("http"):
                urls.append(line)
            else:
                logger.info(f"Skipping non-URL watchlist entry: {line} (add an RSS URL instead)")
        all_items: list[RawItem] = []
        for u in urls:
            sub = RSSCollector(source_id=u, feed_url=u, filter_ai=False)
            all_items.extend(await sub.fetch_since(since))
        return all_items
```

- [ ] **Step 4:** Run, expect PASS.

- [ ] **Step 5:** Commit.

### Task 3.7: Wire collectors via config

**Files:**
- Create: `src/ai_intel/collectors/registry.py`
- Create: `tests/test_collectors_registry.py`

- [ ] **Step 1: Write the failing test.**

```python
# tests/test_collectors_registry.py
from ai_intel.collectors.registry import build_collectors_from_config


def test_registry_builds_enabled():
    cfg = {
        "sources": {
            "enabled": ["hn", "rss_techcrunch", "rss_anthropic", "watchlist"]
        }
    }
    collectors = build_collectors_from_config(cfg)
    names = [c.name for c in collectors]
    assert "hn" in names
    assert "rss:techcrunch" in names
    assert "rss:anthropic" in names
    assert "watchlist" in names
```

- [ ] **Step 2:** Run, expect FAIL.

- [ ] **Step 3:** Write `src/ai_intel/collectors/registry.py`:

```python
from pathlib import Path

from ai_intel.collectors.base import Collector
from ai_intel.collectors.hn import HackerNewsCollector
from ai_intel.collectors.product_hunt import ProductHuntCollector
from ai_intel.collectors.rss import RSSCollector
from ai_intel.collectors.watchlist import WatchlistCollector


RSS_FEEDS = {
    "rss_techcrunch": ("techcrunch", "https://techcrunch.com/feed/", True),
    "rss_verge": ("verge", "https://www.theverge.com/rss/index.xml", True),
    "rss_venturebeat": ("venturebeat", "https://venturebeat.com/feed/", True),
    "rss_a16z": ("a16z", "https://a16z.com/feed/", False),
    "rss_yc": ("yc", "https://www.ycombinator.com/blog/rss", False),
    "rss_anthropic": ("anthropic", "https://www.anthropic.com/news/rss.xml", False),
    "rss_openai": ("openai", "https://openai.com/blog/rss.xml", False),
    "rss_deepmind": ("deepmind", "https://deepmind.com/blog/feed/basic", False),
    "rss_stratechery": ("stratechery", "https://stratechery.com/feed/", True),
    "rss_pragmatic_engineer": ("pragmatic_engineer", "https://blog.pragmaticengineer.com/rss/", False),
    "rss_latent_space": ("latent_space", "https://www.latent.space/feed", False),
    "rss_crunchbase": ("crunchbase", "https://news.crunchbase.com/feed/", True),
}


def build_collectors_from_config(cfg: dict) -> list[Collector]:
    enabled = cfg.get("sources", {}).get("enabled", [])
    collectors: list[Collector] = []
    for src in enabled:
        if src == "hn":
            collectors.append(HackerNewsCollector())
        elif src == "product_hunt":
            collectors.append(ProductHuntCollector())
        elif src == "watchlist":
            collectors.append(WatchlistCollector(Path("config/watchlist.txt")))
        elif src in RSS_FEEDS:
            sid, url, filter_ai = RSS_FEEDS[src]
            collectors.append(RSSCollector(source_id=sid, feed_url=url, filter_ai=filter_ai))
    return collectors
```

- [ ] **Step 4:** Run, expect PASS.

- [ ] **Step 5:** Commit.

### Task 3.8: Run-all-collectors orchestrator

**Files:**
- Create: `src/ai_intel/collectors/runner.py`
- Create: `tests/test_collectors_runner.py`

- [ ] **Step 1: Write failing test using DummyCollector from Task 3.1.**

```python
# tests/test_collectors_runner.py
import asyncio
from datetime import datetime, timezone
from pathlib import Path

from sqlmodel import Session, select

from ai_intel.collectors.base import Collector, RawItem
from ai_intel.collectors.runner import run_all_collectors
from ai_intel.db.models import Item
from ai_intel.db.session import get_engine, init_db


class FakeCollector(Collector):
    name = "fake"

    async def fetch_since(self, since):
        return [
            RawItem(url="https://x.com/1", title="x", published_at=datetime.now(timezone.utc)),
        ]


class FailingCollector(Collector):
    name = "failing"

    async def fetch_since(self, since):
        raise RuntimeError("boom")


async def test_run_all_isolates_failures(tmp_path: Path):
    engine = get_engine(tmp_path / "test.db")
    init_db(engine)
    collectors = [FakeCollector(), FailingCollector()]
    result = await run_all_collectors(engine, collectors, since=datetime.now(timezone.utc))
    assert result["fake"] == 1
    assert "failing" in result["failures"]
```

- [ ] **Step 2:** Run, expect FAIL.

- [ ] **Step 3:** Write `src/ai_intel/collectors/runner.py`:

```python
import logging
from datetime import datetime

from ai_intel.collectors.base import Collector
from ai_intel.collectors.persist import persist_items

logger = logging.getLogger(__name__)


async def run_all_collectors(
    engine, collectors: list[Collector], since: datetime
) -> dict:
    results: dict = {"failures": []}
    for c in collectors:
        try:
            items = await c.fetch_since(since)
            inserted = await persist_items(engine, source=c.name, items=items)
            results[c.name] = inserted
            logger.info(f"{c.name}: collected={len(items)} inserted={inserted}")
        except Exception as e:
            logger.exception(f"{c.name} failed")
            results["failures"].append(c.name)
    return results
```

- [ ] **Step 4:** Run, expect PASS.

- [ ] **Step 5:** Commit.

---

## Phase 4: Enrichment (Haiku)

### Task 4.1: Anthropic client wrapper

**Files:**
- Create: `src/ai_intel/llm.py`
- Create: `tests/test_llm.py`

- [ ] **Step 1: Write failing test.**

```python
# tests/test_llm.py
import os

from ai_intel.llm import get_anthropic_client


def test_client_uses_env_token(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-oat-test")
    client = get_anthropic_client()
    assert client is not None
```

- [ ] **Step 2:** Run, expect FAIL.

- [ ] **Step 3:** Write `src/ai_intel/llm.py`:

```python
import os

from anthropic import Anthropic


def get_anthropic_client() -> Anthropic:
    """Returns a configured Anthropic client.

    Reads ANTHROPIC_API_KEY from env — works with both pay-per-token API keys
    and MAX-plan OAuth tokens (sk-ant-oat-...) set by `claude setup-token`.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set. Run `claude setup-token` to authenticate."
        )
    return Anthropic(api_key=api_key)
```

- [ ] **Step 4:** Run, expect PASS.

- [ ] **Step 5:** Commit.

### Task 4.2: Enrichment prompt template

**Files:**
- Create: `prompts/enrichment.txt`

- [ ] **Step 1:** Write `prompts/enrichment.txt` (verbatim from spec Section 3 enrichment prompt).

- [ ] **Step 2:** Commit.

### Task 4.3: Single-item enrichment with mocked LLM

**Files:**
- Create: `src/ai_intel/enrichment/enrich.py`
- Create: `tests/test_enrichment.py`

- [ ] **Step 1: Write failing test with mocked Anthropic response.**

```python
# tests/test_enrichment.py
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ai_intel.db.models import Item
from ai_intel.enrichment.enrich import enrich_batch


def make_item(title: str, item_id: int) -> Item:
    return Item(
        id=item_id,
        source="hn",
        url=f"https://example.com/{item_id}",
        url_hash=f"hash{item_id}",
        title=title,
        published_at=datetime.now(timezone.utc),
        collected_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_enrich_batch_parses_json():
    items = [make_item("Anthropic launches Claude 5", 1), make_item("Random hire", 2)]
    fake_response = MagicMock()
    fake_response.content = [MagicMock(text=json.dumps([
        {"item_id": 1, "classification": "launch", "ai_relevance": 0.95, "entities": {"companies": ["Anthropic"]}, "pre_score": 9, "skip_reason": None},
        {"item_id": 2, "classification": "hire", "ai_relevance": 0.1, "entities": {}, "pre_score": 2, "skip_reason": "not AI relevant"},
    ]))]
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_response

    enriched = await enrich_batch(items, client=fake_client, model="claude-haiku-4-5-20251001")
    assert enriched[1]["classification"] == "launch"
    assert enriched[1]["ai_relevance"] == 0.95
    assert enriched[2]["skip_reason"] == "not AI relevant"
```

- [ ] **Step 2:** Run, expect FAIL.

- [ ] **Step 3:** Write `src/ai_intel/enrichment/enrich.py`:

```python
import json
import logging
from pathlib import Path
from typing import Any

from ai_intel.db.models import Item

logger = logging.getLogger(__name__)

PROMPT_PATH = Path("prompts/enrichment.txt")


def _load_prompt() -> str:
    return PROMPT_PATH.read_text()


def _build_user_message(items: list[Item]) -> str:
    payload = [
        {"item_id": i.id, "title": i.title, "source": i.source, "body": (i.body or "")[:500]}
        for i in items
    ]
    return f"Items: {json.dumps(payload)}"


async def enrich_batch(
    items: list[Item], client, model: str
) -> dict[int, dict[str, Any]]:
    """Enrich a batch of items. Returns dict keyed by item_id."""
    if not items:
        return {}

    system_prompt = _load_prompt()
    user_msg = _build_user_message(items)

    resp = client.messages.create(
        model=model,
        max_tokens=2048,
        system=system_prompt,
        messages=[{"role": "user", "content": user_msg}],
    )

    raw_text = resp.content[0].text
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as e:
        logger.error(f"Enrichment JSON parse failed: {e}\nRaw: {raw_text[:500]}")
        return {}

    return {entry["item_id"]: entry for entry in parsed}
```

- [ ] **Step 4:** Run, expect PASS.

- [ ] **Step 5:** Commit.

### Task 4.4: Persist enrichment results

**Files:**
- Create: `src/ai_intel/enrichment/runner.py`
- Create: `tests/test_enrichment_runner.py`

- [ ] **Step 1: Write failing test.**

```python
# tests/test_enrichment_runner.py
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from sqlmodel import Session, select

from ai_intel.db.models import Item
from ai_intel.db.session import get_engine, init_db
from ai_intel.enrichment.runner import enrich_new_items


@pytest.mark.asyncio
async def test_enrich_runner_writes_back(tmp_path: Path, monkeypatch):
    engine = get_engine(tmp_path / "test.db")
    init_db(engine)
    # Insert an unenriched item
    with Session(engine) as s:
        s.add(Item(
            id=1,
            source="hn",
            url="https://example.com/1",
            url_hash="h1",
            title="OpenAI ships new GPT",
            published_at=datetime.now(timezone.utc),
            collected_at=datetime.now(timezone.utc),
        ))
        s.commit()

    # Mock the LLM call
    fake_response = MagicMock()
    fake_response.content = [MagicMock(text=json.dumps([
        {"item_id": 1, "classification": "launch", "ai_relevance": 0.95, "entities": {"companies": ["OpenAI"]}, "pre_score": 9, "skip_reason": None},
    ]))]
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_response

    # Patch get_anthropic_client to return our fake
    monkeypatch.setattr("ai_intel.enrichment.runner.get_anthropic_client", lambda: fake_client)
    # Need a prompts file
    monkeypatch.setattr("ai_intel.enrichment.enrich.PROMPT_PATH", tmp_path / "prompt.txt")
    (tmp_path / "prompt.txt").write_text("dummy prompt")

    await enrich_new_items(engine, model="claude-haiku-4-5-20251001", batch_size=10)

    with Session(engine) as s:
        item = s.get(Item, 1)
        assert item.classification == "launch"
        assert item.ai_relevance == 0.95
```

- [ ] **Step 2:** Run, expect FAIL.

- [ ] **Step 3:** Write `src/ai_intel/enrichment/runner.py`:

```python
import json
import logging

from sqlmodel import Session, select

from ai_intel.db.models import Item
from ai_intel.enrichment.enrich import enrich_batch
from ai_intel.llm import get_anthropic_client

logger = logging.getLogger(__name__)


async def enrich_new_items(engine, model: str, batch_size: int = 10) -> int:
    """Process all items lacking enrichment. Returns count enriched."""
    client = get_anthropic_client()
    total = 0

    with Session(engine) as session:
        unenriched = session.exec(
            select(Item).where(Item.classification.is_(None))
        ).all()

    for i in range(0, len(unenriched), batch_size):
        batch = unenriched[i : i + batch_size]
        try:
            results = await enrich_batch(batch, client=client, model=model)
        except Exception as e:
            logger.error(f"Enrich batch failed: {e}")
            continue

        with Session(engine) as session:
            for item in batch:
                r = results.get(item.id)
                if not r:
                    continue
                db_item = session.get(Item, item.id)
                db_item.classification = r.get("classification")
                db_item.ai_relevance = r.get("ai_relevance")
                db_item.entities_json = json.dumps(r.get("entities", {}))
                db_item.pre_score = r.get("pre_score")
                db_item.skip_reason = r.get("skip_reason")
                session.add(db_item)
                total += 1
            session.commit()
    return total
```

- [ ] **Step 4:** Run, expect PASS.

- [ ] **Step 5:** Commit.

---

## Phase 5: Master Analyst (Opus)

### Task 5.1: Analyst prompt

**Files:**
- Create: `prompts/analyst.txt`

- [ ] **Step 1:** Write `prompts/analyst.txt` (verbatim from spec Section 4 scoring rubric).

- [ ] **Step 2:** Commit.

### Task 5.2: Digest generation with validation

**Files:**
- Create: `src/ai_intel/analyst/digest.py`
- Create: `tests/test_analyst.py`

- [ ] **Step 1: Write failing test covering happy path + validation stripping.**

```python
# tests/test_analyst.py
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from sqlmodel import Session

from ai_intel.analyst.digest import generate_digest
from ai_intel.db.models import Item
from ai_intel.db.session import get_engine, init_db


def insert_item(session, item_id, title, pub_dt, ai_rel=0.9, pre_score=8):
    session.add(Item(
        id=item_id,
        source="hn",
        url=f"https://example.com/{item_id}",
        url_hash=f"h{item_id}",
        title=title,
        published_at=pub_dt,
        collected_at=datetime.now(timezone.utc),
        ai_relevance=ai_rel,
        pre_score=pre_score,
        classification="launch",
    ))


@pytest.mark.asyncio
async def test_digest_strips_hallucinated_ids(tmp_path: Path, monkeypatch):
    engine = get_engine(tmp_path / "test.db")
    init_db(engine)
    now = datetime.now(timezone.utc)
    with Session(engine) as s:
        insert_item(s, 1, "Real item", now - timedelta(minutes=30))
        insert_item(s, 2, "Real item 2", now - timedelta(minutes=60))
        s.commit()

    # Opus returns one valid + one hallucinated id
    fake_response = MagicMock()
    fake_response.content = [MagicMock(text=json.dumps({
        "summary": "Test summary",
        "top_50": [
            {"item_id": 1, "rank": 1, "why_it_matters": "Important"},
            {"item_id": 999, "rank": 2, "why_it_matters": "Fake"},
        ],
    }))]
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_response

    monkeypatch.setattr("ai_intel.analyst.digest.get_anthropic_client", lambda: fake_client)
    monkeypatch.setattr("ai_intel.analyst.digest.PROMPT_PATH", tmp_path / "p.txt")
    (tmp_path / "p.txt").write_text("prompt")

    digest = await generate_digest(
        engine, window_start=now - timedelta(hours=2), window_end=now, model="opus"
    )
    # Hallucinated id stripped; only real item 1 remains
    selected_ids = [s["item_id"] for s in digest["top_items"]]
    assert 1 in selected_ids
    assert 999 not in selected_ids


@pytest.mark.asyncio
async def test_digest_enforces_window(tmp_path: Path, monkeypatch):
    engine = get_engine(tmp_path / "test.db")
    init_db(engine)
    now = datetime.now(timezone.utc)
    with Session(engine) as s:
        insert_item(s, 1, "In window", now - timedelta(minutes=30))
        insert_item(s, 2, "OUT of window", now - timedelta(hours=5))
        s.commit()

    fake_response = MagicMock()
    fake_response.content = [MagicMock(text=json.dumps({
        "summary": "S",
        "top_50": [
            {"item_id": 1, "rank": 1, "why_it_matters": "a"},
            {"item_id": 2, "rank": 2, "why_it_matters": "b"},  # opus tries to sneak this in
        ],
    }))]
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_response

    monkeypatch.setattr("ai_intel.analyst.digest.get_anthropic_client", lambda: fake_client)
    monkeypatch.setattr("ai_intel.analyst.digest.PROMPT_PATH", tmp_path / "p.txt")
    (tmp_path / "p.txt").write_text("prompt")

    digest = await generate_digest(
        engine, window_start=now - timedelta(hours=2), window_end=now, model="opus"
    )
    selected_ids = [s["item_id"] for s in digest["top_items"]]
    assert 1 in selected_ids
    assert 2 not in selected_ids  # out-of-window item stripped
```

- [ ] **Step 2:** Run, expect FAIL.

- [ ] **Step 3:** Write `src/ai_intel/analyst/digest.py`:

```python
import json
import logging
from datetime import datetime
from pathlib import Path

from sqlmodel import Session, select

from ai_intel.db.models import Item
from ai_intel.llm import get_anthropic_client

logger = logging.getLogger(__name__)

PROMPT_PATH = Path("prompts/analyst.txt")


def _load_prompt() -> str:
    return PROMPT_PATH.read_text()


async def generate_digest(
    engine,
    window_start: datetime,
    window_end: datetime,
    model: str,
    top_n: int = 50,
    ai_relevance_threshold: float = 0.3,
) -> dict:
    # Step 1: Pull eligible items
    with Session(engine) as s:
        stmt = (
            select(Item)
            .where(Item.published_at >= window_start)
            .where(Item.published_at <= window_end)
            .where(Item.ai_relevance >= ai_relevance_threshold)
            .where(Item.sent_in_digest_at.is_(None))
        )
        items = s.exec(stmt).all()

    if not items:
        return {"summary": "No items in window.", "top_items": [], "items_considered": 0}

    if len(items) < 10:
        # Low-signal mini-digest: send all of them, no ranking needed
        return {
            "summary": f"Low signal window — {len(items)} items.",
            "top_items": [{"item_id": i.id, "rank": idx + 1, "why_it_matters": ""} for idx, i in enumerate(items)],
            "items_considered": len(items),
        }

    # Step 2: Build payload for Opus
    payload = [
        {
            "item_id": i.id,
            "title": i.title,
            "source": i.source,
            "url": i.url,
            "classification": i.classification,
            "pre_score": i.pre_score,
            "entities": json.loads(i.entities_json or "{}"),
            "body": (i.body or "")[:300],
        }
        for i in items
    ]

    client = get_anthropic_client()
    system_prompt = _load_prompt()

    resp = client.messages.create(
        model=model,
        max_tokens=8192,
        system=system_prompt,
        messages=[{"role": "user", "content": f"Items to rank:\n{json.dumps(payload)}"}],
    )

    raw_text = resp.content[0].text
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as e:
        logger.error(f"Opus returned non-JSON: {e}\nRaw: {raw_text[:1000]}")
        # Fallback: pre_score ranking
        sorted_items = sorted(items, key=lambda x: x.pre_score or 0, reverse=True)[:top_n]
        return {
            "summary": "Limited analysis — Opus output unparseable, fell back to pre-score ranking.",
            "top_items": [{"item_id": i.id, "rank": idx + 1, "why_it_matters": ""} for idx, i in enumerate(sorted_items)],
            "items_considered": len(items),
        }

    # Step 3: Validate — drop items not in DB or outside window
    valid_ids = {i.id: i for i in items}
    validated = []
    for entry in parsed.get("top_50", []):
        iid = entry.get("item_id")
        if iid not in valid_ids:
            logger.warning(f"Opus hallucinated item_id {iid} — stripped")
            continue
        item = valid_ids[iid]
        if not (window_start <= item.published_at <= window_end):
            logger.warning(f"Item {iid} outside window — stripped")
            continue
        validated.append(entry)

    return {
        "summary": parsed.get("summary", ""),
        "top_items": validated[:top_n],
        "items_considered": len(items),
    }
```

- [ ] **Step 4:** Run, expect PASS.

- [ ] **Step 5:** Commit.

---

## Phase 6: PDF Generator

### Task 6.1: HTML template

**Files:**
- Create: `src/ai_intel/pdf/templates/digest.html`

- [ ] **Step 1:** Write template:

```html
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>AI Intel · {{ generated_at }}</title>
<style>
  body { font-family: -apple-system, "Segoe UI", sans-serif; color: #1a1a1a; line-height: 1.5; }
  h1 { font-size: 28px; border-bottom: 2px solid #000; padding-bottom: 8px; }
  h2 { font-size: 18px; margin-top: 28px; color: #555; text-transform: uppercase; letter-spacing: 0.05em; }
  .summary { background: #f6f6f6; padding: 12px 16px; border-left: 4px solid #4a4a4a; margin: 16px 0; font-style: italic; }
  .item { margin: 14px 0; padding-bottom: 12px; border-bottom: 1px solid #eee; }
  .title { font-size: 14px; font-weight: 600; }
  .meta { font-size: 11px; color: #888; }
  .why { font-size: 12px; color: #333; margin-top: 4px; }
  a { color: #0066cc; text-decoration: none; }
</style>
</head>
<body>
<h1>AI Intel Digest</h1>
<div class="meta">Generated {{ generated_at }} · {{ items_considered }} items considered · {{ items_selected }} selected · window {{ window_start }} → {{ window_end }}</div>

<div class="summary">{{ summary }}</div>

{% for section_name, section_items in sections.items() %}
<h2>{{ section_name }} ({{ section_items|length }})</h2>
{% for entry in section_items %}
<div class="item">
  <div class="title"><a href="{{ entry.url }}">{{ entry.title }}</a></div>
  <div class="meta">{{ entry.source }} · {{ entry.published_at }}</div>
  {% if entry.why_it_matters %}<div class="why">{{ entry.why_it_matters }}</div>{% endif %}
</div>
{% endfor %}
{% endfor %}
</body>
</html>
```

- [ ] **Step 2:** Commit.

### Task 6.2: PDF render function

**Files:**
- Create: `src/ai_intel/pdf/render.py`
- Create: `tests/test_pdf.py`

- [ ] **Step 1: Write failing test.**

```python
# tests/test_pdf.py
from datetime import datetime, timezone
from pathlib import Path

from ai_intel.pdf.render import render_digest_pdf


def test_pdf_generates_file(tmp_path: Path):
    digest_data = {
        "summary": "Test summary",
        "items_considered": 100,
        "items_selected": 1,
        "window_start": datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc),
        "window_end": datetime(2026, 5, 17, 14, 0, tzinfo=timezone.utc),
        "sections": {
            "Launches": [{
                "title": "Test launch",
                "url": "https://example.com/1",
                "source": "hn",
                "published_at": "2026-05-17 13:00",
                "why_it_matters": "Because.",
            }],
        },
    }
    output = tmp_path / "test.pdf"
    render_digest_pdf(digest_data, output_path=output)
    assert output.exists()
    assert output.stat().st_size > 1000  # PDF should be more than trivial
```

- [ ] **Step 2:** Run, expect FAIL.

- [ ] **Step 3:** Write `src/ai_intel/pdf/render.py`:

```python
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML

TEMPLATE_DIR = Path(__file__).parent / "templates"


def render_digest_pdf(digest_data: dict, output_path: Path) -> None:
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
    template = env.get_template("digest.html")
    html_str = template.render(
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        **digest_data,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html_str).write_pdf(str(output_path))
```

- [ ] **Step 4:** Run, expect PASS. (If WeasyPrint fails on Windows, see Phase 1 troubleshooting.)

- [ ] **Step 5:** Commit.

### Task 6.3: Group digest items by section

**Files:**
- Create: `src/ai_intel/pdf/sections.py`
- Create: `tests/test_pdf_sections.py`

- [ ] **Step 1: Write failing test.**

```python
# tests/test_pdf_sections.py
from datetime import datetime, timezone
from pathlib import Path
from sqlmodel import Session
from ai_intel.db.models import Item
from ai_intel.db.session import get_engine, init_db
from ai_intel.pdf.sections import build_sections


def test_groups_by_classification(tmp_path: Path):
    engine = get_engine(tmp_path / "test.db")
    init_db(engine)
    now = datetime.now(timezone.utc)
    with Session(engine) as s:
        s.add(Item(id=1, source="hn", url="https://a.com", url_hash="h1", title="A", published_at=now, collected_at=now, classification="funding"))
        s.add(Item(id=2, source="hn", url="https://b.com", url_hash="h2", title="B", published_at=now, collected_at=now, classification="launch"))
        s.commit()

    top_items = [
        {"item_id": 1, "rank": 1, "why_it_matters": "1"},
        {"item_id": 2, "rank": 2, "why_it_matters": "2"},
    ]
    sections = build_sections(engine, top_items)
    assert "Funding" in sections
    assert "Launches" in sections
    assert len(sections["Funding"]) == 1
    assert len(sections["Launches"]) == 1
```

- [ ] **Step 2:** Run, expect FAIL.

- [ ] **Step 3:** Write `src/ai_intel/pdf/sections.py`:

```python
from sqlmodel import Session, select
from ai_intel.db.models import Item

SECTION_ORDER = ["Funding", "Launches", "Research", "Viral", "Hires", "Misc"]
CLASS_TO_SECTION = {
    "funding": "Funding",
    "launch": "Launches",
    "research": "Research",
    "viral": "Viral",
    "hire": "Hires",
    "misc": "Misc",
}


def build_sections(engine, top_items: list[dict]) -> dict:
    item_ids = [t["item_id"] for t in top_items]
    if not item_ids:
        return {}
    with Session(engine) as s:
        items_by_id = {
            i.id: i for i in s.exec(select(Item).where(Item.id.in_(item_ids))).all()
        }

    out: dict[str, list[dict]] = {name: [] for name in SECTION_ORDER}
    for t in top_items:
        item = items_by_id.get(t["item_id"])
        if not item:
            continue
        sec = CLASS_TO_SECTION.get(item.classification or "misc", "Misc")
        out[sec].append({
            "title": item.title,
            "url": item.url,
            "source": item.source,
            "published_at": item.published_at.strftime("%Y-%m-%d %H:%M"),
            "why_it_matters": t.get("why_it_matters", ""),
        })
    # Drop empty sections
    return {k: v for k, v in out.items() if v}
```

- [ ] **Step 4:** Run, expect PASS.

- [ ] **Step 5:** Commit.

---

## Phase 7: Email (Resend)

### Task 7.1: Email send function

**Files:**
- Create: `src/ai_intel/mailer/send.py`
- Create: `tests/test_mailer.py`

- [ ] **Step 1: Write failing test with mocked Resend.**

```python
# tests/test_mailer.py
from pathlib import Path
from unittest.mock import MagicMock, patch

from ai_intel.mailer.send import send_digest_email


def test_send_attaches_pdf(tmp_path: Path, monkeypatch):
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setenv("RESEND_API_KEY", "re_test")

    fake_resend = MagicMock()
    fake_resend.Emails.send.return_value = {"id": "msg_1"}
    monkeypatch.setattr("ai_intel.mailer.send.resend", fake_resend)

    msg_id = send_digest_email(
        to="egedemirkapi@gmail.com",
        subject="Test",
        body_html="<p>hi</p>",
        pdf_path=pdf,
    )
    assert msg_id == "msg_1"
    fake_resend.Emails.send.assert_called_once()
    args = fake_resend.Emails.send.call_args[0][0]
    assert args["to"] == "egedemirkapi@gmail.com"
    assert len(args["attachments"]) == 1
```

- [ ] **Step 2:** Run, expect FAIL.

- [ ] **Step 3:** Write `src/ai_intel/mailer/send.py`:

```python
import base64
import logging
import os
from pathlib import Path

import resend

logger = logging.getLogger(__name__)


def send_digest_email(
    to: str, subject: str, body_html: str, pdf_path: Path,
    sender: str = "onboarding@resend.dev",
) -> str:
    """Send the digest email with PDF attached. Returns message id."""
    api_key = os.getenv("RESEND_API_KEY")
    if not api_key:
        raise RuntimeError("RESEND_API_KEY not set")
    resend.api_key = api_key

    pdf_bytes = pdf_path.read_bytes()
    encoded = base64.b64encode(pdf_bytes).decode()

    resp = resend.Emails.send({
        "from": sender,
        "to": to,
        "subject": subject,
        "html": body_html,
        "attachments": [{
            "filename": pdf_path.name,
            "content": encoded,
        }],
    })
    msg_id = resp.get("id") if isinstance(resp, dict) else resp.id
    logger.info(f"Email sent: id={msg_id}")
    return msg_id
```

- [ ] **Step 4:** Run, expect PASS.

- [ ] **Step 5:** Commit.

---

## Phase 8: Orchestration

### Task 8.1: End-to-end digest pipeline

**Files:**
- Create: `src/ai_intel/pipeline.py`
- Create: `tests/test_pipeline.py`

- [ ] **Step 1: Write a smoke-test that runs the full pipeline against an in-memory DB with mocked LLM and mocked email.**

```python
# tests/test_pipeline.py
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from sqlmodel import Session

from ai_intel.db.models import Item
from ai_intel.db.session import get_engine, init_db
from ai_intel.pipeline import generate_and_send_digest


@pytest.mark.asyncio
async def test_pipeline_end_to_end(tmp_path: Path, monkeypatch):
    engine = get_engine(tmp_path / "test.db")
    init_db(engine)
    now = datetime.now(timezone.utc)

    # Insert 15 enriched, AI-relevant items
    with Session(engine) as s:
        for i in range(1, 16):
            s.add(Item(
                id=i, source="hn", url=f"https://x.com/{i}", url_hash=f"h{i}",
                title=f"Item {i}", published_at=now - timedelta(minutes=i*5),
                collected_at=now, ai_relevance=0.9, pre_score=5, classification="launch",
                entities_json="{}",
            ))
        s.commit()

    # Mock LLM
    fake_response = MagicMock()
    fake_response.content = [MagicMock(text=json.dumps({
        "summary": "All good",
        "top_50": [{"item_id": i, "rank": i, "why_it_matters": f"why {i}"} for i in range(1, 16)],
    }))]
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_response
    monkeypatch.setattr("ai_intel.analyst.digest.get_anthropic_client", lambda: fake_client)
    monkeypatch.setattr("ai_intel.analyst.digest.PROMPT_PATH", tmp_path / "p.txt")
    (tmp_path / "p.txt").write_text("prompt")

    # Mock email
    sent_log = []
    def fake_send(**kwargs):
        sent_log.append(kwargs)
        return "msg_id"
    monkeypatch.setattr("ai_intel.pipeline.send_digest_email", fake_send)

    output_dir = tmp_path / "output"
    result = await generate_and_send_digest(
        engine=engine, output_dir=output_dir,
        window_hours=2, model="opus", email_to="test@example.com",
    )
    assert result["sent"] is True
    assert len(sent_log) == 1
    assert sent_log[0]["to"] == "test@example.com"
```

- [ ] **Step 2:** Run, expect FAIL.

- [ ] **Step 3:** Write `src/ai_intel/pipeline.py`:

```python
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

from sqlmodel import Session

from ai_intel.analyst.digest import generate_digest
from ai_intel.db.models import Digest, Item
from ai_intel.mailer.send import send_digest_email
from ai_intel.pdf.render import render_digest_pdf
from ai_intel.pdf.sections import build_sections

logger = logging.getLogger(__name__)


async def generate_and_send_digest(
    engine, output_dir: Path, window_hours: int, model: str, email_to: str,
) -> dict:
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=window_hours)

    digest = await generate_digest(
        engine, window_start=window_start, window_end=now, model=model,
    )
    if not digest["top_items"]:
        logger.info("No items to digest this cycle.")
        return {"sent": False, "reason": "no_items"}

    sections = build_sections(engine, digest["top_items"])
    digest_data = {
        "summary": digest["summary"],
        "items_considered": digest["items_considered"],
        "items_selected": len(digest["top_items"]),
        "window_start": window_start.strftime("%Y-%m-%d %H:%M UTC"),
        "window_end": now.strftime("%Y-%m-%d %H:%M UTC"),
        "sections": sections,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = output_dir / f"ai-intel-{now.strftime('%Y-%m-%d-%H%M')}.pdf"
    render_digest_pdf(digest_data, output_path=pdf_path)

    subject = f"AI Intel · {now.strftime('%Y-%m-%d %H:%M')} · {len(digest['top_items'])} items"
    body_html = f"<p>{digest['summary']}</p><p>PDF attached.</p>"
    msg_id = send_digest_email(to=email_to, subject=subject, body_html=body_html, pdf_path=pdf_path)

    # Mark items as sent
    with Session(engine) as s:
        for entry in digest["top_items"]:
            item = s.get(Item, entry["item_id"])
            if item:
                item.sent_in_digest_at = now
                s.add(item)
        s.add(Digest(
            window_start=window_start, window_end=now,
            items_considered=digest["items_considered"],
            items_selected=len(digest["top_items"]),
            summary=digest["summary"], pdf_path=str(pdf_path),
            sent_at=now, sent_to=email_to,
        ))
        s.commit()

    return {"sent": True, "msg_id": msg_id, "pdf_path": str(pdf_path)}
```

- [ ] **Step 4:** Run, expect PASS.

- [ ] **Step 5:** Commit.

### Task 8.2: APScheduler wiring

**Files:**
- Create: `src/ai_intel/scheduler.py`

- [ ] **Step 1:** Write `src/ai_intel/scheduler.py`:

```python
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from ai_intel.collectors.registry import build_collectors_from_config
from ai_intel.collectors.runner import run_all_collectors
from ai_intel.db.session import get_engine, init_db
from ai_intel.enrichment.runner import enrich_new_items
from ai_intel.pipeline import generate_and_send_digest

logger = logging.getLogger(__name__)


def load_config() -> dict:
    return yaml.safe_load(Path("config/config.yaml").read_text())


def build_scheduler(engine, config: dict, first_run: bool = False) -> AsyncIOScheduler:
    sched = AsyncIOScheduler(timezone="UTC")
    collectors = build_collectors_from_config(config)
    enrich_model = config["llm"]["enrichment_model"]
    analyst_model = config["llm"]["analyst_model"]
    email_to = config["delivery"]["email_to"]
    window_hours = config["delivery"]["digest_window_hours"]
    output_dir = Path("output")

    async def collect_job():
        # Lookback window: 6h to catch slow-publishing feeds + backfill
        since = datetime.now(timezone.utc) - timedelta(hours=6)
        result = await run_all_collectors(engine, collectors, since=since)
        logger.info(f"Collect cycle: {result}")

    async def enrich_job():
        n = await enrich_new_items(engine, model=enrich_model)
        logger.info(f"Enriched {n} items")

    async def digest_job():
        # If first run, use 24h backfill window per spec resolution
        actual_window = 24 if first_run else window_hours
        result = await generate_and_send_digest(
            engine=engine, output_dir=output_dir,
            window_hours=actual_window, model=analyst_model, email_to=email_to,
        )
        logger.info(f"Digest sent: {result}")

    sched.add_job(collect_job, "interval", minutes=5, id="collect", misfire_grace_time=60)
    sched.add_job(enrich_job, "interval", minutes=5, id="enrich", misfire_grace_time=60, next_run_time=datetime.now(timezone.utc) + timedelta(minutes=2))
    sched.add_job(digest_job, "cron", hour="*/2", minute=0, id="digest", misfire_grace_time=300)
    return sched
```

- [ ] **Step 2:** Commit.

### Task 8.3: __main__ entry point

**Files:**
- Create: `src/ai_intel/__main__.py`

- [ ] **Step 1:** Write `src/ai_intel/__main__.py`:

```python
import asyncio
import logging
import signal
from pathlib import Path

from dotenv import load_dotenv

from ai_intel.db.session import get_engine, init_db
from ai_intel.logging_config import setup_logging
from ai_intel.scheduler import build_scheduler, load_config


async def run_first_digest_now(engine, config):
    """Backfill: run a digest immediately on startup using 24h window."""
    from ai_intel.pipeline import generate_and_send_digest
    from ai_intel.collectors.registry import build_collectors_from_config
    from ai_intel.collectors.runner import run_all_collectors
    from ai_intel.enrichment.runner import enrich_new_items
    from datetime import datetime, timezone, timedelta

    log = logging.getLogger(__name__)
    log.info("Running first-cycle backfill (24h window)…")
    collectors = build_collectors_from_config(config)
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    await run_all_collectors(engine, collectors, since=since)
    await enrich_new_items(engine, model=config["llm"]["enrichment_model"])
    await generate_and_send_digest(
        engine=engine, output_dir=Path("output"),
        window_hours=24, model=config["llm"]["analyst_model"],
        email_to=config["delivery"]["email_to"],
    )


async def amain():
    load_dotenv()
    setup_logging()
    log = logging.getLogger(__name__)

    config = load_config()
    db_path = Path("data/items.db")
    db_path.parent.mkdir(exist_ok=True)
    engine = get_engine(db_path)
    init_db(engine)

    # First-run backfill?
    is_first_run = not (Path("data") / ".started").exists()
    if is_first_run:
        await run_first_digest_now(engine, config)
        (Path("data") / ".started").touch()

    scheduler = build_scheduler(engine, config, first_run=False)
    scheduler.start()
    log.info("Scheduler started. Press Ctrl+C to stop.")

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass  # Windows
    await stop_event.wait()
    scheduler.shutdown(wait=False)


def main():
    asyncio.run(amain())


if __name__ == "__main__":
    main()
```

- [ ] **Step 2:** Commit.

---

## Phase 9: First Real Run

### Task 9.1: Local smoke run

- [ ] **Step 1:** Make sure `.env` has real `ANTHROPIC_API_KEY`, `RESEND_API_KEY`, optionally `PRODUCT_HUNT_TOKEN`.

- [ ] **Step 2:** Run all tests one more time.

```bash
pytest -v
```
Expected: all green.

- [ ] **Step 3:** Run the service locally.

```bash
python -m ai_intel
```
Expected: logs show "Running first-cycle backfill", collectors fetch items, enrichment runs, digest generates, PDF written, email sent.

- [ ] **Step 4:** Verify email arrived at `egedemirkapi@gmail.com` with PDF attached.

- [ ] **Step 5:** Open the PDF and sanity-check: at least 10 items, sources visible, no obvious garbage. Click a couple URLs to confirm they're real.

- [ ] **Step 6:** Stop with Ctrl+C, commit any tweaks.

```bash
git add -A
git commit -m "chore: first successful local run"
```

### Task 9.2: Validate 2-hour cycle works

- [ ] **Step 1:** Restart the service and let it run for 2+ hours.

```bash
python -m ai_intel
```

- [ ] **Step 2:** Confirm a second digest arrives at the next 2-hour boundary (e.g., if started at 14:30, expect digest at 16:00).

- [ ] **Step 3:** Confirm second digest contains only items from the past 2h (not all items again).

---

## Phase 10: Deploy to Render

### Task 10.1: Create render.yaml

**Files:**
- Create: `render.yaml`

- [ ] **Step 1:** Write `render.yaml`:

```yaml
services:
  - type: web
    name: ai-intel-pipeline
    runtime: python
    region: oregon
    plan: starter  # $7/mo — Free tier sleeps after inactivity
    buildCommand: pip install -e .
    startCommand: python -m ai_intel
    envVars:
      - key: ANTHROPIC_API_KEY
        sync: false  # set in dashboard
      - key: RESEND_API_KEY
        sync: false
      - key: PRODUCT_HUNT_TOKEN
        sync: false
      - key: LOG_LEVEL
        value: INFO
    disk:
      name: data
      mountPath: /opt/render/project/src/data
      sizeGB: 1
```

- [ ] **Step 2:** Commit.

```bash
git add render.yaml
git commit -m "chore: render.com deploy config"
```

### Task 10.2: Push to GitHub + connect Render

- [ ] **Step 1:** Create a GitHub repo (private recommended) and push.

```bash
# Create repo on github.com (Ege does this in browser), then:
git remote add origin git@github.com:egedemirkapi/ai-intel-pipeline.git
git push -u origin master
```

- [ ] **Step 2:** In Render dashboard, click "New > Blueprint", connect the GitHub repo. Render picks up `render.yaml`.

- [ ] **Step 3:** Set env vars in Render dashboard: `ANTHROPIC_API_KEY`, `RESEND_API_KEY`, `PRODUCT_HUNT_TOKEN`.

- [ ] **Step 4:** Trigger first deploy. Watch logs.

- [ ] **Step 5:** Verify first-run backfill happens and email arrives.

### Task 10.3: 24-hour soak test

- [ ] **Step 1:** Leave Render service running for 24h.

- [ ] **Step 2:** Verify 12 digests arrived (every 2h × 24h).

- [ ] **Step 3:** Check Render logs for errors. Fix any chronic failures.

- [ ] **Step 4:** Tag a v0.1.0 release.

```bash
git tag v0.1.0
git push --tags
```

---

## Phase 11: README

### Task 11.1: Write the README

**Files:**
- Create: `README.md`

- [ ] **Step 1:** Write README covering: what it does, setup, how to run locally, how to deploy, how to add a source to watchlist, how to change schedule. Keep it ≤ 200 lines.

- [ ] **Step 2:** Commit.

---

## Notes for the executor

- **Skip Twitter/LinkedIn** — explicitly out of scope, do not add even if tempted.
- **Anti-hallucination is a hard requirement** — never let the LLM invent items. Validation gate in Task 5.2 is the enforcement. Don't soften it.
- **OAuth token works with regular SDK** — `Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))` accepts both pay-per-token keys and `sk-ant-oat-…` tokens.
- **Email is ALWAYS `egedemirkapi@gmail.com`** — never use other addresses, even if you see them in user config files elsewhere.
- **WeasyPrint on Windows** — if it won't install, swap to `playwright` for PDF and document the swap. Don't spend more than 30 min fighting GTK.
- **Commit after every passing test** — small commits are easy to revert and the user wants visible progress.
