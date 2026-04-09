"""Tests for the DB repository module."""
from __future__ import annotations

import pytest

from career_agent.db.repository import (
    create_application,
    get_approved_jobs,
    get_pending_jobs,
    get_weekly_jobs,
    job_exists,
    mark_approved,
    mark_failed,
    mark_submitted,
    skip_job,
    upsert_job,
)
from career_agent.models.job import JobListing


def _job(external_id: str = "abc123", source: str = "linkedin", title: str = "Solutions Engineer") -> JobListing:
    return JobListing(
        external_id=external_id,
        source=source,
        title=title,
        company="TestCo",
        location="Tel Aviv",
        url=f"https://example.com/{external_id}",
    )


class TestUpsertJob:
    def test_inserts_new_job(self):
        record = upsert_job(_job())
        assert record.id is not None
        assert record.status == "PENDING"

    def test_duplicate_does_not_raise(self):
        job = _job()
        upsert_job(job)
        upsert_job(job)  # should not raise
        assert len(get_pending_jobs()) == 1

    def test_upsert_updates_description(self):
        job = _job()
        upsert_job(job)
        job2 = _job()
        job2.description = "Updated description"
        record = upsert_job(job2)
        assert record.description == "Updated description"


class TestJobExists:
    def test_returns_false_for_unknown_job(self):
        assert not job_exists("linkedin", "nonexistent")

    def test_returns_true_after_insert(self):
        upsert_job(_job(external_id="xyz"))
        assert job_exists("linkedin", "xyz")


class TestStatusTransitions:
    def test_mark_approved(self):
        record = upsert_job(_job())
        count = mark_approved([record.id])
        assert count == 1
        approved = get_approved_jobs()
        assert len(approved) == 1

    def test_mark_approved_skips_non_pending(self):
        record = upsert_job(_job())
        skip_job(record.id, "filtered")
        count = mark_approved([record.id])
        assert count == 0

    def test_skip_job(self):
        record = upsert_job(_job())
        skip_job(record.id, "No include keyword matched")
        pending = get_pending_jobs()
        assert len(pending) == 0

    def test_mark_submitted(self):
        record = upsert_job(_job())
        mark_approved([record.id])
        app = create_application(job_id=record.id, status="SUCCESS")
        mark_submitted(record.id, app.id)
        # Job should no longer be in approved list
        assert len(get_approved_jobs()) == 0

    def test_mark_failed(self):
        record = upsert_job(_job())
        mark_failed(record.id, "Timeout")
        # Should not be in pending or approved
        assert len(get_pending_jobs()) == 0
        assert len(get_approved_jobs()) == 0


class TestGetWeeklyJobs:
    def test_returns_recently_scraped(self):
        upsert_job(_job(external_id="w1"))
        upsert_job(_job(external_id="w2", source="alljobs"))
        weekly = get_weekly_jobs()
        assert len(weekly) == 2
