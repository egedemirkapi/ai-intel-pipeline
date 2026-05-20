"""Action: launch a desktop application.

``apps.launch`` is the riskiest workflow action, so it is gated per-app:
the handler launches an app only if it is on the user's allowlist
(``~/.jarvis/apps_allowed.json``, managed by the dashboard's app picker).
Any app that is NOT allowlisted is refused and queued for approval — it
is never launched silently.

The capability layer (``tools.toml``) sets ``apps.launch = "allow"`` so
this handler runs at all; the *real* gate is the allowlist enforced
below. (A capability-level "deny" would stop the handler from ever
running, leaving no place to do the finer-grained per-app check.)

An app can be named two ways:
    app_id  — a Windows Start-menu AppID from the app scanner (preferred;
              launches via ``explorer.exe shell:AppsFolder\\<AppID>`` and
              works for both Win32 and Store apps)
    name    — a friendly name resolved via ``KNOWN_APPS`` or passed
              straight to the OS resolver (``start`` on Windows)
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import sys

from ai_intel.jarvis.permissions import request_approval
from ai_intel.workflows.app_scanner import is_app_allowed

logger = logging.getLogger(__name__)

# Friendly-name → executable. Extend as needed; unknown names fall
# through to the OS resolver.
KNOWN_APPS: dict[str, str] = {
    "cursor": "cursor",
    "code": "code",
    "vscode": "code",
    "notion": "notion",
    "chrome": "chrome",
    "spotify": "spotify",
    "terminal": "wt" if sys.platform == "win32" else "x-terminal-emulator",
}


async def action_apps_launch(
    engine, *, name: str | None = None, app_id: str | None = None
) -> dict:
    """Launch a desktop application.

    Args:
        name:   friendly app name (resolved via KNOWN_APPS or the OS).
        app_id: Windows Start-menu AppID from the app scanner.
    """
    if not name and not app_id:
        return {"error": "no app name or app_id provided"}

    # Per-app gate — only launch apps the user explicitly allowlisted.
    if not is_app_allowed(app_id=app_id, name=name):
        label = name or app_id
        approval_id = request_approval(
            "apps.launch",
            {"name": name, "app_id": app_id},
            reason="app is not on the launch allowlist — add it via the dashboard app picker",
        )
        logger.info("apps.launch: %r not allowlisted — queued approval %s", label, approval_id)
        return {
            "refused": f"app {label!r} is not on the launch allowlist",
            "approval_id": approval_id,
        }

    try:
        if sys.platform == "win32":
            if app_id:
                # shell:AppsFolder handles both Win32 and Store apps.
                subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{app_id}"])
                target = name or app_id
            else:
                exe = KNOWN_APPS.get(name.lower().strip(), name.strip())
                subprocess.Popen(["cmd", "/c", "start", "", exe], shell=False)
                target = exe
        else:
            if not name:
                return {"error": "app_id launch is Windows-only; provide a name"}
            exe = KNOWN_APPS.get(name.lower().strip(), name.strip())
            resolved = shutil.which(exe)
            if resolved is None:
                return {"error": f"app {exe!r} not found on PATH"}
            subprocess.Popen([resolved])
            target = exe
    except Exception as exc:
        logger.warning("apps.launch: failed to launch %s: %s", name or app_id, exc)
        return {"error": f"failed to launch {name or app_id!r}: {exc}"}

    return {"launched": target, "summary": f"launched {target}"}
