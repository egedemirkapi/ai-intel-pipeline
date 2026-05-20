"""Jarvis voice tray — main entry point.

Run:  python -m voice.jarvis_voice

A Windows system-tray app. Always listening (locally) for:
    "Hey Jarvis"  → record → transcribe → ask the Brain → speak reply
    two claps     → fire the clap_default workflow

Heavy STT / chat / TTS work runs on a worker thread so the audio
callback is never blocked.

Requires the deps in voice/requirements.txt (installed separately
from the core project). If they're missing, the app prints a clear
install hint and exits.
"""
from __future__ import annotations

import logging
import queue
import sys
import threading
from datetime import datetime
from pathlib import Path

import httpx
import numpy as np
import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("jarvis_voice")

CONFIG_PATH = Path(__file__).parent / "config.yaml"


def _load_config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


class JarvisVoice:
    """Owns the mic stream, detectors, worker thread, and tray icon."""

    def __init__(self, config: dict) -> None:
        self.cfg = config
        self.brain_url = config["brain"]["base_url"].rstrip("/")
        self.clap_workflow = config["brain"]["clap_workflow"]

        # Heavy components — built in start() so import errors surface cleanly.
        self.mic = None
        self.wake = None
        self.clap = None
        self.stt = None
        self.tts = None
        self.hotkeys = None
        self.speak_poller = None
        self.context_poller = None

        # Worker thread for the slow STT→chat→TTS pipeline.
        self._work: queue.Queue = queue.Queue()
        self._worker = threading.Thread(
            target=self._worker_loop, daemon=True, name="jarvis-worker",
        )
        self._chat_history: list = []

    # ─── Lifecycle ──────────────────────────────────────────────────

    def start(self) -> None:
        """Bring the tray up. Every subsystem is isolated — one failing
        (no mic, no model, missing dep) degrades that feature only and
        is logged; the tray still starts. Each stage logs so a hang is
        visible in the terminal."""
        from voice.audio import MicStream
        from voice.clap import ClapDetector
        from voice.stt import Transcriber
        from voice.tts import Speaker
        from voice.wake import WakeWordDetector

        ac = self.cfg["audio"]

        # ── microphone ───────────────────────────────────────────────
        logger.info("voice: opening microphone ...")
        try:
            self.mic = MicStream(
                sample_rate=ac["sample_rate"],
                block_ms=ac["block_ms"],
                input_device=ac["input_device"],
            )
        except Exception as exc:
            logger.error("voice: microphone unavailable — wake/clap disabled: %s", exc)
            self.mic = None

        # ── speech-to-text ──────────────────────────────────────────
        logger.info("voice: loading speech-to-text model (this can take a few seconds) ...")
        sc = self.cfg["stt"]
        try:
            self.stt = Transcriber(
                model_size=sc["model_size"],
                language=sc["language"],
                compute_type=sc["compute_type"],
            )
            logger.info("voice: speech-to-text ready")
        except Exception as exc:
            logger.error("voice: STT unavailable — spoken commands disabled: %s", exc)
            self.stt = None

        # ── text-to-speech ──────────────────────────────────────────
        logger.info("voice: starting text-to-speech ...")
        tc = self.cfg["tts"]
        # Resolve a relative Piper model path against the voice/ directory
        # so it works regardless of the process's working directory.
        piper_path = tc.get("piper_voice_path", "")
        if piper_path and not Path(piper_path).is_absolute():
            piper_path = str(Path(__file__).parent / piper_path)
        try:
            self.tts = Speaker(
                engine=tc["engine"], rate=tc["rate"], piper_voice_path=piper_path,
                on_state=self._post_voice_state,
            )
        except Exception as exc:
            logger.error("voice: TTS failed to start: %s", exc)
            self.tts = None

        # ── wake word ('Hey Jarvis') ─────────────────────────────────
        if self.mic is not None:
            logger.info("voice: initializing wake word ...")
            wc = self.cfg["wake"]
            try:
                self.wake = WakeWordDetector(
                    self._on_utterance,
                    model=wc["model"], threshold=wc["threshold"],
                    sample_rate=ac["sample_rate"],
                    silence_ms=wc["silence_ms"],
                    max_utterance_s=wc["max_utterance_s"],
                    on_wake=lambda: self._post_voice_state("listening"),
                )
                self.mic.add_listener(self.wake.feed)
                logger.info("voice: wake word ready")
            except Exception as exc:
                logger.error("voice: wake word unavailable: %s", exc)
                self.wake = None

        # ── two-clap detector ───────────────────────────────────────
        cc = self.cfg["clap"]
        if self.mic is not None and cc.get("enabled", True):
            try:
                self.clap = ClapDetector(
                    self._on_two_claps,
                    rms_threshold=cc["rms_threshold"],
                    min_gap_ms=cc["min_gap_ms"],
                    max_gap_ms=cc["max_gap_ms"],
                    cooldown_s=cc["cooldown_s"],
                )
                self.mic.add_listener(self.clap.feed)
                logger.info("voice: two-clap detector ready")
            except Exception as exc:
                logger.error("voice: clap detector unavailable: %s", exc)

        # ── global hotkeys ──────────────────────────────────────────
        try:
            from voice.hotkeys import HotkeyBinder
            self.hotkeys = HotkeyBinder(self.brain_url, self._on_hotkey)
            self.hotkeys.start()
        except Exception as exc:
            logger.error("voice: hotkeys unavailable: %s", exc)

        # ── proactive speech poller ─────────────────────────────────
        speak_cfg = self.cfg.get("speak", {})
        if speak_cfg.get("poll_enabled", True):
            try:
                from voice.speakpoller import SpeakPoller
                self.speak_poller = SpeakPoller(
                    self.brain_url, self._on_speak,
                    interval_s=speak_cfg.get("poll_interval_s", 4.0),
                )
                self.speak_poller.start()
            except Exception as exc:
                logger.error("voice: speak poller unavailable: %s", exc)

        # ── context-awareness poller ────────────────────────────────
        ctx_cfg = self.cfg.get("context", {})
        if ctx_cfg.get("enabled", True):
            try:
                from voice.contextpoller import ContextPoller
                self.context_poller = ContextPoller(
                    self.brain_url,
                    interval_s=ctx_cfg.get("poll_interval_s", 1.5),
                )
                self.context_poller.start()
            except Exception as exc:
                logger.error("voice: context poller unavailable: %s", exc)

        # ── go ──────────────────────────────────────────────────────
        self._worker.start()
        if self.mic is not None:
            self.mic.start()
        logger.info(
            "Jarvis voice tray ready — say 'Hey Jarvis', clap twice, or use a hotkey."
        )

    def stop(self) -> None:
        if self.mic:
            self.mic.stop()
        if self.tts:
            self.tts.close()
        if self.hotkeys:
            self.hotkeys.stop()
        if self.speak_poller:
            self.speak_poller.stop()
        if self.context_poller:
            self.context_poller.stop()
        self._work.put(None)  # sentinel to end the worker

    # ─── Detector callbacks (run on the mic-dispatch thread) ────────

    def _on_utterance(self, audio: np.ndarray) -> None:
        """Wake word fired + utterance captured — hand off to worker."""
        self._work.put(("utterance", audio))

    def _on_two_claps(self) -> None:
        """Two-clap gesture — hand off to worker."""
        self._work.put(("clap", None))

    def _on_hotkey(self, workflow_name: str) -> None:
        """Global hotkey pressed — hand off to worker."""
        self._work.put(("workflow", workflow_name))

    def _on_speak(self, text: str, kind: str = "manual") -> None:
        """The Brain queued something for Jarvis to say — hand to worker."""
        self._work.put(("speak", text))

    # ─── Worker thread ──────────────────────────────────────────────

    def _worker_loop(self) -> None:
        while True:
            job = self._work.get()
            if job is None:
                return
            kind, payload = job
            try:
                if kind == "utterance":
                    self._handle_utterance(payload)
                elif kind == "clap":
                    self._handle_clap()
                elif kind == "workflow":
                    self._handle_workflow(payload)
                elif kind == "speak":
                    self._handle_speak(payload)
            except Exception as exc:  # pragma: no cover
                logger.exception("worker job %s failed: %s", kind, exc)

    def _handle_utterance(self, audio: np.ndarray) -> None:
        if self.stt is None:
            logger.warning("utterance ignored — speech-to-text is unavailable")
            return
        self._post_voice_state("thinking")
        text = self.stt.transcribe(audio, sample_rate=self.cfg["audio"]["sample_rate"])
        if not text:
            logger.info("empty transcription — skipping")
            self._post_voice_state("idle")
            return
        logger.info("you said: %s", text)
        # A spoken phrase may match a workflow's voice_phrases — try that
        # first; only fall through to conversational chat if nothing matched.
        if self._try_voice_trigger(text):
            return
        reply = self._ask_brain(text)
        if reply:
            self.tts.speak(reply)

    def _try_voice_trigger(self, text: str) -> bool:
        """POST the transcript to /trigger/voice. Returns True if it fired
        a workflow (so the caller should NOT also send it to chat)."""
        try:
            r = httpx.post(
                f"{self.brain_url}/trigger/voice",
                json={"transcript": text},
                timeout=60.0,
            )
            r.raise_for_status()
            data = r.json()
        except Exception as exc:
            logger.debug("voice-trigger check failed: %s", exc)
            return False
        if not data.get("matched"):
            return False
        wf = (data.get("workflow") or "").replace("_", " ")
        ok = (data.get("result") or {}).get("ok")
        logger.info("voice phrase → workflow %r", wf)
        self.tts.speak(f"Running {wf}." if ok else f"{wf} ran with some issues.")
        return True

    def _handle_clap(self) -> None:
        logger.info("two-clap → /trigger/clap")
        self._post_voice_state("thinking")
        fired: list = []
        try:
            r = httpx.post(f"{self.brain_url}/trigger/clap", timeout=60.0)
            r.raise_for_status()
            fired = r.json().get("fired") or []
        except Exception as exc:
            logger.warning("clap trigger failed: %s", exc)
            self.tts.speak("Sorry, that failed.")
            return
        # The clap is also the "welcome" gesture — read the briefing aloud.
        if self.cfg.get("clap", {}).get("speak_brief", True):
            spoken = self._fetch_brief_spoken()
            if spoken:
                self.tts.speak(spoken)
                return
        self.tts.speak("Done." if fired else "No clap routine is set up.")

    def _fetch_brief_spoken(self) -> str:
        """GET /brief and return its spoken summary (empty string on error)."""
        try:
            r = httpx.get(f"{self.brain_url}/brief", timeout=60.0)
            r.raise_for_status()
            return r.json().get("spoken", "")
        except Exception as exc:
            logger.debug("brief fetch failed: %s", exc)
            return ""

    def _handle_workflow(self, name: str) -> None:
        logger.info("hotkey → firing workflow %r", name)
        try:
            r = httpx.post(f"{self.brain_url}/workflow/{name}", timeout=60.0)
            r.raise_for_status()
        except Exception as exc:
            logger.warning("hotkey workflow %s failed: %s", name, exc)

    def _is_quiet_now(self) -> bool:
        """True if the current local hour falls in configured quiet hours."""
        qh = (self.cfg.get("speak") or {}).get("quiet_hours") or {}
        start, end = qh.get("start"), qh.get("end")
        if start is None or end is None:
            return False
        hour = datetime.now().hour
        if start <= end:
            return start <= hour < end
        return hour >= start or hour < end  # window wraps midnight

    def _handle_speak(self, text: str) -> None:
        """Speak a Brain-queued utterance — suppressed during quiet hours."""
        if self._is_quiet_now():
            logger.info("quiet hours — suppressing proactive speech")
            return
        logger.info("speaking (proactive): %s", text[:80])
        self.tts.speak(text)

    def _post_voice_state(self, state: str) -> None:
        """Report Jarvis's voice state to the Brain so the dashboard orb
        animates (listening / thinking / speaking / idle). Fire-and-forget."""
        try:
            httpx.post(
                f"{self.brain_url}/voice/state",
                json={"state": state},
                timeout=5.0,
            )
        except Exception:
            pass

    def _ask_brain(self, message: str) -> str:
        try:
            r = httpx.post(
                f"{self.brain_url}/chat",
                json={"message": message, "history": self._chat_history},
                timeout=90.0,
            )
            r.raise_for_status()
            data = r.json()
            self._chat_history = data.get("history", [])
            return data.get("reply", "")
        except httpx.ConnectError:
            return "I can't reach the Brain — is it running?"
        except Exception as exc:
            logger.warning("chat failed: %s", exc)
            return "Something went wrong talking to the Brain."


