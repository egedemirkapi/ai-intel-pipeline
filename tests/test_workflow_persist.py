"""Tests for workflow CRUD (persist.py) and trigger resolution (triggers.py).

Covers:
- validate_def: well-formed vs. malformed definitions and triggers
- create / update / delete against a temp user file
- builtin protection (cannot delete a bundled default)
- workflows_with_trigger / hotkey_map / match_voice
"""
from __future__ import annotations

import asyncio

import pytest
import yaml

from ai_intel.workflows import (
    WorkflowError,
    create_workflow,
    delete_workflow,
    get_workflow,
    hotkey_map,
    list_workflow_defs,
    match_voice,
    update_workflow,
    validate_def,
    workflows_with_trigger,
)


def _valid_def(**overrides):
    d = {
        "description": "test routine",
        "trigger": {"button": True, "voice_phrases": ["do the thing"]},
        "steps": [{"notify": {"title": "T", "body": "hello"}}],
    }
    d.update(overrides)
    return d


# ─── validate_def ───────────────────────────────────────────────────


def test_validate_accepts_well_formed_def():
    assert validate_def(_valid_def()) == []


def test_validate_rejects_non_mapping():
    assert validate_def("not a dict")


def test_validate_requires_non_empty_steps():
    errors = validate_def(_valid_def(steps=[]))
    assert any("steps" in e for e in errors)


def test_validate_rejects_unknown_action():
    errors = validate_def(_valid_def(steps=[{"bogus.action": {}}]))
    assert any("unknown action" in e for e in errors)


def test_validate_rejects_multi_key_step():
    errors = validate_def(_valid_def(steps=[{"notify": {}, "tabs.open_set": {}}]))
    assert any("single" in e for e in errors)


def test_validate_rejects_bad_trigger_key():
    errors = validate_def(_valid_def(trigger={"bogus": True}))
    assert any("unknown key" in e for e in errors)


def test_validate_rejects_bad_hotkey_type():
    errors = validate_def(_valid_def(trigger={"hotkey": 123}))
    assert any("hotkey" in e for e in errors)


def test_validate_rejects_bad_voice_phrases():
    errors = validate_def(_valid_def(trigger={"voice_phrases": "not a list"}))
    assert any("voice_phrases" in e for e in errors)


# ─── create / update / delete ───────────────────────────────────────


def test_create_writes_to_user_file(tmp_path):
    p = tmp_path / "workflows.yaml"
    create_workflow("my_routine", _valid_def(), path=p)
    assert p.exists()
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert "my_routine" in data["workflows"]
    assert get_workflow("my_routine", path=p)["description"] == "test routine"


def test_create_rejects_duplicate_name(tmp_path):
    p = tmp_path / "workflows.yaml"
    create_workflow("dup", _valid_def(), path=p)
    with pytest.raises(WorkflowError, match="already exists"):
        create_workflow("dup", _valid_def(), path=p)


def test_create_rejects_invalid_name(tmp_path):
    p = tmp_path / "workflows.yaml"
    with pytest.raises(WorkflowError, match="invalid name"):
        create_workflow("bad name!", _valid_def(), path=p)


def test_create_rejects_invalid_def(tmp_path):
    p = tmp_path / "workflows.yaml"
    with pytest.raises(WorkflowError):
        create_workflow("bad", {"steps": []}, path=p)


def test_update_overwrites(tmp_path):
    p = tmp_path / "workflows.yaml"
    create_workflow("r", _valid_def(), path=p)
    update_workflow("r", _valid_def(description="changed"), path=p)
    assert get_workflow("r", path=p)["description"] == "changed"


def test_update_can_override_builtin(tmp_path):
    p = tmp_path / "workflows.yaml"
    update_workflow("clap_default", _valid_def(description="my clap"), path=p)
    assert get_workflow("clap_default", path=p)["description"] == "my clap"


def test_delete_removes_user_workflow(tmp_path):
    p = tmp_path / "workflows.yaml"
    create_workflow("temp", _valid_def(), path=p)
    delete_workflow("temp", path=p)
    assert get_workflow("temp", path=p) is None


def test_delete_builtin_is_refused(tmp_path):
    p = tmp_path / "workflows.yaml"
    with pytest.raises(WorkflowError, match="built-in"):
        delete_workflow("clap_default", path=p)


def test_delete_unknown_is_refused(tmp_path):
    p = tmp_path / "workflows.yaml"
    with pytest.raises(WorkflowError, match="unknown"):
        delete_workflow("nope", path=p)


