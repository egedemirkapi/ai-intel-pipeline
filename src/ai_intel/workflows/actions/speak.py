"""Action: speak a line aloud.

Pushes text onto the Brain's speak queue; the voice tray polls that
queue and reads it via TTS. Lets a workflow *talk* — e.g. an ``on_app``
routine that says "Opening your dev setup" when you launch the IDE.

Only reaches the voice tray when the workflow runs inside the Brain
process (the normal path — /workflow, /trigger/*, /context/app).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def action_speak(engine, *, text: str = "") -> dict:
    """Queue ``text`` for the voice tray to speak."""
    from ai_intel.brain.speak import get_speak_queue

    queued = get_speak_queue().push(text, kind="workflow")
    if not queued:
        return {"spoke": False, "summary": "(nothing to say)"}
    return {"spoke": True, "summary": f"said: {text[:80]}"}
