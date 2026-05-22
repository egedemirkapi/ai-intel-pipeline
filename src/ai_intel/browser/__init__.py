"""ai_intel.browser — Playwright-over-CDP browser driver for Jarvis.

Public API
----------
BrowserSession
    High-level async driver.  Connect to the user's Edge, take snapshots,
    click / type / scroll / screenshot.

PageSnapshot, Element
    Data classes returned by ``snapshot()`` / ``build_snapshot()``.

build_snapshot
    Lower-level async function: given a Playwright ``Page``, return a
    ``(PageSnapshot, [handles])`` tuple.

launcher utilities
    ``ensure_edge_debuggable()`` — start/detect debuggable Edge.
    ``is_debuggable_browser_up()`` — lightweight health check.
    ``cdp_endpoint()`` — ``"http://127.0.0.1:9222"``.
    ``DEBUG_PORT`` — 9222.
"""
from __future__ import annotations

from ai_intel.browser.launcher import (
    DEBUG_PORT,
    cdp_endpoint,
    ensure_edge_debuggable,
    is_debuggable_browser_up,
)
from ai_intel.browser.observe import Element, PageSnapshot, build_snapshot
from ai_intel.browser.session import BrowserError, BrowserSession

__all__ = [
    # session
    "BrowserSession",
    "BrowserError",
    # observe
    "PageSnapshot",
    "Element",
    "build_snapshot",
    # launcher
    "ensure_edge_debuggable",
    "is_debuggable_browser_up",
    "cdp_endpoint",
    "DEBUG_PORT",
]
