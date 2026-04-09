"""AllJobs.co.il scraper — requests + BeautifulSoup4."""
from __future__ import annotations

import hashlib
from typing import Any
from urllib.parse import urlencode

from bs4 import BeautifulSoup
from loguru import logger

from career_agent.models.job import JobListing
from career_agent.parsers.job_parser import detect_experience_level, strip_html
from career_agent.scrapers.base import AbstractScraper

# AllJobs search URL pattern:
# https://www.alljobs.co.il/SearchResultsGuest.aspx?page=1&position=<keywords>&type=0&city=<city_id>&regions=0
# City IDs (examples): Tel Aviv = 6900, Herzliya = 6720, Petah Tikva = 7900
# Using keyword-only search with free text location filtering is more reliable.

_SEARCH_URL = (
    "https://www.alljobs.co.il/SearchResultsGuest.aspx?"
    "page={page}&position={keywords}&type=0&fromdate=7&todate=0"
)
_KEYWORDS = "Solutions+Engineer+Pre-Sales+Technical+Account+Manager+Customer+Success"


class AllJobsScraper(AbstractScraper):
    source = "alljobs"

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self._base_url = config.get("base_url", "https://www.alljobs.co.il")
        self._max_pages = config.get("max_pages", 5)

    async def scrape(self) -> list[JobListing]:
        results: list[JobListing] = []
        for page in range(1, self._max_pages + 1):
            url = _SEARCH_URL.format(page=page, keywords=_KEYWORDS)
            logger.info(f"[alljobs] Fetching page {page}: {url}")
            try:
                resp = await self._get_with_retry(url)
                resp.encoding = "utf-8"
            except Exception as e:
                logger.error(f"[alljobs] Page {page} failed: {e}")
                break

            soup = BeautifulSoup(resp.text, "html.parser")
            job_cards = soup.select(".job-item, .jb-item, [class*='job-item'], [class*='jobItem']")

            if not job_cards:
                # Fallback: look for common AllJobs job card patterns
                job_cards = soup.select("li[id^='job'], div[id^='job'], .JobItem")

            if not job_cards:
                logger.info(f"[alljobs] No job cards found on page {page}, stopping pagination")
                break

            for card in job_cards:
                job = self._parse_card(card)
                if job:
                    results.append(job)

            await self._sleep()

        logger.info(f"[alljobs] Scraped {len(results)} jobs")
        return results

    def _parse_card(self, card) -> JobListing | None:
        try:
            # Title — try multiple selectors
            title_el = (
                card.select_one(".job-title, .jb-title, h2 a, h3 a, .JobTitle a, [class*='title'] a")
                or card.select_one("a[href*='job']")
            )
            if not title_el:
                return None
            title = title_el.get_text(strip=True)
            if not title:
                return None

            # URL
            href = title_el.get("href", "")
            if href and not href.startswith("http"):
                href = self._base_url + href
            if not href:
                return None

            # Company
            company_el = card.select_one(".company-name, .jb-company, .JobCompany, [class*='company']")
            company = company_el.get_text(strip=True) if company_el else "Unknown"

            # Location
            location_el = card.select_one(".location, .jb-location, .JobLocation, [class*='location']")
            location = location_el.get_text(strip=True) if location_el else ""

            # Description snippet
            desc_el = card.select_one(".description, .jb-desc, .JobDesc, [class*='desc']")
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
            logger.debug(f"[alljobs] Failed to parse card: {e}")
            return None
