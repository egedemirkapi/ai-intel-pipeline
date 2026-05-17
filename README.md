# AI Intel Pipeline

> **A self-hosted AI ecosystem monitor that emails you a curated digest every 2 hours — so you never miss a major AI launch, funding round, model release, or pattern shift again.**

The AI ecosystem moves faster than any single person can read. New models drop weekly. Vertical-AI startups get funded daily. Patterns emerge in 48 hours and crystallize in two weeks. If you're a founder, investor, or builder, missing the wave means missing the wedge.

**This pipeline solves that.** It runs 24/7, scans 25+ sources (Hacker News, Google News, Reddit, TechCrunch, Anthropic, OpenAI, DeepMind, Stratechery, Latent Space, AI subreddits, and more), uses Claude to rank the 50 most important updates of every 2-hour window, and emails you a beautifully formatted digest with **2-4 sentences of "why this matters" analysis for every item**.

You wake up fluent in AI. You spot patterns before they're priced in.

---

## What you get

Every 2 hours, an email like this lands in your inbox:

```
AI Intel Digest
Generated 2026-05-17 16:24 UTC · 297 items considered · 50 selected

This cycle reveals a maturing AI agent ecosystem competing fiercely on
infrastructure, safety, and verticalization. Three patterns emerge:
(1) Agent Wars Intensify — OpenAI, Anthropic, and Google racing to embed
agents everywhere. (2) The Wedge Widens — voice agents, code agents, and
trading agents are funding heavily. (3) Job Displacement Meets Reality.

FUNDING (9)
─ Anthropic value soars to $900bn on Claude
  google_news · 2026-05-17 13:04
  Anthropic hits $900B valuation after funding round. This is the biggest
  single data point on where investor capital is flowing in AI right now.

─ ElevenLabs Hits $11 Billion After Massive Injection from Activate
  google_news · 2026-05-16 21:26
  Voice synthesis is becoming a critical agent input layer. Pattern alert:
  voice agents are the third major funding wedge (alongside code agents
  and financial agents).

LAUNCHES (29)
─ OpenAI launches workspace agents that can do your work across third-party apps
  ...
```

Each item links back to its source. Nothing fabricated. Zero hallucinations — guaranteed by a validation gate that strips any item IDs the LLM invents.

---

## Cost: $0

| Component | Cost |
|---|---|
| **Anthropic Claude** | **FREE** with a Claude MAX plan via `claude setup-token`, or ~$5–10/month on pay-per-token. Uses Haiku (cheap) for enrichment + analysis. |
| **Resend** (email delivery) | **FREE** — 100 emails/day on the free tier. This pipeline uses **12/day**. |
| **Hosting** | **FREE** if you run it on your own laptop, or **$7/month** for always-on (Render.com Starter). |

That's it. No other paid services. No vendor lock-in.

---

## Quick start (5 minutes)

**Prerequisites:** Python 3.11+, git.

```bash
# 1. Clone
git clone https://github.com/egedemirkapi/ai-intel-pipeline.git
cd ai-intel-pipeline

# 2. Set up venv + install
python -m venv .venv
source .venv/Scripts/activate     # Git Bash on Windows
# source .venv/bin/activate         # macOS / Linux
pip install -e ".[dev]"
playwright install chromium

# 3. Configure
cp .env.example .env
# Open .env and fill in:
#   ANTHROPIC_API_KEY=<from `claude setup-token` or console.anthropic.com>
#   RESEND_API_KEY=<from resend.com (free)>
#   EMAIL_TO=<your email>

# 4. Run
python -m ai_intel
```

That's it. **The first email lands in ~3 minutes** (24-hour backfill on first run). After that, the scheduler sends a fresh digest every 2 hours, forever.

---

## ⚠️ Common gotchas (read this before you start)

