"""AllJobs.co.il scraper — requests + BeautifulSoup4.

Searches each target role separately to avoid AllJobs ignoring long keyword strings.
"""
from __future__ import annotations

import hashlib
from typing import Any
from urllib.parse import quote_plus

from bs4 import BeautifulSoup
from loguru import logger

from career_agent.models.job import JobListing
from career_agent.parsers.job_parser import detect_experience_level, strip_html
from career_agent.scrapers.base import AbstractScraper

_BASE = "https://www.alljobs.co.il"
_SEARCH_URL = _BASE + "/SearchResultsGuest.aspx?page={page}&position={kw}&type=0&fromdate=30&todate=0"

# Search separately for each role to get targeted results
_SEARCH_TERMS = [
    "Solutions Engineer",
    "Pre-Sales",
    "Presales",
    "Account Manager",
    "Customer Success",
    "Sales Engineer",
    "מהנדס פתרונות",
    "פרה מכירות",
    "הצלחת לקוח",
    "מנהל לקוח",
]


class AllJobsScraper(AbstractScraper):
    source = "alljobs"

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self._max_pages = config.get("max_pages", 2)  # 2 pages per keyword

    async def scrape(self) -> list[JobListing]:
        results: list[JobListing] = []
        seen_ids: set[str] = set()

        for term in _SEARCH_TERMS:
            for page in range(1, self._max_pages + 1):
                url = _SEARCH_URL.format(page=page, kw=quote_plus(term))
                logger.info(f"[alljobs] '{term}' page {page}")
                try:
                    resp = await self._get_with_retry(url)
                    resp.encoding = "utf-8"
                except Exception as e:
                    logger.error(f"[alljobs] Failed: {e}")
                    break

                soup = BeautifulSoup(resp.text, "html.parser")
                batch = self._parse_page(soup)
                if not batch:
                    break  # no more pages for this term

                for job in batch:
                    if job.external_id not in seen_ids:
                        seen_ids.add(job.external_id)
                        results.append(job)

                await self._sleep(1, 2)

        logger.info(f"[alljobs] Scraped {len(results)} unique jobs")
        return results

    def _parse_page(self, soup: BeautifulSoup) -> list[JobListing]:
        jobs = []

        # AllJobs wraps each job in a <div> or <li> containing a link to /Job/ or /SingleJob/
        # Strategy: find all job links and build a listing from the surrounding container
        job_links = soup.find_all("a", href=lambda h: h and ("/Job/" in h or "/SingleJob/" in h or "jobId=" in h))

        for link in job_links:
            job = self._parse_from_link(link)
            if job:
                jobs.append(job)

        return jobs

    def _parse_from_link(self, link) -> JobListing | None:
        try:
            title = link.get_text(strip=True)
            if not title or len(title) < 3:
                return None

            href = link.get("href", "")
            if not href:
                return None
            if not href.startswith("http"):
                href = _BASE + href

            external_id = hashlib.sha256(href.encode()).hexdigest()[:16]

            # Walk up the DOM to find the containing card for company/location
            card = link.parent
            for _ in range(4):  # go up to 4 levels
                if card is None:
                    break
                text = card.get_text(" ", strip=True)
                if len(text) > len(title) + 5:
                    break
                card = card.parent

            card_text = card.get_text(" ", strip=True) if card else ""

            # Extract company — usually the first meaningful text after the title
            company = "Unknown"
            location = ""
            if card:
                # Try to find company name — often in a sibling span or div
                for el in card.find_all(["span", "div", "p"], limit=10):
                    el_text = el.get_text(strip=True)
                    if el_text and el_text != title and 2 < len(el_text) < 60:
                        # Skip if it looks like a location or date
                        if not any(c.isdigit() for c in el_text[:4]):
                            company = el_text
                            break

                # Location — look for known city names
                city_keywords = ["תל אביב", "Tel Aviv", "הרצליה", "Herzliya",
                                 "פתח תקווה", "Petah Tikva", "רמת גן", "Ramat Gan",
                                 "חולון", "Holon", "ראשון לציון", "Rishon"]
                for city in city_keywords:
                    if city in card_text:
                        location = city
                        break

            return JobListing(
                external_id=external_id,
                source=self.source,
                title=title,
                company=company,
                location=location,
                url=href,
                apply_url=href,
                description=card_text[:500],
                experience_level=detect_experience_level(f"{title} {card_text}"),
            )
        except Exception as e:
            logger.debug(f"[alljobs] parse error: {e}")
            return None
