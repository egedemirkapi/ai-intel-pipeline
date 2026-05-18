"""Jarvis capability layer.

A user-level permission registry that gates which tools any Jarvis-side
agent invocation is allowed to call. Bundled defaults live next to this
module under defaults/tools.toml; the user can override at
~/.jarvis/tools.toml. Approval queue lives at ~/.jarvis/approvals.queue.

Public surface:
    load_policy()           -> dict[str, ToolPolicy]
    is_allowed(name, ...)   -> bool
    get_allowed_tools(...)  -> list[str]
    request_approval(...)   -> str       # returns approval id
    list_approvals(...)     -> list[dict]
    resolve_approval(...)
"""
from ai_intel.jarvis.permissions import (
    ToolPolicy,
    get_allowed_tools,
    is_allowed,
    list_approvals,
    load_policy,
    request_approval,
    resolve_approval,
)

__all__ = [
    "ToolPolicy",
    "get_allowed_tools",
    "is_allowed",
    "list_approvals",
    "load_policy",
    "request_approval",
    "resolve_approval",
]