These are issues most first-time users hit. **Skim them now, save yourself 30 minutes.** Full fixes in [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

1. **Resend free tier only sends to your own signup email.** If you sign up at resend.com with `alice@gmail.com` and put `EMAIL_TO=bob@gmail.com` in `.env`, every email will bounce with "You can only send testing emails to your own email address." Fix: use the same email for both, OR verify a domain in Resend.

2. **OAuth tokens from `claude setup-token` expire after a few hours.** When you see `401 Unauthorized: invalid x-api-key`, re-run `claude setup-token` and update `.env`. For a permanent fix, get a real API key from [console.anthropic.com](https://console.anthropic.com) (~$5–10/month at this volume).

3. **MAX-plan rate limits are shared.** If you run this pipeline while also using Claude Code, Sonnet/Opus will 429. The default analyst model is **Haiku 4.5** for this reason — it has the most generous limits. Upgrade to Sonnet in `config/config.yaml` if you're not using Claude Code in parallel.

4. **Gmail can block emails containing security-sensitive terms** in titles (e.g. "kernel exploit"). The full digest is embedded in the email HTML body so you still see content even when Gmail strips the PDF attachment.

5. **Windows users need PowerShell venv activation:** `.\.venv\Scripts\Activate.ps1` not `source .venv/Scripts/activate`.

---

## How it works

```
                ┌───────────────────────────────────────────────┐
                │  COLLECTORS (no LLM — pure scrapers)           │
                │  HN · Google News · Reddit · 14 RSS feeds      │
                └─────────────────────┬─────────────────────────┘
                                      │ ~300 items / 2h
                                      ▼
                ┌───────────────────────────────────────────────┐
                │  ENRICHMENT (Claude Haiku)                    │
                │  Classify · score · extract entities          │
                └─────────────────────┬─────────────────────────┘
                                      │ enriched items
                                      ▼
                ┌───────────────────────────────────────────────┐
                │  ANALYST (Claude Haiku/Sonnet/Opus)           │
                │  Rank top 50 · write "why this matters"       │
                │  → ANTI-HALLUCINATION VALIDATION GATE         │
                └─────────────────────┬─────────────────────────┘
                                      ▼
                ┌───────────────────────────────────────────────┐
                │  HTML email + PDF · sent via Resend            │
                └───────────────────────────────────────────────┘
```

Everything runs as one Python process orchestrated by APScheduler. SQLite stores items so nothing is sent twice.

---

## Customizing

**Add your own RSS feeds or specific company blogs:** edit `config/watchlist.txt`.
```
https://example.com/blog/feed
https://anotherco.com/rss.xml
```

**Toggle built-in sources:** edit `config/config.yaml` under `sources.enabled`. Comment out anything you don't want.

**Change frequency:** edit `config/config.yaml`:
- `delivery.digest_window_hours: 2` — how much time each digest covers
- `delivery.schedule_cron: "0 */2 * * *"` — when to send (standard cron)

**Switch to a more capable analyst model:** in `config/config.yaml`, change `analyst_model: claude-haiku-4-5-20251001` to `claude-sonnet-4-6` or `claude-opus-4-7`. Trade-off: smarter analysis vs. higher rate-limit risk on shared MAX quota.

---

## Anti-hallucination guarantees

This is a hard requirement. The pipeline enforces it at four layers:

1. **Collectors do zero LLM work.** Every item in the database has a real URL fetched from a live source.
2. **Enrichment LLM only adds metadata** (classification, score). It cannot invent new items.
3. **Validation gate** discards any `item_id` returned by the analyst that doesn't exist in the current window — the model literally cannot smuggle in fake stories.
4. **Re-check window:** the same gate also verifies every selected item falls inside the declared time window.

Every link in the email goes to the real article. You can verify any claim by clicking.

---

## Deploy 24/7 (so it runs without your laptop)

The repo includes `render.yaml` for one-click Render deploy:

1. Push to GitHub (already done if you cloned this).
2. Go to [render.com](https://render.com), click **New → Blueprint**, connect this repo.
3. Set env vars in the Render dashboard: `ANTHROPIC_API_KEY`, `RESEND_API_KEY`, `EMAIL_TO`.
4. Click Deploy.

Costs $7/month on the Starter plan (always-on). The Free tier sleeps after inactivity, which would break the scheduler — don't use it.

---

## Tests

```bash
pytest -v
```

38 tests, all mocked — no LLM calls, no email sends, no network. Runs in ~4 seconds.

---

## Architecture

```
src/ai_intel/
  collectors/     RSS, HN, Google News, Reddit, Product Hunt, watchlist + runner
  enrichment/     Haiku enrichment (classification, AI relevance, scoring)
  analyst/        Top-50 ranking + "why it matters" prose + validation gate
  pdf/            Jinja2 HTML template + Playwright PDF renderer
  mailer/         Resend email (HTML body + PDF attachment)
  db/             SQLModel + SQLite
  pipeline.py     End-to-end orchestration
  scheduler.py    APScheduler (collect every 5min, digest every 2h)
  __main__.py     Entry point with 24h backfill on first run
config/
  config.yaml     Schedule, models, thresholds, enabled sources
  watchlist.txt   Your custom RSS feeds
prompts/
  enrichment.txt  System prompt for Haiku enrichment
  analyst.txt     System prompt for the master analyst
```

---

## What's NOT here (yet)

- **Twitter/X firehose** — API costs $100/mo for basic tier; not free. Skipped for v1.
- **LinkedIn monitoring** — no viable API path.
- **Personalization feedback loop** — your clicks don't yet improve ranking. Static rubric for now.
- **Web dashboard** — email is the only delivery surface.

PRs welcome for any of these.

---

## Why I built this

I'm a 15-year-old founder hunting for the next wedge in AI. Reading 25 sources manually wasn't sustainable. So I built this in a focused session with [Claude Code](https://claude.com/claude-code) and shipped it open-source because every founder, investor, and serious AI builder needs this.

If it helps you spot your wedge — pay it forward. PRs welcome.

---

## License

MIT. Do whatever you want with it.

---

**Built with [Claude Code](https://claude.com/claude-code).**
