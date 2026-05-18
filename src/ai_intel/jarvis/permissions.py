"""Tool-policy enforcement and human-in-the-loop approval queue.

Policy resolution order:
    1. user override at ~/.jarvis/tools.toml (or path given to load_policy)
    2. bundled defaults at ai_intel/jarvis/defaults/tools.toml
    3. default-deny for any tool not mentioned in either file

A wildcard policy whose name ends in ``*`` matches any tool whose name
shares that prefix (e.g. ``gworkspace.modify_*`` matches
``gworkspace.modify_calendar``). An explicit non-wildcard entry always
wins over a wildcard.
"""
from __future__ import annotations

import json
import os
import tomllib
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Literal

Decision = Literal["allow", "deny"]

DEFAULTS_PATH = Path(__file__).parent / "defaults" / "tools.toml"
USER_CONFIG_PATH = Path.home() / ".jarvis" / "tools.toml"
APPROVAL_QUEUE_PATH = Path.home() / ".jarvis" / "approvals.queue"


@dataclass(frozen=True)
class ToolPolicy:
    name: str
    decision: Decision
    source: Literal["user", "default"]

    @property
    def is_wildcard(self) -> bool:
        return self.name.endswith("*")

    @property
    def prefix(self) -> str:
        # Only meaningful when is_wildcard
        return self.name[:-1]


def _parse_tools_toml(path: Path, source: Literal["user", "default"]) -> dict[str, ToolPolicy]:
    """Parse a tools.toml into {tool_name: ToolPolicy}.

    Expected schema:
        ["tool.name"] = "allow"  or  "deny"
    Unknown values raise ValueError.
    """
    if not path.exists():
        return {}
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    out: dict[str, ToolPolicy] = {}
    for name, decision in raw.items():
        if decision not in ("allow", "deny"):
            raise ValueError(
                f"Invalid policy for {name!r} in {path}: "
                f"expected 'allow' or 'deny', got {decision!r}"
            )
        out[name] = ToolPolicy(name=name, decision=decision, source=source)
    return out


def load_policy(user_path: Path | None = None) -> dict[str, ToolPolicy]:
    """Return merged {tool_name: ToolPolicy}. User entries override defaults."""
    defaults = _parse_tools_toml(DEFAULTS_PATH, "default")
    user = _parse_tools_toml(user_path or USER_CONFIG_PATH, "user")
    merged = {**defaults, **user}
    return merged


def _matches(rule: ToolPolicy, tool_name: str) -> bool:
    if rule.is_wildcard:
        return tool_name.startswith(rule.prefix)
    return rule.name == tool_name


def is_allowed(tool_name: str, policy: dict[str, ToolPolicy] | None = None) -> bool:
    """True iff there exists an 'allow' rule matching tool_name AND no 'deny' rule
    matches it. Default is deny for unknown tools.

    Resolution: explicit non-wildcard match (allow or deny) wins outright.
    Otherwise, the most specific (longest-prefix) wildcard wins. Tie-break:
    deny over allow (safer).
    """
    if policy is None:
        policy = load_policy()

    explicit = policy.get(tool_name)
    if explicit is not None and not explicit.is_wildcard:
        return explicit.decision == "allow"

    # Look at wildcards
    best_prefix_len = -1
    best_decision: Decision | None = None
    for rule in policy.values():
        if not rule.is_wildcard:
            continue
        if _matches(rule, tool_name):
            if len(rule.prefix) > best_prefix_len:
                best_prefix_len = len(rule.prefix)
                best_decision = rule.decision
            elif len(rule.prefix) == best_prefix_len and rule.decision == "deny":
                # Tie-break in favor of deny
                best_decision = "deny"

    if best_decision is None:
        return False  # default-deny
    return best_decision == "allow"


def get_allowed_tools(policy: dict[str, ToolPolicy] | None = None) -> list[str]:
    """Return all explicitly-named (non-wildcard) tools that resolve to allow.

    This is what bridges pass as ``allowed_tools`` to agent invocations.
    """
    if policy is None:
        policy = load_policy()
    return sorted(
        name
        for name, rule in policy.items()
        if not rule.is_wildcard and is_allowed(name, policy)
    )


# ---------------------------------------------------------------------------
# Approval queue — append-only JSON lines at ~/.jarvis/approvals.queue
# ---------------------------------------------------------------------------


def _ensure_queue_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.touch(mode=0o600)


def request_approval(
    tool_name: str,
    args: dict,
    *,
    reason: str = "",
    queue_path: Path | None = None,
) -> str:
    """Append a pending approval to the queue. Returns approval id."""
    qp = queue_path or APPROVAL_QUEUE_PATH
    _ensure_queue_dir(qp)
    approval_id = uuid.uuid4().hex[:12]
    entry = {
        "id": approval_id,
        "tool": tool_name,
        "args": args,
        "reason": reason,
        "status": "pending",
        "requested_at": datetime.now(timezone.utc).isoformat(),
    }
    with qp.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return approval_id


def list_approvals(
    *,
    queue_path: Path | None = None,
    status: str | Iterable[str] | None = "pending",
) -> list[dict]:
    """Read all approvals matching status (default: 'pending').

    Pass status=None to return everything.
    """
    qp = queue_path or APPROVAL_QUEUE_PATH
    if not qp.exists():
        return []
    if isinstance(status, str):
        wanted = {status}
    elif status is None:
        wanted = None
    else:
        wanted = set(status)

    # Build a dict keyed by id so later entries supersede earlier ones
    # (i.e. status updates replace the original 'pending' entry).
    latest: dict[str, dict] = {}
    for line in qp.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        latest[entry["id"]] = entry

    items = list(latest.values())
    if wanted is not None:
        items = [e for e in items if e.get("status") in wanted]
    items.sort(key=lambda e: e.get("requested_at", ""))
    return items


def resolve_approval(
    approval_id: str,
    decision: Literal["approved", "rejected"],
    *,
    queue_path: Path | None = None,
) -> dict:
    """Append a resolution record. Returns the resolved entry.

    Raises KeyError if no pending entry with that id exists.
    """
    if decision not in ("approved", "rejected"):
        raise ValueError(f"decision must be 'approved' or 'rejected', got {decision!r}")
    qp = queue_path or APPROVAL_QUEUE_PATH
    pending = {e["id"]: e for e in list_approvals(queue_path=qp, status="pending")}
    if approval_id not in pending:
        raise KeyError(f"no pending approval with id {approval_id!r}")
    entry = dict(pending[approval_id])
    entry["status"] = decision
    entry["resolved_at"] = datetime.now(timezone.utc).isoformat()
    _ensure_queue_dir(qp)
    with qp.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def ensure_user_config(*, force: bool = False) -> Path:
    """Copy bundled defaults to ~/.jarvis/tools.toml if it doesn't exist.

    Returns the user config path.
    """
    target = USER_CONFIG_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    if force or not target.exists():
        target.write_text(DEFAULTS_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        try:
            os.chmod(target, 0o600)
        except OSError:
            # Windows / WSL may not honor chmod the same way; non-fatal.
            pass
    return target
