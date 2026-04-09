"""Indeed (il.indeed.com) scraper — requests + BS4, with Playwright fallback on 403/CAPTCHA."""
from __future__ import annotations

import hashlib
from typing import Any
from urllib.parse import quote_plus

from bs4 import BeautifulSoup
from loguru import logger

from career_agent.models.job import JobListing
from career_agent.parsers.job_parser import detect_experience_level, strip_html
from career_agent.scrapers.base import AbstractScraper

_SEARCH_URL = (
    "https://il.indeed.com/jobs?q={keywords}&l={location}"
    "&fromage=14&sort=date&start={start}"
)
_KEYWORDS = quote_plus("Solutions Engineer OR Pre-Sales OR Technical Account Manager OR Customer Success Engineer")
_LOCATION = quote_plus("Tel Aviv, Israel")
_JOBS_PER_PAGE = 15


class IndeedScraper(AbstractScraper):
    source = "indeed"

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self._max_pages = config.get("max_pages", 5)
        self._use_playwright_fallback = config.get("use_playwright_fallback", True)

    async def scrape(self) -> list[JobListing]:
        results: list[JobListing] = []
        use_playwright = False

        for page in range(self._max_pages):
            start = page * _JOBS_PER_PAGE
            url = _SEARCH_URL.format(keywords=_KEYWORDS, location=_LOCATION, start=start)
            logger.info(f"[indeed] Fetching page {page + 1} (start={start})")

            if use_playwright:
                batch = await self._scrape_page_playwright(url)
            else:
                try:
                    resp = await self._get_with_retry(url)
                    if resp.status_code in (403, 429):
                        if self._use_playwright_fallback:
                            logger.warning("[indeed] Received 403/429; switching to Playwright")
                            use_playwright = True
                            batch = await self._scrape_page_playwright(url)
                        else:
                            logger.error("[indeed] 403/429 and Playwright fallback disabled, stopping")
                            break
                    else:
                        resp.encoding = "utf-8"
                        batch = self._parse_html(resp.text)
                except Exception as e:
                    logger.error(f"[indeed] Page {page + 1} failed: {e}")
                    break

            if not batch:
                logger.info(f"[indeed] No jobs on page {page + 1}, stopping")
                break

            results.extend(batch)
            await self._sleep()

        logger.info(f"[indeed] Scraped {len(results)} jobs")
        return results

    def _parse_html(self, html: str) -> list[JobListing]:
        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select(".job_seen_beacon, .tapItem, [class*='jobCard']")
        return [j for j in (self._parse_card(c) for c in cards) if j]

    def _parse_card(self, card) -> JobListing | None:
        try:
            title_el = card.select_one("h2 a, .jobTitle a, [class*='title'] a")
            if not title_el:
                return None
            title = title_el.get_text(strip=True)
            if not title:
                return None

            jk = title_el.get("data-jk") or title_el.get("href", "")
            if jk and not jk.startswith("http"):
                href = f"https://il.indeed.com/viewjob?jk={jk.lstrip('/')}"
                external_id = jk.split("jk=")[-1][:16] if "jk=" in jk else hashlib.sha256(jk.encode()).hexdigest()[:16]
            else:
                href = jk
                external_id = hashlib.sha256(href.encode()).hexdigest()[:16]

            company_el = card.select_one(".companyName, [class*='company']")
            company = company_el.get_text(strip=True) if company_el else "Unknown"

            location_el = card.select_one(".companyLocation, [class*='location']")
            location = location_el.get_text(strip=True) if location_el else ""

            desc_el = card.select_one(".job-snippet, [class*='snippet'], [class*='description']")
            description = strip_html(desc_el.get_text()) if desc_el else ""

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
            logger.debug(f"[indeed] Failed to parse card: {e}")
            return None

    async def _scrape_page_playwright(self, url: str) -> list[JobListing]:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error("[indeed] Playwright not installed")
            return []

        async with async_playwright() as p:
            browser, context = await self._new_browser_context(p)
            try:
                page = await context.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await self._sleep(2, 4)
                content = await page.content()
                return self._parse_html(content)
            except Exception as e:
                logger.error(f"[indeed] Playwright page scrape failed: {e}")
                return []
            finally:
                await browser.close()
