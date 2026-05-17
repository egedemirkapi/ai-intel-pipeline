# AI Intel Pipeline — Design

**Date:** 2026-05-17
**Owner:** Ege
**Status:** Approved (pending spec review)

## Goal

Build a multi-agent monitoring + curation pipeline that emails Ege a PDF digest of the top 50 AI ecosystem updates **every 2 hours**.

**Why:** Ege is wedge-hunting for the next startup. He needs to be fluent in real-time AI ecosystem signal — funding rounds, viral product launches, big-co announcements, research drops, founder commentary — to spot patterns and find his opportunity. Manual reading doesn't scale to dozens of sources updating constantly.

**Success criteria:**
1. PDF arrives at `egedemirkapi@gmail.com` every 2 hours, reliably.
2. Every item is **real** (no hallucinations, no fabricated headlines).
3. Every item is **fresh** (occurred in the prior 2-hour window — hard filter).
4. Top 50 are **actually significant** (Ege would rank ≥40 of them as relevant in a manual check).

## Non-Goals (Out of Scope for v1)

- Twitter/X monitoring (skip until proven need — API is $100/mo)
- LinkedIn monitoring (no viable API path)
- Action-taking by agents (monitor-only, never reply/post/transact)
- Personalization beyond the static scoring rubric (no ML feedback loops yet)
- Web UI / dashboard (email is the only surface)
- OpenClaw integration (deferred — covered in Phase 2 doc)

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    COLLECTORS (Python, no LLM)                  │
│        runs every 5 minutes via APScheduler                     │
│                                                                 │
│  ├── rss_collector.py — RSS feeds (TechCrunch, a16z, YC, etc.) │
│  ├── hn_collector.py  — Hacker News API (top + new)            │
│  ├── ph_collector.py  — Product Hunt API                       │
│  └── watchlist_collector.py — Custom domains/blogs             │
└────────────────────────┬────────────────────────────────────────┘
                         │ inserts raw items
                         ▼
                ┌────────────────┐
                │    SQLite      │   schema: items(id, source,
                │   items.db     │   url, title, body, published_at,
                └────────┬───────┘   collected_at, tags, score, ...)
                         │
                         │ on insert
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│             ENRICHMENT (Claude Haiku, async batch)              │
│                                                                 │
│  For each new item:                                             │
│   - Classify: funding | launch | research | hire | viral | misc │
│   - Tag entities: companies, people, technologies               │
│   - Pre-score significance 1-10                                 │
│   - Skip if not AI/ML-relevant (saves Opus tokens later)        │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         │ every 2 hours (cron: 0 */2 * * *)
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│             MASTER ANALYST (Claude Opus, single call)           │
│                                                                 │
│  Input:  all items from last 2h with pre-scores                 │
│  Process:                                                       │
│   1. Filter to AI-relevant items only                           │
│   2. Re-rank using scoring rubric (see below)                   │
│   3. Pick top 50                                                │
│   4. Write 1-2 sentence "why this matters" for each             │
│   5. Group into sections (Funding / Launches / Research / etc.) │
│   6. Write a 3-sentence executive summary                       │
│  Output: structured JSON digest                                 │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│       PDF GENERATOR (Python, WeasyPrint, HTML template)         │
│                                                                 │
│  - Loads Jinja2 template (clean, readable, dark/light)          │
│  - Renders digest JSON → HTML → PDF                             │
│  - Filename: ai-intel-2026-05-17-1400.pdf                       │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│              EMAIL (Resend API, with PDF attached)              │
│                                                                 │
│  - To: egedemirkapi@gmail.com                                   │
│  - Subject: "AI Intel · 2026-05-17 14:00 · 50 items"            │
│  - Body: 3-line exec summary + "PDF attached"                   │
└─────────────────────────────────────────────────────────────────┘
```

## Components

### 1. Collectors (`collectors/`)

Pure Python data fetchers. **No LLM calls.** Each collector:
- Has a `fetch_since(timestamp) → list[Item]` interface
- Deduplicates by URL hash before inserting
- Logs success/failure to stdout (captured by host)
- Fails silently on individual source errors (one bad feed shouldn't break the run)

**Sources for v1:**

| Source | Type | Endpoint | Notes |
|---|---|---|---|
| Hacker News | API | `hacker-news.firebaseio.com` | Filter: title contains AI/ML/Anthropic/OpenAI/LLM/agent/etc. |
| Product Hunt | GraphQL API | `api.producthunt.com/v2/api/graphql` | Free token, daily launches |
| TechCrunch | RSS | `techcrunch.com/feed/` | AI category filter post-fetch |
| The Verge | RSS | `theverge.com/rss/index.xml` | AI keyword filter |
| VentureBeat | RSS | `venturebeat.com/feed/` | AI keyword filter |
| a16z | RSS | `a16z.com/feed/` | All posts kept |
| YC Blog | RSS | `ycombinator.com/blog/rss` | All posts kept |
| Anthropic News | RSS | `anthropic.com/news/rss` | All posts kept |
| OpenAI Blog | RSS | `openai.com/blog/rss.xml` | All posts kept |
| DeepMind | RSS | `deepmind.com/blog/rss.xml` | All posts kept |
| Stratechery | RSS | `stratechery.com/feed/` | AI/tech filter |
| Pragmatic Engineer | RSS | Substack feed | All posts kept |
| Latent Space | RSS | Substack feed | All posts kept |
| Crunchbase News | RSS | `news.crunchbase.com/feed/` | Funding-tagged filter |
| Watchlist | File | `config/watchlist.txt` | User-editable: one domain or RSS URL per line |

### 2. Storage (`db/`)

SQLite at `data/items.db`. Schema:

```sql
CREATE TABLE items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,             -- 'hn', 'rss:techcrunch', etc.
    url TEXT NOT NULL UNIQUE,
    url_hash TEXT NOT NULL UNIQUE,    -- sha256 for fast dedup
    title TEXT NOT NULL,
    body TEXT,                        -- full text if available, else excerpt
    author TEXT,
    published_at TIMESTAMP NOT NULL,  -- source's reported timestamp
    collected_at TIMESTAMP NOT NULL,  -- when we fetched it
    classification TEXT,              -- enrichment result
    entities_json TEXT,               -- {"companies": [...], "people": [...]}
    pre_score INTEGER,                -- enrichment 1-10
    sent_in_digest_at TIMESTAMP,      -- NULL until included in a sent digest
    raw_json TEXT                     -- original source payload for debugging
);

