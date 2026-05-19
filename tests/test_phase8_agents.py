"""Tests for the Phase 8 startup-ideation agents.

Every test mocks ``call_llm`` so no real Anthropic calls happen. Items
are seeded directly into an in-memory SQLite via SQLModel — same fixture
pattern as test_agents.py / test_memory.py.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from ai_intel.agents import evaluator, proposer, saturator
from ai_intel.agents.runtime import LLMResponse
from ai_intel.db.models import (
    Embedding,
    IdeaCandidate,
    Item,
    SaturationAssessment,
)
from ai_intel.memory.embed import FakeEmbedder
from ai_intel.memory.store import embed_pending


@pytest.fixture
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture
def embedder():
    return FakeEmbedder(dim=128, model="fake-128-test")


def _seed_item(engine, **kw) -> Item:
    """Insert one Item and return it."""
    defaults = {
        "source": "hn",
        "url": f"https://example.test/{kw.get('title','x')[:12]}",
        "url_hash": hashlib.sha256((kw.get("url") or kw.get("title", "x")).encode()).hexdigest()[:32],
        "title": "default title",
        "body": "default body " * 30,
        "published_at": datetime.now(timezone.utc),
        "collected_at": datetime.now(timezone.utc),
        "classification": "news",
        "ai_relevance": 0.8,
    }
    defaults.update(kw)
    item = Item(**defaults)
    with Session(engine) as s:
        s.add(item)
        s.commit()
        s.refresh(item)
    return item


def _mock_llm(text: str, prompt_tokens: int = 100, completion_tokens: int = 50):
    """Build a fake LLMResponse for patching call_llm."""
    return LLMResponse(
        text=text,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        auth_mode="api_key",
        model="claude-haiku-4-5",
        cost_usd=0.001,
    )


# ---------------------------------------------------------------------------
# saturator
# ---------------------------------------------------------------------------


def test_saturator_writes_assessment(engine, embedder, monkeypatch):
    """saturator must persist a SaturationAssessment with parsed fields."""
    # Seed some intel items so recall has hits (uses a fake embedder).
    _seed_item(engine, title="OpenAI funds X agents", source="hn")
    _seed_item(engine, title="Anthropic agents launch", source="hn")
    embed_pending(engine, embedder=embedder)

    monkeypatch.setattr(
        "ai_intel.memory.embed.get_embedder", lambda: embedder
    )

    llm_response = _mock_llm(json.dumps({
        "score": 0.65,
        "competitor_count": 7,
        "competitor_names": ["OpenAI", "Anthropic", "Cohere"],
        "reasoning": "Major incumbents + several Series A startups.",
        "verdict": "crowded",
    }))

    with patch("ai_intel.agents.saturator.call_llm", return_value=llm_response):
        result = asyncio.run(saturator(engine, topic="AI agents", use_cache=False))

    assert "score=0.65" in (result["summary"] or "")
    assert result["auth_mode"] == "api_key"

    with Session(engine) as s:
        rows = list(s.exec(select(SaturationAssessment)))
    assert len(rows) == 1
    row = rows[0]
    assert row.topic == "AI agents"
    assert row.score == pytest.approx(0.65)
    assert row.competitor_count == 7
    assert "crowded" in row.notes


def test_saturator_uses_cache(engine, embedder, monkeypatch):
    """A non-stale assessment should be returned without an LLM call."""
    now = datetime.now(timezone.utc)
    with Session(engine) as s:
        s.add(SaturationAssessment(
            topic="vector dbs",
            score=0.4,
            competitor_count=4,
            assessed_at=now,
            expires_at=now + timedelta(days=7),
            notes="active; multiple players.",
        ))
        s.commit()

    monkeypatch.setattr("ai_intel.memory.embed.get_embedder", lambda: embedder)

    # call_llm must NOT be invoked when cache is fresh
    with patch("ai_intel.agents.saturator.call_llm") as mock_llm:
        result = asyncio.run(saturator(engine, topic="vector dbs"))

    mock_llm.assert_not_called()
    assert "cache hit" in result["summary"]


def test_saturator_clamps_score(engine, embedder, monkeypatch):
    """LLM might return out-of-range; agent should clamp to [0,1]."""
    monkeypatch.setattr("ai_intel.memory.embed.get_embedder", lambda: embedder)
    llm_response = _mock_llm(json.dumps({
        "score": 1.7, "competitor_count": 99,
        "competitor_names": [], "reasoning": "wild",
        "verdict": "saturated",
    }))
    with patch("ai_intel.agents.saturator.call_llm", return_value=llm_response):
        asyncio.run(saturator(engine, topic="bogus topic", use_cache=False))
    with Session(engine) as s:
        row = s.exec(select(SaturationAssessment)).first()
    assert row.score == 1.0


def test_saturator_handles_unparseable_output(engine, embedder, monkeypatch):
    """Garbage LLM output should fail soft — no row written, no exception."""
    monkeypatch.setattr("ai_intel.memory.embed.get_embedder", lambda: embedder)
    llm_response = _mock_llm("definitely not json at all")
    with patch("ai_intel.agents.saturator.call_llm", return_value=llm_response):
        result = asyncio.run(saturator(engine, topic="x", use_cache=False))
    assert "unparseable" in result["summary"]
    with Session(engine) as s:
        rows = list(s.exec(select(SaturationAssessment)))
    assert len(rows) == 0


# ---------------------------------------------------------------------------
# proposer
# ---------------------------------------------------------------------------


def test_proposer_writes_idea_candidate(engine, embedder, monkeypatch):
    tech = _seed_item(
        engine,
        title="GPU-less inference for diffusion models",
        source="hn",
        url="https://example.test/diff",
    )
    pain = _seed_item(
        engine,
        title="Ask HN: Why is image generation still painful?",
        source="pain_source",
        url="https://example.test/painful",
    )
    embed_pending(engine, embedder=embedder)

    monkeypatch.setattr("ai_intel.memory.embed.get_embedder", lambda: embedder)

    llm_response = _mock_llm(json.dumps({
        "idea": "CPU-only diffusion playground for indie designers who hate GPU bills",
        "tech_basis": "GPU-less inference techniques",
        "pain_basis": "image generation is expensive",
        "wedge": "indie graphic designers <10 people",
        "key_assumption": "indie designers will accept 5x slower iteration for 90% cheaper",
        "validation_step": "spin up a free trial limited to 20 generations and watch retention",
    }))

    with patch("ai_intel.agents.proposer.call_llm", return_value=llm_response):
        result = asyncio.run(proposer(
            engine,
            persona_id="paul_graham",
            tech_signal=tech,
            pain=pain,
        ))

    assert "CPU-only diffusion" in result["summary"]
    with Session(engine) as s:
        rows = list(s.exec(select(IdeaCandidate)))
    assert len(rows) == 1
    cand = rows[0]
    assert cand.status == "proposed"
    assert "CPU-only diffusion" in cand.idea_text
    blob = json.loads(cand.persona_critiques_json)["_proposer_detail"]
    assert blob["wedge"].startswith("indie")
    assert blob["persona_used"] == "paul_graham"


def test_proposer_skips_when_no_tech_signal(engine, embedder, monkeypatch):
    monkeypatch.setattr("ai_intel.memory.embed.get_embedder", lambda: embedder)
    # No items seeded → tech_signal lookup returns None
    with patch("ai_intel.agents.proposer.call_llm") as mock_llm:
        result = asyncio.run(proposer(engine, persona_id="paul_graham"))
    mock_llm.assert_not_called()
    assert "no fresh tech signal" in result["summary"]


def test_proposer_handles_unparseable_output(engine, embedder, monkeypatch):
    tech = _seed_item(engine, title="t", source="hn", url="https://example.test/a")
    pain = _seed_item(engine, title="p", source="pain_source", url="https://example.test/b")
    embed_pending(engine, embedder=embedder)
    monkeypatch.setattr("ai_intel.memory.embed.get_embedder", lambda: embedder)

    with patch("ai_intel.agents.proposer.call_llm", return_value=_mock_llm("not json")):
        result = asyncio.run(proposer(
            engine, persona_id="paul_graham",
            tech_signal=tech, pain=pain,
        ))
    assert "unparseable" in result["summary"]
    with Session(engine) as s:
        rows = list(s.exec(select(IdeaCandidate)))
    assert len(rows) == 0


# ---------------------------------------------------------------------------
# evaluator
# ---------------------------------------------------------------------------


def _seed_candidate(engine, *, idea_text: str = "A startup idea") -> IdeaCandidate:
    with Session(engine) as s:
        c = IdeaCandidate(
            proposed_at=datetime.now(timezone.utc),
            idea_text=idea_text,
            tech_basis="some tech",
            status="proposed",
            persona_critiques_json=json.dumps({
                "_proposer_detail": {
                    "wedge": "indie devs",
                    "key_assumption": "they want this",
                    "validation_step": "ship in 7 days",
                    "pain_basis": "their tools are slow",
                    "persona_used": "paul_graham",
                }
            }),
        )
        s.add(c)
        s.commit()
        s.refresh(c)
        return c


def test_evaluator_aggregates_persona_subscores_to_escalated(engine):
    """Every persona scores high → overall ≥75 → escalated."""
    cand = _seed_candidate(engine)

    # Mock every critic to return subscore=85
    def mock_call(*a, **kw):
        return _mock_llm(json.dumps({
            "subscore": 85,
            "critique": "love it",
            "kill_criterion": "none",
            "would_fund_or_advise": True,
        }))

    with patch("ai_intel.agents.evaluator.call_llm", side_effect=mock_call), \
         patch("ai_intel.agents.evaluator.time.sleep", lambda *a, **kw: None):
        result = asyncio.run(evaluator(engine, candidate_id=cand.id))

    with Session(engine) as s:
        row = s.get(IdeaCandidate, cand.id)
    assert row.evaluator_score == 85
    assert row.evaluator_verdict == "escalated"
    assert row.status == "escalated"
    # All 6 personas should have a critique entry
    blob = json.loads(row.persona_critiques_json)
    critique_keys = [k for k in blob if k != "_proposer_detail"]
    assert len(critique_keys) == 6


def test_evaluator_aggregates_to_killed(engine):
    cand = _seed_candidate(engine)
    with patch(
        "ai_intel.agents.evaluator.call_llm",
        return_value=_mock_llm(json.dumps({
            "subscore": 20,
            "critique": "terrible",
            "kill_criterion": "no market",
            "would_fund_or_advise": False,
        })),
    ), patch("ai_intel.agents.evaluator.time.sleep", lambda *a, **kw: None):
        asyncio.run(evaluator(engine, candidate_id=cand.id))
    with Session(engine) as s:
        row = s.get(IdeaCandidate, cand.id)
    assert row.evaluator_score == 20
    assert row.evaluator_verdict == "killed"
    assert row.status == "killed"


def test_evaluator_aggregates_to_needs_work(engine):
    cand = _seed_candidate(engine)
    # Alternate between 80 and 30 → mean ≈ 55 → needs_work
    responses = iter([
        _mock_llm(json.dumps({"subscore": s, "critique": "x", "kill_criterion": "y", "would_fund_or_advise": False}))
        for s in (80, 30, 80, 30, 80, 30)
    ])
    with patch("ai_intel.agents.evaluator.call_llm", side_effect=lambda *a, **kw: next(responses)), \
         patch("ai_intel.agents.evaluator.time.sleep", lambda *a, **kw: None):
        asyncio.run(evaluator(engine, candidate_id=cand.id))
    with Session(engine) as s:
        row = s.get(IdeaCandidate, cand.id)
    assert row.evaluator_score == 55
    assert row.evaluator_verdict == "needs_work"


def test_evaluator_does_nothing_when_no_pending(engine):
    """Empty DB → no work; cost stays zero."""
    with patch("ai_intel.agents.evaluator.call_llm") as mock_llm:
        result = asyncio.run(evaluator(engine))
    mock_llm.assert_not_called()
    assert "nothing to do" in result["summary"]


def test_evaluator_handles_partial_persona_failures(engine):
    """If 5 of 6 personas return garbage but 1 parses, still aggregate."""
    cand = _seed_candidate(engine)
    good = _mock_llm(json.dumps({
        "subscore": 60, "critique": "ok", "kill_criterion": "none",
        "would_fund_or_advise": False,
    }))
    bad = _mock_llm("not parseable json")
    # Cycle: good, then 5 bad
    seq = iter([good, bad, bad, bad, bad, bad])
    with patch("ai_intel.agents.evaluator.call_llm", side_effect=lambda *a, **kw: next(seq)), \
         patch("ai_intel.agents.evaluator.time.sleep", lambda *a, **kw: None):
        asyncio.run(evaluator(engine, candidate_id=cand.id))
    with Session(engine) as s:
        row = s.get(IdeaCandidate, cand.id)
    assert row.evaluator_score == 60
    # Only one persona made it into the critiques blob (plus proposer detail)
    blob = json.loads(row.persona_critiques_json)
    critiques = [k for k in blob if k != "_proposer_detail"]
    assert len(critiques) == 1
