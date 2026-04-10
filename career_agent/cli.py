"""Career Agent CLI — Typer-based command-line interface."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.prompt import Confirm

app = typer.Typer(
    name="career-agent",
    help="Semi-automated job search and application agent for tech-commercial roles in Israel.",
    add_completion=False,
)
console = Console()


def _load() -> dict:
    from career_agent.config_loader import load_settings
    return load_settings()


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------

@app.command()
def run(
    settings_path: str = typer.Option("config/settings.yaml", "--config", "-c", help="Path to settings.yaml"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Scrape and filter but do NOT write to DB"),
    auto_approve: bool = typer.Option(False, "--auto-approve", help="Immediately approve all new jobs (skips manual review)"),
):
    """Scrape all platforms, filter results, save to DB, and print digest."""
    from career_agent.config_loader import load_settings
    from career_agent.db.engine import init_db
    from career_agent.db.repository import get_pending_jobs
    from career_agent.digest.digest_builder import print_digest
    from career_agent.pipeline import run_pipeline

    settings = load_settings(settings_path)

    if not dry_run:
        init_db()

    console.print("\n[bold cyan]Starting scrape...[/bold cyan]")
    stats = asyncio.run(_run_scrape(settings, dry_run=dry_run))

    console.print(
        f"\n[bold green]Scrape complete[/bold green] — "
        f"scraped: {stats['scraped']}, "
        f"[green]new: {stats['new']}[/green], "
        f"skipped: {stats['skipped']}, "
        f"duplicate: {stats['duplicate']}"
    )

    if not dry_run:
        pending = get_pending_jobs()
        print_digest(pending, console)

        if auto_approve and pending:
            from career_agent.db.repository import mark_approved
            ids = [j.id for j in pending]
            count = mark_approved(ids)
            console.print(f"[bold yellow]Auto-approved {count} job(s).[/bold yellow]")
            console.print("Run [bold]career-agent submit[/bold] to apply.")


async def _run_scrape(settings: dict, dry_run: bool) -> dict:
    if dry_run:
        # Dry run: run pipeline but don't persist
        from career_agent.pipeline import run_pipeline
        # Monkey-patch upsert to no-op
        import career_agent.pipeline as pipeline_mod
        import career_agent.db.repository as repo
        _orig_upsert = repo.upsert_job
        _orig_skip = repo.skip_job
        _orig_exists = repo.job_exists

        inserted = []

        def fake_upsert(job, db_path=None):
            from career_agent.models.job import JobListingORM
            from datetime import datetime
            orm = job.to_orm()
            orm.id = len(inserted) + 1
            inserted.append(orm)
            return orm

        repo.upsert_job = fake_upsert
        repo.skip_job = lambda *a, **kw: None
        repo.job_exists = lambda *a, **kw: False

        try:
            stats = await run_pipeline(settings)
        finally:
            repo.upsert_job = _orig_upsert
            repo.skip_job = _orig_skip
            repo.job_exists = _orig_exists

        # Print dry-run digest
        from career_agent.digest.digest_builder import build_rich_table
        from rich.console import Console as C
        c = C()
        if inserted:
            c.print(build_rich_table(inserted, title="Dry Run — Jobs Found"))
        return stats
    else:
        from career_agent.pipeline import run_pipeline
        return await run_pipeline(settings)


# ---------------------------------------------------------------------------
# digest
# ---------------------------------------------------------------------------

@app.command()
def digest(
    settings_path: str = typer.Option("config/settings.yaml", "--config", "-c"),
    markdown: bool = typer.Option(False, "--markdown", "-m", help="Output markdown instead of Rich table"),
):
    """Show today's pending jobs without scraping."""
    from career_agent.db.engine import init_db
    from career_agent.db.repository import get_pending_jobs
    from career_agent.digest.digest_builder import build_markdown_digest, print_digest

    init_db()
    pending = get_pending_jobs()

    if markdown:
        console.print(build_markdown_digest(pending))
    else:
        print_digest(pending, console)


# ---------------------------------------------------------------------------
# approve
# ---------------------------------------------------------------------------

