# src/ai_intel/scheduler.py
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from ai_intel.collectors.registry import build_collectors_from_config
from ai_intel.collectors.runner import run_all_collectors
from ai_intel.enrichment.runner import enrich_new_items
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

    async def collect_job():
        # 24h window so slow RSS feeds (weekly newsletters, etc.) get caught.
        # DB-level url_hash dedup prevents duplicates across overlapping cycles.
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        result = await run_all_collectors(engine, collectors, since=since)
        logger.info(f"Collect cycle: {result}")

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

    sched.add_job(collect_job, "interval", minutes=5, id="collect", misfire_grace_time=60)
    sched.add_job(
        enrich_job, "interval", minutes=5, id="enrich",
        misfire_grace_time=60,
        next_run_time=datetime.now(timezone.utc) + timedelta(minutes=2),
    )
    sched.add_job(digest_job, "cron", hour="*/2", minute=0, id="digest", misfire_grace_time=300)
    return sched