CREATE INDEX idx_published ON items(published_at);
CREATE INDEX idx_sent ON items(sent_in_digest_at);

CREATE TABLE digests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    window_start TIMESTAMP NOT NULL,
    window_end TIMESTAMP NOT NULL,
    items_considered INTEGER,
    items_selected INTEGER,
    summary TEXT,
    pdf_path TEXT,
    sent_at TIMESTAMP,
    sent_to TEXT
);
```

### 3. Enrichment (`enrichment/`)

`enrich_item.py` — runs after collector inserts. Async, batched (10 items per Haiku call).

**Prompt template** (lives in `prompts/enrichment.txt`):

```
You are an AI ecosystem analyst. For each item below, return strict JSON:

{
  "classification": "funding" | "launch" | "research" | "hire" | "viral" | "misc",
  "ai_relevance": 0.0-1.0,
  "entities": {"companies": [], "people": [], "technologies": []},
  "pre_score": 1-10,
  "skip_reason": null | "<short reason>"
}

Significance heuristics:
- funding: dollar amount, stage, novelty of company
- launch: traction signals, technical novelty
- research: paper quality, citations, surprise factor
- viral: engagement, who's reacting
- hire: only senior moves at top-tier labs

Items: [...]
```

Items where `ai_relevance < 0.3` are marked `skip_reason="not AI relevant"` and excluded from the digest queue (kept in DB for audit).

### 4. Master Analyst (`analyst/`)

`run_digest.py` — runs every 2 hours.

Steps:
1. Query: items where `published_at >= now - 2h` AND `ai_relevance >= 0.3` AND `sent_in_digest_at IS NULL`.
2. If <10 items, send a "low signal window" mini-digest instead.
3. Otherwise, send all items + their metadata to Opus with the scoring rubric prompt.
4. Opus returns ranked top 50 + summary.
5. Validate response (50 items present, all have valid URLs in our DB).
6. On validation failure, retry once. On second failure, fall back to pre_score ranking.
7. Mark selected items `sent_in_digest_at = now` after PDF is sent.

**Scoring rubric** (lives in `prompts/analyst.txt`):

```
You are picking the 50 most important AI ecosystem updates from the last 2 hours.

Ranking criteria (in priority order):
1. SIGNIFICANCE — Would a senior AI investor / serious founder care?
   - Big funding (>$10M): high
   - Notable product launches with traction: high
   - Major research releases from top labs: high
   - Pricing/policy changes from frontier labs: high
   - Generic AI news without specifics: low

2. NOVELTY — Is this new info or rehash?
   - First report of something: high
   - Echo/commentary: lower unless from a high-signal voice

3. PATTERN SIGNAL — Does it hint at an emerging market?
   - Multiple companies attacking same wedge: boost
   - New vertical getting funded: boost

4. EGE'S CONTEXT — Solo founder hunting opportunities.
   - Weight: startup launches, vertical-AI wedges, agent infrastructure, dev tools.
   - Down-weight: enterprise sales news, big-co reorgs without product impact.

