"""Tests for the Jarvis capability layer."""
from __future__ import annotations

from pathlib import Path

import pytest

from ai_intel.jarvis import permissions as P


# ---------------------------------------------------------------------------
# Policy loading & resolution
# ---------------------------------------------------------------------------


def _write_toml(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_bundled_defaults_load_cleanly():
    """The shipped defaults file must parse without errors."""
    policy = P._parse_tools_toml(P.DEFAULTS_PATH, "default")
    assert policy, "bundled defaults should be non-empty"
    # Key safety rules must be present and deny
    assert policy["gworkspace.send_email"].decision == "deny"
    assert policy["shell.exec"].decision == "deny"
    assert policy["file.write"].decision == "deny"


def test_load_policy_user_overrides_default(tmp_path, monkeypatch):
    """A user entry must override the bundled default for the same key."""
    user_cfg = tmp_path / "tools.toml"
    _write_toml(
        user_cfg,
        '"file.write" = "allow"\n',  # opt in to writes
    )
    monkeypatch.setattr(P, "USER_CONFIG_PATH", user_cfg)
    policy = P.load_policy()
    assert policy["file.write"].decision == "allow"
    assert policy["file.write"].source == "user"
    # Untouched defaults survive
    assert policy["gworkspace.send_email"].decision == "deny"


def test_is_allowed_explicit_allow(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "USER_CONFIG_PATH", tmp_path / "absent.toml")
    assert P.is_allowed("web.fetch") is True


def test_is_allowed_explicit_deny(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "USER_CONFIG_PATH", tmp_path / "absent.toml")
    assert P.is_allowed("gworkspace.send_email") is False


def test_is_allowed_unknown_tool_is_denied_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "USER_CONFIG_PATH", tmp_path / "absent.toml")
    assert P.is_allowed("totally.invented.tool") is False


def test_wildcard_deny_matches_prefix(tmp_path, monkeypatch):
    """gworkspace.modify_* must deny gworkspace.modify_calendar."""
    monkeypatch.setattr(P, "USER_CONFIG_PATH", tmp_path / "absent.toml")
    assert P.is_allowed("gworkspace.modify_calendar") is False
    assert P.is_allowed("gworkspace.modify_event") is False


def test_explicit_match_beats_wildcard(tmp_path, monkeypatch):
    """An explicit allow must override a wildcard deny."""
    user_cfg = tmp_path / "tools.toml"
    _write_toml(
        user_cfg,
        '"gworkspace.modify_*" = "deny"\n'
        '"gworkspace.modify_one_specific_field" = "allow"\n',
    )
    monkeypatch.setattr(P, "USER_CONFIG_PATH", user_cfg)
    assert P.is_allowed("gworkspace.modify_one_specific_field") is True
    assert P.is_allowed("gworkspace.modify_other") is False


def test_longest_prefix_wildcard_wins(tmp_path, monkeypatch):
    user_cfg = tmp_path / "tools.toml"
    _write_toml(
        user_cfg,
        '"a.*"     = "deny"\n'
        '"a.b.*"   = "allow"\n',
    )
    monkeypatch.setattr(P, "USER_CONFIG_PATH", user_cfg)
    assert P.is_allowed("a.x") is False  # matches a.*
    assert P.is_allowed("a.b.x") is True  # matches a.b.* (longer prefix)


def test_invalid_decision_raises(tmp_path, monkeypatch):
    user_cfg = tmp_path / "tools.toml"
    _write_toml(user_cfg, '"web.fetch" = "maybe"\n')
    monkeypatch.setattr(P, "USER_CONFIG_PATH", user_cfg)
    with pytest.raises(ValueError, match="Invalid policy"):
        P.load_policy()


def test_get_allowed_tools_lists_only_allowed_non_wildcards(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "USER_CONFIG_PATH", tmp_path / "absent.toml")
    allowed = P.get_allowed_tools()
    assert "web.fetch" in allowed
    assert "memory.recall" in allowed
    # No wildcards in this list
    assert not any("*" in name for name in allowed)
    # Denied tools must NOT appear
    assert "gworkspace.send_email" not in allowed
    assert "shell.exec" not in allowed


