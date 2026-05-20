"""One-time download of a Piper neural voice model for Jarvis TTS.

Run once:

    python scripts/setup_piper.py

Downloads the ``en_GB-alan-medium`` voice — a calm British male voice,
fitting for Jarvis — into ``voice/models/`` (~63 MB). After this the
voice tray speaks with a natural neural voice instead of robotic SAPI.
``voice/config.yaml`` already points ``tts.piper_voice_path`` here.
"""
from __future__ import annotations

import sys
from pathlib import Path

import httpx

VOICE = "en_GB-alan-medium"
BASE = (
    "https://huggingface.co/rhasspy/piper-voices/resolve/main"
    "/en/en_GB/alan/medium"
)
DEST = Path("voice") / "models"

FILES = {
    f"{VOICE}.onnx": f"{BASE}/{VOICE}.onnx",
    f"{VOICE}.onnx.json": f"{BASE}/{VOICE}.onnx.json",
}


def main() -> int:
    DEST.mkdir(parents=True, exist_ok=True)
    for fname, url in FILES.items():
        target = DEST / fname
        if target.exists() and target.stat().st_size > 0:
            print(f"{fname} already present — skipping")
            continue
        print(f"downloading {fname} ...")
        try:
            with httpx.stream("GET", url, follow_redirects=True, timeout=180.0) as r:
                r.raise_for_status()
                with target.open("wb") as f:
                    for chunk in r.iter_bytes(chunk_size=65536):
                        f.write(chunk)
        except Exception as exc:
            print(f"ERROR downloading {fname}: {exc}", file=sys.stderr)
            return 1
        print(f"  saved {target}  ({target.stat().st_size // 1024} KB)")

    print("\nPiper voice ready — Jarvis will speak with a natural voice.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
