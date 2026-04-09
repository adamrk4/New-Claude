"""Abstract base scraper — shared retry logic, rate-limiting, and browser context helpers."""
from __future__ import annotations

import asyncio
import random
from abc import ABC, abstractmethod
from typing import Any, Optional

import requests
from loguru import logger
from tenacity import AsyncRetrying, RetryError, stop_after_attempt, wait_exponential

from career_agent.models.job import JobListing


class AbstractScraper(ABC):
    source: str = "unknown"

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self._session: Optional[requests.Session] = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @abstractmethod
    async def scrape(self) -> list[JobListing]:
        """Scrape jobs and return a list of validated JobListing objects."""

    # ------------------------------------------------------------------
    # HTTP helpers (requests-based)
    # ------------------------------------------------------------------

    def _get_session(self) -> requests.Session:
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update({
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9,he;q=0.8",
            })
        return self._session

    async def _get_with_retry(self, url: str, **kwargs) -> requests.Response:
        """GET request with exponential-backoff retry (up to 4 attempts)."""
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(4),
                wait=wait_exponential(multiplier=1, min=2, max=16),
                reraise=True,
            ):
                with attempt:
                    loop = asyncio.get_event_loop()
                    resp = await loop.run_in_executor(
                        None,
                        lambda: self._get_session().get(url, timeout=20, **kwargs)
                    )
                    resp.raise_for_status()
                    return resp
        except RetryError as e:
            logger.error(f"[{self.source}] Failed after retries: {url} — {e}")
            raise

    # ------------------------------------------------------------------
    # Rate-limit helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _sleep(min_s: float = 1.5, max_s: float = 3.5) -> None:
        await asyncio.sleep(random.uniform(min_s, max_s))

    # ------------------------------------------------------------------
    # Playwright helpers
    # ------------------------------------------------------------------

    async def _new_browser_context(self, playwright, auth_state_path: str | None = None):
        """Launch a Chromium browser context, optionally reusing saved auth state."""
        try:
            from playwright_stealth import stealth_async  # noqa: F401 — imported for side effects
        except ImportError:
            logger.warning("playwright-stealth not installed; bot detection may be stronger")

        browser = await playwright.chromium.launch(headless=True)
        context_kwargs: dict[str, Any] = {
            "viewport": {"width": 1280, "height": 800},
            "locale": "en-US",
            "timezone_id": "Asia/Jerusalem",
        }
        if auth_state_path:
            from pathlib import Path
            p = Path(auth_state_path)
            if p.exists():
                context_kwargs["storage_state"] = str(p)
                logger.info(f"[{self.source}] Reusing auth state from {p}")
        return browser, await browser.new_context(**context_kwargs)

    async def _save_auth_state(self, context, auth_state_path: str) -> None:
        from pathlib import Path
        Path(auth_state_path).parent.mkdir(parents=True, exist_ok=True)
        await context.storage_state(path=auth_state_path)
        logger.info(f"[{self.source}] Auth state saved to {auth_state_path}")
