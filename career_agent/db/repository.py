"""CRUD helpers for job listings and applications."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from career_agent.db.engine import get_session
from career_agent.models.application import ApplicationRecord
from career_agent.models.job import JobListing, JobListingORM


def _now() -> datetime:
    return datetime.utcnow()


# ---------------------------------------------------------------------------
# Job listing operations
# ---------------------------------------------------------------------------

def upsert_job(job: JobListing, db_path: Path | None = None) -> JobListingORM:
    """Insert a new job or update description/scraped_at if it already exists.

    Returns the persisted ORM record.
    """
    session: Session = get_session(db_path) if db_path else get_session()
    with session:
        stmt = (
            insert(JobListingORM)
            .values(
                external_id=job.external_id,
                source=job.source,
                title=job.title,
                company=job.company,
                location=job.location,
                url=job.url,
                apply_url=job.apply_url,
                description=job.description,
                salary_min=job.salary_min,
                salary_max=job.salary_max,
                posted_date=job.posted_date,
                is_easy_apply=job.is_easy_apply,
                experience_level=job.experience_level,
                scraped_at=job.scraped_at,
                status="PENDING",
            )
            .on_conflict_do_update(
                index_elements=["source", "external_id"],
                set_={
                    "description": job.description,
                    "scraped_at": job.scraped_at,
                    "apply_url": job.apply_url,
                    "is_easy_apply": job.is_easy_apply,
                },
            )
        )
        session.execute(stmt)
        session.commit()

        record = session.scalar(
            select(JobListingORM)
            .where(JobListingORM.source == job.source)
            .where(JobListingORM.external_id == job.external_id)
        )
        return record


def skip_job(job_id: int, reason: str, db_path: Path | None = None) -> None:
    """Mark a job as SKIPPED with a filter reason."""
    session = get_session(db_path) if db_path else get_session()
    with session:
        record = session.get(JobListingORM, job_id)
        if record:
            record.status = "SKIPPED"
            record.filter_reason = reason
            record.status_updated_at = _now()
            session.commit()


def get_pending_jobs(db_path: Path | None = None) -> list[JobListingORM]:
    session = get_session(db_path) if db_path else get_session()
    with session:
        return session.scalars(
            select(JobListingORM).where(JobListingORM.status == "PENDING").order_by(JobListingORM.id)
        ).all()


def get_approved_jobs(db_path: Path | None = None) -> list[JobListingORM]:
    session = get_session(db_path) if db_path else get_session()
    with session:
        return session.scalars(
            select(JobListingORM).where(JobListingORM.status == "APPROVED").order_by(JobListingORM.id)
        ).all()


def mark_approved(job_ids: list[int], db_path: Path | None = None) -> int:
    """Mark given job IDs as APPROVED. Returns count of updated rows."""
    session = get_session(db_path) if db_path else get_session()
    count = 0
    with session:
        for jid in job_ids:
            record = session.get(JobListingORM, jid)
            if record and record.status == "PENDING":
                record.status = "APPROVED"
                record.status_updated_at = _now()
                count += 1
        session.commit()
    return count


def mark_submitted(job_id: int, application_id: int, db_path: Path | None = None) -> None:
    session = get_session(db_path) if db_path else get_session()
    with session:
        record = session.get(JobListingORM, job_id)
        if record:
            record.status = "SUBMITTED"
            record.status_updated_at = _now()
            session.commit()


def mark_failed(job_id: int, error: str, db_path: Path | None = None) -> None:
    session = get_session(db_path) if db_path else get_session()
    with session:
        record = session.get(JobListingORM, job_id)
        if record:
            record.status = "FAILED"
            record.filter_reason = error
            record.status_updated_at = _now()
            session.commit()


def get_weekly_jobs(
    since: Optional[datetime] = None, db_path: Path | None = None
) -> list[JobListingORM]:
    """Return all jobs scraped or updated in the last 7 days."""
    if since is None:
        since = _now() - timedelta(days=7)
    session = get_session(db_path) if db_path else get_session()
    with session:
        return session.scalars(
            select(JobListingORM)
            .where(JobListingORM.scraped_at >= since)
            .order_by(JobListingORM.scraped_at.desc())
        ).all()


# ---------------------------------------------------------------------------
# Application record operations
# ---------------------------------------------------------------------------

def create_application(
    job_id: int,
    status: str,
    salary_submitted: int = 17500,
    cv_path_used: str = "",
    error_message: str = "",
    screenshot_path: str = "",
    db_path: Path | None = None,
) -> ApplicationRecord:
    session = get_session(db_path) if db_path else get_session()
    with session:
        record = ApplicationRecord(
            job_id=job_id,
            submitted_at=_now(),
            status=status,
            error_message=error_message or None,
            screenshot_path=screenshot_path or None,
            salary_submitted=salary_submitted,
            cv_path_used=cv_path_used or None,
        )
        session.add(record)
        session.commit()
        session.refresh(record)
        return record


def job_exists(source: str, external_id: str, db_path: Path | None = None) -> bool:
    """Return True if a job with this (source, external_id) is already in the DB."""
    session = get_session(db_path) if db_path else get_session()
    with session:
        return session.scalar(
            select(JobListingORM)
            .where(JobListingORM.source == source)
            .where(JobListingORM.external_id == external_id)
        ) is not None
