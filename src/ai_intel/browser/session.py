"""session.py — high-level async driver for an existing Chromium/Edge browser.

The session DETACHES (not closes) when ``close()`` is called, so the user's
browser window is never terminated by Jarvis.

Typical usage::

    async with BrowserSession() as session:
        await session.goto("https://example.com")
        snap = await session.snapshot()
        print(snap.to_prompt())
        await session.click(2)          # click element [2]
        await session.type_text(5, "hello world")
        png = await session.screenshot()
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

from ai_intel.browser.launcher import cdp_endpoint, ensure_edge_debuggable
from ai_intel.browser.observe import PageSnapshot, build_snapshot

logger = logging.getLogger(__name__)


class BrowserError(RuntimeError):
    """Raised when a browser action fails in a predictable, catchable way."""


class BrowserSession:
    """Async context-manager / manual-lifecycle driver for the user's browser.

    Connects over CDP to an existing Edge (or any Chromium) instance.
    The user's session, cookies, and logins are fully preserved.
    Calling ``close()`` only disconnects Playwright — it does NOT close the
    browser window.

    Attributes
    ----------
    page:
        The active Playwright ``Page``.
    """

    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        # Maps element index → Playwright ElementHandle
        self._element_handles: dict[int, Any] = {}

    # ── Lifecycle ───────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Connect to the user's debuggable Edge browser.

        Calls ``ensure_edge_debuggable()`` first; if no browser can be made
        available raises ``BrowserError``.

        After connecting, picks the first existing page or opens a blank one.
        """
        if not ensure_edge_debuggable():
            raise BrowserError(
                "Could not connect to a debuggable Edge browser. "
                "If Edge is already running without --remote-debugging-port, "
                "close your other Edge windows and retry."
            )

        try:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.connect_over_cdp(
                cdp_endpoint()
            )
        except Exception as exc:
            raise BrowserError(f"CDP connect failed: {exc}") from exc

        # Prefer the first existing context / page; fall back to creating one
        contexts = self._browser.contexts
        if contexts:
            self._context = contexts[0]
            pages = self._context.pages
            self._page = pages[0] if pages else await self._context.new_page()
        else:
            self._context = await self._browser.new_context()
            self._page = await self._context.new_page()

        logger.info(
            "BrowserSession connected. Active page: %s — %s",
            self._page.url,
            await self._page.title(),
        )

    async def close(self) -> None:
        """Disconnect Playwright from the browser WITHOUT closing Edge."""
        self._element_handles.clear()
        if self._browser is not None:
            try:
                # disconnect() detaches without terminating the browser process
                await self._browser.close()
            except Exception as exc:
                logger.debug("Browser.close() (detach) raised: %s", exc)
            self._browser = None
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception as exc:
                logger.debug("Playwright.stop() raised: %s", exc)
            self._playwright = None
        self._page = None
        self._context = None
        logger.debug("BrowserSession closed (browser still running).")

    async def __aenter__(self) -> "BrowserSession":
        await self.connect()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    # ── Page property ────────────────────────────────────────────────────────

    @property
    def page(self) -> Page:
        """The active Playwright ``Page``; raises if not connected."""
        if self._page is None:
            raise BrowserError("BrowserSession is not connected. Call connect() first.")
        return self._page

    # ── Navigation ───────────────────────────────────────────────────────────

    async def goto(self, url: str) -> None:
        """Navigate to *url*, waiting for the load event."""
        try:
            await self.page.goto(url, wait_until="load", timeout=30_000)
            logger.debug("goto %s", url)
        except Exception as exc:
            raise BrowserError(f"goto({url!r}) failed: {exc}") from exc

    # ── Observation ──────────────────────────────────────────────────────────

    async def snapshot(self) -> PageSnapshot:
        """Capture an LLM-friendly snapshot of the current page.

        Internally stores the element handles so ``click`` / ``type_text``
        can act on them by index.

        Returns
        -------
        PageSnapshot
            The snapshot; call ``.to_prompt()`` to get the text representation.
        """
        snap, handles = await build_snapshot(self.page)
        self._element_handles = {el.index: handles[i] for i, el in enumerate(snap.elements)}
        logger.debug("Snapshot captured: %d elements on %s", len(snap.elements), snap.url)
        return snap

    # ── Actions ──────────────────────────────────────────────────────────────

    def _get_handle(self, index: int) -> Any:
        """Retrieve the stored element handle for *index* or raise clearly."""
        handle = self._element_handles.get(index)
        if handle is None:
            known = sorted(self._element_handles.keys())
            raise BrowserError(
                f"No element at index {index}. "
                f"Known indices: {known}. "
                "Call snapshot() first, or the index may be stale."
            )
        return handle

    async def click(self, index: int) -> None:
        """Click the element at *index* from the last ``snapshot()``."""
        handle = self._get_handle(index)
        try:
            await handle.click(timeout=10_000)
            logger.debug("click(%d)", index)
        except Exception as exc:
            raise BrowserError(f"click({index}) failed: {exc}") from exc

    async def type_text(self, index: int, text: str) -> None:
        """Focus the element at *index* and type *text* into it."""
        handle = self._get_handle(index)
        try:
            await handle.click(timeout=5_000)
            await handle.fill(text)
            logger.debug("type_text(%d, %r)", index, text[:40])
        except Exception as exc:
            raise BrowserError(f"type_text({index}) failed: {exc}") from exc

    async def press(self, key: str) -> None:
        """Send a keyboard *key* to the active page (e.g. ``'Enter'``)."""
        try:
            await self.page.keyboard.press(key)
            logger.debug("press(%r)", key)
        except Exception as exc:
            raise BrowserError(f"press({key!r}) failed: {exc}") from exc

    async def scroll(self, dy: int) -> None:
        """Scroll the page vertically by *dy* pixels (positive = down)."""
        try:
            await self.page.mouse.wheel(0, dy)
            logger.debug("scroll(dy=%d)", dy)
        except Exception as exc:
            raise BrowserError(f"scroll({dy}) failed: {exc}") from exc

    # ── File operations ──────────────────────────────────────────────────────
    #
    # These let the navigator (or a journey) actually pull files off pages
    # like Google Classroom and push them into NotebookLM. ``download``
    # captures the file triggered by clicking an element; ``upload`` handles
    # both direct ``<input type="file">`` elements and click-to-open-picker
    # buttons via Playwright's expect_file_chooser fallback.

    async def download(
        self,
        index: int,
        save_dir: Path | str,
        *,
        timeout_ms: int = 30_000,
    ) -> Path:
        """Click the element at *index* and save the resulting download.

        Uses Playwright's ``expect_download`` context to capture the file
        triggered by the click. Saves into ``save_dir/`` with the
        browser-suggested filename (or a timestamped fallback if the
        download exposes no name). Returns the absolute path of the
        saved file so the journey orchestrator can pass it forward.

        Raises ``BrowserError`` on timeout / element-mismatch / I/O failure.
        """
        handle = self._get_handle(index)
        save_path = Path(save_dir)
        save_path.mkdir(parents=True, exist_ok=True)
        try:
            async with self.page.expect_download(timeout=timeout_ms) as info:
                await handle.click(timeout=10_000)
            download = await info.value
            suggested = (
                download.suggested_filename
                or f"download-{int(time.time())}.bin"
            )
            target = (save_path / suggested).resolve()
            await download.save_as(target)
            logger.debug("download(%d) → %s", index, target)
            return target
        except Exception as exc:
            raise BrowserError(f"download({index}) failed: {exc}") from exc

    async def upload(
        self,
        index: int,
        file_paths: list[Path | str] | Path | str,
        *,
        timeout_ms: int = 10_000,
    ) -> None:
        """Upload files via the element at *index*.

        Two paths, tried in order:

        1. **Direct** — element is an ``<input type="file">``. Calls
           ``handle.set_input_files(paths)``. This is the fast happy path
           for plain file inputs.
        2. **Picker fallback** — element is a button that opens a native
           file picker. Wraps the click in ``page.expect_file_chooser()``
           and resolves the picker with the same paths. Needed for sites
           like NotebookLM where the visible "Add source" / "Upload"
           control isn't itself the input.

        Accepts a single path or a list. Paths are resolved to absolute
        strings before handing to Playwright.
        """
        handle = self._get_handle(index)
        if not isinstance(file_paths, list):
            file_paths = [file_paths]
        paths = [str(Path(p).resolve()) for p in file_paths]
        if not paths:
            raise BrowserError("upload() called with no files")
        try:
            # Try direct set_input_files first — works for <input type="file">.
            try:
                await handle.set_input_files(paths)
                logger.debug("upload(%d) direct, %d files", index, len(paths))
                return
            except Exception as exc:
                logger.debug(
                    "upload(%d) direct set_input_files failed (%s); "
                    "falling back to file-chooser", index, exc,
                )
            # Picker fallback: click the element and wait for a chooser.
            async with self.page.expect_file_chooser(timeout=timeout_ms) as info:
                await handle.click(timeout=5_000)
            chooser = await info.value
            await chooser.set_files(paths)
            logger.debug(
                "upload(%d) via picker, %d files", index, len(paths),
            )
        except Exception as exc:
            raise BrowserError(f"upload({index}) failed: {exc}") from exc

    # ── Capture ──────────────────────────────────────────────────────────────

    async def screenshot(self) -> bytes:
        """Return a viewport PNG screenshot as bytes."""
        try:
            png = await self.page.screenshot(type="png")
            logger.debug("screenshot captured (%d bytes)", len(png))
            return png
        except Exception as exc:
            raise BrowserError(f"screenshot() failed: {exc}") from exc
