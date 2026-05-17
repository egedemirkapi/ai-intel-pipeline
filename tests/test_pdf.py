from datetime import datetime, timezone
from pathlib import Path

from ai_intel.pdf.render import render_digest_pdf


def test_pdf_generates_file(tmp_path: Path):
    digest_data = {
        "summary": "Test summary",
        "items_considered": 100,
        "items_selected": 1,
        "window_start": datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc),
        "window_end": datetime(2026, 5, 17, 14, 0, tzinfo=timezone.utc),
        "sections": {
            "Launches": [{
                "title": "Test launch",
                "url": "https://example.com/1",
                "source": "hn",
                "published_at": "2026-05-17 13:00",
                "why_it_matters": "Because.",
            }],
        },
    }
    output = tmp_path / "test.pdf"
    render_digest_pdf(digest_data, output_path=output)
    assert output.exists()
    assert output.stat().st_size > 1000  # not a trivial empty PDF
