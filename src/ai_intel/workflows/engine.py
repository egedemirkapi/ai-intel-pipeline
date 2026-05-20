"""Workflow engine — load YAML, run steps, gate every action.

Resolution order for the workflow definitions:
    1. user file at ~/.jarvis/workflows.yaml
    2. bundled defaults at ai_intel/workflows/defaults/workflows.yaml

A workflow:
    workflows:
      <name>:
        description: <text>
        steps:
          - <action.name>:
              <arg>: <value>
          - ...

Each step is a single-key mapping {action_name: args}. Steps run in
order. Every action name is checked against the capability layer
(~/.jarvis/tools.toml). A denied action is skipped + queued for
approval; the workflow continues with remaining steps.

Template interpolation: any string arg containing ``{{ steps.N.field }}``
is replaced with the value of step N's result[field] (N is 0-based,
referring to an EARLIER step). This lets e.g. a ``notify`` step surface
a prior ``classroom.check`` step's summary.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml

from ai_intel.jarvis.permissions import is_allowed, request_approval
from ai_intel.workflows.actions import ACTION_REGISTRY

logger = logging.getLogger(__name__)

DEFAULTS_PATH = Path(__file__).parent / "defaults" / "workflows.yaml"
USER_WORKFLOWS_PATH = Path.home() / ".jarvis" / "workflows.yaml"

_TEMPLATE_RE = re.compile(r"\{\{\s*steps\.(\d+)\.([a-zA-Z0-9_]+)\s*\}\}")


def load_workflows(path: Path | None = None) -> dict[str, Any]:
    """Load workflow definitions. User file overrides bundled defaults
    per-workflow-name (a user workflow with the same name wins).
    """
    merged: dict[str, Any] = {}
    if DEFAULTS_PATH.exists():
        defaults = yaml.safe_load(DEFAULTS_PATH.read_text(encoding="utf-8")) or {}
        merged.update(defaults.get("workflows", {}))
    user_path = path or USER_WORKFLOWS_PATH
    if user_path.exists():
        user = yaml.safe_load(user_path.read_text(encoding="utf-8")) or {}
        merged.update(user.get("workflows", {}))
    return merged


def list_workflows(path: Path | None = None) -> list[dict[str, Any]]:
    """Return [{name, description, trigger, step_count}, ...]."""
    wfs = load_workflows(path)
    out = []
    for name, wf in wfs.items():
        out.append({
            "name": name,
            "description": wf.get("description", ""),
            "trigger": wf.get("trigger", {}) or {},
            "step_count": len(wf.get("steps", [])),
        })
    return out


def _interpolate(value: Any, step_results: list[dict]) -> Any:
    """Replace {{ steps.N.field }} templates in strings (recursively)."""
    if isinstance(value, str):
        def _sub(m: re.Match) -> str:
            idx, field = int(m.group(1)), m.group(2)
            if 0 <= idx < len(step_results):
                return str(step_results[idx].get(field, ""))
            return ""
        return _TEMPLATE_RE.sub(_sub, value)
    if isinstance(value, list):
        return [_interpolate(v, step_results) for v in value]
    if isinstance(value, dict):
        return {k: _interpolate(v, step_results) for k, v in value.items()}
    return value


async def run_workflow(
    engine,
    name: str,
    *,
    path: Path | None = None,
) -> dict[str, Any]:
    """Execute one workflow by name. Returns a result dict.

    The dict has:
        workflow:  the name
        steps:     per-step result dicts (in order)
        ok:        True if no step errored or was refused
    """
    workflows = load_workflows(path)
    wf = workflows.get(name)
    if wf is None:
        return {
            "error": f"unknown workflow {name!r}",
            "available": sorted(workflows.keys()),
        }

    steps = wf.get("steps", [])
    step_results: list[dict[str, Any]] = []
    ok = True

    for i, step in enumerate(steps):
        if not isinstance(step, dict) or len(step) != 1:
            step_results.append({"error": f"step {i} malformed (expect single-key map)"})
            ok = False
            continue
        action_name, raw_args = next(iter(step.items()))
        args = _interpolate(raw_args or {}, step_results)
        if not isinstance(args, dict):
            args = {}

        # Capability gate — the action name IS the capability key
        if not is_allowed(action_name):
            approval_id = request_approval(
                action_name, args,
                reason=f"workflow {name!r} step {i}",
            )
            step_results.append({
                "action": action_name,
                "refused": f"{action_name} denied by policy",
                "approval_id": approval_id,
            })
            ok = False
            logger.info("workflow %s: step %d (%s) refused", name, i, action_name)
            continue

        handler = ACTION_REGISTRY.get(action_name)
        if handler is None:
            step_results.append({
                "action": action_name,
                "error": f"no handler registered for {action_name!r}",
            })
            ok = False
            continue

        try:
            result = await handler(engine, **args)
        except TypeError as exc:
            result = {"action": action_name, "error": f"bad args: {exc}"}
            ok = False
        except Exception as exc:
            logger.exception("workflow %s: step %d (%s) raised", name, i, action_name)
            result = {"action": action_name, "error": f"{type(exc).__name__}: {exc}"}
            ok = False
        else:
            result = {"action": action_name, **(result or {})}
            if "error" in result:
                ok = False
        step_results.append(result)

    return {
        "workflow": name,
        "description": wf.get("description", ""),
        "steps": step_results,
        "ok": ok,
    }
