"""Tests for ai_intel.workflows.web_apps.web_url_for."""
from __future__ import annotations

import pytest

from ai_intel.workflows.web_apps import web_url_for, WEB_FIRST_APPS


# ─── Known apps ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name, expected_url", [
    ("spotify",   "https://open.spotify.com"),
    ("youtube",   "https://youtube.com"),
    ("gmail",     "https://mail.google.com"),
    ("whatsapp",  "https://web.whatsapp.com"),
    ("discord",   "https://discord.com/app"),
    ("notion",    "https://www.notion.so"),
    ("chatgpt",   "https://chatgpt.com"),
    ("maps",      "https://maps.google.com"),
    ("calendar",  "https://calendar.google.com"),
])
def test_known_apps_return_url(name, expected_url):
    assert web_url_for(name) == expected_url


# ─── Unknown apps ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", [
    "cursor",
    "notepad",
    "vlc",
    "",
    "   ",
    "spotify2",
])
def test_unknown_apps_return_none(name):
    assert web_url_for(name) is None


# ─── Case-insensitivity ────────────────────────────────────────────────────


@pytest.mark.parametrize("name", [
    "Spotify",
    "SPOTIFY",
    "SpOtIfY",
    "YouTube",
    "YOUTUBE",
    "Gmail",
    "GMAIL",
])
def test_matching_is_case_insensitive(name):
    result = web_url_for(name)
    assert result is not None, f"Expected a URL for {name!r}, got None"


# ─── Whitespace stripping ──────────────────────────────────────────────────


@pytest.mark.parametrize("name", [
    " spotify",
    "spotify ",
    "  spotify  ",
    "\tspotify\t",
    " Spotify ",
])
def test_matching_strips_whitespace(name):
    assert web_url_for(name) == "https://open.spotify.com"


# ─── Registry completeness ─────────────────────────────────────────────────


def test_all_registry_entries_have_https_urls():
    for app, url in WEB_FIRST_APPS.items():
        assert url.startswith("https://"), (
            f"URL for {app!r} does not start with https://: {url!r}"
        )


def test_all_registry_keys_are_lowercase():
    for key in WEB_FIRST_APPS:
        assert key == key.lower(), f"Registry key {key!r} is not lowercase"
