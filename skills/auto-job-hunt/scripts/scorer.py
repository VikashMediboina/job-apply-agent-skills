#!/usr/bin/env python3
"""Scoring module - applies role-specific scoring criteria to jobs."""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class ScoreResult:
    """Scoring result for a job."""

    score: int
    recommendation: str  # Apply/Consider/Skip
    red_flags: list[str]
    breakdown: dict


def load_scoring_criteria(scoring_path: str) -> dict:
    """Load scoring criteria from scoring.md file."""
    path = Path(scoring_path)
    if not path.exists():
        return get_default_scoring()

    content = path.read_text()
    criteria = {"user_level": {}, "role_level": {}, "thresholds": {}, "red_flags": []}

    # Parse weights
    # User-Level Fit (60%)
    user_match = re.search(
        r"### User-Level Fit.*?\|.*?\|.*?\n(.*?)(?=\n###|\Z)", content, re.DOTALL
    )
    if user_match:
        for line in user_match.group(1).split("\n"):
            if "|" in line:
                parts = [p.strip() for p in line.split("|") if p.strip()]
                if len(parts) >= 2:
                    factor = parts[0]
                    weight = (
                        int(re.search(r"(\d+)%", parts[1]).group(1))
                        if re.search(r"(\d+)%", parts[1])
                        else 0
                    )
                    logic = parts[2] if len(parts) > 2 else ""
                    criteria["user_level"][factor] = {"weight": weight, "logic": logic}

    # Role-Level Fit (40%)
    role_match = re.search(
        r"### Role-Level Fit.*?\|.*?\|.*?\n(.*?)(?=\n###|\Z)", content, re.DOTALL
    )
    if role_match:
        for line in role_match.group(1).split("\n"):
            if "|" in line:
                parts = [p.strip() for p in line.split("|") if p.strip()]
                if len(parts) >= 2:
                    factor = parts[0]
                    weight = (
                        int(re.search(r"(\d+)%", parts[1]).group(1))
                        if re.search(r"(\d+)%", parts[1])
                        else 0
                    )
                    logic = parts[2] if len(parts) > 2 else ""
                    criteria["role_level"][factor] = {"weight": weight, "logic": logic}

    # Thresholds
    thresholds = re.findall(r"\*\*([A-Za-z]+)\*\*:.*?(\d+)%", content)
    for label, threshold in thresholds:
        criteria["thresholds"][label.lower()] = int(threshold)

    # Red flags
    red_flags_match = re.search(
        r"## Red Flags.*?(?=\n##|\Z)", content, re.DOTALL | re.IGNORECASE
    )
    if red_flags_match:
        for line in red_flags_match.group(0).split("\n"):
            line = line.strip().lstrip("-").strip()
            if line and not line.startswith("#"):
                criteria["red_flags"].append(line)

    return criteria


def get_default_scoring() -> dict:
    """Return default scoring criteria if none found."""
    return {
        "user_level": {
            "Work authorization match": {"weight": 20, "logic": "Match"},
            "Visa sponsorship fit": {"weight": 15, "logic": "Match"},
            "Location/relocation fit": {"weight": 10, "logic": "Match"},
            "Work mode fit": {"weight": 10, "logic": "Match"},
            "Salary expectation fit": {"weight": 5, "logic": "Match"},
        },
        "role_level": {
            "Skills match": {"weight": 15, "logic": "Count matching"},
            "Recent experience relevance": {"weight": 10, "logic": "Time-based"},
            "Industry/domain match": {"weight": 5, "logic": "Match"},
            "Education fit": {"weight": 5, "logic": "Match"},
            "Years of experience": {"weight": 5, "logic": "Range"},
        },
        "thresholds": {"apply": 70, "consider": 50, "skip": 50},
        "red_flags": [
            "Visa sponsorship required AND role explicitly says No sponsorship",
            "Location mismatch AND not willing to relocate AND not remote",
            "Salary expectation > 30% above role range",
            "Missing 3+ required skills with no adjacent experience",
        ],
    }


