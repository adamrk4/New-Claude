"""Tests for the job filter module."""
from __future__ import annotations

import pytest

from career_agent.filters.job_filter import FilterConfig, apply_filters
from career_agent.models.job import JobListing


def _make_config(**overrides) -> FilterConfig:
    defaults = dict(
        include_keywords=["Solutions Engineer", "Pre-Sales", "Technical Account Manager", "Customer Success Engineer"],
        exclude_keywords=["Full Stack", "QA Engineer", "Backend Developer"],
        locations=["Tel Aviv", "תל אביב", "Herzliya", "Petah Tikva", "Central Israel"],
        experience_signals=["junior", "entry level", "0-2 years", "new grad"],
        require_experience_signal=False,
    )
    defaults.update(overrides)
    return FilterConfig(**defaults)


def _job(**kwargs) -> JobListing:
    defaults = dict(
        external_id="test123",
        source="linkedin",
        title="Junior Solutions Engineer",
        company="Acme Corp",
        location="Tel Aviv",
        url="https://example.com/job/1",
        description="Entry-level role for a CS graduate.",
    )
    defaults.update(kwargs)
    return JobListing(**defaults)


class TestIncludeKeywords:
    def test_passes_when_title_matches(self):
        result = apply_filters(_job(title="Solutions Engineer"), _make_config())
        assert result.passed

    def test_passes_when_description_matches(self):
        result = apply_filters(
            _job(title="Sales Representative", description="This is a Pre-Sales role"),
            _make_config(),
        )
        assert result.passed

    def test_fails_when_no_match(self):
        result = apply_filters(
            _job(title="Software Developer", description="Backend Python development"),
            _make_config(),
        )
        assert not result.passed
        assert "include keyword" in result.reason.lower()

    def test_case_insensitive(self):
        result = apply_filters(_job(title="SOLUTIONS ENGINEER"), _make_config())
        assert result.passed


class TestExcludeKeywords:
    def test_excludes_full_stack(self):
        result = apply_filters(_job(title="Full Stack Solutions Engineer"), _make_config())
        assert not result.passed
        assert "Full Stack" in result.reason

    def test_excludes_qa_engineer(self):
        result = apply_filters(_job(title="QA Engineer - Technical Sales"), _make_config())
        assert not result.passed

    def test_exclude_only_on_title(self):
        # "Full Stack" in description only should NOT exclude
        result = apply_filters(
            _job(title="Solutions Engineer", description="Work alongside Full Stack developers"),
            _make_config(),
        )
        assert result.passed


class TestLocationFilter:
    def test_passes_for_tel_aviv(self):
        result = apply_filters(_job(location="Tel Aviv"), _make_config())
        assert result.passed

    def test_passes_for_hebrew_location(self):
        result = apply_filters(_job(location="תל אביב"), _make_config())
        assert result.passed

    def test_fails_for_out_of_area(self):
        result = apply_filters(_job(location="Haifa"), _make_config())
        assert not result.passed

    def test_passes_when_location_empty(self):
        # Empty location is allowed (company career pages often omit it)
        result = apply_filters(_job(location=""), _make_config())
        assert result.passed


class TestExperienceFilter:
    def test_passes_without_signal_when_not_required(self):
        result = apply_filters(
            _job(description="Looking for a talented solutions engineer"),
            _make_config(require_experience_signal=False),
        )
        assert result.passed

    def test_passes_with_signal_when_required(self):
        result = apply_filters(
            _job(description="junior solutions engineer, 0-2 years experience"),
            _make_config(require_experience_signal=True),
        )
        assert result.passed

    def test_fails_without_signal_when_required(self):
        result = apply_filters(
            _job(description="5+ years experience required"),
            _make_config(require_experience_signal=True),
        )
        assert not result.passed
