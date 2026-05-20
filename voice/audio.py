"""Microphone plumbing — a shared rolling-buffer mic stream.

Both the wake-word detector and the clap detector consume the SAME
mic stream (you can't open the default input device twice). This
module owns the sounddevice InputStream and fans frames out to
registered listeners.

A "listener" is just a callable that receives each mono int16/float32
block. The wake detector and clap detector each register one.
"""
from __future__ import annotations

import logging
import queue
import threading
from typing import Callable

import numpy as np

logger = logging.getLogger(__name__)

FrameListener = Callable[[np.ndarray], None]


class MicStream:
    """Single mic input stream with multi-listener fan-out.

    Frames are float32 mono in [-1, 1]. Listeners run on a dedicated
    dispatch thread so a slow listener can't stall the audio callback.
    """

    def __init__(
        self,
        *,
        sample_rate: int = 16000,
        block_ms: int = 80,
        input_device: int | None = None,
    ) -> None:
        self.sample_rate = sample_rate
        self.block_size = int(sample_rate * block_ms / 1000)
        self.input_device = input_device
        self._listeners: list[FrameListener] = []
        self._q: queue.Queue[np.ndarray] = queue.Queue(maxsize=64)
        self._stream = None
        self._dispatch_thread: threading.Thread | None = None
        self._running = False

    def add_listener(self, fn: FrameListener) -> None:
        self._listeners.append(fn)

    def _audio_callback(self, indata, frames, time_info, status):  # noqa: ANN001
        if status:
            logger.debug("mic status: %s", status)
        # indata is (frames, channels) float32; collapse to mono
        mono = indata[:, 0].copy() if indata.ndim > 1 else indata.copy()
        try:
            self._q.put_nowait(mono)
        except queue.Full:
            pass  # drop a frame rather than block the audio thread

    def _dispatch_loop(self) -> None:
        while self._running:
            try:
                frame = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            for fn in self._listeners:
                try:
                    fn(frame)
                except Exception as exc:  # pragma: no cover
                    logger.warning("mic listener error: %s", exc)

    def start(self) -> None:
        import sounddevice as sd

        self._running = True
        self._dispatch_thread = threading.Thread(
            target=self._dispatch_loop, daemon=True, name="mic-dispatch",
        )
        self._dispatch_thread.start()
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            blocksize=self.block_size,
            channels=1,
            dtype="float32",
            device=self.input_device,
            callback=self._audio_callback,
        )
        self._stream.start()
        logger.info(
            "mic stream started: %d Hz, block=%d samples",
            self.sample_rate, self.block_size,
        )

    def stop(self) -> None:
        self._running = False
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        logger.info("mic stream stopped")