def load_profile(profile_path: str) -> dict:
    """Load user profile data."""
    path = Path(profile_path)
    if not path.exists():
        return {}

    content = path.read_text()
    profile = {}

    # Extract basic fields using regex
    profile["location"] = re.search(
        r"Location:\s*(.+?)(?:\n|$)", content, re.IGNORECASE
    )
    profile["location"] = (
        profile["location"].group(1).strip() if profile["location"] else None
    )

    profile["visa_status"] = re.search(
        r"(?:Visa|Work).*?status.*?:\s*(.+?)(?:\n|$)", content, re.IGNORECASE
    )
    profile["visa_status"] = (
        profile["visa_status"].group(1).strip() if profile["visa_status"] else None
    )

    profile["work_mode"] = re.search(
        r"Work mode.*?:\s*(.+?)(?:\n|$)", content, re.IGNORECASE
    )
    profile["work_mode"] = (
        profile["work_mode"].group(1).strip() if profile["work_mode"] else "Flexible"
    )

    return {k: v for k, v in profile.items() if v}


def score_job(
    job: dict, scoring_criteria: dict, profile: dict, user_filters: dict
) -> ScoreResult:
    """
    Score a single job against criteria.

    Args:
        job: Job data dictionary
        scoring_criteria: Loaded from scoring.md
        profile: User profile data
        user_filters: User-specified filters (location, visa, work_mode)

    Returns:
        ScoreResult with score, recommendation, red_flags
    """
    red_flags = []
    breakdown = {}
    user_score = 0
    role_score = 0

    user_weights = {k: v["weight"] for k, v in scoring_criteria["user_level"].items()}
    role_weights = {k: v["weight"] for k, v in scoring_criteria["role_level"].items()}

    # User-Level Fit (60%)
    # Work authorization match
    job_auth = job.get("workAuthorization", "")
    if job_auth:
        if profile.get("visa_status") in ["Citizen", "Green Card"]:
            user_score += user_weights.get("Work authorization match", 20)
            breakdown["work_auth"] = 100
        elif "OPT" in profile.get("visa_status", ""):
            user_score += user_weights.get("Work authorization match", 20) * 0.7
            breakdown["work_auth"] = 70

    # Visa sponsorship fit
    job_visa = job.get("visaSponsorship", False)
    if job_visa:
        if not profile.get("visa_required", False):
            user_score += user_weights.get("Visa sponsorship fit", 15) * 0.7
            breakdown["visa"] = 70
    else:
        user_score += user_weights.get("Visa sponsorship fit", 15)
        breakdown["visa"] = 100

    # Location fit
    job_location = job.get("location", {})
    user_location = user_filters.get("location") or profile.get("location", "")

    if job_location.get("remote", False):
        user_score += user_weights.get("Location/relocation fit", 10)
        breakdown["location"] = 100
    elif user_location and user_location.lower() == "remote":
        breakdown["location"] = 0
    elif user_location:
        if user_location.lower() in job_location.get("city", "").lower():
            user_score += user_weights.get("Location/relocation fit", 10)
            breakdown["location"] = 100
        elif user_location.lower() in job_location.get("state", "").lower():
            user_score += user_weights.get("Location/relocation fit", 10) * 0.6
            breakdown["location"] = 60

    # Work mode fit
    job_work_mode = job.get("workType", "").lower()
    user_work_mode = user_filters.get("work_mode", "Flexible").lower()

    if user_work_mode == "flexible":
        user_score += user_weights.get("Work mode fit", 10)
        breakdown["work_mode"] = 100
    elif job_work_mode == "remote" or user_work_mode == "remote":
        user_score += user_weights.get("Work mode fit", 10)
        breakdown["work_mode"] = 100
    elif job_work_mode == user_work_mode:
        user_score += user_weights.get("Work mode fit", 10)
        breakdown["work_mode"] = 100
    else:
        breakdown["work_mode"] = 0

    # Role-Level Fit (40%)
    # Skills match
    job_skills = set(job.get("skills", []))
    profile_skills = set(profile.get("skills", []))

    if job_skills and profile_skills:
        match_count = len(job_skills & profile_skills)
        match_ratio = match_count / len(job_skills) if job_skills else 0
        role_score += role_weights.get("Skills match", 15) * match_ratio
        breakdown["skills"] = int(match_ratio * 100)
    else:
        breakdown["skills"] = 50

    # Experience relevance (simplified)
    role_score += role_weights.get("Recent experience relevance", 10) * 0.7
    breakdown["experience"] = 70

    # Industry match
    job_industry = job.get("company", {}).get("industry", "").lower()
    profile_industry = profile.get("industry", "").lower()

    if job_industry and profile_industry and job_industry in profile_industry:
        role_score += role_weights.get("Industry/domain match", 5)
        breakdown["industry"] = 100
    else:
        breakdown["industry"] = 50

    # Normalize scores
    user_max = sum(user_weights.values())
    role_max = sum(role_weights.values())

    user_pct = (user_score / user_max * 100) if user_max else 0
    role_pct = (role_score / role_max * 100) if role_max else 0

    total_score = int(user_pct * 0.6 + role_pct * 0.4)

    # Check red flags
    if job.get("visaSponsorship", False) and profile.get("visa_required") is False:
        if "No sponsorship" in job.get("jobDescription", ""):
            red_flags.append(
                "Role doesn't sponsor visa but candidate needs future sponsorship"
            )

    if not job_location.get("remote", False) and user_work_mode == "remote":
        red_flags.append("Job is not remote but user wants remote")

    # Determine recommendation
    thresholds = scoring_criteria.get("thresholds", {"apply": 70, "consider": 50})
    if total_score >= thresholds.get("apply", 70):
        recommendation = "Apply"
    elif total_score >= thresholds.get("consider", 50):
        recommendation = "Consider"
    else:
        recommendation = "Skip"

    return ScoreResult(
        score=total_score,
        recommendation=recommendation,
        red_flags=red_flags,
        breakdown=breakdown,
    )


