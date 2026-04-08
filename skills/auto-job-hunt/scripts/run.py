#!/usr/bin/env python3
"""Single entrypoint for the auto-job-hunt skill."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

# Ensure local scripts directory is on sys.path when run directly
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cleanup import cleanup_temp, ensure_jobs_dir, get_output_paths
from csv_generator import consolidate_jobs, create_status_log, jobs_to_xlsx
from md_generator import create_status_log as create_status_log_md, jobs_to_markdown
from paths import jobs_by_date_dir, role_file
from planner import create_distribution_plan, load_search_terms, parse_request
from scorer import score_jobs
from validate_links import validate_role_bundle, validate_skill_files
from validate_mcps import validate_all_mcps
from validate_profile import validate_profile


def run(
    request: str, username: str, role: str, job_files: list[str] | None = None
) -> dict:
    """Validate, plan, score, export to XLSX, and cleanup."""
    if not validate_skill_files()["valid"]:
        raise RuntimeError("Skill tree is incomplete")

    if not validate_profile(username, role)["valid"]:
        raise RuntimeError("Profile bundle is missing required files")

    role_bundle = validate_role_bundle(username, role)
    if not role_bundle["valid"]:
        raise RuntimeError(f"Role bundle incomplete: {role_bundle['missing']}")

    if not (
        Path(role_file(username, role, "profile.md")).parent.parent / "user_qna.md"
    ).exists():
        raise RuntimeError("Candidate user_qna.md is missing")

    mcps = validate_all_mcps()
    if not mcps["valid"]:
        raise RuntimeError("No job board MCP is connected (Dice/Indeed)")

    params = parse_request(request)

    # When run via CLI, we always know the single role from arguments
    # but parse_request() may not extract it from the free-form text.
    # If roles list is empty, default it to the provided role name.
    if not params.roles:
        params.roles = [role]
    searchterms_path = role_file(username, role, "searchterms.md")
    scoring_path = role_file(username, role, "scoring.md")
    profile_path = role_file(username, role, "profile.md")
    terms = load_search_terms(str(searchterms_path))
    role_terms = {role: terms}
    plan = create_distribution_plan(params, role_terms)

    ensure_jobs_dir(jobs_by_date_dir())

    jobs = consolidate_jobs(job_files or [])
    scored = score_jobs(
        jobs=jobs,
        scoring_path=str(scoring_path),
        profile_path=str(profile_path),
        user_filters={
            "location": params.location,
            "visa_status": params.visa_status,
            "visa_required": params.visa_required,
            "work_mode": params.work_mode,
            "score_threshold": params.score_threshold,
        },
        metadata={
            "username": username,
            "role": role,
            "profile_path": str(profile_path),
            "resume_path": str(role_file(username, role, "resume.pdf")),
        },
    )

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_paths = get_output_paths(timestamp)

    md_generated = jobs_to_markdown(
        scored,
        output_paths["xlsx"].parent,
        request=request,
        roles=params.roles,
        filters={
            "location": params.location,
            "work_mode": params.work_mode,
            "visa_status": params.visa_status,
            "score_threshold": params.score_threshold,
        },
    )

    status_path_md = create_status_log_md(
        request=request,
        roles=params.roles,
        filters={
            "location": params.location,
            "work_mode": params.work_mode,
            "visa_status": params.visa_status,
            "score_threshold": params.score_threshold,
        },
        results={
            "dice": {
                "scraped": len(jobs),
                "filtered": len(scored),
                "jobs": scored,
                "target": 0,
            },
            "indeed": {"scraped": 0, "filtered": 0, "jobs": [], "target": 0},
        },
        md_dir=str(output_paths["xlsx"].parent),
        status_dir=output_paths["status"].parent,
        timestamp=timestamp,
    )

    cleanup_temp()
    return {
        "jobs_dir": str(output_paths["xlsx"].parent),
        "jobs_md": str(output_paths["xlsx"].parent / "jobs.md"),
        "index_md": str(output_paths["xlsx"].parent / "index.md"),
        "status": status_path_md,
        "plan": plan,
    }


if __name__ == "__main__":
    # Allow running as a simple CLI for debugging:
    # python run.py "request" username role [job_file1 job_file2 ...]
    if len(sys.argv) < 4:
        raise SystemExit(
            "Usage: python run.py 'request' <username> <role> [job_file1 job_file2 ...]"
        )

    _request = sys.argv[1]
    _username = sys.argv[2]
    _role = sys.argv[3]
    _job_files = sys.argv[4:] or None

    result = run(_request, _username, _role, _job_files)
    print(result["xlsx"])
