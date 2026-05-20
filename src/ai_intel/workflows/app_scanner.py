"""Installed-app scanner + per-app launch allowlist.

Two jobs:

1. **Scan** — enumerate the apps installed on this Windows machine via
   PowerShell ``Get-StartApps`` (covers both classic Win32 apps and
   Store/UWP apps; each has a ``Name`` and an ``AppID``). The result is
   cached to ``~/.jarvis/apps_cache.json`` because the scan takes a
   second or two.

2. **Allowlist** — ``apps.launch`` is powerful, so it only launches apps
   the user has explicitly added to ``~/.jarvis/apps_allowed.json`` (the
   dashboard's app picker writes here). Anything else is refused into the
   approval queue. The allowlist *is* the per-app consent gate.
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CACHE_PATH = Path.home() / ".jarvis" / "apps_cache.json"
ALLOWLIST_PATH = Path.home() / ".jarvis" / "apps_allowed.json"


# ─── Scan ────────────────────────────────────────────────────────────


def _on_windows() -> bool:
    """Isolated so tests can simulate a Windows host."""
    return sys.platform == "win32"


def _powershell_get_startapps() -> str:
    """Run ``Get-StartApps`` and return its JSON text. Windows only.

    Isolated into its own function so tests can monkeypatch it.

    Output is captured as raw bytes and decoded as UTF-8 — ``text=True``
    would decode with the console code page (cp1252), which crashes on
    the non-Latin characters in some app names. We also force PowerShell
    itself to emit UTF-8.
    """
    proc = subprocess.run(
        [
            "powershell", "-NoProfile", "-NonInteractive", "-Command",
            "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
            "Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress",
        ],
        capture_output=True,  # bytes — decode ourselves to avoid cp1252
        timeout=30,
    )
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Get-StartApps failed: {err}")
    return proc.stdout.decode("utf-8", errors="replace").strip()


def scan_installed_apps() -> list[dict[str, str]]:
    """Enumerate installed apps as ``[{name, app_id}]``, sorted by name.

    Returns an empty list (not an error) on a non-Windows host or if the
    scan fails — callers fall back to the KNOWN_APPS map.
    """
    if not _on_windows():
        return []
    try:
        raw = _powershell_get_startapps()
    except Exception as exc:  # subprocess / timeout / non-zero exit
        logger.warning("app scan failed: %s", exc)
        return []
    return _parse_startapps(raw)


def _parse_startapps(raw: str) -> list[dict[str, str]]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("app scan: could not parse Get-StartApps JSON: %s", exc)
        return []
    # ConvertTo-Json yields a bare object for a single app, a list otherwise.
    if isinstance(data, dict):
        data = [data]
    apps: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in data:
        if not isinstance(entry, dict):
            continue
        name = (entry.get("Name") or "").strip()
        app_id = (entry.get("AppID") or "").strip()
        if not name or not app_id or app_id in seen:
            continue
        seen.add(app_id)
        apps.append({"name": name, "app_id": app_id})
    apps.sort(key=lambda a: a["name"].lower())
    return apps


def list_installed_apps(
    *, refresh: bool = False, cache_path: Path | None = None
) -> list[dict[str, str]]:
    """Return installed apps, using the on-disk cache when present.

    ``refresh=True`` forces a fresh scan and rewrites the cache.
    """
    cp = cache_path or CACHE_PATH
    if not refresh and cp.exists():
        try:
            return json.loads(cp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass  # stale/corrupt cache — fall through to a fresh scan
    apps = scan_installed_apps()
    if apps:
        try:
            cp.parent.mkdir(parents=True, exist_ok=True)
            cp.write_text(json.dumps(apps, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.warning("could not write app cache: %s", exc)
    return apps


# ─── Allowlist ───────────────────────────────────────────────────────


def _read_allowlist(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"allowed": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"allowed": []}
    if not isinstance(data.get("allowed"), list):
        data["allowed"] = []
    return data


def _write_allowlist(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_allowlist(*, path: Path | None = None) -> list[dict[str, str]]:
    """Return the list of apps the user has approved for ``apps.launch``."""
    return _read_allowlist(path or ALLOWLIST_PATH)["allowed"]


def add_to_allowlist(
    app_id: str, name: str = "", *, path: Path | None = None
) -> dict[str, str]:
    """Add an app to the launch allowlist (idempotent on ``app_id``)."""
    if not app_id and not name:
        raise ValueError("add_to_allowlist needs an app_id or a name")
    p = path or ALLOWLIST_PATH
    data = _read_allowlist(p)
    key = (app_id or name).lower()
    for entry in data["allowed"]:
        if (entry.get("app_id") or entry.get("name", "")).lower() == key:
            return entry  # already allowed
    entry = {
        "app_id": app_id,
        "name": name,
        "added_at": datetime.now(timezone.utc).isoformat(),
    }
    data["allowed"].append(entry)
    _write_allowlist(p, data)
    return entry


def remove_from_allowlist(app_id: str, *, path: Path | None = None) -> bool:
    """Remove an app from the allowlist. Returns True if something was removed."""
    p = path or ALLOWLIST_PATH
    data = _read_allowlist(p)
    key = (app_id or "").lower()
    before = len(data["allowed"])
    data["allowed"] = [
        e for e in data["allowed"]
        if (e.get("app_id") or "").lower() != key and (e.get("name") or "").lower() != key
    ]
    if len(data["allowed"]) != before:
        _write_allowlist(p, data)
        return True
    return False


def is_app_allowed(
    *, app_id: str | None = None, name: str | None = None, path: Path | None = None
) -> bool:
    """True if an app matching ``app_id`` OR ``name`` is on the allowlist."""
    allowed = get_allowlist(path=path)
    aid = (app_id or "").lower()
    nm = (name or "").lower()
    for entry in allowed:
        e_id = (entry.get("app_id") or "").lower()
        e_nm = (entry.get("name") or "").lower()
        if aid and e_id and aid == e_id:
            return True
        if nm and e_nm and nm == e_nm:
            return True
    return False
