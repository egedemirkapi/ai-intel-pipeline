# AI Intel Pipeline

An always-on AI ecosystem monitoring pipeline that polls RSS feeds, Hacker News, and Product Hunt every 5 minutes, uses Claude Haiku to enrich each item, and lets Claude Opus rank the top 50 items every 2 hours. The result is a PDF digest delivered to your inbox on a fixed schedule, with every item linked back to its source URL so nothing is invented.

---

## Quick start (local)

1. Clone and enter the repo:
   ```
   git clone https://github.com/your-handle/ai-intel-pipeline.git
   cd ai-intel-pipeline
   ```

2. Create and activate a virtual environment:
   ```
   python -m venv .venv && source .venv/Scripts/activate
   ```
   On macOS/Linux use `source .venv/bin/activate` instead.

3. Install dependencies:
   ```
   pip install -e ".[dev]"
   ```

4. Install Playwright's Chromium (used to render the PDF):
   ```
   playwright install chromium
   ```

5. Copy the example env file and fill in your keys:
   ```
   cp .env.example .env
   ```
   - `ANTHROPIC_API_KEY` — run `claude setup-token` or copy from console.anthropic.com
   - `RESEND_API_KEY` — free at resend.com (100 emails/day on the free tier)
   - `PRODUCT_HUNT_TOKEN` — optional; Product Hunt API key from producthunt.com/v2/oauth/applications

6. Run:
   ```
   python -m ai_intel
   ```

---

## What happens on first run

The pipeline does a 24-hour backfill so you get value immediately. It collects every enabled source back 24 hours, enriches all new items, ranks the top 50, generates a PDF, and emails it to the address in `config/config.yaml`. That first email arrives within roughly 2 minutes. After that, the scheduler takes over: collection every 5 minutes, digest every 2 hours.

---

## Customizing sources

**RSS feeds** — edit `config/watchlist.txt`. Add one URL or domain per line. Lines starting with `#` are ignored. The pipeline auto-discovers RSS for bare domains.

**Toggling built-in sources** — edit `config/config.yaml` under `sources.enabled`. Remove or add any of: `hn`, `product_hunt`, `rss_techcrunch`, `rss_verge`, `rss_venturebeat`, `rss_a16z`, `rss_yc`, `rss_anthropic`, `rss_openai`, `rss_deepmind`, `rss_stratechery`, `rss_pragmatic_engineer`, `rss_latent_space`, `rss_crunchbase`, `watchlist`.

---

## Changing the schedule

Edit `config/config.yaml`:

- `delivery.digest_window_hours` — how many hours each digest covers (default: 2)
- `delivery.schedule_cron` — when digests are sent, in standard cron format (default: `"0 */2 * * *"`, i.e. every 2 hours on the hour)

---

## Deploy to Render

1. Push this repo to GitHub.
2. Go to render.com, click "New > Blueprint", and connect the repo. Render auto-detects `render.yaml`.
3. In the Render dashboard, set the three secret env vars: `ANTHROPIC_API_KEY`, `RESEND_API_KEY`, `PRODUCT_HUNT_TOKEN`.
4. Click "Deploy". The `starter` plan ($7/mo) keeps the service always-on so the scheduler never sleeps.

The 1 GB persistent disk is mounted at `/opt/render/project/src/data` and stores the SQLite database between deploys.

---

## Project structure

```
src/ai_intel/
    collectors/     RSS, HN, Product Hunt, watchlist collectors + runner
    enrichment/     Haiku enrichment — relevance score, summary, classification
    analyst/        Opus ranking prompt + anti-hallucination validation gate
    pdf/            Jinja2 HTML template + Playwright PDF renderer + section grouper
    mailer/         Resend email sender
    db/             SQLModel models + SQLite session factory
    pipeline.py     End-to-end orchestration (collect -> enrich -> rank -> pdf -> send)
    scheduler.py    APScheduler wiring (5-min collect, 5-min enrich offset, 2-h digest)
    __main__.py     Entry point with first-run 24h backfill
config/
    config.yaml     Schedule, LLM models, scoring thresholds, enabled sources
    watchlist.txt   Extra RSS URLs / domains to track
```

---

## Tests

```
pytest -v
```

37 tests cover all modules. LLM calls and email sends are fully mocked, so the suite runs offline with no API keys required.

---

## Anti-hallucination guarantees

- Collectors do no LLM work. Every item in the database has a real URL fetched from a live source.
- The validation gate in `analyst/digest.py` discards any `item_id` returned by Opus that does not exist in the current window's database query — Opus cannot invent items.
- The same gate re-checks that every selected item falls within the declared time window, preventing the model from surfacing stale items.
- Every item in the PDF links back to its original source URL, which is stored at collection time and never modified by any LLM step.

---

## Out of scope (Phase 2)

Twitter/X firehose, LinkedIn posts, OpenClaw integration. None of these are in v1.

---

## Tech stack

Python 3.11+, Anthropic SDK (Haiku enrichment + Opus ranking), APScheduler, SQLModel + SQLite, Playwright (PDF), Jinja2, Resend, feedparser, httpx, FastAPI (reserved for Phase 2 API layer).
