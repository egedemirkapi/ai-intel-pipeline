"""Context poller — watches the foreground app and reports switches.

Polls the OS for the focused window ~once a second; when the user
switches to a *different* app (the process changes — a browser tab
change doesn't count) it POSTs the new context to the Brain, which
fires any workflow with a matching ``on_app`` trigger.
"""
from __future__ import annotations

import logging
import threading

import httpx

from voice.windows_context import context_key, get_foreground_window

logger = logging.getLogger(__name__)


class ContextPoller:
    """Reports foreground-app switches to the Brain's /context/app."""

    def __init__(self, brain_url: str, *, interval_s: float = 1.5) -> None:
        self.brain_url = brain_url.rstrip("/")
        self.interval_s = interval_s
        self._last_key = ""
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="jarvis-context-poller",
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                ctx = get_foreground_window()
                key = context_key(ctx)
                if key and key != self._last_key:
                    self._last_key = key
                    self._report(ctx)
            except Exception as exc:
                logger.debug("context poll failed: %s", exc)
            self._stop.wait(self.interval_s)

    def _report(self, ctx: dict) -> None:
        try:
            httpx.post(
                f"{self.brain_url}/context/app",
                json={
                    "process": ctx.get("process") or "",
                    "title": ctx.get("title") or "",
                },
                timeout=10.0,
            )
            logger.info("context → %s", ctx.get("process") or ctx.get("title"))
        except Exception as exc:
            logger.debug("context report failed: %s", exc)
