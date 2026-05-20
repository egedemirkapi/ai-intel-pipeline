"""Global hotkey binder for the voice tray.

Polls the Brain's ``GET /workflows`` for workflows that declare a
``trigger.hotkey`` and binds each combo with the ``keyboard`` library.
Re-polls on an interval so hotkeys edited in the dashboard take effect
without restarting the tray.

If the ``keyboard`` package isn't installed the binder degrades quietly
— the other three triggers (clap, voice, dashboard button) still work.
"""
from __future__ import annotations

import logging
import threading

import httpx

logger = logging.getLogger(__name__)


class HotkeyBinder:
    """Binds workflow hotkeys and keeps them in sync with the Brain."""

    def __init__(self, brain_url: str, on_fire, *, refresh_s: float = 30.0) -> None:
        self.brain_url = brain_url.rstrip("/")
        self.on_fire = on_fire            # callable(workflow_name) -> None
        self.refresh_s = refresh_s
        self._kb = None                   # the `keyboard` module, if available
        self._handles: dict[str, object] = {}   # combo -> keyboard handle
        self._bound: dict[str, str] = {}         # combo -> workflow name
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="jarvis-hotkeys",
        )

    def start(self) -> None:
        try:
            import keyboard  # type: ignore
        except Exception as exc:  # ImportError, or platform issues
            logger.warning(
                "global hotkeys disabled — `keyboard` unavailable (%s). "
                "Install voice/requirements.txt to enable them.", exc,
            )
            return
        self._kb = keyboard
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._unbind_all()

    # ─── internals ──────────────────────────────────────────────────

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._refresh()
            except Exception as exc:
                logger.debug("hotkey refresh failed: %s", exc)
            self._stop.wait(self.refresh_s)

    def _refresh(self) -> None:
        r = httpx.get(f"{self.brain_url}/workflows", timeout=10.0)
        r.raise_for_status()
        wanted: dict[str, str] = {}
        for wf in r.json():
            hotkey = (wf.get("trigger") or {}).get("hotkey")
            if hotkey:
                wanted[hotkey.strip().lower()] = wf["name"]
        if wanted == self._bound:
            return
        self._unbind_all()
        for combo, name in wanted.items():
            try:
                self._handles[combo] = self._kb.add_hotkey(
                    combo, self.on_fire, args=(name,),
                )
            except Exception as exc:
                logger.warning("could not bind hotkey %r → %s: %s", combo, name, exc)
        self._bound = wanted
        if wanted:
            logger.info(
                "hotkeys bound: %s",
                ", ".join(f"{c} → {n}" for c, n in wanted.items()),
            )

    def _unbind_all(self) -> None:
        if not self._kb:
            return
        for handle in self._handles.values():
            try:
                self._kb.remove_hotkey(handle)
            except (KeyError, ValueError):
                pass
        self._handles.clear()
