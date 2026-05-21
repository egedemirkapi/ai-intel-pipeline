"""Tests for the Briefing engine (think/brief.py) and interests.

Google Calendar/Classroom calls are stubbed out (autouse `_no_google`
fixture) so the brief never hits the network during tests.
"""
from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import Session, SQLModel, create_engine

from ai_intel.db.models import Item
from ai_intel.memory.embed import FakeEmbedder
from ai_intel.memory.store import add_note, embed_pending
from ai_intel.think.brief import _compose_spoken, _top_news, build_brief
from ai_intel.think.interests import add_interest, delete_interest, list_interests


@pytest.fixture
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture
def embedder():
    return FakeEmbedder(dim=512, model="fake-512-test")


@pytest.fixture(autouse=True)
def _no_google(monkeypatch):
    """Pretend Google isn't connected so build_brief never makes real
    Calendar/Classroom API calls."""
    monkeypatch.setattr("ai_intel.google_auth.has_token", lambda: False)


def _make_item(
    title: str, *, source: str = "hn", ai_relevance: float = 0.5,
    collected_at: datetime | None = None,
) -> Item:
    url = f"https://example.test/{hashlib.md5(title.encode()).hexdigest()[:10]}"
    when = collected_at or datetime.now(timezone.utc)
    return Item(
        source=source,
        url=url,
        url_hash=hashlib.sha256(url.encode()).hexdigest()[:32],
        title=title,
        body="",
        published_at=when,
        collected_at=when,
        ai_relevance=ai_relevance,
    )


# ─── interests ──────────────────────────────────────────────────────


def test_add_and_list_interest(engine, embedder):
    add_interest(engine, "AI agents", embedder=embedder)
    add_interest(engine, "robotics", embedder=embedder)
    assert {i["text"] for i in list_interests(engine)} == {"AI agents", "robotics"}


def test_delete_interest(engine, embedder):
    iid = add_interest(engine, "dev tools", embedder=embedder)
    assert delete_interest(engine, iid) is True
    assert list_interests(engine) == []
    assert delete_interest(engine, iid) is False  # already gone


def test_delete_interest_ignores_plain_notes(engine, embedder):
    """delete_interest must not delete a normal user note."""
    nid = add_note(engine, "a normal note", embedder=embedder)
    assert delete_interest(engine, nid) is False


# ─── _top_news ──────────────────────────────────────────────────────


def test_top_news_ranks_by_recency(engine):
    """The brief leads with the FRESHEST news (newest collected first) so
    the collector's work is visible — not the highest-relevance item,
    which stayed frozen on top for days under the old ranking."""
    base = datetime.now(timezone.utc)
    with Session(engine) as s:
        s.add(_make_item("oldest", ai_relevance=0.95,
                         collected_at=base - timedelta(hours=3)))
        s.add(_make_item("newest", ai_relevance=0.20,
                         collected_at=base - timedelta(minutes=5)))
        s.add(_make_item("middle", ai_relevance=0.60,
                         collected_at=base - timedelta(hours=1)))
        s.commit()
    news = _top_news(engine, hours=48, limit=5)
    assert [n["title"] for n in news] == ["newest", "middle", "oldest"]


def test_top_news_excludes_corpus_sources(engine):
    with Session(engine) as s:
        s.add(_make_item("real news", source="hn", ai_relevance=0.5))
        s.add(_make_item("pg essay", source="founder_brain", ai_relevance=0.99))
        s.commit()
    assert [n["title"] for n in _top_news(engine, hours=48, limit=5)] == ["real news"]


# ─── build_brief ────────────────────────────────────────────────────


def test_build_brief_empty_db(engine):
    brief = asyncio.run(build_brief(engine))
    assert brief["news"] == []
    assert brief["suggestions"] == []
    assert brief["fresh"] == {"last_hour": 0, "today": 0}
    assert "not connected" in brief["calendar"]["summary"]
    assert isinstance(brief["spoken"], str) and brief["spoken"]