def score_jobs(
    jobs: list[dict],
    scoring_path: str,
    profile_path: str,
    user_filters: dict,
    metadata: dict | None = None,
) -> list[dict]:
    """
    Score multiple jobs.

    Args:
        jobs: List of job dictionaries
        scoring_path: Path to scoring.md
        profile_path: Path to profile.md
        user_filters: User-specified filters
        metadata: Optional metadata (username, role, profile_path, resume_path)

    Returns:
        List of jobs with added score fields
    """
    scoring_criteria = load_scoring_criteria(scoring_path)
    profile = load_profile(profile_path)

    scored_jobs = []
    for job in jobs:
        result = score_job(job, scoring_criteria, profile, user_filters)

        scored_job = {
            **job,
            "score": result.score,
            "recommendation": result.recommendation,
            "red_flags": result.red_flags,
            "score_breakdown": result.breakdown,
            "username": metadata.get("username", "") if metadata else "",
            "role": metadata.get("role", "") if metadata else "",
            "profilePath": metadata.get("profile_path", "") if metadata else "",
            "resumePath": metadata.get("resume_path", "") if metadata else "",
        }

        # Skip if has red flags
        if not result.red_flags:
            scored_jobs.append(scored_job)

    return scored_jobs


if __name__ == "__main__":
    # Test scoring
    test_job = {
        "title": "AI/ML Engineer",
        "jobDescription": "Looking for ML engineer with Python, RAG, Weaviate",
        "skills": ["Python", "RAG", "Weaviate", "LangChain"],
        "workType": "remote",
        "visaSponsorship": False,
        "location": {"city": "Boston", "remote": False},
        "company": {"industry": "AI/Technology"},
    }

    criteria = get_default_scoring()
    result = score_job(test_job, criteria, {}, {"work_mode": "Flexible"})

    print(f"Score: {result.score}")
    print(f"Recommendation: {result.recommendation}")
    print(f"Red Flags: {result.red_flags}")
    print(f"Breakdown: {result.breakdown}")
