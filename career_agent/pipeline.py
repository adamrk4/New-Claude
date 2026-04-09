"""Core pipeline — scrape → filter → upsert → return stats."""
from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger

from career_agent.db.repository import job_exists, skip_job, upsert_job
from career_agent.filters.job_filter import FilterConfig, apply_filters, build_filter_config
from career_agent.models.job import JobListing
from career_agent.scrapers.alljobs import AllJobsScraper
from career_agent.scrapers.company_careers import CompanyCareersScraper
from career_agent.scrapers.drushim import DrushimScraper
from career_agent.scrapers.glassdoor import GlassdoorScraper
from career_agent.scrapers.indeed import IndeedScraper
from career_agent.scrapers.linkedin import LinkedInScraper


async def run_pipeline(settings: dict[str, Any]) -> dict[str, int]:
    """
    Run the full scrape → filter → upsert pipeline.
    Returns a stats dict: {"scraped": n, "new": n, "skipped": n, "duplicate": n}.
    """
    scraper_cfg = settings.get("scrapers", {})
    filter_cfg = build_filter_config(settings)
    include_kws = settings.get("filters", {}).get("include_keywords", [])

    # Build enabled scrapers
    scrapers = []
    if scraper_cfg.get("linkedin", {}).get("enabled", True):
        scrapers.append(LinkedInScraper(scraper_cfg.get("linkedin", {})))
    if scraper_cfg.get("alljobs", {}).get("enabled", True):
        scrapers.append(AllJobsScraper(scraper_cfg.get("alljobs", {})))
    if scraper_cfg.get("drushim", {}).get("enabled", True):
        scrapers.append(DrushimScraper(scraper_cfg.get("drushim", {})))
    if scraper_cfg.get("glassdoor", {}).get("enabled", True):
        scrapers.append(GlassdoorScraper(scraper_cfg.get("glassdoor", {})))
    if scraper_cfg.get("indeed", {}).get("enabled", True):
        scrapers.append(IndeedScraper(scraper_cfg.get("indeed", {})))
    if scraper_cfg.get("company_careers", {}).get("enabled", True):
        scrapers.append(
            CompanyCareersScraper(
                scraper_cfg.get("company_careers", {}),
                include_keywords=include_kws,
            )
        )

    # Run scrapers (non-Playwright ones can run concurrently; Playwright ones are sequential
    # to avoid spawning too many browsers — they already run async internally)
    all_jobs: list[JobListing] = []
    tasks = [scraper.scrape() for scraper in scrapers]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for scraper, result in zip(scrapers, results):
        if isinstance(result, Exception):
            logger.error(f"Scraper {scraper.source} raised: {result}")
        else:
            all_jobs.extend(result)

    logger.info(f"[pipeline] Total scraped: {len(all_jobs)}")

    stats = {"scraped": len(all_jobs), "new": 0, "skipped": 0, "duplicate": 0}

    for job in all_jobs:
        # Skip duplicates (already in DB)
        if job_exists(job.source, job.external_id):
            stats["duplicate"] += 1
            continue

        # Apply filters
        result = apply_filters(job, filter_cfg)
        record = upsert_job(job)

        if not result.passed:
            skip_job(record.id, result.reason)
            stats["skipped"] += 1
            logger.debug(f"[pipeline] SKIP '{job.title}' @ {job.company}: {result.reason}")
        else:
            stats["new"] += 1
            logger.info(f"[pipeline] NEW  '{job.title}' @ {job.company} ({job.source})")

    logger.info(
        f"[pipeline] Done — new: {stats['new']}, "
        f"skipped: {stats['skipped']}, duplicate: {stats['duplicate']}"
    )
    return stats
