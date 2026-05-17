import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlmodel import Session

from ai_intel.db.models import Item
from ai_intel.db.session import get_engine, init_db
from ai_intel.pipeline import generate_and_send_digest


@pytest.mark.asyncio
async def test_pipeline_end_to_end(tmp_path: Path, monkeypatch):
    engine = get_engine(tmp_path / "test.db")
    init_db(engine)
    now = datetime.now(timezone.utc)

    # Insert 15 enriched, AI-relevant items in window
    with Session(engine) as s:
        for i in range(1, 16):
            s.add(Item(
                id=i, source="hn", url=f"https://x.com/{i}", url_hash=f"h{i}",
                title=f"Item {i}",
                published_at=now - timedelta(minutes=i * 5),
                collected_at=now,
                ai_relevance=0.9, pre_score=5, classification="launch",
                entities_json="{}",
            ))
        s.commit()

    # Mock the Opus analyst
    fake_response = MagicMock()
    fake_response.content = [MagicMock(text=json.dumps({
        "summary": "All good",
        "top_50": [{"item_id": i, "rank": i, "why_it_matters": f"why {i}"} for i in range(1, 16)],
    }))]
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_response
    monkeypatch.setattr("ai_intel.analyst.digest.get_anthropic_client", lambda: fake_client)
    monkeypatch.setattr("ai_intel.analyst.digest.PROMPT_PATH", tmp_path / "p.txt")
    (tmp_path / "p.txt").write_text("prompt")

    # Mock the email sender (so no Resend API call)
    sent_log = []
    def fake_send(**kwargs):
        sent_log.append(kwargs)
        return "msg_id"
    monkeypatch.setattr("ai_intel.pipeline.send_digest_email", fake_send)

    output_dir = tmp_path / "output"
    result = await generate_and_send_digest(
        engine=engine,
        output_dir=output_dir,
        window_hours=2,
        model="opus",
        email_to="test@example.com",
    )

    assert result["sent"] is True
    assert len(sent_log) == 1
    assert sent_log[0]["to"] == "test@example.com"
    assert "AI Intel" in sent_log[0]["subject"]
    pdf_path = Path(sent_log[0]["pdf_path"])
    assert pdf_path.exists()


@pytest.mark.asyncio
async def test_pipeline_no_items_skips_send(tmp_path: Path, monkeypatch):
    """When the digest has 0 items, don't send an empty email."""
    engine = get_engine(tmp_path / "test.db")
    init_db(engine)
    monkeypatch.setattr("ai_intel.analyst.digest.PROMPT_PATH", tmp_path / "p.txt")
    (tmp_path / "p.txt").write_text("prompt")

    sent_log = []
    monkeypatch.setattr("ai_intel.pipeline.send_digest_email",
                        lambda **kw: sent_log.append(kw) or "msg_id")

    result = await generate_and_send_digest(
        engine=engine,
        output_dir=tmp_path / "output",
        window_hours=2,
        model="opus",
        email_to="test@example.com",
    )
    assert result["sent"] is False
    assert result["reason"] == "no_items"
    assert len(sent_log) == 0
