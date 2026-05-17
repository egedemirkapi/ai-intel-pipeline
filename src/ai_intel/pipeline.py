# src/ai_intel/pipeline.py
import asyncio
import html
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


def _build_email_html(digest_data: dict) -> str:
    """Build a rich HTML email body containing the full digest inline.

    Gmail often strips or rejects PDF attachments (especially when content mentions
    security-sensitive terms). Embedding the digest in the body guarantees Ege sees
    the content even when the PDF gets stripped.
    """
    e = html.escape  # shorthand

    sections_html = []
    for section_name, items in digest_data["sections"].items():
        sections_html.append(
            f'<h2 style="font-size:16px;margin:24px 0 8px;color:#555;'
            f'text-transform:uppercase;letter-spacing:0.05em;'
            f'border-bottom:1px solid #ddd;padding-bottom:4px;">'
            f'{e(section_name)} ({len(items)})</h2>'
        )
        for entry in items:
            why = entry.get("why_it_matters", "")
            sections_html.append(
                f'<div style="margin:12px 0 16px;padding-bottom:10px;'
                f'border-bottom:1px solid #f0f0f0;">'
                f'<div style="font-size:14px;font-weight:600;line-height:1.3;">'
                f'<a href="{e(entry["url"])}" style="color:#0066cc;text-decoration:none;">'
                f'{e(entry["title"])}</a></div>'
                f'<div style="font-size:11px;color:#888;margin-top:2px;">'
                f'{e(entry["source"])} · {e(str(entry["published_at"]))}</div>'
                + (f'<div style="font-size:13px;color:#333;margin-top:6px;'
                   f'line-height:1.5;">{e(why)}</div>' if why else "")
                + '</div>'
            )

    return f'''
    <html>
    <body style="font-family:-apple-system,'Segoe UI',sans-serif;
                 color:#1a1a1a;line-height:1.5;max-width:680px;
                 margin:0 auto;padding:24px;">
      <h1 style="font-size:24px;border-bottom:2px solid #000;
                 padding-bottom:8px;margin:0 0 8px;">AI Intel Digest</h1>
      <div style="font-size:11px;color:#888;margin-bottom:16px;">
        Generated {e(digest_data["window_end"])} ·
        {digest_data["items_considered"]} items considered ·
        {digest_data["items_selected"]} selected ·
        window {e(digest_data["window_start"])} → {e(digest_data["window_end"])}
      </div>
      <div style="background:#f6f6f6;padding:14px 18px;
                  border-left:4px solid #4a4a4a;margin:16px 0 24px;
                  font-style:italic;line-height:1.6;">
        {e(digest_data["summary"])}
      </div>
      {"".join(sections_html)}
      <hr style="margin:32px 0 16px;border:none;border-top:1px solid #eee;">
      <div style="font-size:11px;color:#aaa;">
        PDF version attached. Full digest also embedded above so you can read
        without opening the attachment.
      </div>
    </body>
    </html>
    '''


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
    body_html = _build_email_html(digest_data)
    try:
        msg_id = send_digest_email(
            to=email_to, subject=subject, body_html=body_html, pdf_path=pdf_path,
        )
    except Exception as e:
        # Don't crash the scheduler on transient email failures (Resend sandbox
        # restrictions, rate limits, network blips). PDF is preserved on disk so
        # the user can re-send manually, and items stay unmarked so the next
        # cycle can retry.
        logger.error(
            f"Email send failed ({type(e).__name__}): {e}. "
            f"PDF preserved at {pdf_path}; items NOT marked as sent."
        )
        return {"sent": False, "reason": "email_failed", "error": str(e), "pdf_path": str(pdf_path)}

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
