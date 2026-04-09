"""Job listing models — Pydantic (in-memory) and SQLAlchemy ORM (persistent)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field
from sqlalchemy import Boolean, Column, Date, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase


# ---------------------------------------------------------------------------
# SQLAlchemy base
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# ORM model
# ---------------------------------------------------------------------------

class JobListingORM(Base):
    __tablename__ = "job_listings"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_source_external_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    external_id = Column(String(512), nullable=False)
    source = Column(String(64), nullable=False)   # linkedin | alljobs | drushim | glassdoor | indeed | company_direct
    title = Column(String(256), nullable=False)
    company = Column(String(256), nullable=False)
    location = Column(String(256), nullable=True)
    url = Column(Text, nullable=False)
    apply_url = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    salary_min = Column(Integer, nullable=True)
    salary_max = Column(Integer, nullable=True)
    posted_date = Column(Date, nullable=True)
    is_easy_apply = Column(Boolean, default=False)
    experience_level = Column(String(32), nullable=True)  # entry | junior | mid | None
    scraped_at = Column(DateTime, nullable=False)
    # Workflow status
    status = Column(String(32), nullable=False, default="PENDING")
    # PENDING | APPROVED | SUBMITTED | FAILED | SKIPPED
    status_updated_at = Column(DateTime, nullable=True)
    filter_reason = Column(Text, nullable=True)  # populated when status == SKIPPED


# ---------------------------------------------------------------------------
# Pydantic validation model (in-memory, produced by scrapers)
# ---------------------------------------------------------------------------

class JobListing(BaseModel):
    external_id: str
    source: str
    title: str
    company: str
    location: str = ""
    url: str
    apply_url: Optional[str] = None
    description: str = ""
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    posted_date: Optional[date] = None
    is_easy_apply: bool = False
    experience_level: Optional[str] = None
    scraped_at: datetime = Field(default_factory=datetime.utcnow)

    def to_orm(self) -> JobListingORM:
        return JobListingORM(
            external_id=self.external_id,
            source=self.source,
            title=self.title,
            company=self.company,
            location=self.location,
            url=self.url,
            apply_url=self.apply_url,
            description=self.description,
            salary_min=self.salary_min,
            salary_max=self.salary_max,
            posted_date=self.posted_date,
            is_easy_apply=self.is_easy_apply,
            experience_level=self.experience_level,
            scraped_at=self.scraped_at,
            status="PENDING",
        )
