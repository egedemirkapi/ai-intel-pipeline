"""Action: show a desktop notification (toast).

On Windows 10/11 uses the ``windows-toasts`` / winrt path if available,
otherwise falls back to a console log. Notifications are low-risk so
``notify`` is allow-by-default in tools.toml.

A workflow step can set ``body`` directly OR ``body_from`` referencing
a prior step's output — the engine interpolates ``{{ steps.N.field }}``
before this handler is called, so by the time we run, body is plain text.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _try_windows_toast(title: str, body: str) -> bool:
    """Attempt a native Windows toast. Returns True on success."""
    try:
        from windows_toasts import Toast, WindowsToaster
        toaster = WindowsToaster("Jarvis")
        toast = Toast()
        toast.text_fields = [title, body]
        toaster.show_toast(toast)
        return True
    except Exception:
        return False


async def action_notify(
    engine,
    *,
    title: str = "Jarvis",
    body: str = "",
    body_from: str | None = None,
) -> dict:
    """Show a desktop toast.

    Args:
        title: notification title.
        body: notification body text.
        body_from: ignored here — the engine resolves {{steps...}}
                   templates into ``body`` before calling this action.
                   Kept in the signature so a YAML step using body_from
                   doesn't raise a TypeError.
    """
    text = body or body_from or ""
    shown_native = _try_windows_toast(title, text)
    if not shown_native:
        # Fallback: log it so the workflow still "notifies" somewhere
        logger.info("NOTIFY [%s] %s", title, text)
    return {
        "shown": True,
        "native_toast": shown_native,
        "title": title,
        "body": text,
        "summary": f"notified: {title}",
    }
