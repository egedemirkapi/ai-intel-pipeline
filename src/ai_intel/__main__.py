# src/ai_intel/__main__.py
import argparse
import asyncio
import logging
import signal
from datetime import datetime, timezone, timedelta
from pathlib import Path

from dotenv import load_dotenv

from ai_intel.collectors.registry import build_collectors_from_config
from ai_intel.collectors.runner import run_all_collectors
from ai_intel.db.session import get_engine, init_db
from ai_intel.enrichment.runner import enrich_new_items
from ai_intel.logging_config import setup_logging
from ai_intel.pipeline import generate_and_send_digest
from ai_intel.scheduler import build_scheduler, load_config


async def run_first_digest_now(engine, config):
    """First-cycle backfill: 24h window so Ege gets immediate value on first run."""
    log = logging.getLogger(__name__)
    log.info("Running first-cycle backfill (24h window)...")
    collectors = build_collectors_from_config(config)
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    await run_all_collectors(engine, collectors, since=since)
    await enrich_new_items(engine, model=config["llm"]["enrichment_model"])
    await generate_and_send_digest(
        engine=engine,
        output_dir=Path("output"),
        window_hours=24,
        model=config["llm"]["analyst_model"],
        email_to=config["delivery"]["email_to"],
    )


async def run_once(engine, config):
    """Single-shot pipeline: collect -> enrich -> digest, then exit.

    Designed for cron/GitHub Actions invocation. Honors first-run 24h backfill.
    """
    log = logging.getLogger(__name__)
    is_first_run = not (Path("data") / ".started").exists()
    if is_first_run:
        await run_first_digest_now(engine, config)
        (Path("data") / ".started").touch()
        return

    log.info("Running single-shot pipeline cycle...")
    collectors = build_collectors_from_config(config)
    since = datetime.now(timezone.utc) - timedelta(hours=6)
    await run_all_collectors(engine, collectors, since=since)
    await enrich_new_items(engine, model=config["llm"]["enrichment_model"])
    await generate_and_send_digest(
        engine=engine,
        output_dir=Path("output"),
        window_hours=config["delivery"]["digest_window_hours"],
        model=config["llm"]["analyst_model"],
        email_to=config["delivery"]["email_to"],
    )


async def amain(once: bool):
    load_dotenv()
    setup_logging()
    log = logging.getLogger(__name__)

    config = load_config()
    log.info(
        "Loaded config: enrichment=%s | analyst=%s | email_to=%s | window=%sh",
        config["llm"]["enrichment_model"],
        config["llm"]["analyst_model"],
        config["delivery"]["email_to"],
        config["delivery"]["digest_window_hours"],
    )

    import os as _os
    ak = _os.getenv("ANTHROPIC_API_KEY", "")
    rk = _os.getenv("RESEND_API_KEY", "")
    log.info(
        "Loaded keys: ANTHROPIC_API_KEY=%s... (len=%d) | RESEND_API_KEY=%s... (len=%d)",
        ak[:14] if ak else "<UNSET>",
        len(ak),
        rk[:6] if rk else "<UNSET>",
        len(rk),
    )
    db_path = Path("data/items.db")
    db_path.parent.mkdir(exist_ok=True)
    engine = get_engine(db_path)
    init_db(engine)

    if once:
        await run_once(engine, config)
        return

    is_first_run = not (Path("data") / ".started").exists()
    if is_first_run:
        await run_first_digest_now(engine, config)
        (Path("data") / ".started").touch()

    scheduler = build_scheduler(engine, config, first_run=False)
    scheduler.start()
    log.info("Scheduler started. Press Ctrl+C to stop.")

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass  # Windows
    await stop_event.wait()
    scheduler.shutdown(wait=False)


def main():
    parser = argparse.ArgumentParser(prog="ai-intel")
    parser.add_argument("--once", action="store_true",
                        help="Run a single collect+enrich+digest cycle and exit")
    args = parser.parse_args()
    asyncio.run(amain(once=args.once))


if __name__ == "__main__":
    main()
