"""Weekly report generator — queries DB and renders a markdown summary."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from jinja2 import Template
from loguru import logger

from career_agent.db.repository import get_weekly_jobs
from career_agent.models.job import JobListingORM

_TEMPLATE = """\
# Career Agent — Weekly Report

**Period:** {{ period_start }} → {{ period_end }}
**Generated:** {{ generated_at }}

---

## Summary

| Status | Count |
|--------|-------|
{% for status, count in summary.items() -%}
| {{ status }} | {{ count }} |
{% endfor %}

---

## Applications Submitted ✅

{% if submitted %}
| Company | Job Title | Platform | Link | Applied |
|---------|-----------|----------|------|---------|
{% for job in submitted -%}
| {{ job.company }} | {{ job.title }} | {{ job.source }} | [link]({{ job.url }}) | {{ job.status_updated_at | datefmt }} |
{% endfor %}
{% else %}
_No applications submitted this week._
{% endif %}

---

## Failed Applications ❌

{% if failed %}
| Company | Job Title | Error |
|---------|-----------|-------|
{% for job in failed -%}
| {{ job.company }} | {{ job.title }} | {{ job.filter_reason or "Unknown error" }} |
{% endfor %}
{% else %}
_No failures this week._
{% endif %}

---

## Pending (not yet actioned) ⏳

{% if pending %}
| ID | Company | Job Title | Platform | Link |
|----|---------|-----------|----------|------|
{% for job in pending -%}
| {{ job.id }} | {{ job.company }} | {{ job.title }} | {{ job.source }} | [link]({{ job.url }}) |
{% endfor %}
{% else %}
_No pending jobs._
{% endif %}

---

## Skipped (filtered out) 🚫

{% if skipped %}
| Company | Job Title | Reason |
|---------|-----------|--------|
{% for job in skipped -%}
| {{ job.company }} | {{ job.title }} | {{ job.filter_reason or "—" }} |
{% endfor %}
{% else %}
_No jobs skipped this week._
{% endif %}
"""


def _datefmt(dt) -> str:
    if dt is None:
        return "—"
    if isinstance(dt, str):
        return dt[:10]
    return dt.strftime("%Y-%m-%d")


def generate_weekly_report(output_dir: str | Path = "data/exports") -> Path:
    """Generate a weekly markdown report and save it. Returns the output path."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=7)

    jobs = get_weekly_jobs(since=since.replace(tzinfo=None))

    submitted = [j for j in jobs if j.status == "SUBMITTED"]
    failed = [j for j in jobs if j.status == "FAILED"]
    pending = [j for j in jobs if j.status == "PENDING"]
    approved = [j for j in jobs if j.status == "APPROVED"]
    skipped = [j for j in jobs if j.status == "SKIPPED"]

    summary = {
        "SUBMITTED": len(submitted),
        "APPROVED (not yet submitted)": len(approved),
        "PENDING (awaiting review)": len(pending),
        "FAILED": len(failed),
        "SKIPPED": len(skipped),
        "TOTAL": len(jobs),
    }

    tpl = Template(_TEMPLATE)
    tpl.globals["datefmt"] = _datefmt

    content = tpl.render(
        period_start=since.strftime("%Y-%m-%d"),
        period_end=now.strftime("%Y-%m-%d"),
        generated_at=now.strftime("%Y-%m-%d %H:%M UTC"),
        summary=summary,
        submitted=submitted,
        failed=failed,
        pending=pending,
        skipped=skipped,
    )

    filename = output_dir / f"report_{now.strftime('%Y-%m-%d')}.md"
    filename.write_text(content, encoding="utf-8")
    logger.info(f"Weekly report written to {filename}")
    return filename
