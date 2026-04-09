"""Job filter — applies include/exclude keyword, location, experience, and duplicate rules."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from career_agent.models.job import JobListing
from career_agent.parsers.job_parser import normalise_text


@dataclass
class FilterConfig:
    include_keywords: list[str]
    exclude_keywords: list[str]
    locations: list[str]
    experience_signals: list[str]
    require_experience_signal: bool = False


@dataclass
class FilterResult:
    passed: bool
    reason: str = ""


def _compile_patterns(keywords: list[str]) -> list[re.Pattern]:
    return [re.compile(re.escape(kw), re.IGNORECASE) for kw in keywords]


def _any_match(patterns: list[re.Pattern], text: str) -> str | None:
    """Return the first matching keyword string, or None."""
    for p in patterns:
        m = p.search(text)
        if m:
            return m.group(0)
    return None


def apply_filters(job: JobListing, config: FilterConfig) -> FilterResult:
    """
    Run all filters in order. Returns FilterResult(passed=True) only if all pass.

    Order:
      1. Include-keyword check (title + description must match at least one)
      2. Exclude-keyword check (title must NOT match any)
      3. Location check (location field must contain a known Central Israel city)
      4. Experience-level check (optional, controlled by require_experience_signal)
    """
    title_and_desc = normalise_text(f"{job.title} {job.description}")
    title_only = normalise_text(job.title)
    location_text = normalise_text(job.location)

    include_pats = _compile_patterns(config.include_keywords)
    exclude_pats = _compile_patterns(config.exclude_keywords)
    location_pats = _compile_patterns(config.locations)
    exp_pats = _compile_patterns(config.experience_signals)

    # 1. Include keyword
    hit = _any_match(include_pats, title_and_desc)
    if not hit:
        return FilterResult(passed=False, reason=f"No include keyword matched in title/description")

    # 2. Exclude keyword (check title only — avoids false positives from JD body text)
    bad = _any_match(exclude_pats, title_only)
    if bad:
        return FilterResult(passed=False, reason=f"Excluded keyword in title: '{bad}'")

    # 3. Location — allow empty location (company career pages often omit it)
    if location_text:
        loc_hit = _any_match(location_pats, location_text)
        if not loc_hit:
            return FilterResult(passed=False, reason=f"Location '{job.location}' not in Central Israel list")

    # 4. Experience signal (optional gate)
    if config.require_experience_signal:
        exp_hit = _any_match(exp_pats, title_and_desc)
        if not exp_hit:
            return FilterResult(
                passed=False,
                reason="No entry-level experience signal found (require_experience_signal=true)"
            )

    return FilterResult(passed=True, reason=f"Matched include keyword: '{hit}'")


def build_filter_config(settings: dict[str, Any]) -> FilterConfig:
    """Build a FilterConfig from the parsed settings.yaml dict."""
    f = settings.get("filters", {})
    return FilterConfig(
        include_keywords=f.get("include_keywords", []),
        exclude_keywords=f.get("exclude_keywords", []),
        locations=f.get("locations", []),
        experience_signals=f.get("experience_signals", []),
        require_experience_signal=f.get("require_experience_signal", False),
    )