def test_list_workflow_defs_marks_builtins(tmp_path):
    p = tmp_path / "workflows.yaml"
    create_workflow("custom", _valid_def(), path=p)
    rows = {r["name"]: r for r in list_workflow_defs(path=p)}
    assert rows["clap_default"]["is_builtin"] is True
    assert rows["custom"]["is_builtin"] is False
    assert "trigger" in rows["custom"] and "step_count" in rows["custom"]


# ─── triggers ───────────────────────────────────────────────────────


def test_workflows_with_trigger_finds_clap_default(tmp_path):
    p = tmp_path / "workflows.yaml"
    assert "clap_default" in workflows_with_trigger("clap", path=p)
    assert "clap_default" in workflows_with_trigger("button", path=p)


def test_hotkey_map_collects_hotkeys(tmp_path):
    p = tmp_path / "workflows.yaml"
    create_workflow(
        "hk",
        _valid_def(trigger={"hotkey": "ctrl+alt+j"}),
        path=p,
    )
    assert hotkey_map(path=p).get("hk") == "ctrl+alt+j"


def test_match_voice_picks_workflow_by_phrase(tmp_path):
    p = tmp_path / "workflows.yaml"
    # clap_default has voice phrase "study setup"
    assert match_voice("hey jarvis, study setup please", path=p) == "clap_default"


def test_match_voice_returns_none_on_no_match(tmp_path):
    p = tmp_path / "workflows.yaml"
    assert match_voice("completely unrelated sentence", path=p) is None


def test_match_voice_prefers_longest_phrase(tmp_path):
    p = tmp_path / "workflows.yaml"
    create_workflow(
        "specific",
        _valid_def(trigger={"voice_phrases": ["open my study setup dashboard"]}),
        path=p,
    )
    # transcript contains both "study setup" (clap_default) and the longer phrase
    got = match_voice("please open my study setup dashboard now", path=p)
    assert got == "specific"


# ─── schedule trigger ───────────────────────────────────────────────


def test_validate_accepts_valid_cron_schedule():
    assert validate_def(_valid_def(trigger={"schedule": "0 8 * * *"})) == []


def test_validate_rejects_bad_cron_schedule():
    errors = validate_def(_valid_def(trigger={"schedule": "every day at 8"}))
    assert any("schedule" in e for e in errors)


def test_validate_rejects_non_string_schedule():
    errors = validate_def(_valid_def(trigger={"schedule": 800}))
    assert any("schedule" in e for e in errors)


def test_workflows_with_schedule_lists_scheduled(tmp_path):
    from ai_intel.workflows.triggers import workflows_with_schedule

    p = tmp_path / "workflows.yaml"
    create_workflow(
        "daily_digest",
        _valid_def(trigger={"schedule": "0 8 * * *"}),
        path=p,
    )
    found = dict(workflows_with_schedule(path=p))
    assert found.get("daily_digest") == "0 8 * * *"


# ─── builtin scheduled workflows ───────────────────────────────────


def test_daily_trend_refresh_loads_and_validates(tmp_path):
    """daily_trend_refresh must load from defaults and pass validate_def."""
    from ai_intel.workflows.persist import get_workflow, validate_def

    p = tmp_path / "workflows.yaml"
    wf = get_workflow("daily_trend_refresh", path=p)
    assert wf is not None, "daily_trend_refresh not found in defaults"
    errors = validate_def(wf)
    assert errors == [], f"validate_def errors: {errors}"


def test_weekly_idea_run_loads_and_validates(tmp_path):
    """weekly_idea_run must load from defaults and pass validate_def."""
    from ai_intel.workflows.persist import get_workflow, validate_def

    p = tmp_path / "workflows.yaml"
    wf = get_workflow("weekly_idea_run", path=p)
    assert wf is not None, "weekly_idea_run not found in defaults"
    errors = validate_def(wf)
    assert errors == [], f"validate_def errors: {errors}"


def test_builtin_scheduled_workflows_appear_in_workflows_with_schedule(tmp_path):
    """workflows_with_schedule must return both new builtins with correct cron strings."""
    from ai_intel.workflows.triggers import workflows_with_schedule

    p = tmp_path / "workflows.yaml"
    found = dict(workflows_with_schedule(path=p))
    assert found.get("daily_trend_refresh") == "0 6 * * *", (
        f"daily_trend_refresh cron mismatch: {found.get('daily_trend_refresh')!r}"
    )
    assert found.get("weekly_idea_run") == "0 6 * * 1", (
        f"weekly_idea_run cron mismatch: {found.get('weekly_idea_run')!r}"
    )


