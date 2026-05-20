"""Tests for the workflow engine.

Covers:
- YAML load + user-override merge
- {{ steps.N.field }} template interpolation
- Sequential step execution with result chaining
- Capability gating: a denied action is skipped + queued, not run
- Unknown workflow / unknown action error handling
"""
from __future__ import annotations

import asyncio
import json

import pytest

from ai_intel.workflows.engine import (
    _interpolate,
    list_workflows,
    load_workflows,
    run_workflow,
)


# ─── Template interpolation ─────────────────────────────────────────


def test_interpolate_pulls_prior_step_field():
    results = [{"summary": "3 assignments due"}, {"count": 7}]
    out = _interpolate("Homework: {{ steps.0.summary }}", results)
    assert out == "Homework: 3 assignments due"


def test_interpolate_recurses_into_lists_and_dicts():
    results = [{"x": "VALUE"}]
    out = _interpolate(
        {"body": "{{ steps.0.x }}", "urls": ["{{ steps.0.x }}", "static"]},
        results,
    )
    assert out["body"] == "VALUE"
    assert out["urls"] == ["VALUE", "static"]


def test_interpolate_out_of_range_step_yields_empty():
    out = _interpolate("{{ steps.9.summary }}", [{"summary": "x"}])
    assert out == ""


# ─── Workflow loading ───────────────────────────────────────────────


def test_load_workflows_includes_bundled_defaults():
    wfs = load_workflows()
    assert "clap_default" in wfs
    assert "homework_check" in wfs
    assert "morning_brief" in wfs


def test_user_workflow_overrides_default(tmp_path):
    user_yaml = tmp_path / "workflows.yaml"
    user_yaml.write_text(
        "workflows:\n"
        "  clap_default:\n"
        "    description: my override\n"
        "    steps:\n"
        "      - notify:\n"
        "          title: Custom\n"
        "          body: overridden\n",
        encoding="utf-8",
    )
    wfs = load_workflows(user_yaml)
    assert wfs["clap_default"]["description"] == "my override"
    # Bundled-only workflows still present
    assert "morning_brief" in wfs


def test_list_workflows_shape():
    rows = list_workflows()
    names = {r["name"] for r in rows}
    assert "clap_default" in names
    for r in rows:
        assert "description" in r and "step_count" in r


# ─── run_workflow ───────────────────────────────────────────────────


def test_run_unknown_workflow_returns_error():
    out = asyncio.run(run_workflow(None, "does_not_exist"))
    assert "error" in out
    assert "available" in out


def test_run_workflow_executes_steps(tmp_path, monkeypatch):
    """A simple notify-only workflow runs its step and reports ok."""
    user_yaml = tmp_path / "workflows.yaml"
    user_yaml.write_text(
        "workflows:\n"
        "  smoke:\n"
        "    description: smoke test\n"
        "    steps:\n"
        "      - notify:\n"
        "          title: Test\n"
        "          body: hello\n",
        encoding="utf-8",
    )
    out = asyncio.run(run_workflow(None, "smoke", path=user_yaml))
    assert out["workflow"] == "smoke"
    assert out["ok"] is True
    assert len(out["steps"]) == 1
    assert out["steps"][0]["action"] == "notify"
    assert out["steps"][0]["title"] == "Test"


def test_run_workflow_interpolates_between_steps(tmp_path):
    """Step 1's notify body pulls step 0's notify summary."""
    user_yaml = tmp_path / "workflows.yaml"
    user_yaml.write_text(
        "workflows:\n"
        "  chained:\n"
        "    description: chained\n"
        "    steps:\n"
        "      - notify:\n"
        "          title: First\n"
        "          body: alpha\n"
        "      - notify:\n"
        "          title: Second\n"
        "          body: \"got {{ steps.0.summary }}\"\n",
        encoding="utf-8",
    )
    out = asyncio.run(run_workflow(None, "chained", path=user_yaml))
    # step 0's notify returns summary="notified: First"
    assert "notified: First" in out["steps"][1]["body"]


def test_run_workflow_denied_action_is_skipped_and_queued(tmp_path, monkeypatch):
    """A workflow step naming a denied action must be refused + queued,
    never executed — and remaining steps still run."""
    # Approval queue + policy → temp files
    qp = tmp_path / "approvals.queue"
    user_cfg = tmp_path / "tools.toml"
    # Force apps.launch to deny at the capability layer so the engine
    # refuses the step before the handler (which has its own allowlist).
    user_cfg.write_text('"apps.launch" = "deny"\n', encoding="utf-8")
    monkeypatch.setattr("ai_intel.jarvis.permissions.APPROVAL_QUEUE_PATH", qp)
    monkeypatch.setattr("ai_intel.jarvis.permissions.USER_CONFIG_PATH", user_cfg)

    user_yaml = tmp_path / "workflows.yaml"
    user_yaml.write_text(
        "workflows:\n"
        "  mixed:\n"
        "    description: mixed\n"
        "    steps:\n"
        "      - apps.launch:\n"
        "          name: somethingdangerous\n"
        "      - notify:\n"
        "          title: After\n"
        "          body: still ran\n",
        encoding="utf-8",
    )
    out = asyncio.run(run_workflow(None, "mixed", path=user_yaml))
    assert out["ok"] is False  # one step refused
    assert "refused" in out["steps"][0]
    assert out["steps"][0]["approval_id"]
    # The notify step after it STILL ran
    assert out["steps"][1].get("title") == "After"
    # Approval was queued
    assert qp.exists()
    lines = [l for l in qp.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert json.loads(lines[0])["tool"] == "apps.launch"
