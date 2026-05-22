"""observe.py — turn a live Playwright page into an LLM-friendly snapshot.

The snapshot enumerates interactive elements (links, buttons, inputs, …),
assigns stable integer indices, and exposes a ``to_prompt()`` text rendering
that the LLM can reason about.

Usage::

    snapshot, handles = await build_snapshot(page)
    print(snapshot.to_prompt())
    # [0] link  'Home'
    # [1] button  'Submit'
    # ...
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Maximum interactive elements captured per snapshot
_MAX_ELEMENTS = 120

# CSS selectors that identify interactive elements
_INTERACTIVE_SELECTORS = [
    "a[href]",
    "button",
    "[role=button]",
    "input:not([type=hidden])",
    "textarea",
    "[contenteditable]",
    "select",
    "[role=link]",
    "[role=checkbox]",
    "[role=radio]",
    "[role=menuitem]",
    "[role=tab]",
    "[role=option]",
    "[role=combobox]",
    "[role=listbox]",
    "[role=switch]",
    "[role=spinbutton]",
    "[role=slider]",
    "[role=textbox]",
    "[onclick]",
    "[tabindex]:not([tabindex='-1'])",
]


@dataclass
class Element:
    """A single interactive element captured from the page."""

    index: int
    role: str
    label: str
    editable: bool


@dataclass
class PageSnapshot:
    """LLM-friendly snapshot of a page's interactive surface."""

    url: str
    title: str
    elements: list[Element] = field(default_factory=list)

    def to_prompt(self) -> str:
        """Return a compact numbered text list suitable for an LLM prompt.

        Example output::

            URL: https://example.com
            TITLE: Example Domain
            INTERACTIVE ELEMENTS:
            [0] link  'Example Link'
            [1] button  'Submit'
            [2] input  'Search' (editable)
        """
        lines: list[str] = [
            f"URL: {self.url}",
            f"TITLE: {self.title}",
            "INTERACTIVE ELEMENTS:",
        ]
        for el in self.elements:
            editable_marker = " (editable)" if el.editable else ""
            lines.append(f"[{el.index}] {el.role}  '{el.label}'{editable_marker}")
        return "\n".join(lines)


async def build_snapshot(page: Any) -> tuple[PageSnapshot, list[Any]]:
    """Enumerate interactive elements on *page* and return a snapshot + handles.

    Parameters
    ----------
    page:
        An async Playwright ``Page`` object.

    Returns
    -------
    tuple[PageSnapshot, list]
        The snapshot (safe to serialize / send to an LLM) and a parallel list
        of Playwright element handles so the caller can act on element N by
        index.  Hidden / invisible elements are skipped.  At most
        ``_MAX_ELEMENTS`` elements are returned.
    """
    url: str = page.url
    title: str = await page.title()

    seen_handles: set[str] = set()  # deduplicate by element JSON identity
    elements: list[Element] = []
    handles: list[Any] = []

    # Build a combined selector that covers all interactive elements
    combined_selector = ", ".join(_INTERACTIVE_SELECTORS)

    try:
        raw_handles = await page.query_selector_all(combined_selector)
    except Exception as exc:
        logger.warning("query_selector_all failed: %s", exc)
        raw_handles = []

    for raw_handle in raw_handles:
        if len(elements) >= _MAX_ELEMENTS:
            break

        try:
            # Skip hidden / invisible elements
            is_visible = await raw_handle.is_visible()
            if not is_visible:
                continue

            # Deduplicate: use bounding box + tag as a rough identity key
            tag = await raw_handle.evaluate("el => el.tagName.toLowerCase()")
            bbox = await raw_handle.bounding_box()
            if bbox is None:
                # Element has no layout box — skip
                continue

            identity = f"{tag}:{bbox['x']:.0f},{bbox['y']:.0f},{bbox['width']:.0f},{bbox['height']:.0f}"
            if identity in seen_handles:
                continue
            seen_handles.add(identity)

            # Determine role
            role = await _get_role(raw_handle, tag)

            # Determine label / accessible name
            label = await _get_label(raw_handle, tag)
            label = label.strip()[:120]  # truncate very long labels

            # Editable?
            editable = await _is_editable(raw_handle, tag)

            idx = len(elements)
            elements.append(Element(index=idx, role=role, label=label, editable=editable))
            handles.append(raw_handle)

        except Exception as exc:
            logger.debug("Skipping element due to error: %s", exc)
            continue

    snapshot = PageSnapshot(url=url, title=title, elements=elements)
    return snapshot, handles


async def _get_role(handle: Any, tag: str) -> str:
    """Derive a human-readable role string for an element."""
    try:
        aria_role = await handle.evaluate(
            "el => el.getAttribute('role') || ''"
        )
        if aria_role:
            return aria_role.lower()
    except Exception:
        pass

    _tag_to_role: dict[str, str] = {
        "a": "link",
        "button": "button",
        "input": "input",
        "textarea": "textarea",
        "select": "select",
    }
    return _tag_to_role.get(tag, tag)


async def _get_label(handle: Any, tag: str) -> str:
    """Extract the best available accessible label for an element."""
    # Try aria-label, aria-labelledby text, placeholder, value, inner text
    try:
        label = await handle.evaluate(
            """el => {
                if (el.getAttribute('aria-label')) return el.getAttribute('aria-label');
                const lby = el.getAttribute('aria-labelledby');
                if (lby) {
                    const ref = document.getElementById(lby);
                    if (ref) return ref.textContent.trim();
                }
                if (el.placeholder) return el.placeholder;
                if (el.title) return el.title;
                if (el.alt) return el.alt;
                const txt = (el.innerText || el.textContent || '').trim();
                if (txt) return txt;
                if (el.value && el.tagName !== 'SELECT') return el.value;
                return el.name || el.id || '';
            }"""
        )
        return str(label or "")
    except Exception:
        return ""


async def _is_editable(handle: Any, tag: str) -> bool:
    """Return True if the element accepts text input."""
    if tag in ("input", "textarea"):
        try:
            input_type = await handle.evaluate(
                "el => (el.getAttribute('type') || 'text').toLowerCase()"
            )
            return input_type not in ("button", "submit", "reset", "image", "checkbox", "radio", "file")
        except Exception:
            return True
    try:
        ce = await handle.evaluate("el => el.getAttribute('contenteditable')")
        if ce is not None and ce != "false":
            return True
    except Exception:
        pass
    return False
