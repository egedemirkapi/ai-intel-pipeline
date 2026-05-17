from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright

TEMPLATE_DIR = Path(__file__).parent / "templates"


def render_digest_pdf(digest_data: dict, output_path: Path) -> None:
    """Render the digest data to a PDF using Playwright (HTML→Chromium→PDF)."""
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
    template = env.get_template("digest.html")
    html_str = template.render(
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        **digest_data,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html_str, wait_until="load")
        page.pdf(
            path=str(output_path),
            format="A4",
            margin={"top": "0.5in", "right": "0.5in", "bottom": "0.5in", "left": "0.5in"},
            print_background=True,
        )
        browser.close()
