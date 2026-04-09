"""Application record ORM model — tracks each submission attempt."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from career_agent.models.job import Base


class ApplicationRecord(Base):
    __tablename__ = "applications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(Integer, ForeignKey("job_listings.id"), nullable=False)
    submitted_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    status = Column(String(32), nullable=False)     # SUCCESS | FAILED | PARTIAL
    error_message = Column(Text, nullable=True)
    screenshot_path = Column(Text, nullable=True)
    salary_submitted = Column(Integer, nullable=True)   # always 17500
    cv_path_used = Column(Text, nullable=True)
