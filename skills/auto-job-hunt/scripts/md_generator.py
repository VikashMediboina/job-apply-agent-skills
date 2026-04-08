#!/usr/bin/env python3
"""Markdown generation for auto-job-hunt - agent-readable format with proper segregation."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from paths import jobs_dir, jobs_status_dir, sanitize_filename


def jobs_to_markdown(
    jobs: list[dict],
    output_dir: Path,
    request: str = "",
    roles: list[str] = None,
    filters: dict = None,
) -> dict[str, str]:
    """Generate markdown files with proper segregation."""
    output_dir.mkdir(parents=True, exist_ok=True)
    generated = {}

    roles = roles or []
    filters = filters or {}

    by_role = {}
    for job in jobs:
        role = job.get("role", "Unknown")
        by_role.setdefault(role, []).append(job)

    index_jobs = []
    all_jobs_content = []

    for role, role_jobs in by_role.items():
        apply_jobs = [j for j in role_jobs if j.get("recommendation") == "Apply"]
        consider_jobs = [j for j in role_jobs if j.get("recommendation") == "Consider"]

        role_section = render_role_section(role, apply_jobs, consider_jobs)
        all_jobs_content.append(role_section)
        index_jobs.extend(role_jobs)

    jobs_file = output_dir / "jobs.md"
    jobs_content = render_jobs_md(
        all_jobs_content, request=request, roles=roles, filters=filters
    )
    jobs_file.write_text(jobs_content)
    generated[str(jobs_file)] = "jobs"

    index_file = output_dir / "index.md"
    index_content = render_index_md(
        index_jobs,
        request=request,
        roles=roles,
        filters=filters,
        by_role=by_role,
    )
    index_file.write_text(index_content)
    generated[str(index_file)] = "index"

    return generated


def render_index_md(
    jobs: list[dict],
    request: str = "",
    roles: list[str] = None,
    filters: dict = None,
    by_role: dict = None,
) -> str:
    """Render the main index.md file."""
    roles = roles or []
    filters = filters or {}
    by_role = by_role or {}

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    apply_count = sum(1 for j in jobs if j.get("recommendation") == "Apply")
    consider_count = sum(1 for j in jobs if j.get("recommendation") == "Consider")
    skip_count = sum(1 for j in jobs if j.get("recommendation") == "Skip")

    lines = [
        "# Job Search Results",
        "",
        f"**Generated**: {timestamp}",
        f'**Request**: "{request}"',
        "",
        "## Summary",
        "",
        f"- **Total Jobs**: {len(jobs)}",
        f"- **Apply (>=70%)**: {apply_count}",
        f"- **Consider (50-69%)**: {consider_count}",
        f"- **Skip (<50%)**: {skip_count}",
        "",
        "## Filters Applied",
        "",
    ]

    for key, value in filters.items():
        if value:
            lines.append(f"- {key}: {value}")

    lines.extend(
        [
            "",
            "## Jobs by Role",
            "",
            "| Role | Count | Apply | Consider |",
            "|------|-------|-------|----------|",
        ]
    )

    for role, role_jobs in sorted(by_role.items()):
        apply_c = sum(1 for j in role_jobs if j.get("recommendation") == "Apply")
        consider_c = sum(1 for j in role_jobs if j.get("recommendation") == "Consider")
        lines.append(f"| {role} | {len(role_jobs)} | {apply_c} | {consider_c} |")

    lines.extend(
        [
            "",
            "## Quick Links",
            "",
            f"- [All Jobs](./jobs.md)",
        ]
    )

    return "\n".join(lines)


def render_jobs_md(
    role_sections: list[str],
    request: str = "",
    roles: list[str] = None,
    filters: dict = None,
) -> str:
    """Render all jobs to single markdown with proper segregation."""
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    lines = [
        "# All Jobs",
        "",
        f"**Generated**: {timestamp}",
        f'**Request**: "{request}"',
        "",
        "---",
        "",
    ]

    lines.extend(role_sections)

    return "\n".join(lines)


def render_role_section(
    role: str, apply_jobs: list[dict], consider_jobs: list[dict]
) -> str:
    """Render a role section with Apply and Consider jobs properly segregated."""
    lines = [
        f"## {role}",
        "",
    ]

    if apply_jobs:
        lines.extend(
            [
                "### ✅ Apply (Score >= 70%)",
                "",
            ]
        )
        for job in sorted(apply_jobs, key=lambda j: -(j.get("score", 0))):
            lines.append(render_job_card(job))
            lines.append("")

    if consider_jobs:
        lines.extend(
            [
                "### 🤔 Consider (Score 50-69%)",
                "",
            ]
        )
        for job in sorted(consider_jobs, key=lambda j: -(j.get("score", 0))):
            lines.append(render_job_card(job))
            lines.append("")

    if not apply_jobs and not consider_jobs:
        lines.append("_No matching jobs found_")
        lines.append("")

    return "\n".join(lines)


def render_job_card(job: dict) -> str:
    """Render a single job as a compact markdown card with source info."""
    title = job.get("title", "Unknown Title")
    score = job.get("score", 0)
    recommendation = job.get("recommendation", "Skip")
    source = job.get("source", job.get("jobSource", {}).get("sourceName", "N/A"))

    lines = [
        f"**{title}**",
        "",
        f"- Company: {job.get('company', {}).get('name', 'N/A')}",
        f"- Location: {job.get('location', {}).get('city', 'N/A')}, {job.get('location', {}).get('state', '')} {job.get('location', {}).get('country', '')}",
        f"- Work Type: {job.get('workType', 'N/A')}",
        f"- Source: {source}",
    ]

    salary = job.get("salary", {})
    if salary.get("min") or salary.get("max"):
        min_s = f"${salary['min']:,}" if salary.get("min") else "N/A"
        max_s = f"${salary['max']:,}" if salary.get("max") else "N/A"
        lines.append(
            f"- Salary: {min_s} - {max_s} {salary.get('currencyCode', 'USD')} {salary.get('type', '')}"
        )

    lines.append(f"- Score: {score}% | {recommendation}")

    apply_url = job.get("apply", {}).get("applyUrl")
    if apply_url:
        lines.append(f"- Apply: {apply_url}")

    lines.append(f"- ID: {job.get('id', 'N/A')}")

    return "\n".join(lines)


def create_status_log(
    request: str,
    roles: list[str],
    filters: dict,
    results: dict,
    md_dir: str,
    status_dir: str | Path | None = None,
    timestamp: str | None = None,
) -> str:
    """Create the status log markdown file."""
    timestamp = timestamp or datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    status_root = Path(status_dir) if status_dir else jobs_status_dir()
    status_root.mkdir(parents=True, exist_ok=True)
    status_path = status_root / f"{timestamp}.md"

    total_scraped = sum(r.get("scraped", 0) for r in results.values())
    total_filtered = sum(r.get("filtered", 0) for r in results.values())
    apply_count = sum(
        1
        for r in results.values()
        for j in r.get("jobs", [])
        if j.get("recommendation") == "Apply"
    )
    consider_count = sum(
        1
        for r in results.values()
        for j in r.get("jobs", [])
        if j.get("recommendation") == "Consider"
    )
    skip_count = sum(
        1
        for r in results.values()
        for j in r.get("jobs", [])
        if j.get("recommendation") == "Skip"
    )

    lines = [
        "# Job Scraping Status",
        "",
        f"**Generated**: {timestamp}",
        f'**User Request**: "{request}"',
        f"**Roles**: {', '.join(roles)}",
        f"**Filters**: {format_filters(filters)}",
        "",
        "## Results Summary",
        "",
        "| Source | Scraped | After Filter | Notes |",
        "|--------|---------|---------------|-------|",
    ]

    for source, data in results.items():
        lines.append(
            f"| {source.capitalize()} | {data.get('scraped', 0)} | {data.get('filtered', 0)} | {data.get('notes', '')} |"
        )

    lines.extend(
        [
            f"| **Total** | **{total_scraped}** | **{total_filtered}** | Target: {sum(r.get('target', 0) for r in results.values())} |",
            "",
            "## Score Distribution",
            "",
            f"- Apply (>=70%): {apply_count}",
            f"- Consider (50-69%): {consider_count}",
            f"- Skip (<50%): {skip_count}",
            "",
            "## Output Directory",
            "",
            f"- Jobs: `{md_dir}`",
            f"- Status: `{status_path}`",
            "",
        ]
    )

    status_path.write_text("\n".join(lines))
    return str(status_path)


def format_filters(filters: dict) -> str:
    """Format filters for display."""
    parts = []
    if filters.get("location"):
        parts.append(f"location: {filters['location']}")
    if filters.get("work_mode"):
        parts.append(f"work_mode: {filters['work_mode']}")
    if filters.get("visa_status"):
        parts.append(f"visa: {filters['visa_status']}")
    if filters.get("score_threshold"):
        parts.append(f"score > {filters['score_threshold']}%")
    return ", ".join(parts) if parts else "default"


def consolidate_jobs(job_files: list[str]) -> list[dict]:
    """Consolidate jobs from multiple JSON files."""
    jobs: list[dict] = []
    for filepath in job_files:
        path = Path(filepath)
        if not path.exists():
            continue
        try:
            loaded = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        if isinstance(loaded, list):
            jobs.extend(loaded)
        elif isinstance(loaded, dict):
            jobs.append(loaded)
    return jobs


if __name__ == "__main__":
    test_jobs = [
        {
            "id": "1",
            "externalJobId": "EXT001",
            "title": "AI/ML Engineer",
            "jobDescription": "Looking for ML engineer with Python and TensorFlow experience",
            "salary": {
                "min": 120000,
                "max": 180000,
                "currencyCode": "USD",
                "type": "yearly",
            },
            "jobTypes": ["Full-time"],
            "workType": "remote",
            "location": {
                "city": "Boston",
                "state": "MA",
                "country": "US",
                "remote": True,
            },
            "company": {"name": "TechCorp", "industry": "AI"},
            "apply": {"applyUrl": "https://example.com/apply"},
            "jobSource": {"sourceName": "Dice"},
            "score": 75,
            "recommendation": "Apply",
            "searchTerm": "AI Engineer",
            "source": "dice",
            "username": "test_user",
            "role": "AI/ML Engineer",
        },
        {
            "id": "2",
            "externalJobId": "EXT002",
            "title": "Data Scientist",
            "jobDescription": "Looking for data scientist with Python and SQL",
            "salary": {
                "min": 100000,
                "max": 150000,
                "currencyCode": "USD",
                "type": "yearly",
            },
            "jobTypes": ["Full-time"],
            "workType": "hybrid",
            "location": {
                "city": "New York",
                "state": "NY",
                "country": "US",
                "remote": False,
            },
            "company": {"name": "DataCorp", "industry": "Analytics"},
            "apply": {"applyUrl": "https://example.com/apply2"},
            "jobSource": {"sourceName": "Indeed"},
            "score": 55,
            "recommendation": "Consider",
            "searchTerm": "Data Scientist",
            "source": "indeed",
            "username": "test_user",
            "role": "Data Scientist",
        },
    ]
    output = jobs_dir() / "test_output"
    result = jobs_to_markdown(
        test_jobs, output, "test request", ["AI/ML Engineer", "Data Scientist"]
    )
    print(f"Generated files: {list(result.keys())}")
