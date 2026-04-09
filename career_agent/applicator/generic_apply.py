"""Generic applicator — ATS detection and form-filling for non-LinkedIn job pages."""
from __future__ import annotations

import asyncio
import re
from typing import Any

from loguru import logger

from career_agent.applicator.form_filler import FormFiller
from career_agent.models.job import JobListingORM

# -------------------------------------------------------------------------
# ATS URL patterns
# -------------------------------------------------------------------------
_ATS_PATTERNS = {
    "greenhouse": re.compile(r"boards\.greenhouse\.io|grnh\.se", re.I),
    "lever": re.compile(r"jobs\.lever\.co", re.I),
    "workday": re.compile(r"workday\.com/.*apply|myworkdayjobs\.com", re.I),
    "smartrecruiters": re.compile(r"jobs\.smartrecruiters\.com", re.I),
    "icims": re.compile(r"careers\.icims\.com|\.icims\.com/jobs", re.I),
    "taleo": re.compile(r"taleo\.net", re.I),
}

# Success indicators: URL change or page text after submit
_SUCCESS_TEXT = re.compile(
    r"thank you|application (has been )?received|successfully (applied|submitted)|"
    r"we.ll be in touch|application complete|תודה|הגשת מועמדות|נשלח בהצלחה",
    re.I,
)
_SUCCESS_URL = re.compile(r"thank[-_]?you|confirmation|submitted|success", re.I)


def _detect_ats(url: str) -> str | None:
    for name, pattern in _ATS_PATTERNS.items():
        if pattern.search(url):
            return name
    return None


