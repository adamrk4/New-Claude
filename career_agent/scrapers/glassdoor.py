"""Glassdoor scraper — Playwright with persistent auth state."""
from __future__ import annotations

import hashlib
import re
from typing import Any
from urllib.parse import quote_plus

from loguru import logger

from career_agent.models.job import JobListing
from career_agent.parsers.job_parser import detect_experience_level, strip_html
from career_agent.scrapers.base import AbstractScraper

_LOGIN_URL = "https://www.glassdoor.com/profile/login_input.htm"
_JOBS_URL = (
    "https://www.glassdoor.com/Job/israel-{keyword_slug}-jobs-SRCH_IL.0,6_IN119_KO7,{kw_end}.htm"
    "?fromAge=14&seniorityType=entrylevel&seniorityType=associate"
)
_JOBS_SEARCH_URL = (
    "https://www.glassdoor.com/Job/jobs.htm?sc.keyword={keywords}"
    "&locT=N&locId=119&fromAge=14"
)


class GlassdoorScraper(AbstractScraper):
    source = "glassdoor"

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self._max_jobs = config.get("max_jobs", 30)
        self._auth_state_path = config.get("auth_state_path", "data/glassdoor_auth.json")
        self._email = None
        self._password = None
        self._load_credentials()

    def _load_credentials(self) -> None:
        import os
        from dotenv import load_dotenv
        load_dotenv()
        self._email = os.getenv("GLASSDOOR_EMAIL")
        self._password = os.getenv("GLASSDOOR_PASSWORD")

    async def scrape(self) -> list[JobListing]:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error("[glassdoor] Playwright not installed")
            return []

        async with async_playwright() as p:
            browser, context = await self._new_browser_context(p, self._auth_state_path)
            page = await context.new_page()

            try:
                await self._ensure_logged_in(page, context)
            except Exception as e:
                logger.warning(f"[glassdoor] Login failed (continuing as guest): {e}")

            results = await self._scrape_jobs(page)
            await self._save_auth_state(context, self._auth_state_path)
            await browser.close()
            return results

    async def _ensure_logged_in(self, page, context) -> None:
        await page.goto("https://www.glassdoor.com/member/home/index.htm", timeout=30000)
        await self._sleep(1, 2)

        if "member/home" in page.url:
            logger.info("[glassdoor] Already logged in")
            return

        if not self._email or not self._password:
            logger.info("[glassdoor] No credentials — scraping as guest (limited results)")
            return

        await page.goto(_LOGIN_URL, wait_until="domcontentloaded")
        await page.fill("#userEmail", self._email)
        await page.click('[type="submit"]')
        await self._sleep(1, 2)
        try:
            await page.fill("#userPassword", self._password)
            await page.click('[type="submit"]')
            await page.wait_for_url(re.compile(r"glassdoor\.com/member"), timeout=15000)
            logger.info("[glassdoor] Login successful")
        except Exception as e:
            logger.warning(f"[glassdoor] Login step 2 failed: {e}")

    async def _scrape_jobs(self, page) -> list[JobListing]:
        keywords = quote_plus("Solutions Engineer OR Pre-Sales OR Technical Account Manager")
        url = _JOBS_SEARCH_URL.format(keywords=keywords)
        logger.info(f"[glassdoor] Searching: {url}")

        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await self._sleep(2, 4)

        results: list[JobListing] = []
        seen_ids: set[str] = set()

        # Close any popups
        for popup_selector in ["[alt='Close']", "button[data-test='modal-close']", ".modal-container button"]:
            try:
                close_btn = await page.query_selector(popup_selector)
                if close_btn:
                    await close_btn.click()
                    await self._sleep(0.5, 1)
            except Exception:
                pass

        for _ in range(min(self._max_jobs // 30 + 2, 5)):
            cards = await page.query_selector_all(
                "li[data-test='jobListing'], .react-job-listing, [class*='jobListing'], "
                "article[class*='job']"
            )
            for card in cards:
                if len(results) >= self._max_jobs:
                    break
                job = await self._parse_card(card)
                if job and job.external_id not in seen_ids:
                    seen_ids.add(job.external_id)
                    results.append(job)

            if len(results) >= self._max_jobs:
                break

            # Next page
            next_btn = await page.query_selector("button[data-test='pagination-next'], [aria-label='Next page']")
            if not next_btn:
                break
            await next_btn.click()
            await self._sleep(2, 4)

        logger.info(f"[glassdoor] Scraped {len(results)} jobs")
        return results

    async def _parse_card(self, card) -> JobListing | None:
        try:
            title_el = await card.query_selector(
                "[data-test='job-title'], .job-title, [class*='jobTitle'] a, a[class*='title']"
            )
            if not title_el:
                return None
            title = (await title_el.inner_text()).strip()
            if not title:
                return None

            href = await title_el.get_attribute("href") or ""
            if href and not href.startswith("http"):
                href = "https://www.glassdoor.com" + href
            if not href:
                return None

            # Extract job ID from URL
            m = re.search(r"jobListingId=(\d+)|/job-listing/[^/]+-JV_IC\d+_KO\d+,\d+_JV(\d+)", href)
            external_id = m.group(1) or m.group(2) if m else hashlib.sha256(href.encode()).hexdigest()[:16]

            company_el = await card.query_selector(
                "[data-test='employer-name'], .employerName, [class*='employerName']"
            )
            company = (await company_el.inner_text()).strip() if company_el else "Unknown"

            location_el = await card.query_selector(
                "[data-test='emp-location'], .location, [class*='location']"
            )
            location = (await location_el.inner_text()).strip() if location_el else ""

            return JobListing(
                external_id=str(external_id),
                source=self.source,
                title=title,
                company=company,
                location=location,
                url=href,
                apply_url=href,
                description="",
                experience_level=detect_experience_level(title),
            )
        except Exception as e:
            logger.debug(f"[glassdoor] Failed to parse card: {e}")
            return None
