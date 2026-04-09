"""Digest builder — renders today's pending jobs as a Rich table and markdown snippet."""
from __future__ import annotations

from datetime import datetime, timezone

from rich.console import Console
from rich.table import Table
from rich import box

from career_agent.models.job import JobListingORM

_PLATFORM_COLORS = {
    "linkedin": "bright_blue",
    "alljobs": "green",
    "drushim": "cyan",
    "glassdoor": "bright_green",
    "indeed": "yellow",
    "company_direct": "magenta",
}


def _platform_color(source: str) -> str:
    return _PLATFORM_COLORS.get(source.lower(), "white")


def build_rich_table(jobs: list[JobListingORM], title: str = "Today's Pending Jobs") -> Table:
    """Build a Rich Table from a list of job ORM records."""
    table = Table(
        title=title,
        box=box.ROUNDED,
        show_header=True,
        header_style="bold white",
        highlight=True,
    )
    table.add_column("ID", style="bold", width=5, justify="right")
    table.add_column("Title", style="white", min_width=30)
    table.add_column("Company", style="bold yellow", min_width=20)
    table.add_column("Platform", min_width=12)
    table.add_column("Location", style="dim", min_width=16)
    table.add_column("Exp Level", width=10)
    table.add_column("Easy Apply", width=10, justify="center")
    table.add_column("URL", style="blue underline", min_width=20, no_wrap=True, overflow="fold")

    for job in jobs:
        color = _platform_color(job.source)
        exp = job.experience_level or "—"
        easy = "✓" if job.is_easy_apply else ""
        # Shorten URL for display
        display_url = job.url
        if len(display_url) > 60:
            display_url = display_url[:57] + "..."
        table.add_row(
            str(job.id),
            job.title,
            job.company,
            f"[{color}]{job.source}[/{color}]",
            job.location or "—",
            exp,
            easy,
            display_url,
        )

    return table


def build_markdown_digest(jobs: list[JobListingORM]) -> str:
    """Render jobs as a markdown table string (for pasting into notes/email)."""
    if not jobs:
        return "_No pending jobs today._\n"

    lines = [
        f"## Job Digest — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
        "",
        "| ID | Title | Company | Platform | Location | Easy Apply | Link |",
        "|----|-------|---------|----------|----------|------------|------|",
    ]
    for job in jobs:
        easy = "Yes" if job.is_easy_apply else "No"
        link = f"[link]({job.url})"
        lines.append(
            f"| {job.id} | {job.title} | {job.company} | {job.source} "
            f"| {job.location or '—'} | {easy} | {link} |"
        )
    return "\n".join(lines) + "\n"


def print_digest(jobs: list[JobListingORM], console: Console | None = None) -> None:
    """Print a Rich digest table to the terminal."""
    c = console or Console()
    if not jobs:
        c.print("\n[bold yellow]No pending jobs found. Run `career-agent run` to scrape.[/bold yellow]\n")
        return

    table = build_rich_table(jobs)
    c.print()
    c.print(table)
    c.print(
        f"\n[bold green]{len(jobs)} pending job(s).[/bold green] "
        "Run [bold]career-agent approve --id <IDs>[/bold] or "
        "[bold]career-agent approve --interactive[/bold] to select jobs.\n"
    )
