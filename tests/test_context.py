"""Tests for Sprint 4 context awareness — foreground tracking, on_app
triggers, the speak action, and the /context endpoints."""
from __future__ import annotations

import asyncio

from ai_intel.brain.context import (
    get_current_context,
    reset_context,
    set_current_context,
)
from ai_intel.brain.speak import get_speak_queue, reset_speak_queue
from ai_intel.workflows import (
    create_workflow,
    match_app,
    validate_def,
    workflows_with_trigger,
)
from ai_intel.workflows.actions.speak import action_speak
from voice.windows_context import context_key


def _def(on_app=None):
    d = {
        "description": "t",
        "trigger": {},
        "steps": [{"notify": {"title": "T", "body": "b"}}],
    }
    if on_app is not None:
        d["trigger"]["on_app"] = on_app
    return d


# ─── current-context singleton ──────────────────────────────────────


def test_context_set_get_reset():
    reset_context()
    assert get_current_context() == {}
    set_current_context("Code.exe", "main.py - VS Code")
    ctx = get_current_context()
    assert ctx["process"] == "Code.exe"
    assert "since" in ctx
    reset_context()
    assert get_current_context() == {}


# ─── context_key ────────────────────────────────────────────────────


def test_context_key_prefers_process():
    assert context_key({"process": "Code.exe", "title": "x"}) == "code.exe"


def test_context_key_falls_back_to_title():
    assert context_key({"process": None, "title": "Notion Calendar"}) == "notion"


def test_context_key_none():
    assert context_key(None) == ""


# ─── on_app validation ──────────────────────────────────────────────


def test_validate_accepts_on_app_string():
    assert validate_def(_def(on_app="Code.exe")) == []


def test_validate_accepts_on_app_list():
    assert validate_def(_def(on_app=["code", "cursor"])) == []


def test_validate_rejects_bad_on_app():
    assert any("on_app" in e for e in validate_def(_def(on_app=123)))


# ─── match_app ──────────────────────────────────────────────────────


def test_match_app_by_process(tmp_path):
    p = tmp_path / "workflows.yaml"
    create_workflow("dev_setup", _def(on_app="cursor"), path=p)
    assert match_app("Cursor.exe", "", path=p) == ["dev_setup"]
    assert match_app("chrome.exe", "", path=p) == []


def test_match_app_by_title(tmp_path):
    p = tmp_path / "workflows.yaml"
    create_workflow("study", _def(on_app="classroom"), path=p)
    assert match_app("chrome.exe", "Google Classroom", path=p) == ["study"]


def test_match_app_accepts_a_list(tmp_path):
    p = tmp_path / "workflows.yaml"
    create_workflow("ide", _def(on_app=["code", "cursor"]), path=p)
    assert match_app("Cursor.exe", "", path=p) == ["ide"]


def test_workflows_with_on_app_trigger(tmp_path):
    p = tmp_path / "workflows.yaml"
    create_workflow("x", _def(on_app="code"), path=p)
    assert "x" in workflows_with_trigger("on_app", path=p)


# ─── speak action ───────────────────────────────────────────────────


def test_speak_action_pushes_to_queue():
    reset_speak_queue()
    try:
        out = asyncio.run(action_speak(None, text="opening your dev setup"))
        assert out["spoke"] is True
        assert [u.text for u in get_speak_queue().drain()] == ["opening your dev setup"]
    finally:
        reset_speak_queue()


def test_speak_action_empty_is_noop():
    reset_speak_queue()
    try:
        out = asyncio.run(action_speak(None, text="   "))
        assert out["spoke"] is False
    finally:
        reset_speak_queue()


# ─── Brain /context endpoints + context.app tool ────────────────────


def test_context_endpoints_and_tool():
    from fastapi.testclient import TestClient

    from ai_intel.brain.app import create_app
    from ai_intel.brain.tools import _h_context_app

    reset_context()
    try:
        with TestClient(create_app()) as c:
            r = c.post(
                "/context/app",
                json={"process": "Cursor.exe", "title": "brief.py"},
            )
            assert r.status_code == 200
            assert r.json()["context"]["process"] == "Cursor.exe"
            assert c.get("/context").json()["context"]["process"] == "Cursor.exe"
        # the context.app chat tool reads the same singleton
        out = asyncio.run(_h_context_app(None))
        assert out["context"]["process"] == "Cursor.exe"
    finally:
        reset_context()
