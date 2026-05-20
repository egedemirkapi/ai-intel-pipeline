# Jarvis Voice Tray

An always-listening Windows system-tray helper. Two triggers:

- **"Hey Jarvis"** — wake word → records your question → transcribes
  it locally → asks the Brain → speaks the reply.
- **Two claps** — fires the `clap_default` workflow (opens your study
  tabs by default).

Everything audio-related runs **locally**. The only thing that leaves
the machine is the final transcript text — and that goes only to the
Brain on `127.0.0.1`.

## Install

The voice deps are heavy (~400MB: CTranslate2, onnxruntime) and kept
separate from the core project. Install them into the project venv:

```powershell
.\.venv\Scripts\python.exe -m pip install -r voice\requirements.txt
```

First run downloads two models automatically:
- openWakeWord's pretrained `hey_jarvis` model (~few MB)
- faster-whisper `small` (~500MB) — cached under `~/.cache`

## Run

The Brain must be running first:

```powershell
.\.venv\Scripts\python.exe -m ai_intel.jarvis brain serve
```

Then the voice tray:

```powershell
.\.venv\Scripts\python.exe -m voice.jarvis_voice
```

A cyan dot appears in your system tray. Say **"Hey Jarvis, what's the
fleet doing?"** or **clap twice**.

## Start automatically at login

```powershell
voice\install_startup.bat
```

This adds a shortcut to your Startup folder (uses `pythonw.exe` so no
console window appears). Remove it by deleting `JarvisVoice.lnk` from
the folder you reach by pasting `shell:startup` into Explorer.

## Tuning (voice/config.yaml)

- `wake.threshold` — raise toward 1.0 if "Hey Jarvis" false-triggers.
- `clap.rms_threshold` — raise if normal sounds trigger claps; lower if
  your claps aren't detected. Room-dependent.
- `stt.model_size` — `base` is faster but rougher; `medium` is much
  more accurate but ~4-5s latency on CPU.
- `tts.engine` — `pyttsx3` (default, local Windows voices) or `piper`
  (set `piper_voice_path` to a downloaded Piper voice model).

## Privacy

- Wake-word detection, clap detection, and speech-to-text all run on
  your CPU. No audio is uploaded anywhere.
- TTS uses Windows' built-in voices (`pyttsx3`) — also fully local.
  We deliberately do NOT use a cloud TTS.
- The transcript goes only to the local Brain. The Brain's LLM call
  prefers your Max-plan OAuth bridge when reachable.