@app.command()
def approve(
    ids: Optional[str] = typer.Option(None, "--id", help="Comma-separated job IDs to approve, e.g. 3,7,11"),
    all_pending: bool = typer.Option(False, "--all", help="Approve ALL pending jobs"),
    interactive: bool = typer.Option(False, "--interactive", "-i", help="Interactive checkbox selection"),
):
    """Mark jobs as APPROVED so they will be submitted."""
    from career_agent.db.engine import init_db
    from career_agent.db.repository import get_pending_jobs, mark_approved

    init_db()
    pending = get_pending_jobs()

    if not pending:
        console.print("[yellow]No pending jobs to approve.[/yellow]")
        raise typer.Exit()

    if all_pending:
        job_ids = [j.id for j in pending]
    elif interactive:
        job_ids = _interactive_approve(pending)
    elif ids:
        try:
            job_ids = [int(x.strip()) for x in ids.split(",")]
        except ValueError:
            console.print("[red]Invalid ID list. Use --id 3,7,11[/red]")
            raise typer.Exit(1)
    else:
        from career_agent.digest.digest_builder import print_digest
        print_digest(pending, console)
        console.print("Use [bold]--id <IDs>[/bold], [bold]--interactive[/bold], or [bold]--all[/bold]")
        raise typer.Exit()

    count = mark_approved(job_ids)
    console.print(f"\n[bold green]Approved {count} job(s).[/bold green] Run [bold]career-agent submit[/bold] to apply.\n")


def _interactive_approve(pending) -> list[int]:
    """Present a questionary checkbox list. Returns selected job IDs."""
    try:
        import questionary
    except ImportError:
        console.print("[red]questionary not installed. Run: pip install questionary[/red]")
        return []

    choices = [
        questionary.Choice(
            title=f"[{j.id:>4}] {j.title:<45} {j.company:<25} ({j.source})",
            value=j.id,
        )
        for j in pending
    ]
    selected = questionary.checkbox("Select jobs to approve:", choices=choices).ask()
    return selected or []


# ---------------------------------------------------------------------------
# skipped
# ---------------------------------------------------------------------------

@app.command()
def skipped():
    """Show jobs that were filtered out and why — useful for debugging filters."""
    from sqlalchemy import select
    from rich.table import Table
    from rich import box
    from career_agent.db.engine import init_db, get_session
    from career_agent.models.job import JobListingORM

    init_db()
    session = get_session()
    with session:
        jobs = session.scalars(
            select(JobListingORM)
            .where(JobListingORM.status == "SKIPPED")
            .order_by(JobListingORM.id.desc())
            .limit(100)
        ).all()

    if not jobs:
        console.print("[green]No skipped jobs.[/green]")
        raise typer.Exit()

    table = Table(title=f"Skipped Jobs ({len(jobs)} shown)", box=box.ROUNDED)
    table.add_column("ID", width=5, justify="right")
    table.add_column("Title", min_width=30)
    table.add_column("Company", min_width=18)
    table.add_column("Platform", width=12)
    table.add_column("Reason", style="dim")

    for job in jobs:
        table.add_row(
            str(job.id),
            job.title,
            job.company,
            job.source,
            job.filter_reason or "—",
        )

    console.print()
    console.print(table)
    console.print()


# ---------------------------------------------------------------------------
# submit
# ---------------------------------------------------------------------------

@app.command()
def submit(
    settings_path: str = typer.Option("config/settings.yaml", "--config", "-c"),
    job_id: Optional[int] = typer.Option(None, "--id", help="Submit only this specific job ID"),
):
    """Submit applications for all APPROVED jobs."""
    from career_agent.config_loader import load_settings
    from career_agent.db.engine import init_db
    from career_agent.db.repository import get_approved_jobs, get_session, mark_failed, mark_submitted, create_application
    from career_agent.models.job import JobListingORM

    settings = load_settings(settings_path)
    init_db()

    session = get_session()
    with session:
        if job_id:
            from sqlalchemy import select
            jobs = session.scalars(
                select(JobListingORM).where(JobListingORM.id == job_id).where(JobListingORM.status == "APPROVED")
            ).all()
        else:
            from sqlalchemy import select
            jobs = session.scalars(
                select(JobListingORM).where(JobListingORM.status == "APPROVED")
            ).all()

    if not jobs:
        console.print("[yellow]No approved jobs to submit. Run `career-agent approve` first.[/yellow]")
        raise typer.Exit()

    console.print(f"\n[bold cyan]Submitting {len(jobs)} application(s)...[/bold cyan]\n")
    asyncio.run(_submit_all(jobs, settings))


