import pytest

from ai_intel.collectors.registry import build_collectors_from_config


def test_registry_builds_known_collectors():
    cfg = {
        "sources": {
            "enabled": ["hn", "rss_techcrunch", "rss_anthropic", "watchlist"]
        }
    }
    collectors = build_collectors_from_config(cfg)
    names = [c.name for c in collectors]
    assert "hn" in names
    assert "rss:techcrunch" in names
    assert "rss:anthropic" in names
    assert "watchlist" in names


def test_registry_skips_unknown_sources():
    cfg = {
        "sources": {
            "enabled": ["hn", "rss_nonexistent_feed_xyz"]
        }
    }
    collectors = build_collectors_from_config(cfg)
    names = [c.name for c in collectors]
    assert "hn" in names
    # unknown entry should be skipped, not raise
    assert len(collectors) == 1


def test_registry_empty_enabled_returns_empty():
    cfg = {"sources": {"enabled": []}}
    collectors = build_collectors_from_config(cfg)
    assert collectors == []
