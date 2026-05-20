"""Tests for the proactive-speech queue and fleet-event narration."""
from __future__ import annotations

from ai_intel.brain.events import FleetEvent
from ai_intel.brain.speak import (
    SpeakQueue,
    narration_for,
    reset_speak_queue,
)


# ─── SpeakQueue ─────────────────────────────────────────────────────


def test_push_and_drain():
    q = SpeakQueue()
    q.push("hello")
    q.push("world", kind="briefing")
    items = q.drain()
    assert [u.text for u in items] == ["hello", "world"]
    assert items[1].kind == "briefing"
    assert q.drain() == []  # drained


def test_push_rejects_empty():
    q = SpeakQueue()
    assert q.push("   ") is False
    assert q.pending == 0


def test_queue_is_bounded_dropping_oldest():
    q = SpeakQueue(maxlen=3)
    for i in range(10):
        q.push(f"u{i}")
    items = q.drain()
    assert [u.text for u in items] == ["u7", "u8", "u9"]


# ─── narration_for ──────────────────────────────────────────────────


def test_narration_for_trend():
    ev = FleetEvent(type="trend_synthesized", summary="agentic coding tools")
    phrase = narration_for(ev)
    assert phrase and "trend" in phrase.lower()
    assert "agentic coding tools" in phrase


def test_narration_for_idea():
    ev = FleetEvent(type="idea_evaluated", summary="#12 escalated at 78")
    assert narration_for(ev) is not None


def test_narration_skips_routine_events():
    assert narration_for(FleetEvent(type="agent_started")) is None
    assert narration_for(FleetEvent(type="workflow_finished", summary="x")) is None


def test_narration_skips_when_no_summary():
    assert narration_for(FleetEvent(type="trend_synthesized", summary=None)) is None


# ─── Brain /speak endpoints ─────────────────────────────────────────


def test_speak_endpoints_roundtrip():
    from fastapi.testclient import TestClient

    from ai_intel.brain.app import create_app

    reset_speak_queue()
    try:
        with TestClient(create_app()) as c:
            r = c.post("/speak", json={"text": "good morning", "kind": "briefing"})
            assert r.status_code == 200
            assert r.json()["queued"] is True

            utts = c.get("/speak/pending").json()["utterances"]
            assert len(utts) == 1
            assert utts[0]["text"] == "good morning"
            assert utts[0]["kind"] == "briefing"

            # queue is drained after a GET
            assert c.get("/speak/pending").json()["utterances"] == []
    finally:
        reset_speak_queue()
