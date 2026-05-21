"""Trigger resolution — which workflow(s) a clap, hotkey, button or
spoken phrase should fire.

A workflow opts into a trigger via its ``trigger`` block (see
``persist.py``). The voice tray and the Brain ask this module which
workflows to run for an incoming event, so the event→workflow mapping
lives in exactly one place.
"""
from __future__ import annotations

import re
from pathlib import Path

from ai_intel.workflows.engine import load_workflows

_WORD_RE = re.compile(r"[a-z0-9]+")


def workflows_with_trigger(kind: str, path: Path | None = None) -> list[str]:
    """Return the names of workflows whose ``trigger.<kind>`` is set.

    ``kind`` is one of ``button``, ``clap``, ``hotkey``, ``voice``, ``on_app``.
    """
    out: list[str] = []
    for name, wf in load_workflows(path).items():
        trigger = wf.get("trigger") or {}
        if kind == "button" and trigger.get("button"):
            out.append(name)
        elif kind == "clap" and trigger.get("clap"):
            out.append(name)
        elif kind == "hotkey" and trigger.get("hotkey"):
            out.append(name)
        elif kind == "voice" and trigger.get("voice_phrases"):
            out.append(name)
        elif kind == "on_app" and trigger.get("on_app"):
            out.append(name)
    return out


def hotkey_map(path: Path | None = None) -> dict[str, str]:
    """Return ``{workflow_name: hotkey_string}`` for every hotkey workflow."""
    out: dict[str, str] = {}
    for name, wf in load_workflows(path).items():
        hotkey = (wf.get("trigger") or {}).get("hotkey")
        if hotkey:
            out[name] = hotkey
    return out


def workflows_with_schedule(path: Path | None = None) -> list[tuple[str, str]]:
    """Return ``[(workflow_name, cron_string), ...]`` for every workflow
    whose ``trigger.schedule`` is set. The always-on daemon reads this to
    register a cron job per scheduled workflow.
    """
    out: list[tuple[str, str]] = []
    for name, wf in load_workflows(path).items():
        cron = (wf.get("trigger") or {}).get("schedule")
        if isinstance(cron, str) and cron.strip():
            out.append((name, cron.strip()))
    return out


def _normalize(text: str) -> str:
    """Lowercase, keep only words, collapse whitespace."""
    return " ".join(_WORD_RE.findall((text or "").lower()))


def match_app(
    process: str | None, title: str | None, path: Path | None = None,
) -> list[str]:
    """Return workflow names whose ``trigger.on_app`` matches the app.

    ``on_app`` is a string or list of strings; a needle matches if it is
    a case-insensitive substring of the process name OR the window title
    (so "code", "Visual Studio Code", "cursor" all work).
    """
    hay = f"{process or ''} {title or ''}".lower()
    if not hay.strip():
        return []
    out: list[str] = []
    for name, wf in load_workflows(path).items():
        on_app = (wf.get("trigger") or {}).get("on_app")
        if not on_app:
            continue
        needles = [on_app] if isinstance(on_app, str) else on_app
        if any(isinstance(n, str) and n.strip() and n.lower() in hay for n in needles):
            out.append(name)
    return out


def match_voice(transcript: str, path: Path | None = None) -> str | None:
    """Return the workflow whose ``voice_phrases`` best-match ``transcript``.

    A phrase matches if its normalized form is a substring of the
    normalized transcript. When several match, the longest phrase wins
    (most specific).
    """
    norm = _normalize(transcript)
    if not norm:
        return None
    best_name: str | None = None
    best_len = 0
    for name, wf in load_workflows(path).items():
        for phrase in (wf.get("trigger") or {}).get("voice_phrases") or []:
            np = _normalize(phrase)
            if np and np in norm and len(np) > best_len:
                best_len = len(np)
                best_name = name
    return best_name
