"""Action: open a set of URLs in the browser.

Used by the clap_default workflow to set up study tabs. On Windows we
shell out to the default browser via ``os.startfile`` (or ``start``),
which opens each URL in a new tab of the running browser.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import webbrowser

logger = logging.getLogger(__name__)


async def action_tabs_open_set(engine, *, urls: list[str] | None = None) -> dict:
    """Open each URL in ``urls`` in the default browser.

    Args:
        urls: list of URLs to open. Each opens in a new tab.

    Returns a dict with how many opened + any that failed.
    """
    urls = urls or []
    if not urls:
        return {"opened": 0, "note": "no urls provided"}

    opened = 0
    failed: list[str] = []
    for url in urls:
        url = str(url).strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            failed.append(url)
            continue
        try:
            if sys.platform == "win32":
                # `start` opens in the default browser without blocking.
                # Empty first arg is the window title `start` expects.
                subprocess.Popen(
                    ["cmd", "/c", "start", "", url],
                    shell=False,
                )
            else:
                webbrowser.open_new_tab(url)
            opened += 1
        except Exception as exc:
            logger.warning("tabs.open_set: failed to open %s: %s", url, exc)
            failed.append(url)

    return {
        "opened": opened,
        "failed": failed,
        "summary": f"opened {opened}/{len(urls)} tabs",
    }
