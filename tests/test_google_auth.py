"""Tests for Google auth + the three Google collectors.

The OAuth browser flow itself can't be unit-tested. We test:
- storage.py token round-trip (with an in-memory keyring backend)
- the pure RawItem-conversion helpers in each collector
- graceful degradation: collectors return [] when no token is stored
- the classroom.read brain tool errors cleanly with no token
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import pytest


# ─── In-memory keyring backend so storage tests don't touch the OS ───


class _MemoryKeyring:
    """Minimal in-memory keyring backend for tests."""
    def __init__(self):
        self._store: dict[tuple[str, str], str] = {}

    def set_password(self, service, username, password):
        self._store[(service, username)] = password

    def get_password(self, service, username):
        return self._store.get((service, username))

    def delete_password(self, service, username):
        import keyring.errors
        if (service, username) not in self._store:
            raise keyring.errors.PasswordDeleteError("not found")
        del self._store[(service, username)]


@pytest.fixture
def mem_keyring(monkeypatch):
    import keyring
    backend = _MemoryKeyring()
    monkeypatch.setattr(keyring, "set_password", backend.set_password)
    monkeypatch.setattr(keyring, "get_password", backend.get_password)
    monkeypatch.setattr(keyring, "delete_password", backend.delete_password)
    return backend


# ─── storage.py ──────────────────────────────────────────────────────


def test_token_store_load_roundtrip(mem_keyring):
    from ai_intel.google_auth.storage import store_token, load_token, has_token
    assert not has_token()
    blob = json.dumps({"refresh_token": "abc", "token": "xyz"})
    store_token(blob)
    assert has_token()
    assert load_token() == blob


def test_token_clear(mem_keyring):
    from ai_intel.google_auth.storage import store_token, clear_token, has_token
    store_token(json.dumps({"refresh_token": "abc"}))
    assert has_token()
    clear_token()
    assert not has_token()
    # Clearing again is a no-op, not an error
    clear_token()


def test_parse_token_rejects_garbage():
    from ai_intel.google_auth.storage import parse_token
    with pytest.raises(ValueError):
        parse_token("not json")


# ─── Classroom collector helpers ────────────────────────────────────


def test_classroom_coursework_to_item_with_due_date():
    from ai_intel.collectors.google_classroom import _coursework_to_item
    cw = {
        "id": "cw1",
        "title": "Essay on Hamlet",
        "description": "Write 1000 words.",
        "dueDate": {"year": 2026, "month": 5, "day": 25},
        "dueTime": {"hours": 14, "minutes": 30},
        "state": "PUBLISHED",
        "workType": "ASSIGNMENT",
        "alternateLink": "https://classroom.google.com/c/x/a/y",
        "creationTime": "2026-05-19T10:00:00Z",
    }
    item = _coursework_to_item("English Lit", cw)
    assert item.title == "[English Lit] Essay on Hamlet"
    assert "Due: 2026-05-25T14:30" in item.body
    assert "Write 1000 words." in item.body
    assert item.raw["kind"] == "assignment"
    assert item.raw["due_date"] == "2026-05-25T14:30"
    assert item.raw["course"] == "English Lit"


def test_classroom_coursework_to_item_no_due_date():
    from ai_intel.collectors.google_classroom import _coursework_to_item
    cw = {"id": "cw2", "title": "Reading", "state": "PUBLISHED"}
    item = _coursework_to_item("History", cw)
    assert "Due: (no due date)" in item.body
    assert item.raw["due_date"] is None


def test_classroom_announcement_to_item():
    from ai_intel.collectors.google_classroom import _announcement_to_item
    ann = {
        "id": "a1",
        "text": "Class cancelled Friday.\nEnjoy the long weekend.",
        "alternateLink": "https://classroom.google.com/c/x/p/z",
        "creationTime": "2026-05-19T09:00:00Z",
    }
    item = _announcement_to_item("Physics", ann)
    assert "Class cancelled Friday" in item.title
    assert item.raw["kind"] == "announcement"


# ─── Calendar collector helpers ─────────────────────────────────────


def test_calendar_event_to_item_timed():
    from ai_intel.collectors.google_calendar import _event_to_item
    ev = {
        "id": "ev1",
        "summary": "Dentist",
        "start": {"dateTime": "2026-05-21T09:00:00+00:00"},
        "end": {"dateTime": "2026-05-21T10:00:00+00:00"},
        "location": "123 Main St",
        "htmlLink": "https://calendar.google.com/event?eid=x",
    }
    item = _event_to_item(ev)
    assert item.title == "[Calendar] Dentist"
    assert "Location: 123 Main St" in item.body
    assert item.raw["kind"] == "calendar_event"


def test_calendar_event_to_item_all_day():
    from ai_intel.collectors.google_calendar import _event_to_item
    ev = {
        "id": "ev2",
        "summary": "Holiday",
        "start": {"date": "2026-05-25"},
        "end": {"date": "2026-05-26"},
    }
    item = _event_to_item(ev)
    assert "all day" in item.body


# ─── Gmail collector helpers ────────────────────────────────────────


def test_gmail_message_to_item():
    from ai_intel.collectors.google_gmail import _message_to_item
    msg = {
        "id": "m1",
        "internalDate": "1779000000000",
        "snippet": "Your order has shipped",
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Shipping update"},
                {"name": "From", "value": "store@example.com"},
                {"name": "Date", "value": "Tue, 19 May 2026 10:00:00 +0000"},
            ],
        },
    }
    item = _message_to_item(msg)
    assert item.title == "[Email] Shipping update"
    assert "store@example.com" in item.body
    assert "Your order has shipped" in item.body
    assert item.raw["kind"] == "email"


# ─── Graceful degradation: no token → empty, no crash ───────────────


def test_classroom_collector_no_token_returns_empty(monkeypatch):
    from ai_intel.collectors.google_classroom import GoogleClassroomCollector
    monkeypatch.setattr("ai_intel.google_auth.has_token", lambda: False)
    collector = GoogleClassroomCollector()
    items = asyncio.run(collector.fetch_since(datetime.now(timezone.utc)))
    assert items == []


def test_calendar_collector_no_token_returns_empty(monkeypatch):
    from ai_intel.collectors.google_calendar import GoogleCalendarCollector
    monkeypatch.setattr("ai_intel.google_auth.has_token", lambda: False)
    collector = GoogleCalendarCollector()
    items = asyncio.run(collector.fetch_since(datetime.now(timezone.utc)))
    assert items == []


def test_gmail_collector_no_token_returns_empty(monkeypatch):
    from ai_intel.collectors.google_gmail import GoogleGmailCollector
    monkeypatch.setattr("ai_intel.google_auth.has_token", lambda: False)
    collector = GoogleGmailCollector()
    items = asyncio.run(collector.fetch_since(datetime.now(timezone.utc)))
    assert items == []


def test_classroom_tool_errors_cleanly_without_token(monkeypatch):
    """The brain's gworkspace.read_classroom tool returns a clear error
    (not a crash) when Google isn't connected."""
    from ai_intel.brain.tools import _h_classroom_read
    monkeypatch.setattr("ai_intel.google_auth.has_token", lambda: False)
    out = asyncio.run(_h_classroom_read(None))
    assert "error" in out
    assert "setup_google_auth" in out["error"]
    assert out["items"] == []


