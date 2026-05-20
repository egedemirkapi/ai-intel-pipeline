"""Tests for the installed-app scanner and launch allowlist.

The PowerShell ``Get-StartApps`` call is mocked so these run on any OS.
"""
from __future__ import annotations

import json

from ai_intel.workflows import app_scanner

_FAKE_JSON = json.dumps([
    {"Name": "Spotify", "AppID": "Spotify.exe"},
    {"Name": "Cursor", "AppID": "C:\\Users\\me\\cursor.lnk"},
    {"Name": "Calculator", "AppID": "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App"},
])


# ─── _parse_startapps ───────────────────────────────────────────────


def test_parse_startapps_returns_sorted_list():
    apps = app_scanner._parse_startapps(_FAKE_JSON)
    assert [a["name"] for a in apps] == ["Calculator", "Cursor", "Spotify"]
    assert all("app_id" in a for a in apps)


def test_parse_startapps_handles_single_object():
    raw = json.dumps({"Name": "Solo", "AppID": "solo.exe"})
    apps = app_scanner._parse_startapps(raw)
    assert apps == [{"name": "Solo", "app_id": "solo.exe"}]


def test_parse_startapps_dedups_and_skips_blanks():
    raw = json.dumps([
        {"Name": "A", "AppID": "a.exe"},
        {"Name": "A again", "AppID": "a.exe"},   # dup app_id
        {"Name": "", "AppID": "b.exe"},          # blank name
        {"Name": "C", "AppID": ""},              # blank id
    ])
    apps = app_scanner._parse_startapps(raw)
    assert apps == [{"name": "A", "app_id": "a.exe"}]


def test_parse_startapps_tolerates_garbage():
    assert app_scanner._parse_startapps("") == []
    assert app_scanner._parse_startapps("not json") == []


# ─── scan_installed_apps ────────────────────────────────────────────


def test_scan_uses_powershell_when_on_windows(monkeypatch):
    monkeypatch.setattr(app_scanner, "_on_windows", lambda: True)
    monkeypatch.setattr(app_scanner, "_powershell_get_startapps", lambda: _FAKE_JSON)
    apps = app_scanner.scan_installed_apps()
    assert len(apps) == 3


def test_scan_returns_empty_off_windows(monkeypatch):
    monkeypatch.setattr(app_scanner, "_on_windows", lambda: False)
    assert app_scanner.scan_installed_apps() == []


def test_scan_returns_empty_when_powershell_fails(monkeypatch):
    monkeypatch.setattr(app_scanner, "_on_windows", lambda: True)
    def _boom():
        raise RuntimeError("Get-StartApps failed")
    monkeypatch.setattr(app_scanner, "_powershell_get_startapps", _boom)
    assert app_scanner.scan_installed_apps() == []


# ─── list_installed_apps caching ────────────────────────────────────


def test_list_installed_apps_caches(tmp_path, monkeypatch):
    cache = tmp_path / "apps_cache.json"
    calls = []
    def _fake_scan():
        calls.append(1)
        return [{"name": "Cached", "app_id": "cached.exe"}]
    monkeypatch.setattr(app_scanner, "scan_installed_apps", _fake_scan)

    first = app_scanner.list_installed_apps(cache_path=cache)
    second = app_scanner.list_installed_apps(cache_path=cache)
    assert first == second == [{"name": "Cached", "app_id": "cached.exe"}]
    assert len(calls) == 1  # second call hit the cache

    app_scanner.list_installed_apps(refresh=True, cache_path=cache)
    assert len(calls) == 2  # refresh forced a rescan


# ─── allowlist ──────────────────────────────────────────────────────


def test_add_and_get_allowlist(tmp_path):
    p = tmp_path / "apps_allowed.json"
    app_scanner.add_to_allowlist("spotify.exe", "Spotify", path=p)
    allowed = app_scanner.get_allowlist(path=p)
    assert len(allowed) == 1
    assert allowed[0]["name"] == "Spotify"


def test_add_to_allowlist_is_idempotent(tmp_path):
    p = tmp_path / "apps_allowed.json"
    app_scanner.add_to_allowlist("spotify.exe", "Spotify", path=p)
    app_scanner.add_to_allowlist("spotify.exe", "Spotify", path=p)
    assert len(app_scanner.get_allowlist(path=p)) == 1


def test_is_app_allowed_matches_by_id_or_name(tmp_path):
    p = tmp_path / "apps_allowed.json"
    app_scanner.add_to_allowlist("spotify.exe", "Spotify", path=p)
    assert app_scanner.is_app_allowed(app_id="spotify.exe", path=p) is True
    assert app_scanner.is_app_allowed(name="Spotify", path=p) is True
    assert app_scanner.is_app_allowed(name="Notepad", path=p) is False


def test_remove_from_allowlist(tmp_path):
    p = tmp_path / "apps_allowed.json"
    app_scanner.add_to_allowlist("spotify.exe", "Spotify", path=p)
    assert app_scanner.remove_from_allowlist("spotify.exe", path=p) is True
    assert app_scanner.get_allowlist(path=p) == []
    assert app_scanner.remove_from_allowlist("spotify.exe", path=p) is False


def test_unknown_app_is_not_allowed_by_default(tmp_path):
    p = tmp_path / "apps_allowed.json"
    assert app_scanner.is_app_allowed(name="anything", path=p) is False
