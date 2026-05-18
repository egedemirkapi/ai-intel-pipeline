"""Tests for scripts/_common.py and the ingest_* scripts.

The PG and Altman scrapers are tested end-to-end against mocked HTTP
responses via pytest-httpx, so we exercise the index parsing + body
extraction without hitting the live sites.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from ai_intel.db.models import Item
from scripts._common import (
    build_item,
    clean_whitespace,
    ingest_batch,
    insert_if_new,
    url_hash,
)


@pytest.fixture
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    return eng


# ---------------------------------------------------------------------------
# _common helpers
# ---------------------------------------------------------------------------


def test_url_hash_is_deterministic():
    h1 = url_hash("https://example.com/a")
    h2 = url_hash("https://example.com/a")
    assert h1 == h2
    assert len(h1) == 32


def test_url_hash_differs_per_url():
    assert url_hash("https://a") != url_hash("https://b")


def test_clean_whitespace_collapses_runs():
    raw = "hello   world\n\n\n\nnext"
    assert clean_whitespace(raw) == "hello world\n\nnext"


def test_build_item_shape():
    it = build_item(
        url="https://example.com/post",
        title="A title",
        body="The body",
        author="Test Author",
    )
    assert it.source == "founder_brain"
    assert it.url == "https://example.com/post"
    assert it.title == "A title"
    assert it.body == "The body"
    assert it.author == "Test Author"
    assert it.classification == "essay"
    # entities_json is JSON-encoded
    import json
    parsed = json.loads(it.entities_json)
    assert parsed["author"] == "Test Author"
    assert parsed["kind"] == "essay"


def test_insert_if_new_is_idempotent(engine):
    it1 = build_item(
        url="https://example.com/x", title="T", body="B" * 300, author="A"
    )
    with Session(engine) as s:
        assert insert_if_new(s, it1) is True
        # Same URL should NOT be re-inserted
        it2 = build_item(
            url="https://example.com/x", title="T2", body="B2" * 300, author="A"
        )
        assert insert_if_new(s, it2) is False
        rows = s.exec(select(Item)).all()
    assert len(rows) == 1
    # Original title preserved (we don't update on conflict)
    assert rows[0].title == "T"


def test_ingest_batch_counts(engine):
    items = [
        build_item(url=f"https://e.com/{i}", title=f"t{i}", body="B" * 300, author="A")
        for i in range(3)
    ]
    inserted, skipped = ingest_batch(engine, items)
    assert inserted == 3 and skipped == 0
    # Re-running same batch: all skipped
    items2 = [
        build_item(url=f"https://e.com/{i}", title=f"t{i}", body="B" * 300, author="A")
        for i in range(3)
    ]
    inserted, skipped = ingest_batch(engine, items2)
    assert inserted == 0 and skipped == 3


# ---------------------------------------------------------------------------
# PG ingester (mocked HTTP)
# ---------------------------------------------------------------------------


PG_INDEX_HTML = """
<html><body>
<a href="wealth.html">How to Make Wealth</a>
<a href="schlep.html">Schlep Blindness</a>
<a href="articles.html">Back to index</a>
<a href="rss.html">RSS</a>
<a href="http://external.example/x">External</a>
</body></html>
"""

PG_ESSAY_HTML_WEALTH = """
<html><head><title>How to Make Wealth</title></head>
<body><table><tr><td>
<font>
{long_body}
</font>
</td></tr></table></body></html>
""".replace("{long_body}", "Wealth is not money. " * 80)

PG_ESSAY_HTML_SCHLEP = """
<html><head><title>Schlep Blindness</title></head>
<body><table><tr><td>
<font>
{long_body}
</font>
</td></tr></table></body></html>
""".replace("{long_body}", "The schlep is what stops you. " * 80)


def test_pg_fetch_index_finds_essays(httpx_mock):
    from scripts.ingest_pg import INDEX_URL, fetch_index
    from scripts._common import make_client

    httpx_mock.add_response(url=INDEX_URL, text=PG_INDEX_HTML)
    with make_client() as client:
        essays = fetch_index(client)
    urls = [u for _, u in essays]
    assert "http://paulgraham.com/wealth.html" in urls
    assert "http://paulgraham.com/schlep.html" in urls
    # boilerplate / external links filtered
    assert not any("articles.html" in u for u in urls)
    assert not any("rss.html" in u for u in urls)
    assert not any("external.example" in u for u in urls)


def test_pg_fetch_essay_extracts_title_and_body(httpx_mock):
    from scripts.ingest_pg import fetch_essay
    from scripts._common import make_client

    httpx_mock.add_response(
        url="http://paulgraham.com/wealth.html", text=PG_ESSAY_HTML_WEALTH
    )
    with make_client() as client:
        result = fetch_essay(client, "http://paulgraham.com/wealth.html")
    assert result is not None
    title, body = result
    assert title == "How to Make Wealth"
    assert "Wealth is not money" in body
    assert len(body) > 200


def test_pg_fetch_essay_rejects_thin_body(httpx_mock):
    from scripts.ingest_pg import fetch_essay
    from scripts._common import make_client

    httpx_mock.add_response(
        url="http://paulgraham.com/empty.html",
        text="<html><body><font>tiny</font></body></html>",
    )
    with make_client() as client:
        assert fetch_essay(client, "http://paulgraham.com/empty.html") is None


# ---------------------------------------------------------------------------
# Altman ingester (mocked HTTP)
# ---------------------------------------------------------------------------


ALTMAN_ARCHIVE_HTML = """
<html><body>
<a href="/the-merge">The Merge</a>
<a href="/superintelligence">Superintelligence</a>
<a href="/archive">Archive</a>
<a href="/feed">RSS</a>
<a href="/about">About</a>
</body></html>
"""

ALTMAN_POST_HTML = """
<html><head><title>The Merge</title></head><body>
<h1>The Merge</h1>
<div class="posthaven-post-body">
{long_body}
</div>
</body></html>
""".replace("{long_body}", "We will be the last species to do X. " * 60)


def test_altman_archive_links(httpx_mock):
    from scripts.ingest_altman import ARCHIVE_URL, fetch_archive_links
    from scripts._common import make_client

    httpx_mock.add_response(url=ARCHIVE_URL, text=ALTMAN_ARCHIVE_HTML)
    with make_client() as client:
        urls = fetch_archive_links(client)
    assert "https://blog.samaltman.com/the-merge" in urls
    assert "https://blog.samaltman.com/superintelligence" in urls
    # boilerplate filtered
    assert not any(u.endswith("/archive") for u in urls)
    assert not any(u.endswith("/feed") for u in urls)
    assert not any(u.endswith("/about") for u in urls)


def test_altman_fetch_post(httpx_mock):
    from scripts.ingest_altman import fetch_post
    from scripts._common import make_client

    httpx_mock.add_response(
        url="https://blog.samaltman.com/the-merge", text=ALTMAN_POST_HTML
    )
    with make_client() as client:
        result = fetch_post(client, "https://blog.samaltman.com/the-merge")
    assert result is not None
    title, body = result
    assert title == "The Merge"
    assert "last species" in body
