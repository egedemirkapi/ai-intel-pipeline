"""Foreground-window detection — what app the user is looking at.

Pure ctypes against user32 for the window handle + title; the process
name comes from psutil when available (falls back to title-only). This
is the "eyes" for Sprint 4 context awareness: the voice tray polls
``get_foreground_window()`` and tells the Brain when the user switches
apps, so ``on_app`` workflows can fire.
"""
from __future__ import annotations

import logging
import sys

logger = logging.getLogger(__name__)


def _on_windows() -> bool:
    return sys.platform == "win32"


def _process_name(pid: int) -> str | None:
    """Best-effort process name for a pid. None if psutil is unavailable."""
    if not pid:
        return None
    try:
        import psutil
        return psutil.Process(pid).name()
    except Exception:
        return None


def get_foreground_window() -> dict | None:
    """Return ``{title, process, pid}`` for the focused window, or None.

    Returns None on a non-Windows host or if there is no foreground
    window. ``process`` is None when psutil isn't installed.
    """
    if not _on_windows():
        return None
    import ctypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None

    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    title = buf.value or ""

    pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

    return {
        "title": title,
        "process": _process_name(pid.value),
        "pid": int(pid.value),
    }


def context_key(ctx: dict | None) -> str:
    """A stable key for 'which app' — used to detect a real app switch.

    Keys on the process name (browser tab changes shift the title but
    not the process); falls back to the title's first word when psutil
    isn't available.
    """
    if not ctx:
        return ""
    process = (ctx.get("process") or "").strip().lower()
    if process:
        return process
    title = (ctx.get("title") or "").strip().lower()
    return title.split()[0] if title else ""
