"""
Dynamic path resolution for flow-applicator.

All paths are computed at runtime so the skill works across any agent
(OpenCode, Claude Code, Codex, etc.) and any workspace layout.

Key directories:
  repo_root        - Git repository root (anchor for everything)
  workspace_root   - The workspace that invoked the skill (e.g. Jobs-skill/)
  flows_dir        - GLOBAL flows storage:  {repo_root}/.agents/skills/flow-applicator/flows/
  applications_dir - Per-workspace tracker: {workspace_root}/applications/
  profile_dir      - Candidate profile:     {workspace_root}/[candidate]/[role]/
  references_dir   - Shared references:     {repo_root}/references/
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional


def get_repo_root() -> Path:
    """Find the git repo root by walking up from cwd."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        return Path(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        # Fallback: walk up until we find .git
        current = Path.cwd()
        while current != current.parent:
            if (current / ".git").exists():
                return current
            current = current.parent
        raise RuntimeError("Cannot determine repo root — not inside a git repo")


def get_workspace_root() -> Path:
    """Return the workspace root (directory containing this skill).

    Heuristic: walk up from this file until we find a directory that
    contains a 'skills/' subfolder or is a direct child of repo_root.
    """
    skill_dir = Path(__file__).resolve().parent.parent  # scripts/ -> flow-applicator/
    workspace = skill_dir.parent.parent  # flow-applicator/ -> skills/ -> workspace
    if workspace.exists():
        return workspace
    return Path.cwd()


# ── Global (repo-level) paths ──────────────────────────────────────


def flows_dir() -> Path:
    """GLOBAL flow storage: {repo_root}/.agents/skills/flow-applicator/flows/"""
    d = get_repo_root() / ".agents" / "skills" / "flow-applicator" / "flows"
    d.mkdir(parents=True, exist_ok=True)
    return d


def registry_path() -> Path:
    return flows_dir() / "registry.json"


def flow_path(flow_id: str) -> Path:
    return flows_dir() / f"{flow_id}.json"


# ── Workspace-level paths ──────────────────────────────────────────


def applications_dir() -> Path:
    """Per-workspace application tracking: {workspace}/applications/"""
    d = get_workspace_root() / "applications"
    d.mkdir(parents=True, exist_ok=True)
    return d


def applications_index_path() -> Path:
    return applications_dir() / "_index.json"


def daily_applications_dir(date: Optional[str] = None) -> Path:
    """applications/{YYYY-MM-DD}/"""
    date = date or datetime.now().strftime("%Y-%m-%d")
    d = applications_dir() / date
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── References ─────────────────────────────────────────────────────


def references_dir() -> Path:
    return get_repo_root() / "references"


def question_templates_path() -> Path:
    return references_dir() / "question_templates.md"


def profile_data_path() -> Path:
    return references_dir() / "profile_data.md"


# ── Candidate profile ─────────────────────────────────────────────


def candidate_dir(candidate: Optional[str] = None) -> Path:
    """Get candidate directory, auto-detect if not provided."""
    if candidate:
        return get_workspace_root() / candidate
    # Auto-detect: find first directory with profile.md
    workspace = get_workspace_root()
    for d in workspace.iterdir():
        if d.is_dir() and (d / "profile.md").exists():
            return d
    raise RuntimeError(f"No candidate profile found in {workspace}")


def role_dir(candidate: Optional[str] = None, role: Optional[str] = None) -> Path:
    """Get role directory, auto-detect if not provided."""
    cand_dir = candidate_dir(candidate)
    if role:
        return cand_dir / role
    # Auto-detect: find first subdirectory with profile.md
    for d in cand_dir.iterdir():
        if d.is_dir() and d != cand_dir and (d / "profile.md").exists():
            return d
    return cand_dir


def role_profile_path(
    candidate: Optional[str] = None, role: Optional[str] = None
) -> Path:
    return role_dir(candidate, role) / "profile.md"


def role_qna_path(candidate: Optional[str] = None, role: Optional[str] = None) -> Path:
    return role_dir(candidate, role) / "role_qna.md"


def resume_pdf_path(
    candidate: Optional[str] = None, role: Optional[str] = None
) -> Path:
    return role_dir(candidate, role) / "pdf" / "resume.pdf"


# ── Jobs ───────────────────────────────────────────────────────────


def jobs_base_dir() -> Path:
    return get_workspace_root() / "jobs"


def find_jobs_file(date: Optional[str] = None) -> Optional[Path]:
    """Find the most recent jobs.md for a given date (or today).

    Searches: {workspace}/jobs/{date}/{timestamp}/jobs.md
    Returns the newest timestamp directory's jobs.md, or None.
    """
    date = date or datetime.now().strftime("%Y-%m-%d")
    date_dir = jobs_base_dir() / date
    if not date_dir.exists():
        return None
    # Find all timestamp directories, sort descending
    ts_dirs = sorted(
        [d for d in date_dir.iterdir() if d.is_dir()],
        key=lambda p: p.name,
        reverse=True,
    )
    for ts_dir in ts_dirs:
        jobs_md = ts_dir / "jobs.md"
        if jobs_md.exists():
            return jobs_md
    return None


def find_all_jobs_files(date: Optional[str] = None) -> list[Path]:
    """Return all jobs.md files for a given date, newest first."""
    date = date or datetime.now().strftime("%Y-%m-%d")
    date_dir = jobs_base_dir() / date
    if not date_dir.exists():
        return []
    results = []
    ts_dirs = sorted(
        [d for d in date_dir.iterdir() if d.is_dir()],
        key=lambda p: p.name,
        reverse=True,
    )
    for ts_dir in ts_dirs:
        jobs_md = ts_dir / "jobs.md"
        if jobs_md.exists():
            results.append(jobs_md)
    return results


# ── Skill-local paths ─────────────────────────────────────────────


def skill_dir() -> Path:
    """The flow-applicator skill directory inside the workspace."""
    return get_workspace_root() / "skills" / "flow-applicator"


def instincts_path() -> Path:
    return skill_dir() / "instincts" / "instincts.json"


def prompts_dir() -> Path:
    return skill_dir() / "prompts"


# ── Utilities ──────────────────────────────────────────────────────


def ensure_dir(path: Path) -> Path:
    """Create directory (and parents) if it doesn't exist, return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_json(path: Path) -> dict:
    """Load JSON file, return empty dict if missing or invalid."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_json(path: Path, data: dict, indent: int = 2) -> None:
    """Write dict to JSON file, creating parent dirs as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=indent, ensure_ascii=False) + "\n", encoding="utf-8"
    )
