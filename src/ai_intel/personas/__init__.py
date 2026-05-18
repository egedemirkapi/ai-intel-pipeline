"""Founder personas as evaluator skills.

Each persona is a markdown file in this package. The evaluator agent
(Phase 8) loads them and weaves them into its multi-lens critique
prompt. Personas are user-editable — re-running the agent picks up
changes immediately.
"""
from __future__ import annotations

from pathlib import Path

# Persona ids match the markdown filenames (without .md).
KNOWN_PERSONAS: tuple[str, ...] = (
    "paul_graham",
    "sam_altman",
    "garry_tan",
    "alex_hormozi",
    "a16z",
    "yc_partner",
)

_PACKAGE_DIR = Path(__file__).parent


def load_persona(persona_id: str) -> str:
    """Return the raw markdown text for one persona.

    Raises FileNotFoundError if persona_id isn't recognized OR the file
    is missing on disk (so a typo fails loud, not silent).
    """
    path = _PACKAGE_DIR / f"{persona_id}.md"
    if not path.exists():
        raise FileNotFoundError(
            f"persona {persona_id!r} not found at {path}. "
            f"known personas: {', '.join(KNOWN_PERSONAS)}"
        )
    return path.read_text(encoding="utf-8")


def load_all() -> dict[str, str]:
    """Return {persona_id: markdown_text} for every persona on disk."""
    out: dict[str, str] = {}
    for pid in KNOWN_PERSONAS:
        path = _PACKAGE_DIR / f"{pid}.md"
        if path.exists():
            out[pid] = path.read_text(encoding="utf-8")
    return out
