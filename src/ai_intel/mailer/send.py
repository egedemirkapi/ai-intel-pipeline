# src/ai_intel/mailer/send.py
import base64
import logging
import os
from pathlib import Path

import resend

logger = logging.getLogger(__name__)


def send_digest_email(
    to: str | list[str],
    subject: str,
    body_html: str,
    pdf_path: Path,
    sender: str = "onboarding@resend.dev",
) -> str:
    """Send the digest email with PDF attached. Returns Resend message id.

    `to` accepts a single email string OR a list of emails. Resend handles
    both directly. A comma-separated string is also accepted for convenience.
    """
    api_key = os.getenv("RESEND_API_KEY")
    if not api_key:
        raise RuntimeError("RESEND_API_KEY not set. Get one from resend.com dashboard.")
    resend.api_key = api_key

    # Normalise: list passes through; single string passes through; comma-
    # separated string -> list of trimmed strings.
    if isinstance(to, str) and "," in to:
        to = [addr.strip() for addr in to.split(",") if addr.strip()]

    pdf_bytes = pdf_path.read_bytes()
    encoded = base64.b64encode(pdf_bytes).decode()

    payload = {
        "from": sender,
        "to": to,
        "subject": subject,
        "html": body_html,
        "attachments": [{
            "filename": pdf_path.name,
            "content": encoded,
        }],
    }

    resp = resend.Emails.send(payload)
    # Resend SDK returns either a dict or an object with .id depending on version
    msg_id = resp.get("id") if isinstance(resp, dict) else getattr(resp, "id", None)
    logger.info(f"Email sent: id={msg_id}")
    return msg_id