class GenericApplicator:
    """Applies to a job on a company career page or non-Easy-Apply platform."""

    def __init__(self, page, settings: dict[str, Any], cv_path: str):
        self._page = page
        self._filler = FormFiller(settings)
        self._cv_path = cv_path
        self._settings = settings

    async def apply(self, job: JobListingORM) -> tuple[bool, str]:
        """
        Navigate to apply_url, fill the form, submit.
        Returns (success: bool, error_message: str).
        """
        apply_url = job.apply_url or job.url
        ats = _detect_ats(apply_url)
        logger.info(f"[generic_apply] Job {job.id} ({job.company}) — ATS: {ats or 'unknown'}")

        try:
            await self._page.goto(apply_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)

            # Detect and click "Apply" button if we land on the job description page
            await self._click_apply_button_if_needed()

            if ats == "greenhouse":
                success, err = await self._apply_greenhouse(job)
            elif ats == "lever":
                success, err = await self._apply_lever(job)
            elif ats == "workday":
                success, err = await self._apply_workday(job)
            else:
                success, err = await self._apply_generic(job)

            return success, err

        except Exception as e:
            return False, str(e)

    async def _click_apply_button_if_needed(self) -> None:
        """Click an Apply button if visible on the current page."""
        apply_selectors = [
            "a[href*='apply']",
            "button:has-text('Apply')",
            "a:has-text('Apply Now')",
            "button:has-text('Apply Now')",
            "[data-automation='job-detail-apply']",
        ]
        for sel in apply_selectors:
            try:
                el = await self._page.query_selector(sel)
                if el and await el.is_visible():
                    await el.click()
                    await asyncio.sleep(1.5)
                    return
            except Exception:
                pass

    # ------------------------------------------------------------------
    # ATS-specific strategies
    # ------------------------------------------------------------------

    async def _apply_greenhouse(self, job: JobListingORM) -> tuple[bool, str]:
        logger.info(f"[generic_apply] Greenhouse form for job {job.id}")
        page = self._page
        filler = self._filler

        await filler.fill_text_field(page, ["#first_name", "[name='first_name']"], filler.applicant_name.split()[0])
        last = " ".join(filler.applicant_name.split()[1:])
        await filler.fill_text_field(page, ["#last_name", "[name='last_name']"], last)
        await filler.fill_text_field(page, ["#email", "[name='email']"], filler.applicant_email)
        await filler.fill_text_field(page, ["#phone", "[name='phone']"], filler.applicant_phone)

        await filler.upload_cv(page, self._cv_path)
        await filler.fill_cover_note(page, company=job.company, role=job.title)
        await filler.fill_salary(page)

        # Greenhouse-specific questions
        for textarea in await page.query_selector_all("textarea"):
            placeholder = (await textarea.get_attribute("placeholder") or "").lower()
            if any(w in placeholder for w in ("why", "motivation", "cover")):
                await filler.fill_cover_note(page, company=job.company, role=job.title)
            elif "experience" in placeholder:
                await filler.fill_experience_question(page)

        return await self._submit_and_check(job)

    async def _apply_lever(self, job: JobListingORM) -> tuple[bool, str]:
        logger.info(f"[generic_apply] Lever form for job {job.id}")
        page = self._page
        filler = self._filler

        await filler.fill_text_field(page, ["[name='name']", "#name"], filler.applicant_name)
        await filler.fill_text_field(page, ["[name='email']", "#email"], filler.applicant_email)
        await filler.fill_text_field(page, ["[name='phone']", "#phone"], filler.applicant_phone)
        await filler.upload_cv(page, self._cv_path)
        await filler.fill_cover_note(page, company=job.company, role=job.title)
        await filler.fill_salary(page)

        return await self._submit_and_check(job)

    async def _apply_workday(self, job: JobListingORM) -> tuple[bool, str]:
        logger.info(f"[generic_apply] Workday form for job {job.id} (best-effort)")
        # Workday uses iframes — switch context
        page = self._page
        filler = self._filler

        # Try to find the main application iframe
        frames = page.frames
        target_frame = None
        for frame in frames:
            if "workday" in (frame.url or "").lower():
                target_frame = frame
                break

        work_page = target_frame or page

        await filler.fill_contact_info(work_page)
        await filler.upload_cv(work_page, self._cv_path)
        await filler.fill_salary(work_page)
        await filler.fill_cover_note(work_page, company=job.company, role=job.title)

        return await self._submit_and_check(job, page=work_page)

    async def _apply_generic(self, job: JobListingORM) -> tuple[bool, str]:
        """Heuristic form filling for unknown ATS / custom forms."""
        logger.info(f"[generic_apply] Generic form for job {job.id}")
        page = self._page
        filler = self._filler

        await filler.fill_contact_info(page)
        await filler.upload_cv(page, self._cv_path)
        await filler.fill_salary(page)
        await filler.fill_cover_note(page, company=job.company, role=job.title)
        await filler.fill_experience_question(page)

        # Fill any remaining visible text inputs we haven't handled
        inputs = await page.query_selector_all("input[type='text'], input[type='email'], input[type='tel']")
        for inp in inputs:
            name_attr = (await inp.get_attribute("name") or "").lower()
            placeholder = (await inp.get_attribute("placeholder") or "").lower()
            val = await inp.input_value()
            if val:
                continue  # already filled
            if "linkedin" in name_attr or "linkedin" in placeholder:
                await inp.fill(filler.applicant_linkedin)

        return await self._submit_and_check(job)

    # ------------------------------------------------------------------
    # Submit + success detection
    # ------------------------------------------------------------------

    async def _submit_and_check(self, job: JobListingORM, page=None) -> tuple[bool, str]:
        if page is None:
            page = self._page
        filler = self._filler

        # Screenshot before submit
        await filler.take_screenshot(page, job.id)

        submit_selectors = [
            "button[type='submit']",
            "input[type='submit']",
            "button:has-text('Submit')",
            "button:has-text('Apply')",
            "button:has-text('Send Application')",
            "[data-automation='submit']",
        ]
        submitted = False
        for sel in submit_selectors:
            try:
                btn = await page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    submitted = True
                    break
            except Exception:
                pass

        if not submitted:
            return False, "Submit button not found"

        await asyncio.sleep(3)

        # Check for success
        current_url = page.url
        if _SUCCESS_URL.search(current_url):
            return True, ""

        try:
            body_text = await page.inner_text("body")
            if _SUCCESS_TEXT.search(body_text):
                return True, ""
        except Exception:
            pass

        # Assume success if no error is obvious
        logger.warning(f"[generic_apply] Job {job.id}: could not confirm success; assuming submitted")
        return True, ""
