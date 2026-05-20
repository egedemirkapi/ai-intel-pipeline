"""Text-to-speech — runs on its own dedicated thread.

CRITICAL DESIGN: the TTS engine is created AND driven on ONE dedicated
thread. pyttsx3 is not thread-safe — its ``runAndWait()`` hangs forever
if called from a thread other than the one that init'd it. The old
design init'd the engine on the main thread but called ``speak()`` from
the voice tray's worker thread, so Jarvis silently never spoke.

Now ``Speaker`` owns a ``jarvis-tts`` thread: that thread initializes the
engine and is the only thread that ever touches it. ``speak()`` just
enqueues text — it is non-blocking; utterances play serially.

Engines (all local — nothing leaves the machine):
    piper   — neural voice; needs a voice model (scripts/setup_piper.py)
    pyttsx3 — Windows SAPI5; zero download; automatic fallback
"""
from __future__ import annotations

import logging
import os
import queue
import threading

logger = logging.getLogger(__name__)

_STOP = object()  # queue sentinel for shutdown


class Speaker:
    """Speak text aloud from a dedicated thread. ``speak()`` is non-blocking."""

    def __init__(
        self,
        *,
        engine: str = "piper",
        rate: int = 185,
        piper_voice_path: str = "",
        on_state=None,
    ) -> None:
        self._want_engine = engine
        self.rate = rate
        self.piper_voice_path = piper_voice_path
        # Optional callback(str): fired with "speaking" when an utterance
        # starts and "idle" when the queue drains — drives the dashboard orb.
        self._on_state = on_state

        self._engine: str | None = None  # resolved engine after init/fallback
        self._pyttsx = None
        self._piper = None

        self._q: queue.Queue = queue.Queue()
        self._ready = threading.Event()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="jarvis-tts",
        )
        self._thread.start()
        # Give engine init a moment so the first speak() isn't lost; if it
        # takes longer, speak() still queues and plays once ready.
        self._ready.wait(timeout=30)

    # ─── public API ─────────────────────────────────────────────────

    def speak(self, text: str) -> None:
        """Queue ``text`` to be spoken. Non-blocking — plays on the TTS thread."""
        text = (text or "").strip()
        if text:
            self._q.put(text)

    def close(self) -> None:
        self._q.put(_STOP)

    # ─── the dedicated TTS thread ───────────────────────────────────

    def _emit_state(self, state: str) -> None:
        if self._on_state:
            try:
                self._on_state(state)
            except Exception:
                pass

    def _run(self) -> None:
        self._init_engine()
        self._ready.set()
        speaking = False
        while True:
            item = self._q.get()
            if item is _STOP:
                return
            if not speaking:
                speaking = True
                self._emit_state("speaking")
            try:
                self._say(item)
            except Exception as exc:  # never let one bad utterance kill TTS
                logger.warning("TTS: speak failed: %s", exc)
            if self._q.empty():
                speaking = False
                self._emit_state("idle")

    def _init_engine(self) -> None:
        if self._want_engine == "piper" and self._init_piper():
            self._engine = "piper"
            logger.info("TTS: Piper neural voice ready")
            return
        if self._want_engine == "piper":
            logger.warning("TTS: Piper unavailable — falling back to Windows SAPI")
        if self._init_pyttsx3():
            self._engine = "pyttsx3"
            logger.info("TTS: Windows SAPI (pyttsx3) ready")
            return
        self._engine = None
        logger.error("TTS: no working speech engine — Jarvis cannot speak")

    def _init_piper(self) -> bool:
        path = self.piper_voice_path
        if not path or not os.path.exists(path):
            logger.warning(
                "TTS: Piper voice model not found at %r "
                "(run: python scripts/setup_piper.py)", path,
            )
            return False
        try:
            from piper import PiperVoice
            config = path + ".json" if os.path.exists(path + ".json") else None
            self._piper = PiperVoice.load(path, config_path=config)
            return True
        except Exception as exc:
            logger.warning("TTS: Piper init failed: %s", exc)
            return False

    def _init_pyttsx3(self) -> bool:
        try:
            import pyttsx3
            self._pyttsx = pyttsx3.init()
            self._pyttsx.setProperty("rate", self.rate)
            return True
        except Exception as exc:
            logger.warning("TTS: pyttsx3 init failed: %s", exc)
            return False

    def _say(self, text: str) -> None:
        if self._engine == "piper":
            self._say_piper(text)
        elif self._engine == "pyttsx3":
            self._pyttsx.say(text)
            self._pyttsx.runAndWait()
        # else: no engine — drop silently (already logged at init)

    def _say_piper(self, text: str) -> None:
        import io
        import wave

        import numpy as np
        import sounddevice as sd

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            self._piper.synthesize_wav(text, wf)
        buf.seek(0)
        with wave.open(buf, "rb") as wf:
            frames = wf.readframes(wf.getnframes())
            rate = wf.getframerate()
        audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
        sd.play(audio, rate)
        sd.wait()