def test_calendar_tool_errors_cleanly_without_token(monkeypatch):
    """gworkspace.read_calendar returns a clear error, not a crash."""
    from ai_intel.brain.tools import _h_calendar_read
    monkeypatch.setattr("ai_intel.google_auth.has_token", lambda: False)
    out = asyncio.run(_h_calendar_read(None))
    assert "error" in out
    assert "setup_google_auth" in out["error"]
    assert out["events"] == []


def test_email_tool_errors_cleanly_without_token(monkeypatch):
    """gworkspace.read_email returns a clear error, not a crash."""
    from ai_intel.brain.tools import _h_email_read
    monkeypatch.setattr("ai_intel.google_auth.has_token", lambda: False)
    out = asyncio.run(_h_email_read(None))
    assert "error" in out
    assert "setup_google_auth" in out["error"]
    assert out["messages"] == []


# ─── Calendar + Email workflow actions ──────────────────────────────


def test_calendar_action_no_token_returns_summary(monkeypatch):
    """calendar.check degrades to a clean summary when not connected."""
    from ai_intel.workflows.actions.calendar import action_calendar_check
    monkeypatch.setattr("ai_intel.google_auth.has_token", lambda: False)
    out = asyncio.run(action_calendar_check(None))
    assert out["events"] == []
    assert "not connected" in out["summary"]


def test_email_action_no_token_returns_summary(monkeypatch):
    """email.check degrades to a clean summary when not connected."""
    from ai_intel.workflows.actions.gmail import action_email_check
    monkeypatch.setattr("ai_intel.google_auth.has_token", lambda: False)
    out = asyncio.run(action_email_check(None))
    assert out["messages"] == []
    assert "not connected" in out["summary"]


def test_google_tools_and_actions_registered():
    """The new Calendar/Email tools + actions are wired into the registries."""
    from ai_intel.brain.tools import build_registry
    from ai_intel.workflows.actions import ACTION_REGISTRY

    reg = build_registry()
    assert "gworkspace.read_calendar" in reg
    assert "gworkspace.read_email" in reg
    assert "calendar.check" in ACTION_REGISTRY
    assert "email.check" in ACTION_REGISTRY


def test_google_workflows_are_valid():
    """The bundled calendar_brief + email_check workflows pass validation."""
    from ai_intel.workflows import get_workflow, validate_def

    for name in ("calendar_brief", "email_check"):
        wf = get_workflow(name)
        assert wf is not None, f"{name} missing from defaults"
        assert validate_def(wf) == []