def test_build_brief_suggestions_fallback_without_interests(engine):
    """With no interests set, the 'For you' section still fills — from
    recent high-relevance intel — so it is never blank."""
    with Session(engine) as s:
        s.add(_make_item("A notable AI launch", ai_relevance=0.9))
        s.add(_make_item("Another AI story", ai_relevance=0.7))
        s.commit()
    brief = asyncio.run(build_brief(engine))
    assert len(brief["suggestions"]) >= 1


def test_build_brief_includes_news(engine):
    with Session(engine) as s:
        s.add(_make_item("OpenAI ships something big", ai_relevance=0.9))
        s.commit()
    brief = asyncio.run(build_brief(engine))
    assert len(brief["news"]) == 1
    assert "OpenAI" in brief["spoken"]


def test_build_brief_suggestions_from_interests(engine, embedder):
    with Session(engine) as s:
        s.add(_make_item("OpenAI launches a new agent framework", ai_relevance=0.8))
        s.add(_make_item("Weather forecast for Paris is rainy", ai_relevance=0.8))
        s.commit()
    embed_pending(engine, embedder=embedder)
    add_interest(engine, "OpenAI agent frameworks", embedder=embedder)

    brief = asyncio.run(build_brief(engine, embedder=embedder))
    assert len(brief["suggestions"]) >= 1
    assert any("OpenAI" in s["title"] for s in brief["suggestions"])


# ─── _compose_spoken ────────────────────────────────────────────────


def test_compose_spoken_quiet_day():
    spoken = _compose_spoken(
        [], {"summary": "", "events": []}, {"summary": "", "assignments": []},
        [], {},
    )
    assert "quiet" in spoken.lower()


def test_compose_spoken_mentions_top_story():
    news = [{"title": "Big AI news today"}]
    spoken = _compose_spoken(
        news, {"summary": "", "events": []}, {"summary": "", "assignments": []},
        [], {},
    )
    assert "Big AI news today" in spoken


def test_compose_spoken_mentions_collector_activity():
    """The brief tells the user the collector is alive — the numbers move
    every cycle, which is how the 24/7 collector becomes visible."""
    spoken = _compose_spoken(
        [], {"summary": "", "events": []}, {"summary": "", "assignments": []},
        [], {"last_hour": 12, "today": 80},
    )
    assert "12" in spoken and "collector" in spoken.lower()


# ─── news.open action ───────────────────────────────────────────────


def test_action_news_open_opens_freshest_articles(engine, monkeypatch):
    """news.open opens the freshest tech-news article URLs (newest first),
    so 'open the top news' opens the actual pages — not just a list."""
    import ai_intel.workflows.actions.news as news_mod

    captured: dict = {}

    async def fake_open(_engine, *, urls=None):
        captured["urls"] = list(urls or [])
        return {"opened": len(urls or [])}

    monkeypatch.setattr(news_mod, "action_tabs_open_set", fake_open)
    base = datetime.now(timezone.utc)
    with Session(engine) as s:
        s.add(_make_item("stale story", ai_relevance=0.95,
                         collected_at=base - timedelta(hours=6)))
        s.add(_make_item("breaking story", ai_relevance=0.30,
                         collected_at=base - timedelta(minutes=2)))
        s.commit()
    result = asyncio.run(news_mod.action_news_open(engine, count=2))
    assert result["opened"] == 2
    assert result["articles"][0]["title"] == "breaking story"  # freshest first
    assert len(captured["urls"]) == 2


def test_action_news_open_handles_empty_vault(engine, monkeypatch):
    """With nothing collected, news.open reports it cleanly — no crash."""
    import ai_intel.workflows.actions.news as news_mod

    async def fake_open(_engine, *, urls=None):  # pragma: no cover - not reached
        return {"opened": 0}

    monkeypatch.setattr(news_mod, "action_tabs_open_set", fake_open)
    result = asyncio.run(news_mod.action_news_open(engine))
    assert result["opened"] == 0
    assert result["articles"] == []