def test_daily_trend_refresh_has_one_synthesizer_step(tmp_path):
    """daily_trend_refresh must have exactly one step: agent.run synthesizer."""
    from ai_intel.workflows.persist import get_workflow

    p = tmp_path / "workflows.yaml"
    wf = get_workflow("daily_trend_refresh", path=p)
    steps = wf["steps"]
    assert len(steps) == 1
    step = steps[0]
    assert "agent.run" in step
    assert step["agent.run"]["agent_id"] == "synthesizer"


def test_weekly_idea_run_has_two_steps_in_order(tmp_path):
    """weekly_idea_run must have two steps: synthesizer then weekly_ideation."""
    from ai_intel.workflows.persist import get_workflow

    p = tmp_path / "workflows.yaml"
    wf = get_workflow("weekly_idea_run", path=p)
    steps = wf["steps"]
    assert len(steps) == 2
    assert steps[0].get("agent.run", {}).get("agent_id") == "synthesizer"
    assert steps[1].get("agent.run", {}).get("agent_id") == "weekly_ideation"


# ─── routine workflow ───────────────────────────────────────────────


def test_routine_workflow_loads_and_validates(tmp_path):
    """routine must load from defaults and pass validate_def."""
    from ai_intel.workflows.persist import get_workflow, validate_def

    p = tmp_path / "workflows.yaml"
    wf = get_workflow("routine", path=p)
    assert wf is not None, "routine workflow not found in defaults"
    errors = validate_def(wf)
    assert errors == [], f"validate_def errors: {errors}"


def test_routine_workflow_has_voice_phrases(tmp_path):
    """routine must expose the expected voice phrases."""
    from ai_intel.workflows.persist import get_workflow

    p = tmp_path / "workflows.yaml"
    wf = get_workflow("routine", path=p)
    phrases = (wf.get("trigger") or {}).get("voice_phrases", [])
    assert "run the routine" in phrases
    assert "run my routine" in phrases
    assert "start my routine" in phrases
    assert "the routine" in phrases


def test_routine_workflow_has_button_trigger(tmp_path):
    """routine must have button: true."""
    from ai_intel.workflows.persist import get_workflow

    p = tmp_path / "workflows.yaml"
    wf = get_workflow("routine", path=p)
    assert (wf.get("trigger") or {}).get("button") is True


def test_routine_workflow_has_tabs_and_brief_steps(tmp_path):
    """routine must include a tabs.open_set step and a brief.compose step."""
    from ai_intel.workflows.persist import get_workflow

    p = tmp_path / "workflows.yaml"
    wf = get_workflow("routine", path=p)
    actions = [list(step.keys())[0] for step in wf["steps"]]
    assert "tabs.open_set" in actions, f"tabs.open_set not in steps: {actions}"
    assert "brief.compose" in actions, f"brief.compose not in steps: {actions}"


def test_match_voice_run_the_routine(tmp_path):
    """'run the routine' must resolve to the routine workflow."""
    p = tmp_path / "workflows.yaml"
    result = match_voice("run the routine", path=p)
    assert result == "routine", f"expected 'routine', got {result!r}"


def test_match_voice_run_name_fallback_resolves_workflow(tmp_path):
    """'run routine' (no article) falls back to the routine workflow via name matching."""
    p = tmp_path / "workflows.yaml"
    result = match_voice("run routine", path=p)
    assert result == "routine", f"expected 'routine', got {result!r}"


def test_match_voice_run_name_fallback_resolves_underscored_name(tmp_path):
    """'run morning brief' resolves morning_brief via the name-fallback."""
    p = tmp_path / "workflows.yaml"
    result = match_voice("run morning brief", path=p)
    assert result == "morning_brief", f"expected 'morning_brief', got {result!r}"


# ─── workflow.create chat tool ──────────────────────────────────────


def test_workflow_create_tool_rejects_bad_definition():
    """The workflow.create chat tool returns an error (does not raise, does
    not write) for an invalid definition."""
    from ai_intel.brain.tools import _h_workflow_create

    result = asyncio.run(
        _h_workflow_create(None, name="bad", definition={"steps": []})
    )
    assert "error" in result and "created" not in result
