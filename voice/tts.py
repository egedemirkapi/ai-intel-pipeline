"""Text-to-speech.

Two engines:
    pyttsx3 (default) — Windows SAPI5 voices. Fully local, zero
                        download, works offline. Good enough for a
                        personal assistant.
    piper             — higher-quality neural voices; needs a Piper
                        voice model file. Opt-in via config.yaml.

We deliberately do NOT use a cloud TTS (e.g. Edge TTS) — that would
send the reply text to a remote server, breaking the max-privacy
posture. Both engines here keep everything on the machine.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class Speaker:
    """Speak text aloud. Engine chosen at construction."""

    def __init__(
        self,
        *,
        engine: str = "pyttsx3",
        rate: int = 185,
        piper_voice_path: str = "",
    ) -> None:
        self.engine_name = engine
        self.rate = rate
        self.piper_voice_path = piper_voice_path
        self._pyttsx = None
        self._piper = None
        if engine == "pyttsx3":
            self._init_pyttsx3()
        elif engine == "piper":
            self._init_piper()
        else:
            logger.warning("unknown TTS engine %r — falling back to pyttsx3", engine)
            self.engine_name = "pyttsx3"
            self._init_pyttsx3()

    def _init_pyttsx3(self) -> None:
        import pyttsx3
        self._pyttsx = pyttsx3.init()
        self._pyttsx.setProperty("rate", self.rate)

    def _init_piper(self) -> None:
        if not self.piper_voice_path:
            logger.warning("piper selected but no voice path — using pyttsx3")
            self.engine_name = "pyttsx3"
            self._init_pyttsx3()
            return
        from piper.voice import PiperVoice
        self._piper = PiperVoice.load(self.piper_voice_path)

    def speak(self, text: str) -> None:
        """Speak ``text`` aloud. Blocks until done."""
        text = (text or "").strip()
        if not text:
            return
        if self.engine_name == "pyttsx3":
            self._pyttsx.say(text)
            self._pyttsx.runAndWait()
        elif self.engine_name == "piper":
            self._speak_piper(text)

    def _speak_piper(self, text: str) -> None:
        import io
        import wave

        import sounddevice as sd

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            self._piper.synthesize(text, wf)
        buf.seek(0)
        with wave.open(buf, "rb") as wf:
            frames = wf.readframes(wf.getnframes())
            rate = wf.getframerate()
        import numpy as np
        audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
        sd.play(audio, rate)
        sd.wait()
