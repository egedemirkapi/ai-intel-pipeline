"""Speech-to-text via faster-whisper — fully local, CPU-friendly.

The model loads once at startup (~600MB RAM for "small"). Transcription
of a 5-second clip takes ~2s on a modern laptop CPU with int8 compute.

No audio ever leaves the machine — faster-whisper runs the Whisper
model locally via CTranslate2.
"""
from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)


class Transcriber:
    """Wraps a faster-whisper model. Call ``transcribe(audio)``."""

    def __init__(
        self,
        *,
        model_size: str = "small",
        language: str = "en",
        compute_type: str = "int8",
    ) -> None:
        self.language = language
        # Lazy import — faster-whisper is a heavy optional dep.
        from faster_whisper import WhisperModel
        logger.info("loading faster-whisper '%s' (%s) ...", model_size, compute_type)
        self._model = WhisperModel(
            model_size, device="cpu", compute_type=compute_type,
        )
        logger.info("faster-whisper ready")

    def transcribe(self, audio: np.ndarray, *, sample_rate: int = 16000) -> str:
        """Transcribe float32 mono audio to text.

        faster-whisper accepts a float32 numpy array directly at 16 kHz.
        """
        if audio.size == 0:
            return ""
        audio = audio.astype(np.float32)
        segments, _info = self._model.transcribe(
            audio,
            language=self.language,
            beam_size=1,            # greedy — fast; quality fine for commands
            vad_filter=True,        # drop leading/trailing silence
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        logger.info("transcribed: %r", text[:120])
        return text
