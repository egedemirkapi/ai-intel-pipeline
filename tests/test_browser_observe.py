"""tests/test_browser_observe.py — unit tests for browser observe / snapshot.

Uses a throwaway headless Chromium (the same binary the PDF renderer uses)
loaded via ``page.set_content()`` so no real browser or network is needed.

Run::

    python -m pytest tests/test_browser_observe.py -q
"""
from __future__ import annotations

import pytest
from playwright.async_api import async_playwright

from ai_intel.browser.observe import Element, PageSnapshot, build_snapshot

# ---------------------------------------------------------------------------
# HTML fixtures
# ---------------------------------------------------------------------------

_SIMPLE_HTML = """
<!DOCTYPE html>
<html>
<head><title>Test Page</title></head>
<body>
  <a href="/home">Home</a>
  <button>Submit</button>
  <input type="text" placeholder="Search" />
  <textarea aria-label="Notes"></textarea>
  <select><option value="a">Option A</option></select>
  <div role="button" aria-label="Custom button">Click me</div>
  <a href="/about" aria-label="About us">About</a>
  <!-- hidden element — should NOT appear in snapshot -->
  <button style="display:none">Hidden</button>
</body>
</html>
"""

_CONTENTEDITABLE_HTML = """
<!DOCTYPE html>
<html>
<head><title>Editable</title></head>
<body>
  <div contenteditable="true" aria-label="Rich text editor">Edit me</div>
  <button>Save</button>
</body>
</html>
"""

_EMPTY_HTML = """
<!DOCTYPE html>
<html>
<head><title>Empty</title></head>
<body><p>No interactive elements here.</p></body>
</html>
"""

# ---------------------------------------------------------------------------
# Tests: Element & PageSnapshot data classes (pure Python, no browser needed)
# ---------------------------------------------------------------------------


def test_element_dataclass():
    el = Element(index=0, role="button", label="Click me", editable=False)
    assert el.index == 0
    assert el.role == "button"
    assert el.label == "Click me"
    assert el.editable is False


def test_page_snapshot_to_prompt_basic():
    snap = PageSnapshot(
        url="https://example.com",
        title="Example",
        elements=[
            Element(index=0, role="link", label="Home", editable=False),
            Element(index=1, role="button", label="Submit", editable=False),
            Element(index=2, role="input", label="Search", editable=True),
        ],
    )
    text = snap.to_prompt()
    assert "URL: https://example.com" in text
    assert "TITLE: Example" in text
    assert "[0] link  'Home'" in text
    assert "[1] button  'Submit'" in text
    assert "[2] input  'Search' (editable)" in text


def test_page_snapshot_to_prompt_empty():
    snap = PageSnapshot(url="https://example.com", title="Empty", elements=[])
    text = snap.to_prompt()
    assert "INTERACTIVE ELEMENTS:" in text
    lines = text.splitlines()
    assert lines[-1] == "INTERACTIVE ELEMENTS:"


def test_page_snapshot_indices_are_sequential():
    elements = [
        Element(index=i, role="button", label=f"Btn {i}", editable=False)
        for i in range(5)
    ]
    snap = PageSnapshot(url="u", title="t", elements=elements)
    prompt = snap.to_prompt()
    for i in range(5):
        assert f"[{i}] button" in prompt


# ---------------------------------------------------------------------------
# Tests: build_snapshot with live headless Chromium (function-scoped fixture)
# ---------------------------------------------------------------------------


@pytest.fixture
async def browser_page():
    """Yield a fresh headless Chromium page per test; close when done."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        yield page
        await browser.close()


async def test_build_snapshot_returns_tuple(browser_page):
    await browser_page.set_content(_SIMPLE_HTML, wait_until="load")
    result = await build_snapshot(browser_page)
    assert isinstance(result, tuple)
    assert len(result) == 2
    snap, handles = result
    assert isinstance(snap, PageSnapshot)
    assert isinstance(handles, list)


async def test_build_snapshot_title(browser_page):
    await browser_page.set_content(_SIMPLE_HTML, wait_until="load")
    snap, _ = await build_snapshot(browser_page)
    assert snap.title == "Test Page"


async def test_build_snapshot_finds_interactive_elements(browser_page):
    await browser_page.set_content(_SIMPLE_HTML, wait_until="load")
    snap, handles = await build_snapshot(browser_page)
    # We expect at least: Home link, Submit button, Search input, Notes textarea,
    # select, custom div[role=button], About link — at least 5
    assert len(snap.elements) >= 5
    assert len(handles) == len(snap.elements)


async def test_build_snapshot_skips_hidden_elements(browser_page):
    await browser_page.set_content(_SIMPLE_HTML, wait_until="load")
    snap, _ = await build_snapshot(browser_page)
    labels = [el.label.lower() for el in snap.elements]
    # The hidden button must NOT appear
    assert "hidden" not in labels


async def test_build_snapshot_indices_are_sequential(browser_page):
    await browser_page.set_content(_SIMPLE_HTML, wait_until="load")
    snap, _ = await build_snapshot(browser_page)
    for i, el in enumerate(snap.elements):
        assert el.index == i


async def test_build_snapshot_handles_match_elements(browser_page):
    await browser_page.set_content(_SIMPLE_HTML, wait_until="load")
    snap, handles = await build_snapshot(browser_page)
    assert len(snap.elements) == len(handles)
    for h in handles:
        assert h is not None


async def test_build_snapshot_input_is_editable(browser_page):
    await browser_page.set_content(_SIMPLE_HTML, wait_until="load")
    snap, _ = await build_snapshot(browser_page)
    input_els = [el for el in snap.elements if el.role == "input"]
    assert len(input_els) >= 1
    assert all(el.editable for el in input_els)


async def test_build_snapshot_button_not_editable(browser_page):
    await browser_page.set_content(_SIMPLE_HTML, wait_until="load")
    snap, _ = await build_snapshot(browser_page)
    button_els = [el for el in snap.elements if el.role == "button"]
    assert len(button_els) >= 1
    assert all(not el.editable for el in button_els)


async def test_build_snapshot_contenteditable(browser_page):
    await browser_page.set_content(_CONTENTEDITABLE_HTML, wait_until="load")
    snap, _ = await build_snapshot(browser_page)
    editable_els = [el for el in snap.elements if el.editable]
    assert len(editable_els) >= 1
    labels = [el.label for el in editable_els]
    assert any("edit" in lbl.lower() or "rich" in lbl.lower() for lbl in labels)


async def test_build_snapshot_empty_page(browser_page):
    await browser_page.set_content(_EMPTY_HTML, wait_until="load")
    snap, handles = await build_snapshot(browser_page)
    assert snap.title == "Empty"
    assert isinstance(snap.elements, list)
    assert len(snap.elements) == len(handles)


async def test_to_prompt_roundtrip(browser_page):
    await browser_page.set_content(_SIMPLE_HTML, wait_until="load")
    snap, _ = await build_snapshot(browser_page)
    prompt = snap.to_prompt()
    assert prompt.startswith("URL:")
    assert "TITLE: Test Page" in prompt
    assert "INTERACTIVE ELEMENTS:" in prompt
    for el in snap.elements:
        assert f"[{el.index}]" in prompt
