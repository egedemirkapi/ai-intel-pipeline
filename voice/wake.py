"""Wake-word detector + utterance capture.

Uses openWakeWord's pretrained "hey_jarvis" model — no training needed.
The detector consumes mic frames; when "Hey Jarvis" scores above the
threshold it captures the following speech (until a silence gap) and
hands the raw audio to a callback for transcription.

openWakeWord expects 16 kHz mono int16 in 80 ms chunks (1280 samples).
The MicStream gives us float32; we convert per frame.
"""
from __future__ import annotations

import logging
import time
from typing import Callable

import numpy as np

logger = logging.getLogger(__name__)

# openWakeWord wants 16 kHz; 1280 samples = 80 ms per inference chunk.
_CHUNK = 1280


class WakeWordDetector:
    """Detect 'Hey Jarvis', then capture the spoken request after it."""

    def __init__(
        self,
        on_utterance: Callable[[np.ndarray], None],
        *,
        model: str = "hey_jarvis",
        threshold: float = 0.5,
        sample_rate: int = 16000,
        silence_ms: int = 800,
        max_utterance_s: int = 12,
        on_wake: Callable[[], None] | None = None,
    ) -> None:
        self.on_utterance = on_utterance
        self.on_wake = on_wake  # fired the instant the wake word triggers
        self.threshold = threshold
        self.sample_rate = sample_rate
        self.silence_samples = int(sample_rate * silence_ms / 1000)
        self.max_utterance_samples = sample_rate * max_utterance_s

        # Lazy import — openWakeWord is a heavy optional dep.
        from openwakeword.model import Model
        import openwakeword.utils

        # openWakeWord ships no model weights in the wheel. Fetch them on
        # first use; this is idempotent (skips files already on disk, so no
        # network on later runs) and pulls both .onnx and .tflite variants.
        # Guarded: a network failure here must not hang tray startup — if
        # the models are already cached, Model() below still loads fine.
        try:
            openwakeword.utils.download_models(model_names=[model])
        except Exception as exc:
            logger.warning(
                "wake: model download failed (using cached models if present): %s",
                exc,
            )

        # Force the ONNX backend. onnxruntime is our declared dependency and
        # has Windows wheels; tflite_runtime (openWakeWord's default) has no
        # Windows wheels, so the default "tflite" framework cannot load here.
        self._oww = Model(wakeword_models=[model], inference_framework="onnx")

        self._buf = np.zeros(0, dtype=np.float32)   # accumulates to _CHUNK
        self._capturing = False
        self._utterance: list[np.ndarray] = []
        self._silence_run = 0
        self._capture_started = 0.0

    def feed(self, frame: np.ndarray) -> None:
        if self._capturing:
            self._capture(frame)
            return

        # Accumulate to 1280-sample chunks for openWakeWord inference.
        self._buf = np.concatenate([self._buf, frame])
        while len(self._buf) >= _CHUNK:
            chunk = self._buf[:_CHUNK]
            self._buf = self._buf[_CHUNK:]
            pcm16 = (np.clip(chunk, -1.0, 1.0) * 32767).astype(np.int16)
            scores = self._oww.predict(pcm16)
            if any(s >= self.threshold for s in scores.values()):
                logger.info("wake word detected — capturing utterance")
                self._start_capture()
                break

    def _start_capture(self) -> None:
        self._capturing = True
        self._utterance = []
        self._silence_run = 0
        self._capture_started = time.monotonic()
        self._buf = np.zeros(0, dtype=np.float32)
        if self.on_wake:
            try:
                self.on_wake()
            except Exception:
                pass

    def _capture(self, frame: np.ndarray) -> None:
        self._utterance.append(frame)
        rms = float(np.sqrt(np.mean(np.square(frame)))) if frame.size else 0.0

        # Silence accounting — ends the utterance after a quiet gap.
        if rms < 0.015:
            self._silence_run += len(frame)
        else:
            self._silence_run = 0

        total = sum(len(f) for f in self._utterance)
        too_long = total >= self.max_utterance_samples
        enough_silence = (
            self._silence_run >= self.silence_samples
            and total > self.sample_rate // 2  # at least 0.5s of something
        )
        if enough_silence or too_long:
            self._finish_capture()

    def _finish_capture(self) -> None:
        self._capturing = False
        audio = (
            np.concatenate(self._utterance)
            if self._utterance else np.zeros(0, dtype=np.float32)
        )
        self._utterance = []
        # openWakeWord keeps internal state — reset so the next detection
        # isn't biased by this utterance's audio.
        try:
            self._oww.reset()
        except Exception:
            pass
        if audio.size > self.sample_rate // 4:  # ignore <0.25s noise
            self.on_utterance(audio)
        else:
            logger.info("captured utterance too short — ignoring")