# ---------------------------------------------------------------------------
# Security-critical assertion (per plan's open-risks #2)
# ---------------------------------------------------------------------------


def test_email_send_is_denied_under_every_reasonable_config(tmp_path, monkeypatch):
    """No accident shall allow the agent to send email on the user's behalf.

    Even with an empty user config OR a hostile one that tries to allow
    a wildcard, the explicit `gworkspace.send_email = deny` must hold.
    """
    # 1. No user file at all
    monkeypatch.setattr(P, "USER_CONFIG_PATH", tmp_path / "absent.toml")
    assert P.is_allowed("gworkspace.send_email") is False

    # 2. User file tries to allow everything via wildcard — explicit deny still wins
    user_cfg = tmp_path / "tools.toml"
    _write_toml(user_cfg, '"gworkspace.*" = "allow"\n')
    monkeypatch.setattr(P, "USER_CONFIG_PATH", user_cfg)
    assert P.is_allowed("gworkspace.send_email") is False, (
        "explicit deny in defaults must beat user's wildcard allow"
    )


# ---------------------------------------------------------------------------
# Approval queue
# ---------------------------------------------------------------------------


def test_request_approval_writes_pending(tmp_path):
    qp = tmp_path / "approvals.queue"
    aid = P.request_approval("shell.exec", {"cmd": "ls"}, queue_path=qp)
    assert isinstance(aid, str) and len(aid) == 12
    pending = P.list_approvals(queue_path=qp)
    assert len(pending) == 1
    assert pending[0]["tool"] == "shell.exec"
    assert pending[0]["status"] == "pending"


def test_resolve_approval_round_trip(tmp_path):
    qp = tmp_path / "approvals.queue"
    aid = P.request_approval("file.write", {"path": "/etc/passwd"}, queue_path=qp)
    entry = P.resolve_approval(aid, "rejected", queue_path=qp)
    assert entry["status"] == "rejected"

    # No longer in pending
    assert P.list_approvals(queue_path=qp, status="pending") == []
    # But visible in full history
    all_entries = P.list_approvals(queue_path=qp, status=None)
    assert len(all_entries) == 1
    assert all_entries[0]["status"] == "rejected"


def test_resolve_unknown_id_raises(tmp_path):
    qp = tmp_path / "approvals.queue"
    with pytest.raises(KeyError):
        P.resolve_approval("deadbeef", "approved", queue_path=qp)


def test_resolve_invalid_decision_raises(tmp_path):
    qp = tmp_path / "approvals.queue"
    aid = P.request_approval("x", {}, queue_path=qp)
    with pytest.raises(ValueError):
        P.resolve_approval(aid, "maybe", queue_path=qp)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# User-config bootstrap
# ---------------------------------------------------------------------------


def test_ensure_user_config_creates_when_missing(tmp_path, monkeypatch):
    target = tmp_path / "tools.toml"
    monkeypatch.setattr(P, "USER_CONFIG_PATH", target)
    assert not target.exists()
    path = P.ensure_user_config()
    assert path == target
    assert target.exists()
    # Round-trips with the parser
    parsed = P._parse_tools_toml(target, "user")
    assert "gworkspace.send_email" in parsed


def test_ensure_user_config_does_not_clobber_unless_forced(tmp_path, monkeypatch):
    target = tmp_path / "tools.toml"
    monkeypatch.setattr(P, "USER_CONFIG_PATH", target)
    target.write_text('"custom.tool" = "allow"\n', encoding="utf-8")
    P.ensure_user_config()
    assert "custom.tool" in target.read_text(encoding="utf-8")

    P.ensure_user_config(force=True)
    assert "custom.tool" not in target.read_text(encoding="utf-8")
    assert "gworkspace.send_email" in target.read_text(encoding="utf-8")