async def _submit_all(jobs, settings: dict) -> None:
    cv_path = settings.get("cv_path", "data/cv/my_cv.pdf")
    submitted_count = 0
    failed_count = 0

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        console.print("[red]Playwright not installed. Run: pip install playwright && playwright install chromium[/red]")
        return

    from career_agent.applicator.linkedin_apply import LinkedInApplicator
    from career_agent.applicator.generic_apply import GenericApplicator
    from career_agent.db.repository import create_application, mark_failed, mark_submitted
    from career_agent.scrapers.base import AbstractScraper

    # Load LinkedIn auth for application (reuse login)
    linkedin_auth = settings.get("scrapers", {}).get("linkedin", {}).get("auth_state_path", "data/linkedin_auth.json")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context_kwargs = {"viewport": {"width": 1280, "height": 800}}
        if Path(linkedin_auth).exists():
            context_kwargs["storage_state"] = linkedin_auth
        context = await browser.new_context(**context_kwargs)
        page = await context.new_page()

        for job in jobs:
            console.print(f"  Applying → [bold]{job.title}[/bold] @ {job.company} ({job.source})")
            try:
                if job.source == "linkedin" and job.is_easy_apply:
                    applicator = LinkedInApplicator(page, settings, cv_path)
                else:
                    applicator = GenericApplicator(page, settings, cv_path)

                success, error = await applicator.apply(job)
            except Exception as e:
                success, error = False, str(e)

            app_record = create_application(
                job_id=job.id,
                status="SUCCESS" if success else "FAILED",
                salary_submitted=settings.get("application", {}).get("salary_value", 17500),
                cv_path_used=cv_path,
                error_message=error,
            )

            if success:
                mark_submitted(job.id, app_record.id)
                submitted_count += 1
                console.print(f"    [green]✓ Submitted[/green]")
            else:
                mark_failed(job.id, error)
                failed_count += 1
                console.print(f"    [red]✗ Failed: {error}[/red]")

        await browser.close()

    console.print(
        f"\n[bold green]Done.[/bold green] "
        f"Submitted: {submitted_count}, Failed: {failed_count}\n"
    )


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

@app.command()
def report(
    output_dir: str = typer.Option("data/exports", "--output", "-o", help="Directory for report files"),
):
    """Generate the weekly markdown report now."""
    from career_agent.db.engine import init_db
    from career_agent.reporter.weekly_report import generate_weekly_report

    init_db()
    path = generate_weekly_report(output_dir)
    console.print(f"\n[bold green]Report saved:[/bold green] {path}\n")


# ---------------------------------------------------------------------------
# scheduler
# ---------------------------------------------------------------------------

@app.command()
def scheduler(
    settings_path: str = typer.Option("config/settings.yaml", "--config", "-c"),
):
    """Start the background scheduler (daily scrape + weekly report)."""
    from career_agent.config_loader import load_settings
    from career_agent.db.engine import init_db
    from career_agent.scheduler.scheduler import start_scheduler

    settings = load_settings(settings_path)
    init_db()

    console.print("\n[bold cyan]Starting scheduler...[/bold cyan]")
    console.print("Press Ctrl+C to stop.\n")
    asyncio.run(start_scheduler(settings))


# ---------------------------------------------------------------------------
# cv-info
# ---------------------------------------------------------------------------

@app.command(name="cv-info")
def cv_info(
    settings_path: str = typer.Option("config/settings.yaml", "--config", "-c"),
):
    """Parse and display your CV summary."""
    from career_agent.config_loader import load_settings
    from career_agent.parsers.cv_parser import parse_cv

    settings = load_settings(settings_path)
    cv_path = settings.get("cv_path", "data/cv/my_cv.pdf")

    try:
        cv = parse_cv(cv_path)
        console.print(f"\n[bold]Name:[/bold] {cv.name}")
        console.print(f"[bold]Email:[/bold] {cv.email}")
        console.print(f"[bold]Phone:[/bold] {cv.phone}")
        console.print(f"[bold]Skills ({len(cv.skills)}):[/bold] {', '.join(cv.skills[:10])}")
        console.print(f"[bold]Education:[/bold] {cv.education[:200]}")
        console.print(f"[bold]Projects ({len(cv.projects)}):[/bold] {cv.projects[:3]}")
    except FileNotFoundError:
        console.print(f"[red]CV not found at '{cv_path}'. Drop your PDF/DOCX in data/cv/ and update config/settings.yaml.[/red]")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
