"""Core Playwright form-filling helpers shared by all applicator strategies."""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Template
from loguru import logger


class FormFiller:
    """
    Provides helper methods for filling common form fields via Playwright.
    All methods accept a Playwright `page` object as their first argument.
    """

    def __init__(self, settings: dict[str, Any]):
        app_cfg = settings.get("application", {})
        self._salary = app_cfg.get("salary_value", 17500)
        self._why_you_tpl = app_cfg.get("why_you_template", "")
        self._experience_answer = app_cfg.get("experience_answer", "")
        self._screenshot_enabled = app_cfg.get("screenshot_before_submit", True)
        self._screenshot_dir = Path("data/screenshots")
        self._screenshot_dir.mkdir(parents=True, exist_ok=True)

        # Personal info from env
        import dotenv
        dotenv.load_dotenv()
        self.applicant_name = os.getenv("APPLICANT_NAME", "")
        self.applicant_email = os.getenv("APPLICANT_EMAIL", "")
        self.applicant_phone = os.getenv("APPLICANT_PHONE_IL", "")
        self.applicant_phone_intl = os.getenv("APPLICANT_PHONE_INTL", "")
        self.applicant_linkedin = os.getenv("APPLICANT_LINKEDIN_URL", "")

    # ------------------------------------------------------------------
    # Field-filling helpers
    # ------------------------------------------------------------------

    async def fill_text_field(
        self,
        page,
        selector_hints: list[str],
        value: str,
        clear_first: bool = True,
    ) -> bool:
        """Try each selector hint in order; fill the first visible one. Returns True on success."""
        for sel in selector_hints:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    if clear_first:
                        await el.triple_click()
                    await el.fill(value)
                    return True
            except Exception:
                pass

        # Fallback: find by placeholder or aria-label containing any hint fragment
        for hint in selector_hints:
            hint_clean = hint.lstrip("#.[").rstrip("]\"'")
            for attr in ("placeholder", "aria-label", "name", "id"):
                try:
                    el = await page.query_selector(f"[{attr}*='{hint_clean}' i]")
                    if el and await el.is_visible():
                        if clear_first:
                            await el.triple_click()
                        await el.fill(value)
                        return True
                except Exception:
                    pass

        logger.debug(f"fill_text_field: no selector matched for hints {selector_hints}")
        return False

    async def fill_salary(self, page, is_range: bool = False) -> bool:
        """Fill salary field(s). Tries common salary selector patterns."""
        salary_selectors = [
            "[name*='salary' i]",
            "[id*='salary' i]",
            "[placeholder*='salary' i]",
            "[aria-label*='salary' i]",
            "[name*='compensation' i]",
            "[placeholder*='expected' i]",
        ]
        result = await self.fill_text_field(page, salary_selectors, str(self._salary))
        if is_range:
            # Try to fill max salary too
            max_selectors = [
                "[name*='salary_max' i]",
                "[id*='salary-max' i]",
                "[placeholder*='maximum' i]",
            ]
            await self.fill_text_field(page, max_selectors, str(self._salary))
        return result

    async def fill_cover_note(
        self,
        page,
        company: str = "",
        role: str = "",
    ) -> bool:
        """Render the 'Why you?' template and insert into cover letter / motivation field."""
        rendered = Template(self._why_you_tpl).render(company=company, role=role)
        cover_selectors = [
            "textarea[name*='cover' i]",
            "textarea[id*='cover' i]",
            "textarea[placeholder*='cover' i]",
            "textarea[aria-label*='cover' i]",
            "textarea[name*='motivation' i]",
            "textarea[name*='message' i]",
            "textarea[placeholder*='tell us' i]",
            "textarea[placeholder*='why' i]",
            "[contenteditable='true']",
        ]
        return await self.fill_text_field(page, cover_selectors, rendered)

    async def fill_experience_question(self, page) -> bool:
        """Answer experience / background open text questions."""
        exp_selectors = [
            "textarea[name*='experience' i]",
            "textarea[placeholder*='experience' i]",
            "textarea[aria-label*='experience' i]",
            "textarea[name*='background' i]",
        ]
        return await self.fill_text_field(page, exp_selectors, self._experience_answer)

    async def fill_contact_info(self, page) -> None:
        """Fill name, email, phone if fields are present."""
        await self.fill_text_field(
            page,
            ["[name*='first' i][name*='name' i]", "[id*='first' i][id*='name' i]", "[name='firstName']", "[id='firstName']"],
            self.applicant_name.split()[0] if self.applicant_name else "",
        )
        last = " ".join(self.applicant_name.split()[1:]) if self.applicant_name else ""
        await self.fill_text_field(
            page,
            ["[name*='last' i][name*='name' i]", "[id*='last' i][id*='name' i]", "[name='lastName']", "[id='lastName']"],
            last,
        )
        # Full name (some forms have a single full-name field)
        await self.fill_text_field(
            page,
            ["[name='name']", "[id='name']", "[placeholder*='full name' i]"],
            self.applicant_name,
        )
        await self.fill_text_field(
            page,
            ["[name='email']", "[id='email']", "[type='email']", "[placeholder*='email' i]"],
            self.applicant_email,
        )
        await self.fill_text_field(
            page,
            ["[name*='phone' i]", "[id*='phone' i]", "[placeholder*='phone' i]", "[type='tel']"],
            self.applicant_phone,
        )

    async def upload_cv(self, page, cv_path: str) -> bool:
        """Upload CV file via a file input element."""
        cv_path_obj = Path(cv_path)
        if not cv_path_obj.exists():
            logger.error(f"CV file not found: {cv_path}")
            return False

        file_input_selectors = [
            "input[type='file']",
            "input[accept*='pdf' i]",
            "input[accept*='doc' i]",
            "input[name*='resume' i]",
            "input[name*='cv' i]",
        ]
        for sel in file_input_selectors:
            try:
                el = await page.query_selector(sel)
                if el:
                    await el.set_input_files(str(cv_path_obj))
                    logger.info(f"Uploaded CV: {cv_path}")
                    return True
            except Exception as e:
                logger.debug(f"upload_cv selector '{sel}' failed: {e}")
        return False

    async def handle_dropdown(self, page, selector_hints: list[str], target_value_patterns: list[str]) -> bool:
        """Select an option in a <select> or custom dropdown that best matches target patterns."""
        import re
        for sel in selector_hints:
            try:
                el = await page.query_selector(sel)
                if not el:
                    continue
                tag = await el.evaluate("el => el.tagName")
                if tag.upper() == "SELECT":
                    options = await el.evaluate(
                        "el => [...el.options].map(o => ({value: o.value, text: o.text}))"
                    )
                    for pattern in target_value_patterns:
                        for opt in options:
                            if re.search(pattern, opt["text"], re.IGNORECASE):
                                await el.select_option(value=opt["value"])
                                return True
            except Exception:
                pass
        return False

    async def take_screenshot(self, page, job_id: int) -> str:
        """Take a screenshot and save to data/screenshots/. Returns the path."""
        if not self._screenshot_enabled:
            return ""
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        path = self._screenshot_dir / f"job_{job_id}_{ts}.png"
        try:
            await page.screenshot(path=str(path), full_page=True)
            logger.info(f"Screenshot saved: {path}")
            return str(path)
        except Exception as e:
            logger.warning(f"Screenshot failed: {e}")
            return ""
