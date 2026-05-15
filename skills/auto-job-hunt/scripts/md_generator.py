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


def _safe_get(obj: dict | None, *keys: str, default: str = "N/A") -> str:
    """Safely traverse nested dicts, returning *default* if any key is missing."""
    current = obj
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
        if current is None:
            return default
    return str(current) if current else default


def render_job_card(job: dict) -> str:
    """Render a single job as a strict, consistent markdown card.

    Strict format — every card has the SAME fields in the SAME order.
    Missing data renders as "N/A", never omitted.

    Sections:
    1. Title + Score
    2. Company details (name, website, industry, rating)
    3. Client/Vendor company (for staffing/contract roles)
    4. Location + Work type
    5. Salary
    6. Employment details
    7. Recruiter info
    8. Source + Apply link
    9. ID
    """
    title = job.get("title", "Unknown Title")
    score = job.get("score", 0)
    recommendation = job.get("recommendation", "Skip")

    company = job.get("company") or {}
    if isinstance(company, str):
        company = {"name": company}
    client_company = job.get("clientCompany") or {}
    vendor_company = job.get("vendorCompany") or {}
    location = job.get("location") or {}
    if isinstance(location, str):
        location = {"city": location}
    salary = job.get("salary") or {}
    recruiter = job.get("recruiter") or {}
    job_source = job.get("jobSource") or {}
    apply_info = job.get("apply") or {}

    # --- Source (handles both nested and flat schemas) ---
    raw_source = job.get("source", job_source.get("sourceName", "N/A"))
    if isinstance(raw_source, dict):
        source_name = raw_source.get("name", "N/A")
        source_type = raw_source.get("type", job_source.get("sourceType", "N/A"))
    else:
        source_name = str(raw_source) if raw_source else "N/A"
        source_type = job_source.get("sourceType", "N/A")

    # --- Apply URL (handles both nested and flat schemas) ---
    apply_url = (
        apply_info.get("applyUrl")
        or job.get("applyUrl")
        or job.get("apply_url")
        or "N/A"
    )
    easy_apply = apply_info.get("easyApply", job.get("easyApply", "N/A"))
    if isinstance(easy_apply, bool):
        easy_apply = "Yes" if easy_apply else "No"

    # --- Location string ---
    loc_parts = [
        location.get("city", ""),
        location.get("state", ""),
        location.get("country", ""),
    ]
    loc_str = ", ".join(p for p in loc_parts if p) or "N/A"

    # --- Salary string ---
    sal_min = salary.get("min")
    sal_max = salary.get("max")
    if sal_min or sal_max:
        min_s = f"${sal_min:,}" if sal_min else "N/A"
        max_s = f"${sal_max:,}" if sal_max else "N/A"
        currency = salary.get("currency", salary.get("currencyCode", "USD"))
        sal_type = salary.get("type", "")
        salary_str = f"{min_s} - {max_s} {currency} {sal_type}".strip()
    else:
        salary_str = "N/A"

    # --- Job types ---
    job_types = job.get("jobTypes", [])
    job_types_str = ", ".join(job_types) if job_types else "N/A"

    # --- Build card ---
    lines = [
        f"**{title}**",
        f"Score: {score}% | {recommendation}",
        "",
        # Company details — always present
        f"- Company: {_safe_get(company, 'name')}",
        f"- Company Website: {_safe_get(company, 'website')}",
        f"- Industry: {_safe_get(company, 'industry')}",
        f"- Company Size: {_safe_get(company, 'employeeRange')}",
        f"- Company Rating: {_safe_get(company, 'rating')}",
    ]

    # Client company (for staffing/vendor roles)
    client_name = _safe_get(client_company, "name")
    if client_name != "N/A":
        lines.extend(
            [
                f"- Client Company: {client_name}",
                f"- Client Industry: {_safe_get(client_company, 'industry')}",
                f"- Client Website: {_safe_get(client_company, 'website')}",
            ]
        )

    # Vendor company
    vendor_name = _safe_get(vendor_company, "name")
    if vendor_name != "N/A":
        lines.extend(
            [
                f"- Vendor: {vendor_name}",
                f"- Vendor Website: {_safe_get(vendor_company, 'website')}",
            ]
        )

    # --- Remote flag ---
    remote_val = location.get("remote")
    if isinstance(remote_val, bool):
        remote_str = "Yes" if remote_val else "No"
    elif remote_val is not None:
        remote_str = str(remote_val)
    else:
        remote_str = "N/A"

    lines.extend(
        [
            # Location + work
            f"- Location: {loc_str}",
            f"- Remote: {remote_str}",
            f"- Work Type: {job.get('workType', 'N/A')}",
            f"- Job Types: {job_types_str}",
            # Salary
            f"- Salary: {salary_str}",
            # Recruiter — always present
            f"- Recruiter: {_safe_get(recruiter, 'name')}",
            f"- Recruiter Email: {_safe_get(recruiter, 'email')}",
            f"- Recruiter Phone: {_safe_get(recruiter, 'phone')}",
            f"- Recruiter LinkedIn: {_safe_get(recruiter, 'linkedin')}",
            f"- Recruiter Company: {_safe_get(recruiter, 'company')}",
            # Source + Apply
            f"- Source: {source_name}",
            f"- Source Type: {source_type}",
            f"- Apply: {apply_url}",
            f"- Easy Apply: {easy_apply}",
            # ID
            f"- ID: {job.get('id', 'N/A')}",
            f"- External ID: {job.get('externalJobId', 'N/A')}",
        ]
    )

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
