"""Tests for the digest builder module."""
from __future__ import annotations

from datetime import datetime

from career_agent.digest.digest_builder import build_markdown_digest, build_rich_table
from career_agent.models.job import JobListingORM


def _make_orm_job(
    id: int = 1,
    title: str = "Solutions Engineer",
    company: str = "Acme",
    source: str = "linkedin",
    location: str = "Tel Aviv",
    is_easy_apply: bool = True,
    url: str = "https://example.com/job/1",
) -> JobListingORM:
    job = JobListingORM()
    job.id = id
    job.title = title
    job.company = company
    job.source = source
    job.location = location
    job.is_easy_apply = is_easy_apply
    job.url = url
    job.experience_level = "entry"
    job.status = "PENDING"
    job.scraped_at = datetime.utcnow()
    return job


class TestBuildRichTable:
    def test_creates_table_with_correct_columns(self):
        jobs = [_make_orm_job()]
        table = build_rich_table(jobs)
        # Rich Table has column objects
        col_names = [col.header for col in table.columns]
        assert "Title" in col_names
        assert "Company" in col_names
        assert "Platform" in col_names

    def test_empty_jobs_still_creates_table(self):
        table = build_rich_table([])
        assert table is not None


class TestBuildMarkdownDigest:
    def test_returns_no_jobs_message_when_empty(self):
        result = build_markdown_digest([])
        assert "No pending jobs" in result

    def test_contains_job_info(self):
        jobs = [_make_orm_job(title="Pre-Sales Engineer", company="BigCorp")]
        md = build_markdown_digest(jobs)
        assert "Pre-Sales Engineer" in md
        assert "BigCorp" in md

    def test_contains_link(self):
        jobs = [_make_orm_job(url="https://linkedin.com/job/999")]
        md = build_markdown_digest(jobs)
        assert "https://linkedin.com/job/999" in md

    def test_easy_apply_shown(self):
        jobs = [_make_orm_job(is_easy_apply=True)]
        md = build_markdown_digest(jobs)
        assert "Yes" in md
