"""Workflow CRUD — read/write ``~/.jarvis/workflows.yaml``.

The engine (``engine.py``) only *reads* workflows. This module lets the
dashboard's routine editor *create, edit and delete* them, persisting to
the user file. Bundled defaults are never modified; saving a workflow
whose name matches a default writes a user-file override (the existing
"user wins" merge in ``load_workflows`` does the rest).

A workflow definition::

    description: <text>
    trigger:                       # all keys optional
      button: true                 # show a button on the dashboard
      clap: false                  # fire on a two-clap gesture
      hotkey: "ctrl+alt+s"          # global hotkey, or null
      voice_phrases: ["study setup"]
    steps:
      - <action.name>: { <arg>: <value> }
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from ai_intel.workflows.actions import ACTION_REGISTRY
from ai_intel.workflows.engine import (
    DEFAULTS_PATH,
    USER_WORKFLOWS_PATH,
    load_workflows,
)

_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
_VALID_TRIGGER_KEYS = {"button", "clap", "hotkey", "voice_phrases"}


class WorkflowError(ValueError):
    """Raised on a CRUD precondition failure (bad name, conflict, etc.)."""


# ─── Read ────────────────────────────────────────────────────────────


def _builtin_names() -> set[str]:
    if not DEFAULTS_PATH.exists():
        return set()
    data = yaml.safe_load(DEFAULTS_PATH.read_text(encoding="utf-8")) or {}
    return set((data.get("workflows") or {}).keys())


def _user_names(path: Path | None = None) -> set[str]:
    p = path or USER_WORKFLOWS_PATH
    if not p.exists():
        return set()
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return set((data.get("workflows") or {}).keys())


def get_workflow(name: str, path: Path | None = None) -> dict[str, Any] | None:
    """Return the effective (merged) definition for one workflow, or None."""
    return load_workflows(path).get(name)


def list_workflow_defs(path: Path | None = None) -> list[dict[str, Any]]:
    """Return every workflow as ``{name, description, trigger, step_count,
    is_builtin, is_overridden}``."""
    merged = load_workflows(path)
    builtin = _builtin_names()
    user = _user_names(path)
    out: list[dict[str, Any]] = []
    for name, wf in merged.items():
        out.append({
            "name": name,
            "description": wf.get("description", ""),
            "trigger": wf.get("trigger", {}) or {},
            "step_count": len(wf.get("steps", []) or []),
            "is_builtin": name in builtin,
            "is_overridden": name in builtin and name in user,
        })
    return out


# ─── Validate ────────────────────────────────────────────────────────


def validate_def(definition: Any) -> list[str]:
    """Return a list of human-readable errors. Empty list = valid."""
    errors: list[str] = []
    if not isinstance(definition, dict):
        return ["workflow definition must be a mapping"]

    desc = definition.get("description", "")
    if desc is not None and not isinstance(desc, str):
        errors.append("'description' must be text")

    trigger = definition.get("trigger")
    if trigger is not None:
        errors.extend(_validate_trigger(trigger))

    steps = definition.get("steps")
    if steps is None or not isinstance(steps, list) or not steps:
        errors.append("'steps' must be a non-empty list")
    else:
        known = set(ACTION_REGISTRY)
        for i, step in enumerate(steps):
            if not isinstance(step, dict) or len(step) != 1:
                errors.append(f"step {i}: must be a single {{action: args}} mapping")
                continue
            action, args = next(iter(step.items()))
            if action not in known:
                errors.append(
                    f"step {i}: unknown action {action!r} "
                    f"(known: {', '.join(sorted(known))})"
                )
            if args is not None and not isinstance(args, dict):
                errors.append(f"step {i}: args for {action!r} must be a mapping")
    return errors


def _validate_trigger(trigger: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(trigger, dict):
        return ["'trigger' must be a mapping"]
    for key in trigger:
        if key not in _VALID_TRIGGER_KEYS:
            errors.append(
                f"trigger: unknown key {key!r} "
                f"(valid: {', '.join(sorted(_VALID_TRIGGER_KEYS))})"
            )
    for key in ("button", "clap"):
        if key in trigger and not isinstance(trigger[key], bool):
            errors.append(f"trigger.{key} must be true or false")
    hotkey = trigger.get("hotkey")
    if hotkey is not None and not isinstance(hotkey, str):
        errors.append("trigger.hotkey must be a string like 'ctrl+alt+s' or null")
    phrases = trigger.get("voice_phrases")
    if phrases is not None:
        if not isinstance(phrases, list) or not all(isinstance(p, str) for p in phrases):
            errors.append("trigger.voice_phrases must be a list of strings")
    return errors


# ─── Write ───────────────────────────────────────────────────────────


def _load_user_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"workflows": {}}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if "workflows" not in data or not isinstance(data.get("workflows"), dict):
        data["workflows"] = {}
    return data


def _write_user_file(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# Jarvis user workflows — managed by the dashboard routine editor.\n"
        "# Hand edits are fine; a workflow here overrides a bundled default\n"
        "# of the same name.\n\n"
    )
    body = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False)
    path.write_text(header + body, encoding="utf-8")


def create_workflow(
    name: str, definition: dict[str, Any], *, path: Path | None = None
) -> dict[str, Any]:
    """Create a new workflow. Raises WorkflowError if the name is taken."""
    if not _NAME_RE.match(name or ""):
        raise WorkflowError(
            f"invalid name {name!r} — use letters, digits, '-' or '_' (1-64 chars)"
        )
    if name in load_workflows(path):
        raise WorkflowError(f"workflow {name!r} already exists — use update instead")
    errors = validate_def(definition)
    if errors:
        raise WorkflowError("; ".join(errors))
    p = path or USER_WORKFLOWS_PATH
    data = _load_user_file(p)
    data["workflows"][name] = definition
    _write_user_file(p, data)
    return get_workflow(name, path) or definition


def update_workflow(
    name: str, definition: dict[str, Any], *, path: Path | None = None
) -> dict[str, Any]:
    """Create or overwrite a workflow in the user file. Saving a name that
    matches a bundled default writes an override."""
    if not _NAME_RE.match(name or ""):
        raise WorkflowError(f"invalid name {name!r}")
    errors = validate_def(definition)
    if errors:
        raise WorkflowError("; ".join(errors))
    p = path or USER_WORKFLOWS_PATH
    data = _load_user_file(p)
    data["workflows"][name] = definition
    _write_user_file(p, data)
    return get_workflow(name, path) or definition


def delete_workflow(name: str, *, path: Path | None = None) -> None:
    """Remove a workflow from the user file.

    A user workflow is deleted outright. A user *override* of a builtin
    reverts to the builtin. A pure builtin cannot be deleted.
    """
    p = path or USER_WORKFLOWS_PATH
    in_user = name in _user_names(path)
    in_builtin = name in _builtin_names()
    if not in_user:
        if in_builtin:
            raise WorkflowError(
                f"{name!r} is a built-in workflow — it cannot be deleted"
            )
        raise WorkflowError(f"unknown workflow {name!r}")
    data = _load_user_file(p)
    data["workflows"].pop(name, None)
    _write_user_file(p, data)
