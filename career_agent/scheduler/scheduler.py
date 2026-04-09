"""APScheduler daemon — daily scrape at 08:00 and weekly report on Sundays at 09:00."""
from __future__ import annotations

import asyncio
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger


def _parse_time(time_str: str) -> tuple[int, int]:
    h, m = time_str.split(":")
    return int(h), int(m)


def build_scheduler(settings: dict[str, Any]) -> AsyncIOScheduler:
    """Create and configure the APScheduler instance from settings."""
    sched_cfg = settings.get("scheduling", {})
    scrape_time = sched_cfg.get("scrape_time", "08:00")
    report_time = sched_cfg.get("report_time", "09:00")
    report_day = sched_cfg.get("report_day", "sunday")[:3].lower()  # "sun"
    timezone = sched_cfg.get("timezone", "Asia/Jerusalem")

    scrape_h, scrape_m = _parse_time(scrape_time)
    report_h, report_m = _parse_time(report_time)

    scheduler = AsyncIOScheduler(timezone=timezone)

    scheduler.add_job(
        _run_daily_scrape,
        CronTrigger(hour=scrape_h, minute=scrape_m, timezone=timezone),
        id="daily_scrape",
        name="Daily job scrape + filter",
        replace_existing=True,
        kwargs={"settings": settings},
    )

    scheduler.add_job(
        _run_weekly_report,
        CronTrigger(day_of_week=report_day, hour=report_h, minute=report_m, timezone=timezone),
        id="weekly_report",
        name="Weekly markdown report",
        replace_existing=True,
    )

    return scheduler


async def _run_daily_scrape(settings: dict[str, Any]) -> None:
    """Invoked by the scheduler — runs the full scrape+filter pipeline."""
    from career_agent.pipeline import run_pipeline
    logger.info("[scheduler] Starting daily scrape")
    try:
        stats = await run_pipeline(settings)
        logger.info(
            f"[scheduler] Daily scrape complete — "
            f"new: {stats['new']}, skipped: {stats['skipped']}"
        )
    except Exception as e:
        logger.error(f"[scheduler] Daily scrape failed: {e}")


async def _run_weekly_report() -> None:
    """Invoked by the scheduler — generates the weekly report."""
    from career_agent.reporter.weekly_report import generate_weekly_report
    logger.info("[scheduler] Generating weekly report")
    try:
        path = generate_weekly_report()
        logger.info(f"[scheduler] Weekly report saved: {path}")
    except Exception as e:
        logger.error(f"[scheduler] Weekly report failed: {e}")


async def start_scheduler(settings: dict[str, Any]) -> None:
    """Start the scheduler and run until interrupted."""
    scheduler = build_scheduler(settings)
    scheduler.start()
    logger.info(
        f"[scheduler] Started. Daily scrape at {settings.get('scheduling', {}).get('scrape_time', '08:00')}, "
        f"weekly report on {settings.get('scheduling', {}).get('report_day', 'sunday')}s."
    )
    try:
        while True:
            await asyncio.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        logger.info("[scheduler] Stopped.")
