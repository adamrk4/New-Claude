"""Company career pages scraper — YAML-driven, bs4 or playwright per entry."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import yaml
from bs4 import BeautifulSoup
from loguru import logger

from career_agent.models.job import JobListing
from career_agent.parsers.job_parser import detect_experience_level
from career_agent.scrapers.base import AbstractScraper

# Keywords to look for in job titles on career pages (from global include list)
_DEFAULT_KEYWORDS = [
    "solutions engineer",
    "pre-sales",
    "presales",
    "pre sales",
    "customer success engineer",
    "technical account manager",
    "sales engineer",
    "technical sales",
]


class CompanyCareersScraper(AbstractScraper):
    source = "company_direct"

    def __init__(self, config: dict[str, Any], include_keywords: list[str] | None = None):
        super().__init__(config)
        config_path = config.get("config_path", "config/target_companies.yaml")
        self._companies = self._load_companies(config_path)
        self._keywords = [kw.lower() for kw in (include_keywords or _DEFAULT_KEYWORDS)]

    @staticmethod
    def _load_companies(config_path: str) -> list[dict]:
        p = Path(config_path)
        if not p.exists():
            logger.warning(f"[company_careers] Config not found: {config_path}")
            return []
        with open(p, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data.get("companies", [])

    async def scrape(self) -> list[JobListing]:
        results: list[JobListing] = []
        for company in self._companies:
            name = company.get("name", "Unknown")
            strategy = company.get("strategy", "bs4")
            url = company.get("careers_url", "")
            if not url:
                continue

            logger.info(f"[company_careers] Scraping {name} ({strategy})")
            try:
                if strategy == "playwright":
                    batch = await self._scrape_playwright(company)
                else:
                    batch = await self._scrape_bs4(company)
                results.extend(batch)
                logger.info(f"[company_careers] {name}: found {len(batch)} matching jobs")
            except Exception as e:
                logger.error(f"[company_careers] {name} failed: {e}")

            await self._sleep(2, 5)

        logger.info(f"[company_careers] Total: {len(results)} jobs")
        return results

    async def _scrape_bs4(self, company: dict) -> list[JobListing]:
        url = company["careers_url"]
        name = company.get("name", "Unknown")
        resp = await self._get_with_retry(url)
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")

        job_list_sel = company.get("job_list_selector")
        job_title_sel = company.get("job_title_selector")

        results = []
        if job_list_sel:
            cards = soup.select(job_list_sel)
            for card in cards:
                link = card.select_one(job_title_sel) if job_title_sel else card.find("a")
                if not link:
                    continue
                title = link.get_text(strip=True)
                href = link.get("href", "")
                if href and not href.startswith("http"):
                    from urllib.parse import urljoin
                    href = urljoin(url, href)
                job = self._make_job(title, href, name)
                if job:
                    results.append(job)
        else:
            # Full-text keyword scan
            for link in soup.find_all("a", href=True):
                title = link.get_text(strip=True)
                href = link.get("href", "")
                if any(kw in title.lower() for kw in self._keywords):
                    if href and not href.startswith("http"):
                        from urllib.parse import urljoin
                        href = urljoin(url, href)
                    job = self._make_job(title, href, name)
                    if job:
                        results.append(job)

        return results

    async def _scrape_playwright(self, company: dict) -> list[JobListing]:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error("[company_careers] Playwright not installed")
            return []

        url = company["careers_url"]
        name = company.get("name", "Unknown")
        job_list_sel = company.get("job_list_selector")
        job_title_sel = company.get("job_title_selector")

        async with async_playwright() as p:
            browser, context = await self._new_browser_context(p)
            page = await context.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await self._sleep(2, 4)

                if job_list_sel:
                    try:
                        await page.wait_for_selector(job_list_sel, timeout=8000)
                    except Exception:
                        logger.debug(f"[company_careers] {name}: selector '{job_list_sel}' not found")

                content = await page.content()
            finally:
                await browser.close()

        # Parse via BS4 after Playwright renders
        soup = BeautifulSoup(content, "html.parser")
        results = []

        if job_list_sel:
            cards = soup.select(job_list_sel)
            for card in cards:
                link = card.select_one(job_title_sel) if job_title_sel else card.find("a")
                if not link:
                    continue
                title = link.get_text(strip=True)
                href = link.get("href", "")
                if href and not href.startswith("http"):
                    from urllib.parse import urljoin
                    href = urljoin(url, href)
                job = self._make_job(title, href, name)
                if job:
                    results.append(job)
        else:
            for link in soup.find_all("a", href=True):
                title = link.get_text(strip=True)
                href = link.get("href", "")
                if any(kw in title.lower() for kw in self._keywords):
                    if href and not href.startswith("http"):
                        from urllib.parse import urljoin
                        href = urljoin(url, href)
                    job = self._make_job(title, href, name)
                    if job:
                        results.append(job)

        return results

    def _make_job(self, title: str, url: str, company: str) -> JobListing | None:
        if not title or not url:
            return None
        # Verify keyword match
        if not any(kw in title.lower() for kw in self._keywords):
            return None
        external_id = hashlib.sha256(url.encode()).hexdigest()[:16]
        return JobListing(
            external_id=external_id,
            source=self.source,
            title=title,
            company=company,
            location="",   # usually not on listing page
            url=url,
            apply_url=url,
            description="",
            experience_level=detect_experience_level(title),
        )
