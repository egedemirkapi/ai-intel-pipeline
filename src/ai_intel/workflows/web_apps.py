"""Web-first app registry.

Maps lowercased app names to canonical webapp URLs. Apps listed here are
opened in the browser by default when the user asks to "open <app>"; the
desktop version is only launched if the user explicitly asks for it.

No heavy imports — this module is a plain data lookup used at chat-tool
dispatch time.
"""
from __future__ import annotations

WEB_FIRST_APPS: dict[str, str] = {
    "spotify":  "https://open.spotify.com",
    "youtube":  "https://youtube.com",
    "gmail":    "https://mail.google.com",
    "whatsapp": "https://web.whatsapp.com",
    "discord":  "https://discord.com/app",
    "notion":   "https://www.notion.so",
    "chatgpt":  "https://chatgpt.com",
    "maps":     "https://maps.google.com",
    "calendar": "https://calendar.google.com",
}


def web_url_for(name: str) -> str | None:
    """Return the canonical webapp URL for *name*, or None if unknown.

    Matching is case-insensitive and strips surrounding whitespace so
    'Spotify', ' SPOTIFY ', and 'spotify' all resolve the same way.
    """
    return WEB_FIRST_APPS.get((name or "").strip().lower())
