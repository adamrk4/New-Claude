"""LinkedIn scraper — Playwright with persistent auth state and stealth mode."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from loguru import logger

from career_agent.models.job import JobListing
from career_agent.parsers.job_parser import detect_experience_level, strip_html
from career_agent.scrapers.base import AbstractScraper

_LOGIN_URL = "https://www.linkedin.com/login"
_JOBS_URL = (
    "https://www.linkedin.com/jobs/search/"
    "?keywords={keywords}&location={location}"
    "&f_E=1,2&f_TPR=r604800&sortBy=DD"   # f_E=1,2 = Entry level + Associate; last 7 days
)


class LinkedInScraper(AbstractScraper):
    source = "linkedin"

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self._max_jobs = config.get("max_jobs", 50)
        self._keywords = config.get("search_keywords", "Solutions Engineer OR Pre-Sales")
        self._location = config.get("location", "Tel Aviv, Israel")
        self._auth_state_path = config.get("auth_state_path", "data/linkedin_auth.json")
        self._email = None
        self._password = None
        self._load_credentials()

    def _load_credentials(self) -> None:
        import os
        from dotenv import load_dotenv
        load_dotenv()
        self._email = os.getenv("LINKEDIN_EMAIL")
        self._password = os.getenv("LINKEDIN_PASSWORD")

    async def scrape(self) -> list[JobListing]:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error("[linkedin] Playwright not installed. Run: pip install playwright && playwright install chromium")
            return []

        async with async_playwright() as p:
            browser, context = await self._new_browser_context(p, self._auth_state_path)
            page = await context.new_page()

            try:
                await self._ensure_logged_in(page, context)
            except Exception as e:
                logger.error(f"[linkedin] Login failed: {e}")
                await browser.close()
                return []

            results = await self._scrape_jobs(page)
            await self._save_auth_state(context, self._auth_state_path)
            await browser.close()
            return results

    async def _ensure_logged_in(self, page, context) -> None:
        await page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=30000)
        await self._sleep(1, 2)

        # Check if already logged in
        if "feed" in page.url or "mynetwork" in page.url:
            logger.info("[linkedin] Already logged in via saved auth state")
            return

        if not self._email or not self._password:
            raise RuntimeError(
                "LinkedIn credentials not found. Set LINKEDIN_EMAIL and LINKEDIN_PASSWORD in .env"
            )

        logger.info("[linkedin] Logging in...")
        await page.goto(_LOGIN_URL, wait_until="domcontentloaded")
        await page.fill("#username", self._email)
        await page.fill("#password", self._password)
        await self._sleep(0.5, 1.5)
        await page.click('[type="submit"]')
        await page.wait_for_url(re.compile(r"linkedin\.com/(feed|checkpoint|jobs)"), timeout=20000)
        logger.info("[linkedin] Login successful")

    async def _scrape_jobs(self, page) -> list[JobListing]:
        url = _JOBS_URL.format(
            keywords=quote_plus(self._keywords),
            location=quote_plus(self._location),
        )
        logger.info(f"[linkedin] Searching: {url}")
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await self._sleep(2, 3)

        results: list[JobListing] = []
        seen_ids: set[str] = set()
        scroll_attempts = 0
        max_scrolls = (self._max_jobs // 25) + 3

        while len(results) < self._max_jobs and scroll_attempts < max_scrolls:
            cards = await page.query_selector_all(
                ".job-card-container, .jobs-search-results__list-item, "
                "[class*='job-card'], li[data-occludable-job-id]"
            )

            for card in cards:
                if len(results) >= self._max_jobs:
                    break
                job = await self._parse_card(page, card)
                if job and job.external_id not in seen_ids:
                    seen_ids.add(job.external_id)
                    results.append(job)

            # Scroll to load more
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await self._sleep(2, 4)
            scroll_attempts += 1

            # Check if "See more jobs" button exists
            see_more = await page.query_selector("button[aria-label*='more jobs'], .infinite-scroller__show-more-button")
            if see_more:
                await see_more.click()
                await self._sleep(2, 3)

        logger.info(f"[linkedin] Scraped {len(results)} jobs")
        return results

    async def _parse_card(self, page, card) -> JobListing | None:
        try:
            # Job ID
            job_id = await card.get_attribute("data-occludable-job-id") or await card.get_attribute("data-job-id")
            if not job_id:
                link_el = await card.query_selector("a[href*='/jobs/view/']")
                if link_el:
                    href = await link_el.get_attribute("href") or ""
                    m = re.search(r"/jobs/view/(\d+)", href)
                    job_id = m.group(1) if m else hashlib.sha256(href.encode()).hexdigest()[:16]
            if not job_id:
                return None

            # Title
            title_el = await card.query_selector(
                ".job-card-list__title, .job-card-container__link, "
                "[class*='job-title'], h3"
            )
            title = (await title_el.inner_text()).strip() if title_el else ""
            if not title:
                return None

            # Company
            company_el = await card.query_selector(
                ".job-card-container__company-name, .job-card-list__company-name, "
                "[class*='company']"
            )
            company = (await company_el.inner_text()).strip() if company_el else "Unknown"

            # Location
            location_el = await card.query_selector(
                ".job-card-container__metadata-item, [class*='location']"
            )
            location = (await location_el.inner_text()).strip() if location_el else ""

            # Easy Apply badge
            easy_apply = bool(await card.query_selector("[class*='easy-apply'], .job-card-container__apply-method"))

            # URL
            job_url = f"https://www.linkedin.com/jobs/view/{job_id}/"
            apply_url = job_url

            return JobListing(
                external_id=str(job_id),
                source=self.source,
                title=title,
                company=company,
                location=location,
                url=job_url,
                apply_url=apply_url,
                description="",   # fetched lazily during application
                is_easy_apply=easy_apply,
                experience_level=detect_experience_level(title),
            )
        except Exception as e:
            logger.debug(f"[linkedin] Failed to parse card: {e}")
            return None