HARD RULES:
- Never fabricate items. Only rank items provided.
- Never inflate dollar amounts or add details not in the source.
- If unsure, lower the score.

Return strict JSON: {summary, top_50: [{item_id, rank, why_it_matters}]}
```

### 5. PDF Generator (`pdf/`)

`render_pdf.py`:
- Loads Jinja2 template (`templates/digest.html`)
- Sections: Executive Summary → Funding → Launches → Research → Viral → Misc
- Each item: title (linked) · source · 1-2 sentence "why this matters"
- WeasyPrint renders HTML → PDF
- Save to `output/ai-intel-YYYY-MM-DD-HHMM.pdf`

### 6. Email (`mailer/`)

Renamed from `email/` to avoid shadowing Python's stdlib `email` module.

`send_digest.py` — uses Resend SDK.
- API key from env: `RESEND_API_KEY`
- From: `onboarding@resend.dev` (Resend's default sender — zero DNS setup for v1; migrate to `intel@evasocial.ai` later if delivery becomes an issue)
- To: `egedemirkapi@gmail.com` (from config, overridable)
- Subject: `AI Intel · {YYYY-MM-DD HH:MM} · {N} items`
- Body: HTML with the executive summary + "PDF attached"
- Attachment: the generated PDF
- On failure: log + retry once with exponential backoff. Persistent failure raises alert.

### 7. Scheduler (`scheduler.py`)

APScheduler running in the same process as collectors/analyst:
- Every 5 min: `run_all_collectors()`
- Every 5 min (offset 2 min): `enrich_new_items()` — picks up anything not yet enriched
- Every 2 hours on the hour (00:00, 02:00, 04:00, ...): `generate_and_send_digest()`

## Data Flow

```
Source → Collector → SQLite (raw)
                       ↓
                    Haiku enrichment → SQLite (enriched)
                       ↓
              [every 2h] Opus master analyst → top 50 JSON
                       ↓
                    PDF render → output/
                       ↓
                    Resend send → Ege's inbox
                       ↓
                    Mark sent_in_digest_at
```

## Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.11+ | Best ecosystem for scraping + scheduling + LLM SDKs |
| HTTP framework | FastAPI (admin endpoints + health checks) | Lightweight, async-friendly |
| Scheduler | APScheduler | In-process cron, no external dependencies |
| HTTP client | httpx | Async-native |
| RSS | feedparser | Standard |
| HTML parsing | beautifulsoup4 | For article bodies |
| LLM | anthropic Python SDK | Official, supports OAuth from setup-token |
| DB | SQLite via sqlmodel | Single-file, zero infra |
| PDF | WeasyPrint | HTML→PDF, best output quality |
| Templates | Jinja2 | Standard |
| Email | resend Python SDK | Simple API, 100 free emails/day |
| Hosting | Render.com web service | Free tier viable; $7/mo for guaranteed uptime |
| Secrets | `.env` (local) + Render env vars (prod) | Standard |

## Configuration

`config/config.yaml`:
```yaml
delivery:
  email_to: egedemirkapi@gmail.com
  digest_window_hours: 2
  schedule_cron: "0 */2 * * *"

llm:
  enrichment_model: claude-haiku-4-5-20251001
  analyst_model: claude-opus-4-7
  auth_mode: oauth_setup_token  # uses ANTHROPIC_API_KEY from claude setup-token

scoring:
  ai_relevance_threshold: 0.3
  min_items_for_full_digest: 10
  top_n: 50

sources:
  enabled:
    - hn
    - product_hunt
    - rss_techcrunch
    - rss_verge
    - rss_venturebeat
    - rss_a16z
    - rss_yc
    - rss_anthropic
    - rss_openai
    - rss_deepmind
    - rss_stratechery
    - rss_pragmatic_engineer
    - rss_latent_space
    - rss_crunchbase
    - watchlist
