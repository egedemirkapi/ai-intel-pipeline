"""launcher.py — ensure a debuggable Microsoft Edge is available via CDP.

Usage::

    from ai_intel.browser.launcher import ensure_edge_debuggable, cdp_endpoint

    if ensure_edge_debuggable():
        # Playwright can now connect with chromium.connect_over_cdp(cdp_endpoint())
        ...
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

DEBUG_PORT: int = 9222

_EDGE_CANDIDATE_PATHS: list[str] = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def cdp_endpoint() -> str:
    """Return the CDP HTTP endpoint for the debuggable browser."""
    return f"http://127.0.0.1:{DEBUG_PORT}"


def is_debuggable_browser_up() -> bool:
    """Return True if a CDP-ready browser is already listening on DEBUG_PORT."""
    try:
        with urllib.request.urlopen(
            f"{cdp_endpoint()}/json/version", timeout=2
        ) as resp:
            return resp.status == 200
    except Exception:
        return False


def _find_edge_exe() -> Path | None:
    """Locate msedge.exe from standard install paths or PATH."""
    for path_str in _EDGE_CANDIDATE_PATHS:
        p = Path(path_str)
        if p.exists():
            return p
    # Fallback: check PATH (handles custom installs or non-Windows mocking)
    import shutil

    found = shutil.which("msedge") or shutil.which("msedge.exe")
    if found:
        return Path(found)
    return None


def ensure_edge_debuggable() -> bool:
    """Ensure a debuggable Edge instance is listening on DEBUG_PORT.

    * If one is already up — return True immediately.
    * Else attempt to launch Edge with ``--remote-debugging-port=9222`` bound
      to the user's *real* profile so existing logins / cookies are available.
    * If the profile directory is locked by a running non-debuggable Edge the
      launch will typically fail or refuse to open the profile; a clear message
      is logged and False is returned — the caller should surface "close your
      other Edge windows and retry".
    * On non-Windows platforms this function degrades gracefully: if a browser
      is already up it returns True, otherwise False.

    Returns
    -------
    bool
        True when a debuggable browser is confirmed on DEBUG_PORT.
    """
    if is_debuggable_browser_up():
        logger.debug("Debuggable browser already up on port %d.", DEBUG_PORT)
        return True

    if sys.platform != "win32":
        logger.warning(
            "Not on Windows — cannot launch Edge automatically. "
            "Start Edge manually with --remote-debugging-port=%d.",
            DEBUG_PORT,
        )
        return False

    edge_exe = _find_edge_exe()
    if edge_exe is None:
        logger.error(
            "Microsoft Edge not found. Install Edge or add msedge.exe to PATH."
        )
        return False

    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if not local_app_data:
        logger.error("LOCALAPPDATA env var not set — cannot locate Edge profile.")
        return False

    user_data_dir = Path(local_app_data) / "Microsoft" / "Edge" / "User Data"

    cmd: list[str] = [
        str(edge_exe),
        f"--remote-debugging-port={DEBUG_PORT}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
    ]

    logger.info("Launching Edge with CDP: %s", " ".join(cmd))
    try:
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    except OSError as exc:
        logger.error("Failed to launch Edge: %s", exc)
        return False

    # Poll /json/version for up to 8 seconds
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        if is_debuggable_browser_up():
            logger.info("Edge CDP ready on port %d.", DEBUG_PORT)
            return True
        time.sleep(0.4)

    # Timed out — most likely the profile is locked by a running Edge that
    # refused to accept remote-debugging because it was already started
    # without that flag.
    logger.error(
        "Edge did not become debuggable within 8 s. "
        "If Edge is already running without --remote-debugging-port, "
        "close your other Edge windows and retry."
    )
    return False
