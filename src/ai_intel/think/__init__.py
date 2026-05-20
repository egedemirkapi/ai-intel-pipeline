"""The 'think' layer — Jarvis's higher-order reasoning over the fleet's data.

Currently:
    build_brief()   — assemble the daily briefing
    interests       — manage the user's interest list (seeds suggestions)
"""
from ai_intel.think.brief import build_brief
from ai_intel.think.interests import add_interest, delete_interest, list_interests

__all__ = ["build_brief", "add_interest", "delete_interest", "list_interests"]
