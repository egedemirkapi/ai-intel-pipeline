"""Current foreground-app context — what the user is looking at now.

The voice tray watches the OS foreground window and POSTs changes to
``/context/app``, which updates this module-level singleton. The
``context.app`` chat tool reads it so Jarvis can answer "what am I
working on" and tailor its replies.
"""
from __future__ import annotations

import threading
import time
from typing import Any

_LOCK = threading.Lock()
_CURRENT: dict[str, Any] = {}


def set_current_context(process: str | None, title: str | None) -> None:
    """Record the app the user just switched to."""
    with _LOCK:
        _CURRENT.clear()
        _CURRENT.update({
            "process": (process or "").strip(),
            "title": (title or "").strip(),
            "since": time.time(),
        })


def get_current_context() -> dict[str, Any]:
    """Return the current context, or ``{}`` if nothing reported yet."""
    with _LOCK:
        return dict(_CURRENT)


def reset_context() -> None:
    """Test-only: clear the recorded context."""
    with _LOCK:
        _CURRENT.clear()
