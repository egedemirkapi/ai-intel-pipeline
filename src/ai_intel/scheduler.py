# src/ai_intel/scheduler.py
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx
import yaml
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from ai_intel.collectors.registry import build_collectors_from_config
from ai_intel.collectors.runner import run_all_collectors
from ai_intel.enrichment.runner import enrich_new_items
from ai_intel.maintenance import run_daily_maintenance
from ai_intel.pipeline import generate_and_send_digest

logger = logging.getLogger(__name__)


def load_config() -> dict:
    return yaml.safe_load(Path("config/config.yaml").read_text(encoding="utf-8"))


def build_scheduler(engine, config: dict, first_run: bool = False) -> AsyncIOScheduler:
    sched = AsyncIOScheduler(timezone="UTC")
    collectors = build_collectors_from_config(config)
    enrich_model = config["llm"]["enrichment_model"]
    analyst_model = config["llm"]["analyst_model"]
    email_to = config["delivery"]["email_to"]
    window_hours = config["delivery"]["digest_window_hours"]
    output_dir = Path("output")

    brief_cfg = config.get("briefing", {}) or {}
    brain_url = brief_cfg.get("brain_url", "http://127.0.0.1:9999").rstrip("/")

    async def collect_job():
        # 24h window so slow RSS feeds (weekly newsletters, etc.) get caught.
        # DB-level url_hash dedup prevents duplicates across overlapping cycles.
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        result = await run_all_collectors(engine, collectors, since=since)
        logger.info(f"Collect cycle: {result}")
        # Tell the Brain new intel landed so the dashboard feed refreshes
        # live (the collector and Brain are separate processes).
        new_items = sum(
            v for k, v in result.items()
            if k != "failures" and isinstance(v, int)
        )
        if new_items > 0:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    await client.post(
                        f"{brain_url}/events/intel",
                        json={
                            "count": new_items,
                            "sources": [
                                k for k, v in result.items()
                                if k != "failures" and isinstance(v, int) and v > 0
                            ],
                        },
                    )
            except Exception as exc:
                logger.debug("intel-event push failed (Brain not running?): %s", exc)

    async def enrich_job():
        n = await enrich_new_items(engine, model=enrich_model)
        logger.info(f"Enriched {n} items")

    async def digest_job():
        actual_window = 24 if first_run else window_hours
        result = await generate_and_send_digest(
            engine=engine, output_dir=output_dir,
            window_hours=actual_window, model=analyst_model, email_to=email_to,
        )
        logger.info(f"Digest sent: {result}")

    async def maintenance_job():
        # Daily prune of audit-table churn so AgentRun + SaturationAssessment
        # don't grow unbounded over 24/7 operation.
        summary = run_daily_maintenance(engine)
        logger.info("Maintenance prune: %s", summary)

    async def briefing_job():
        # Assemble the daily brief and hand it to the Brain's speak queue;
        # the voice tray polls that queue and reads it aloud. Degrades
        # quietly if the Brain isn't running.
        from ai_intel.think.brief import build_brief
        brief = await build_brief(engine)
        spoken = brief.get("spoken", "")
        if not spoken:
            return
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(
                    f"{brain_url}/speak",
                    json={"text": spoken, "kind": "briefing"},
                )
            logger.info("Briefing queued for the voice tray")
        except Exception as exc:
            logger.warning("Briefing push failed (is the Brain running?): %s", exc)

    # 15-minute misfire grace: a laptop sleeping/waking suspends APScheduler,
    # and a too-small grace makes the job "misfire" and skip — collection
    # would silently stall after every sleep. 900s lets it resume cleanly.
    sched.add_job(collect_job, "interval", minutes=5, id="collect", misfire_grace_time=900)
    sched.add_job(
        enrich_job, "interval", minutes=5, id="enrich",
        misfire_grace_time=900,
        next_run_time=datetime.now(timezone.utc) + timedelta(minutes=2),
    )
    sched.add_job(digest_job, "cron", hour="*/2", minute=0, id="digest", misfire_grace_time=300)
    sched.add_job(
        maintenance_job, "cron", hour=4, minute=0,
        id="maintenance", misfire_grace_time=3600,
    )
    if brief_cfg.get("enabled", True):
        sched.add_job(
            briefing_job, "cron",
            hour=brief_cfg.get("hour", 6), minute=brief_cfg.get("minute", 0),
            id="briefing", misfire_grace_time=600,
        )
    return sched
