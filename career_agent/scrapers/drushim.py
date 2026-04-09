"""Drushim.co.il scraper — requests + BeautifulSoup4."""
from __future__ import annotations

import hashlib
from typing import Any

from bs4 import BeautifulSoup
from loguru import logger

from career_agent.models.job import JobListing
from career_agent.parsers.job_parser import detect_experience_level, strip_html
from career_agent.scrapers.base import AbstractScraper

# Drushim search: https://www.drushim.co.il/jobs/cat11/?q=<keywords>&page=<n>
# Category 11 = Hi-Tech; free-text search for role keywords

_SEARCH_URL = "https://www.drushim.co.il/jobs/cat11/?q={keywords}&page={page}"
_KEYWORDS = "Solutions+Engineer+Pre-Sales+Technical+Account+Manager"


class DrushimScraper(AbstractScraper):
    source = "drushim"

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self._base_url = config.get("base_url", "https://www.drushim.co.il")
        self._max_pages = config.get("max_pages", 5)

    async def scrape(self) -> list[JobListing]:
        results: list[JobListing] = []
        for page in range(1, self._max_pages + 1):
            url = _SEARCH_URL.format(keywords=_KEYWORDS, page=page)
            logger.info(f"[drushim] Fetching page {page}: {url}")
            try:
                resp = await self._get_with_retry(url)
                resp.encoding = "utf-8"
            except Exception as e:
                logger.error(f"[drushim] Page {page} failed: {e}")
                break

            soup = BeautifulSoup(resp.text, "html.parser")

            # Drushim job cards
            job_cards = soup.select(
                ".job-list-item, .jobItem, [class*='job-item'], "
                "li[data-job-id], div[data-job-id]"
            )

            if not job_cards:
                logger.info(f"[drushim] No job cards on page {page}, stopping")
                break

            for card in job_cards:
                job = self._parse_card(card)
                if job:
                    results.append(job)

            await self._sleep()

        logger.info(f"[drushim] Scraped {len(results)} jobs")
        return results

    def _parse_card(self, card) -> JobListing | None:
        try:
            title_el = (
                card.select_one("h2 a, h3 a, .job-title a, .JobTitle a, [class*='title'] a")
                or card.select_one("a[href*='job']")
            )
            if not title_el:
                return None
            title = title_el.get_text(strip=True)
            if not title:
                return None

            href = title_el.get("href", "")
            if href and not href.startswith("http"):
                href = self._base_url + href
            if not href:
                return None

            company_el = card.select_one(".company, .CompanyName, [class*='company']")
            company = company_el.get_text(strip=True) if company_el else "Unknown"

            location_el = card.select_one(".location, .city, [class*='location'], [class*='city']")
            location = location_el.get_text(strip=True) if location_el else ""

            desc_el = card.select_one(".description, .desc, [class*='desc']")
            description = strip_html(desc_el.get_text()) if desc_el else ""

            external_id = hashlib.sha256(href.encode()).hexdigest()[:16]

            return JobListing(
                external_id=external_id,
                source=self.source,
                title=title,
                company=company,
                location=location,
                url=href,
                apply_url=href,
                description=description,
                experience_level=detect_experience_level(f"{title} {description}"),
            )
        except Exception as e:
            logger.debug(f"[drushim] Failed to parse card: {e}")
            return None
