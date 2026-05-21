"""Voice self-test — measures YOUR mic, speaker, and claps.

Run:

    python -m voice.diagnose

It runs three checks and prints exactly what it finds — no guessing:

  [1] MIC     — is the microphone actually capturing audio?
  [2] SPEAKER — Jarvis says a test line; you confirm you heard it.
  [3] CLAP    — you clap a few times, then talk for a few seconds. It
                measures how a clap differs in SHAPE from your speech
                and writes the right thresholds into config, so talking
                never false-fires the clap detector.

Paste the WHOLE output back. Whatever is broken will be visible in it.
"""
from __future__ import annotations

import io
import re
import statistics
import time
import wave
from pathlib import Path

import numpy as np
import yaml

CONFIG = Path(__file__).parent / "config.yaml"


def _bar(rms: float, width: int = 36) -> str:
    n = max(0, min(width, int(rms * width * 2.4)))
    return "#" * n + "-" * (width - n)


def _list_devices(kind: str) -> None:
    try:
        import sounddevice as sd
        key = "max_input_channels" if kind == "input" else "max_output_channels"
        for i, d in enumerate(sd.query_devices()):
            if d.get(key, 0) > 0:
                print(f"        [{i}] {d['name']}")
    except Exception as exc:
        print(f"        (could not list devices: {exc})")


# ─── [1] microphone ──────────────────────────────────────────────────


def check_mic(ac: dict) -> bool:
    print("\n[1/3] MICROPHONE — listening 4s. Tap the mic or say 'hello'.\n")
    from voice.audio import MicStream

    levels: list[float] = []

    def on_frame(frame: np.ndarray) -> None:
        rms = float(np.sqrt(np.mean(np.square(frame)))) if frame.size else 0.0
        levels.append(rms)
        print(f"\r  level {rms:6.3f} [{_bar(rms)}]", end="", flush=True)

    try:
        mic = MicStream(
            sample_rate=ac["sample_rate"], block_ms=ac["block_ms"],
            input_device=ac["input_device"],
        )
        mic.add_listener(on_frame)
        mic.start()
        time.sleep(4)
        mic.stop()
    except Exception as exc:
        print(f"\n  RESULT: ** mic stream failed to start ** — {exc}")
        return False

    print()
    if not levels:
        print("  RESULT: ** no audio frames ** — the mic produced nothing.")
        return False
    peak, avg = max(levels), sum(levels) / len(levels)
    print(f"  ambient avg = {avg:.4f}   peak = {peak:.4f}")
    if peak < 0.012:
        print("  RESULT: ** MIC IS SILENT ** — it is not picking up sound.")
        print("        Fix: check Windows mic permission, or the wrong input")
        print("        device is selected. Available input devices:")
        _list_devices("input")
        return False
    print("  RESULT: mic is capturing audio. OK.")
    return True


# ─── [2] speaker ─────────────────────────────────────────────────────


def check_speaker(cfg: dict) -> bool:
    print("\n[2/3] SPEAKER — Jarvis will speak a test line now.\n")
    tc = cfg.get("tts", {})
    piper_path = tc.get("piper_voice_path", "")
    if piper_path and not Path(piper_path).is_absolute():
        piper_path = str(Path(__file__).parent / piper_path)
    line = (
        "Jarvis voice test. If you can hear this sentence, "
        "your speaker is working."
    )
    engine = "none"
    try:
        if tc.get("engine") == "piper" and piper_path and Path(piper_path).exists():
            import sounddevice as sd
            from piper import PiperVoice

            cfgp = piper_path + ".json"
            voice = PiperVoice.load(
                piper_path, config_path=cfgp if Path(cfgp).exists() else None,
            )
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                voice.synthesize_wav(line, wf)
            buf.seek(0)
            with wave.open(buf, "rb") as wf:
                frames = wf.readframes(wf.getnframes())
                rate = wf.getframerate()
            audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
            sd.play(audio, rate)
            sd.wait()
            engine = "piper (neural)"
        else:
            import pyttsx3
            eng = pyttsx3.init()
            eng.say(line)
            eng.runAndWait()
            engine = "pyttsx3 (Windows SAPI)"
    except Exception as exc:
        print(f"  RESULT: ** TTS FAILED ** — {exc}")
        return False

    print(f"  spoke the test line via: {engine}")
    print("  >>> Did you HEAR it?")
    print("      If NOT, the wrong audio OUTPUT device is the default.")
    print("      Available output devices:")
    _list_devices("output")
    print("  RESULT: TTS produced audio — confirm with your ears.")
    return True


# ─── [3] clap-vs-speech calibration ──────────────────────────────────


