"""LinkedIn Easy Apply — multi-step modal state machine."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from loguru import logger

from career_agent.applicator.form_filler import FormFiller
from career_agent.models.job import JobListingORM


_EASY_APPLY_BTN = (
    "button[aria-label*='Easy Apply' i], "
    ".jobs-apply-button, "
    "[data-control-name='jobdetails_topcard_inapply']"
)
_NEXT_BTN = "button[aria-label*='Continue' i], button[aria-label*='Next' i], button[aria-label*='Review' i]"
_SUBMIT_BTN = "button[aria-label*='Submit application' i], button[aria-label*='Done' i]"
_MODAL = ".jobs-easy-apply-modal, [role='dialog'][aria-label*='Apply' i]"
_CLOSE_BTN = "button[aria-label*='Dismiss' i], button[data-test-modal-close-btn]"


class LinkedInApplicator:
    """Drives the LinkedIn Easy Apply multi-step modal for a single job."""

    def __init__(self, page, settings: dict[str, Any], cv_path: str):
        self._page = page
        self._filler = FormFiller(settings)
        self._cv_path = cv_path
        self._settings = settings

    async def apply(self, job: JobListingORM) -> tuple[bool, str]:
        """
        Navigate to the job page, click Easy Apply, fill the modal, submit.
        Returns (success: bool, error_message: str).
        """
        try:
            await self._page.goto(job.url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)

            # Click the Easy Apply button
            try:
                await self._page.wait_for_selector(_EASY_APPLY_BTN, timeout=8000)
                await self._page.click(_EASY_APPLY_BTN)
                await asyncio.sleep(1.5)
            except Exception:
                return False, "Easy Apply button not found"

            # Wait for modal
            try:
                await self._page.wait_for_selector(_MODAL, timeout=8000)
            except Exception:
                return False, "Easy Apply modal did not open"

            # Step through modal pages (max 10 steps to prevent infinite loop)
            for step in range(10):
                logger.info(f"[linkedin_apply] Job {job.id} — modal step {step + 1}")
                await self._fill_current_step()
                await asyncio.sleep(0.5)

                # Check if submit button is present
                submit_btn = await self._page.query_selector(_SUBMIT_BTN)
                if submit_btn:
                    screenshot_path = await self._filler.take_screenshot(self._page, job.id)
                    await submit_btn.click()
                    await asyncio.sleep(2)
                    # Dismiss confirmation
                    close = await self._page.query_selector(_CLOSE_BTN)
                    if close:
                        await close.click()
                    return True, ""

                # Click Next / Continue
                next_btn = await self._page.query_selector(_NEXT_BTN)
                if next_btn:
                    await next_btn.click()
                    await asyncio.sleep(1)
                else:
                    return False, "Could not find Next or Submit button in modal"

            return False, "Exceeded maximum modal steps (10)"

        except Exception as e:
            return False, str(e)

    async def _fill_current_step(self) -> None:
        """Fill whatever fields are visible in the current modal step."""
        filler = self._filler
        page = self._page

        # Contact info
        await filler.fill_contact_info(page)

        # CV upload
        if self._cv_path:
            await filler.upload_cv(page, self._cv_path)

        # Phone (LinkedIn sometimes asks separately)
        await filler.fill_text_field(
            page,
            ["#phone-number", "[name='phoneNumber']", "[placeholder*='phone' i]"],
            filler.applicant_phone,
        )

        # Salary
        await filler.fill_salary(page)

        # Cover / motivation
        await filler.fill_cover_note(page)

        # Experience open text
        await filler.fill_experience_question(page)

        # Years of experience dropdowns — prefer "0-1" or "1" or "Less than 1"
        exp_selectors = [
            "select[id*='experience' i]",
            "select[name*='experience' i]",
            "select[aria-label*='years' i]",
        ]
        await filler.handle_dropdown(
            page, exp_selectors,
            [r"0\s*[-–]\s*1", r"less than", r"^0$", r"^1$", r"entry"],
        )

        # Education level dropdowns
        edu_selectors = [
            "select[id*='education' i]",
            "select[name*='education' i]",
            "select[aria-label*='education' i]",
        ]
        await filler.handle_dropdown(
            page, edu_selectors,
            [r"bachelor", r"b\.?sc", r"degree"],
        )

        # Generic yes/no screening questions — default to "Yes" for positive questions
        radio_labels = await page.query_selector_all("label")
        for label in radio_labels:
            text = (await label.inner_text()).strip().lower()
            if text in ("yes", "כן"):
                try:
                    input_el = await page.query_selector(f"#{await label.get_attribute('for')}")
                    if input_el:
                        await input_el.click()
                except Exception:
                    pass
