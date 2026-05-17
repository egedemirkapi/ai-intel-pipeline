# src/ai_intel/pipeline.py
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from functools import partial
from pathlib import Path

from sqlmodel import Session

from ai_intel.analyst.digest import generate_digest
from ai_intel.db.models import Digest, Item
from ai_intel.mailer.send import send_digest_email
from ai_intel.pdf.render import render_digest_pdf
from ai_intel.pdf.sections import build_sections

logger = logging.getLogger(__name__)


async def generate_and_send_digest(
    engine,
    output_dir: Path,
    window_hours: int,
    model: str,
    email_to: str,
) -> dict:
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=window_hours)

    digest = await generate_digest(
        engine, window_start=window_start, window_end=now, model=model,
    )
    if not digest["top_items"]:
        logger.info("No items to digest this cycle.")
        return {"sent": False, "reason": "no_items"}

    sections = build_sections(engine, digest["top_items"])
    digest_data = {
        "summary": digest["summary"],
        "items_considered": digest["items_considered"],
        "items_selected": len(digest["top_items"]),
        "window_start": window_start.strftime("%Y-%m-%d %H:%M UTC"),
        "window_end": now.strftime("%Y-%m-%d %H:%M UTC"),
        "sections": sections,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = output_dir / f"ai-intel-{now.strftime('%Y-%m-%d-%H%M')}.pdf"
    # render_digest_pdf uses sync Playwright — run in a thread so it doesn't
    # block or conflict with the running asyncio event loop
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, partial(render_digest_pdf, digest_data, output_path=pdf_path))

    subject = f"AI Intel · {now.strftime('%Y-%m-%d %H:%M')} · {len(digest['top_items'])} items"
    body_html = f"<p>{digest['summary']}</p><p>PDF attached.</p>"
    msg_id = send_digest_email(
        to=email_to, subject=subject, body_html=body_html, pdf_path=pdf_path,
    )

    # Mark items as sent + record the digest
    # Intentionally placed AFTER email send — if email fails, we don't claim items were sent
    with Session(engine) as s:
        for entry in digest["top_items"]:
            item = s.get(Item, entry["item_id"])
            if item:
                item.sent_in_digest_at = now
                s.add(item)
        s.add(Digest(
            window_start=window_start, window_end=now,
            items_considered=digest["items_considered"],
            items_selected=len(digest["top_items"]),
            summary=digest["summary"], pdf_path=str(pdf_path),
            sent_at=now, sent_to=email_to,
        ))
        s.commit()

    return {"sent": True, "msg_id": msg_id, "pdf_path": str(pdf_path)}