```

`config/watchlist.txt`:
```
# One RSS URL or domain per line. Lines starting with # are ignored.
# Add companies, blogs, newsletters Ege specifically wants tracked.
mindra.ai
caretta.ai
hockeystack.com
```

## Error Handling

| Failure | Behavior |
|---|---|
| One collector fails | Log, continue with others. Alert if same collector fails 3 cycles in a row. |
| Haiku enrichment fails | Retry once. On second failure, store item without enrichment, exclude from digest. |
| Opus returns malformed JSON | Retry once with stricter prompt. On second failure, fall back to pre_score ranking. |
| Opus hallucinates items not in our DB | Validation strips them. Log warning. |
| PDF generation fails | Email a text-only digest with item list. Alert. |
| Resend API down | Retry with exponential backoff (1, 5, 25 min). After 3 retries, write to `output/failed/` for manual send. |
| Rate limit on Haiku enrichment (429) | Detect, exponential backoff, halve batch size. |
| Rate limit on Opus analyst (429) | Wait full retry-after duration (Opus call is single critical), retry up to 3x. If still failing, fall back to pre_score ranking and send digest with "limited analysis" header note. |
| DB locked | SQLite WAL mode + retry. |

## Anti-Hallucination Measures

The user explicitly required: **agents must collect real info, not hallucinate**. Enforcement:

1. **Collectors never generate content.** They only fetch + parse from real URLs. No LLM in collection layer.
2. **Enrichment LLM only adds metadata** (classification, tags). It can't invent new items — its input is strict JSON of real items.
3. **Master analyst is strictly told**: "Only rank items provided. Never fabricate. Never inflate facts."
4. **Validation layer**: After Opus runs, every selected `item_id` is checked against the DB **AND verified to have `published_at` within the active 2-hour window**. Items failing either check are stripped from output (with warning logged). This is the enforcement gate, not the SQL filter alone.
5. **Source URL is always shown** in the PDF alongside every item — Ege can click through to verify.
6. **2-hour window enforcement**: SQL query filters by `published_at`, not by Opus's judgment. Opus cannot include older items.

## Deployment

**v1 target: Render.com web service**
- Single Python service running collectors + scheduler + analyst + email in one process
- Render Free tier (sleeps after inactivity) — NOT viable for "always-on monitoring"
- Render $7/mo Starter — viable, 24/7 uptime
- Persistent disk add-on for `data/items.db` and `output/*.pdf`

**Local-first option:** Run via `python -m ai_intel_pipeline` on Ege's laptop with cron. Free but laptop must stay on.

**Recommendation:** Start local for the first 48 hours to verify correctness, then deploy to Render.

## Project Structure

```
ai-intel-pipeline/
├── README.md
├── pyproject.toml
├── .env.example
├── .gitignore
├── config/
│   ├── config.yaml
│   └── watchlist.txt
├── src/
│   └── ai_intel/
│       ├── __init__.py
│       ├── __main__.py             # entry point
│       ├── scheduler.py
│       ├── collectors/
│       │   ├── __init__.py
│       │   ├── base.py
│       │   ├── rss.py
│       │   ├── hn.py
│       │   ├── product_hunt.py
│       │   └── watchlist.py
│       ├── enrichment/
│       │   ├── __init__.py
│       │   └── enrich.py
│       ├── analyst/
│       │   ├── __init__.py
│       │   └── digest.py
│       ├── pdf/
│       │   ├── __init__.py
│       │   ├── render.py
│       │   └── templates/
│       │       └── digest.html
│       ├── mailer/
│       │   ├── __init__.py
│       │   └── send.py
│       └── db/
│           ├── __init__.py
│           ├── models.py
│           └── migrations/
├── prompts/
│   ├── enrichment.txt
│   └── analyst.txt
├── data/
│   └── .gitkeep                    # items.db lives here
├── output/
│   └── .gitkeep                    # PDFs land here
├── tests/
│   ├── test_collectors.py
│   ├── test_enrichment.py
│   ├── test_analyst.py
│   └── test_e2e.py
├── docs/
│   └── superpowers/
│       └── specs/
│           └── 2026-05-17-ai-intel-pipeline-design.md
└── render.yaml                     # deployment config
```

## Testing Strategy

- **Unit**: each collector tested with recorded HTTP responses (vcr.py)
- **Integration**: enrichment + analyst tested with fixture items, real LLM calls in CI-skipped suite (manually run before deploy)
- **E2E smoke**: full pipeline against fixtures, asserts PDF generated and email-mock called

## Future Phases (Out of Scope for v1)

- **Phase 2**: Add Twitter via paid API ($100/mo) once we confirm RSS+HN coverage gaps.
- **Phase 3**: Move always-on monitoring to OpenClaw server with webhook ingestion (vs polling). Adds: real-time alerts for "huge news" events (>$100M funding, frontier model release) outside the 2-hour cycle.
- **Phase 4**: Personalization — track which items Ege clicks through to, feed back into ranking.
- **Phase 5**: Pattern detection — second-order analysis ("3 companies got funded this week in voice agents → that's a pattern").

## Resolved Decisions

1. **Sender address (v1):** `onboarding@resend.dev` — Resend's default, zero DNS setup. Migrate to `intel@evasocial.ai` if deliverability suffers.
2. **First-cycle backfill:** First digest includes items from the past **24 hours** (not just 2h), so Ege gets immediate value. Cycle 2+ uses strict 2h window. Implemented as a `--backfill-hours` CLI flag, default 24 on first run, 2 thereafter.
3. **Watchlist seed items:** Start with Mindra, Caretta, Hockeystack. Ege adds more anytime via `config/watchlist.txt`.
