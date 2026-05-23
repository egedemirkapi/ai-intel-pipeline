"""Founder profile — who the proposer is actually proposing for.

The proposer reads this on every run so it designs ideas in domains
where the founder has lived edge (rather than reaching for domains
every other founder also has no insight into — the "hasn't lived
this" auto-kill that the evaluator hands out otherwise).

Override path: ``~/.jarvis/founder_profile.md`` — if present, it wins
over the bundled package profile. Mirrors the ``tools.toml`` override
pattern so a user can keep a private profile without touching the repo.
"""
from __future__ import annotations

from pathlib import Path

_PACKAGE_PROFILE = Path(__file__).parent / "profile.md"
_USER_OVERRIDE = Path.home() / ".jarvis" / "founder_profile.md"


def load_founder_profile() -> str:
    """Return the founder profile markdown text.

    Reads fresh on every call — the profile is small (~3 KB) and the
    proposer fires infrequently, so the cost is trivial and we'd rather
    pick up edits immediately than maintain a cache invalidation story.

    Returns an empty string if neither path exists; the proposer treats
    that as "no founder edge data — propose conservatively."
    """
    if _USER_OVERRIDE.exists():
        return _USER_OVERRIDE.read_text(encoding="utf-8")
    if _PACKAGE_PROFILE.exists():
        return _PACKAGE_PROFILE.read_text(encoding="utf-8")
    return ""


__all__ = ["load_founder_profile"]
