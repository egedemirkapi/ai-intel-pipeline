"""Voice self-test — measures YOUR mic, speaker, and claps.

Run:

    python -m voice.diagnose

It runs three checks and prints exactly what it finds — no guessing:

  [1] MIC     — is the microphone actually capturing audio?
  [2] SPEAKER — Jarvis says a test line; you confirm you heard it.
  [3] CLAP    — you clap a few times; it measures how loud your claps
                really are and writes the right threshold into config.

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


# ─── [3] clap calibration ────────────────────────────────────────────


def check_clap(cfg: dict, ac: dict) -> None:
    print("\n[3/3] CLAP — listening 18s. CLAP FIRMLY 6-8 times, ~1s apart.\n")
    from voice.audio import MicStream

    floor = 0.05
    st = {"above": False, "peak": 0.0}
    transients: list[float] = []

    def on_frame(frame: np.ndarray) -> None:
        rms = float(np.sqrt(np.mean(np.square(frame)))) if frame.size else 0.0
        print(f"\r  level {rms:6.3f} [{_bar(rms)}]", end="", flush=True)
        if rms >= floor and not st["above"]:
            st["above"] = True
            st["peak"] = rms
        elif st["above"]:
            st["peak"] = max(st["peak"], rms)
            if rms < floor * 0.6:
                st["above"] = False
                transients.append(st["peak"])
                print(f"\r  >> sound detected — peak rms = {st['peak']:.3f}"
                      + " " * 24)

    try:
        mic = MicStream(
            sample_rate=ac["sample_rate"], block_ms=ac["block_ms"],
            input_device=ac["input_device"],
        )
        mic.add_listener(on_frame)
        mic.start()
        time.sleep(18)
        mic.stop()
    except Exception as exc:
        print(f"\n  RESULT: ** mic failed ** — {exc}")
        return

    print()
    if not transients:
        print("  RESULT: ** heard NO loud sounds ** — your claps are not")
        print("        reaching the mic (or [1/3] already showed the mic is off).")
        return

    transients.sort(reverse=True)
    claps = transients[:12]
    med = statistics.median(claps)
    rec = max(0.10, min(0.40, round(med * 0.6, 2)))
    cur = cfg.get("clap", {}).get("rms_threshold")
    print(f"  loudest sounds (rms): {', '.join(f'{t:.3f}' for t in claps)}")
    print(f"  median clap level: {med:.3f}")
    print(f"  current threshold in config: {cur}")
    if isinstance(cur, (int, float)) and cur > med:
        print(f"  ** FOUND IT — your claps (~{med:.2f}) are BELOW the threshold")
        print(f"     ({cur}); they never register. THIS is why nothing happens. **")
    print(f"  recommended clap.rms_threshold: {rec}")
    _write_threshold(rec)


def _write_threshold(rec: float) -> None:
    try:
        text = CONFIG.read_text(encoding="utf-8")
        new = re.sub(
            r"(\brms_threshold:\s*)[\d.]+", rf"\g<1>{rec}", text, count=1,
        )
        if new == text:
            print("  (could not find rms_threshold line — set it manually)")
            return
        CONFIG.write_text(new, encoding="utf-8")
        print(f"  -> wrote clap.rms_threshold = {rec} into voice/config.yaml")
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