def _record(ac: dict, seconds: float, label: str) -> list[tuple[float, float]]:
    """Run the mic for ``seconds``; return (rms, peak) for every frame."""
    from voice.audio import MicStream

    frames: list[tuple[float, float]] = []

    def on_frame(frame: np.ndarray) -> None:
        if not frame.size:
            return
        rms = float(np.sqrt(np.mean(np.square(frame))))
        peak = float(np.max(np.abs(frame)))
        frames.append((rms, peak))
        print(f"\r  {label} level {rms:6.3f} [{_bar(rms)}]", end="", flush=True)

    try:
        mic = MicStream(
            sample_rate=ac["sample_rate"], block_ms=ac["block_ms"],
            input_device=ac["input_device"],
        )
        mic.add_listener(on_frame)
        mic.start()
        time.sleep(seconds)
        mic.stop()
    except Exception as exc:
        print(f"\n  ** mic failed: {exc} **")
    print()
    return frames


def _transients(frames: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Pick short, loud impulses out of a recording. Returns the
    (peak, crest-factor) of each — that is what a clap looks like."""
    floor = 0.10
    out: list[tuple[float, float]] = []
    above = False
    max_peak = max_crest = 0.0
    for rms, peak in frames:
        crest = peak / rms if rms > 1e-6 else 0.0
        if peak >= floor:
            if not above:
                above, max_peak, max_crest = True, peak, crest
            else:
                max_peak, max_crest = max(max_peak, peak), max(max_crest, crest)
        elif above:
            above = False
            out.append((max_peak, max_crest))
    if above:
        out.append((max_peak, max_crest))
    return out


def check_clap(cfg: dict, ac: dict) -> None:
    print("\n[3/3] CLAP vs SPEECH — calibrating how a clap differs from talking.")

    print("\n  Part A — CLAP FIRMLY 6-8 times, about 1 second apart. (16s)\n")
    claps = _transients(_record(ac, 16, "clap"))

    print("\n  Part B — now TALK normally for 8 seconds (say anything). (8s)\n")
    speech_frames = _record(ac, 8, "talk")

    if not claps:
        print("\n  RESULT: ** heard NO claps ** — they aren't reaching the mic")
        print("        (or [1/3] already showed the mic is off).")
        return

    clap_peaks = sorted((p for p, _ in claps), reverse=True)[:10]
    clap_crests = sorted((c for _, c in claps), reverse=True)[:10]
    clap_peak = statistics.median(clap_peaks)
    clap_crest = statistics.median(clap_crests)

    # The spikiest speech frame is the bar crest_min must clear so that
    # talking never registers as a clap.
    speech_crests = [p / r for r, p in speech_frames if r >= 0.02 and p > 0]
    speech_crest = max(speech_crests) if speech_crests else 0.0

    print(f"\n  your claps : peak ~{clap_peak:.2f}   crest factor ~{clap_crest:.1f}")
    print(f"  your speech: spikiest crest factor ~{speech_crest:.1f}")

    peak_min = round(max(0.10, min(0.60, clap_peak * 0.55)), 2)
    if clap_crest > speech_crest + 1.5:
        crest_min = round((clap_crest + speech_crest) / 2, 1)
        print("\n  Good separation — a clap is clearly spikier than your speech,")
        print("  so talking will not false-trigger it.")
    else:
        crest_min = round(speech_crest + 1.5, 1)
        print("\n  ** Tight separation ** — your claps are not much spikier than")
        print("     your speech. Clap closer to the mic / more firmly and re-run.")
        print("     Setting the threshold just above your speech for now.")
    print(f"\n  recommended  clap.peak_min  = {peak_min}")
    print(f"  recommended  clap.crest_min = {crest_min}")
    _write_clap_calibration(peak_min, crest_min)


def _write_clap_calibration(peak_min: float, crest_min: float) -> None:
    try:
        text = CONFIG.read_text(encoding="utf-8")
        new = re.sub(r"(\bpeak_min:\s*)[\d.]+", rf"\g<1>{peak_min}", text, count=1)
        new = re.sub(r"(\bcrest_min:\s*)[\d.]+", rf"\g<1>{crest_min}", new, count=1)
        if new == text:
            print("  (could not find peak_min/crest_min lines — set them manually)")
            return
        CONFIG.write_text(new, encoding="utf-8")
        print(f"  -> wrote clap.peak_min = {peak_min}, "
              f"clap.crest_min = {crest_min} into voice/config.yaml")
        print("  -> RESTART the voice tray for it to take effect.")
    except Exception as exc:
        print(f"  (could not write config: {exc})")


def main() -> int:
    print("=" * 60)
    print(" JARVIS VOICE SELF-TEST")
    print("=" * 60)
    try:
        cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"could not read voice/config.yaml: {exc}")
        return 1
    ac = cfg.get("audio", {"sample_rate": 16000, "block_ms": 80, "input_device": None})

    mic_ok = check_mic(ac)
    check_speaker(cfg)
    if mic_ok:
        check_clap(cfg, ac)
    else:
        print("\n[3/3] CLAP — skipped (fix the microphone first).")

    print("\n" + "=" * 60)
    print(" Done. Paste this whole output back.")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
