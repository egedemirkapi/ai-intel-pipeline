"""Tests for the founder personas loader."""
from __future__ import annotations

import pytest

from ai_intel.personas import KNOWN_PERSONAS, load_all, load_persona


def test_all_known_personas_load():
    """Every persona file declared in KNOWN_PERSONAS must exist on disk."""
    for pid in KNOWN_PERSONAS:
        text = load_persona(pid)
        assert text, f"{pid} is empty"
        # Every persona must have the four canonical sections
        assert "## Lens" in text, f"{pid} missing Lens section"
        assert "## Top questions" in text, f"{pid} missing Top questions"
        assert "## Red flags" in text, f"{pid} missing Red flags"
        assert "## Quick test" in text, f"{pid} missing Quick test"


def test_unknown_persona_raises():
    with pytest.raises(FileNotFoundError):
        load_persona("warren_buffett")


def test_load_all_returns_dict():
    everyone = load_all()
    # All known personas should resolve
    for pid in KNOWN_PERSONAS:
        assert pid in everyone
        assert everyone[pid]
