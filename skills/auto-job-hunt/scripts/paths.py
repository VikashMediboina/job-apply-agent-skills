#!/usr/bin/env python3
"""Shared path helpers for the auto-job-hunt skill."""

from __future__ import annotations

from pathlib import Path


def script_dir() -> Path:
    return Path(__file__).resolve().parent


def skill_root() -> Path:
    return script_dir().parent


def repo_root() -> Path:
    return skill_root().parents[1]


def workspace_root() -> Path:
    return repo_root().parent


def jobs_dir() -> Path:
    return repo_root() / "jobs"


def jobs_status_dir() -> Path:
    return jobs_dir() / "status"


def temp_dir() -> Path:
    return workspace_root() / "temp"


def candidate_root(username: str) -> Path:
    return repo_root() / username


def role_root(username: str, role: str) -> Path:
    return candidate_root(username) / role


def role_file(username: str, role: str, filename: str) -> Path:
    return role_root(username, role) / filename


def sanitize_filename(value: str) -> str:
    cleaned = []
    for char in value.lower():
        cleaned.append(char if char.isalnum() else "_")
    return "".join(cleaned).strip("_") or "item"


def jobs_by_date_dir(date: str = None) -> Path:
    """Get jobs directory for a specific date (YYYY-MM-DD)."""
    if date is None:
        from datetime import datetime

        date = datetime.now().strftime("%Y-%m-%d")
    return jobs_dir() / date


def jobs_by_timestamp(timestamp: str = None) -> dict[str, Path]:
    """Get jobs output directory and status paths for a specific timestamp.

    The 'jobs_dir' key points to the timestamped output directory where
    jobs.md and index.md are written. The legacy 'xlsx' key is an alias
    for a path inside that directory (kept for backward compat — actual
    output is jobs.md, not xlsx).
    """
    if timestamp is None:
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    date = timestamp.split("_")[0]
    date_dir = jobs_by_date_dir(date)
    jobs_output_dir = date_dir / timestamp
    return {
        # 'xlsx' key retained for backward compat — callers use .parent to get the dir
        "xlsx": jobs_output_dir / "jobs.md",
        "jobs_dir": jobs_output_dir,
        "status": jobs_status_dir() / date / f"{timestamp}.md",
    }