def _make_tray_icon(app, jarvis: JarvisVoice):
    """Build the system-tray icon + menu. Returns the QSystemTrayIcon."""
    from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
    from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

    # Draw a simple cyan dot icon — no icon file dependency.
    pix = QPixmap(64, 64)
    pix.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(34, 211, 238))  # cyan
    painter.setPen(QColor(34, 211, 238))
    painter.drawEllipse(12, 12, 40, 40)
    painter.end()

    tray = QSystemTrayIcon(QIcon(pix))
    tray.setToolTip("Jarvis — listening")

    menu = QMenu()
    status = QAction("Jarvis: listening")
    status.setEnabled(False)
    menu.addAction(status)
    menu.addSeparator()
    quit_action = QAction("Quit Jarvis")

    def _quit():
        jarvis.stop()
        app.quit()

    quit_action.triggered.connect(_quit)
    menu.addAction(quit_action)
    tray.setContextMenu(menu)
    tray.show()
    return tray


def main() -> int:
    try:
        from PyQt6.QtWidgets import QApplication
    except ImportError:
        print(
            "Missing voice dependencies. Install them with:\n"
            "  .\\.venv\\Scripts\\python.exe -m pip install -r voice/requirements.txt",
            file=sys.stderr,
        )
        return 1

    try:
        from ai_intel.single_instance import acquire_single_instance
    except ImportError:
        acquire_single_instance = None  # ai_intel not importable — skip the guard

    if acquire_single_instance and not acquire_single_instance("jarvis-voice-tray"):
        print(
            "Jarvis voice tray is already running — not starting a second copy.",
            file=sys.stderr,
        )
        return 0

    config = _load_config()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # tray app — no main window

    jarvis = JarvisVoice(config)
    try:
        jarvis.start()
    except ImportError as exc:
        print(
            f"Missing voice dependency: {exc}\n"
            f"Install: .\\.venv\\Scripts\\python.exe -m pip install -r voice/requirements.txt",
            file=sys.stderr,
        )
        return 1

    _tray = _make_tray_icon(app, jarvis)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
