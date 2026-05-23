# Founder Profile — Ege

This file describes who's actually behind the proposer. The proposer reads
it on every run to design ideas in domains where the founder has lived
edge — not domains where every other founder also lacks insight. **Edit
this file freely as your context evolves; the proposer picks up changes
immediately.** A user override at `~/.jarvis/founder_profile.md` wins
over this file if present.

## Who

- Builder in Turkey, deeply hands-on across the stack: Next.js dashboards,
  FastAPI Python services, LLM orchestration + embeddings + agent
  pipelines, autostart supervisors, voice + audio loops.
- Engineering-first, ships fast from real friction. Not a sales-led GTM
  founder — works best when the product solves a problem he has
  personally lived and can iterate on with conviction.

## Currently built (deep, not surface-level)

- **24/7 personal AI intel pipeline**: RSS / HN / Reddit / Google News
  collectors, Voyage-3 embeddings, semantic dedup, persona-calibrated
  multi-agent evaluator fleet (saturator + synthesizer + proposer +
  evaluator + `weekly_ideation` orchestrator), trend syntheses on
  schedule, scheduled daily news digests delivered as PDF email.
- **Jarvis personal assistant**: FastAPI brain on `:9999`, voice tray with
  mic-muting-during-TTS, clap detection with crest-factor gating,
  autostart supervisor (revives crashed services with backoff and a
  single-instance guard), capability layer with an append-only approval
  queue, in-app browser navigator over Chrome DevTools Protocol with
  recipe memory for replay.
- **Workflow / routine engine** driven by cron + voice + clap + hotkey +
  app-focus triggers, with a dashboard editor and chat-built automations
  ("every day at 8am email me a PDF of the news" → working workflow).
- **Live web research in chat** — `web.search` + `web.fetch` tools so the
  brain can answer weather / current-news / lookup questions.

## Pains actually felt — not theoretical

- **LLM rate-limit cliffs**: when the OAuth subscription bridge isn't
  running, every agent falls onto the direct Anthropic API and burns its
  Sonnet RPM in seconds. Routing, per-agent budgeting, model-class
  selection, and graceful degradation matter more than benchmark scores.
- **Demo-vs-production gap in agentic AI**: CDP profile-lock when Edge
  is already open, page-snapshot quality on real webapp UIs (Google
  Classroom, NotebookLM), navigator-wandering-and-hitting-step-limit on
  complex pages even when the plumbing works.
- **Multi-account Google complexity**: school workflows under `/u/1`,
  agents routed to `/u/0` by default and reading empty data; no clean
  way for an agent to know which Google account hosts which workflow.
- **Voice-assistant feedback loop**: TTS output coming back through the
  mic and re-triggering wake-word detection; mic-mute-while-speaking
  gymnastics and crest-factor clap detection.
- **Persona / evaluator calibration drift**: anchors disappearing and
  "all ideas scoring 52" syndrome. Tuning the evaluator down is the
  wrong fix; the proposer side has to think harder.
- **Schema drift in long-running pipelines**: `create_all()` builds new
  tables but never alters existing ones, so a new model column silently
  doesn't land in the SQLite DB until a query hits it. (Now fixed with
  a self-healing migration — but the broader lesson is about long-running
  data systems and schema evolution.)
- **Generic agents wandering complex UIs**: watching a navigator burn 25
  steps because its snapshot is too thin, its prompt too vague, and its
  loop doesn't compound on recipe memory yet.
- **OAuth bridge as a missing prerequisite**: the architectural
  assumption that a free / high-headroom OAuth path exists, when the
  bridge isn't actually running anywhere — and everything downstream
  degrades.

## Domains where this founder has an edge

- **AI agent infrastructure & reliability** — orchestration, supervision,
  crash recovery, capability gating, approval queues, retry-with-backoff
  at the right layer. Real systems that survive idle weeks, not demoware.
- **LLM cost & route management** — OAuth subscription bridges, direct-API
  fallback, per-agent model/token budgeting, transient-error handling.
- **Personal & founder productivity tooling for builders** — the kind of
  person who would actually use the thing themselves first.
- **Browser-driving + webapp automation with real-profile auth** — CDP,
  page snapshotting, recipe-memory for replay, edge cases nobody else
  hits because they don't actually run their automation against real
  signed-in browsers.
- **Voice + ambient assistants with always-on supervision** — autostart,
  health probes, the mic-vs-speaker feedback loop, wake-word reliability.
- **Multi-agent debate / persona-based evaluation systems** — anchored
  scoring rubrics, evaluator dissent gating, surfacing the vetoer.
- **Student / study workflows** — Google Classroom, NotebookLM, exam-prep
  loops, daily-briefing routines.

## Don't propose into these (no felt experience, no edge)

- **Regulated-industry compliance** (legal, pharma, finance) unless an
  external pain signal is overwhelming AND the wedge is genuinely
  defensible. No insider angle on these procurements.
- **Sales / GTM / outbound-driven plays** — engineering-first founder,
  not a closer.
- **Consumer family / home-life products** — wrong life context.
- **Enterprise procurement (IT-buyer-driven sales)** — wrong access pattern.
- **Pure infrastructure middleware** ("abstraction layer across vendors")
  unless a network or data effect makes it more than a temporary
  vendor-fragmentation gap.
- **Creator-economy tools for non-builders** (video editors, content
  creators) — not the founder's life, not his pain.

## How the proposer should use this

When designing an idea:

1. **Match it to a lived pain or edge domain above.** If you can't, the
   idea is structurally weak — pivot the angle until it lands somewhere
   this founder can actually move fast.
2. **Use the founder's existing built systems as wedges.** This pipeline,
   the agent fleet, Jarvis, the navigator — they're already running
   surface area. An idea that extends or productizes one of them is
   stronger than an idea that requires standing up new domain expertise.
3. **Avoid the don't-propose list unless the why-now overrides** —
   external pain signal, defensible wedge, and no other reasonable angle.
