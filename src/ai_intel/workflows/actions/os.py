"""Action: OS-level desktop control.

Currently exposes ``os.set_wallpaper`` for Windows via the Win32
``SystemParametersInfoW`` API. Falls back gracefully on non-Windows.

Default policy in ``tools.toml`` is **deny** — system changes are
opt-in: the user enables ``os.set_wallpaper`` once via the existing
approval queue. The handler refuses missing files and unsupported
formats up-front so the API call only fires on a known-good input.

This module is the natural home for future OS-level actions (volume,
notifications-beyond-toast, lock screen, etc.). Keeping them gated
per-action in tools.toml means each new system-touching capability
opts in independently.
"""
from __future__ import annotations

import logging
import platform
from pathlib import Path

logger = logging.getLogger(__name__)

# Formats SystemParametersInfoW reliably accepts. Older Windows reject
# WebP / some TIFF variants; if the user hits that we surface the
# SetSysParam return code, not a generic error.
_SUPPORTED_EXT = {".bmp", ".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}


async def action_os_set_wallpaper(engine, *, path: str) -> dict:
    """Set the desktop wallpaper to the image at ``path`` (Windows only).

    Uses ``SystemParametersInfoW(SPI_SETDESKWALLPAPER=20, 0, path,
    SPIF_UPDATEINIFILE | SPIF_SENDCHANGE)`` so the change applies
    immediately and persists across reboots.

    Returns ``{"set": True, "path", "summary"}`` on success; an
    ``{"error": ...}`` dict otherwise.
    """
    if not path:
        return {"error": "no path given"}

    p = Path(path).expanduser()
    if not p.is_absolute():
        p = p.resolve()
    if not p.exists():
        return {"error": f"file not found: {p}"}
    if p.suffix.lower() not in _SUPPORTED_EXT:
        return {
            "error": (
                f"unsupported image format: {p.suffix} "
                f"(supported: {', '.join(sorted(_SUPPORTED_EXT))})"
            )
        }
    if platform.system() != "Windows":
        return {
            "error": (
                f"os.set_wallpaper is currently Windows-only "
                f"(detected: {platform.system()})"
            )
        }

    try:
        import ctypes

        # SPI_SETDESKWALLPAPER = 20
        # SPIF_UPDATEINIFILE | SPIF_SENDCHANGE = 1 | 2 = 3
        # (persist to the user profile AND broadcast WM_SETTINGCHANGE
        # so Explorer + other listeners pick it up immediately).
        result = ctypes.windll.user32.SystemParametersInfoW(
            20, 0, str(p), 3,
        )
        if not result:
            return {
                "error": (
                    "SystemParametersInfoW returned 0 — wallpaper not set. "
                    "Check that the file is readable and the format is "
                    "supported by this Windows version."
                )
            }
        logger.info("os.set_wallpaper: %s", p)
        return {
            "set": True,
            "path": str(p),
            "summary": f"Desktop wallpaper set to {p.name}.",
        }
    except Exception as exc:  # noqa: BLE001 — surface as a step error
        logger.warning("os.set_wallpaper failed: %s", exc)
        return {"error": f"os.set_wallpaper failed: {type(exc).__name__}: {exc}"}
