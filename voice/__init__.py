"""Jarvis voice tray — Windows-side always-listening helper.

Runs as a system-tray app, independent of the Brain. Two triggers:

    "Hey Jarvis"  — wake word (openWakeWord) → record → transcribe
                    (faster-whisper, local) → POST /chat → speak reply
    two claps     — amplitude detector → POST /workflow/clap_default

All audio capture + transcription happens locally. Nothing is uploaded
except the final transcript text to the local Brain (127.0.0.1:9999).

The heavy ML dependencies (faster-whisper, openWakeWord) are NOT in the
main project's pyproject.toml — install them separately via
``voice/requirements.txt`` so the core pipeline stays lean.
"""
