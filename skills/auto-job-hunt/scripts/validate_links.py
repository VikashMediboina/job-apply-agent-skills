#!/usr/bin/env python3
"""Validate the skill file tree and role bundle wiring."""

from __future__ import annotations

import sys

from paths import repo_root, role_root


DECLARED_FILES = [
    "skills/auto-job-hunt/SKILL.md",
    "skills/auto-job-hunt/scripts/__init__.py",
    "skills/auto-job-hunt/scripts/paths.py",
    "skills/auto-job-hunt/scripts/validate_profile.py",
    "skills/auto-job-hunt/scripts/validate_mcps.py",
    "skills/auto-job-hunt/scripts/validate_links.py",
    "skills/auto-job-hunt/scripts/planner.py",
    "skills/auto-job-hunt/scripts/scorer.py",
    "skills/auto-job-hunt/scripts/csv_generator.py",
    "skills/auto-job-hunt/scripts/cleanup.py",
    "skills/auto-job-hunt/prompts/role_subagent.md",
    "skills/auto-job-hunt/prompts/source_subagent.md",
    "skills/auto-job-hunt/prompts/search_term_subagent.md",
    "skills/auto-job-hunt/sources/dice/capabilities.md",
    "skills/auto-job-hunt/sources/indeed/capabilities.md",
]


def validate_skill_files() -> dict:
    root = repo_root()
    missing = []
    for relative in DECLARED_FILES:
        if not (root / relative).exists():
            missing.append(relative)
    return {"valid": not missing, "missing": missing}


def validate_role_bundle(username: str, role: str) -> dict:
    base = role_root(username, role)
    required = [
        "profile.md",
        "scoring.md",
        "searchterms.md",
        "role_qna.md",
        "generation.md",
    ]
    missing = [name for name in required if not (base / name).exists()]
    user_qna = base.parent / "user_qna.md"
    if not user_qna.exists():
        missing.append("../user_qna.md")
    return {"valid": not missing, "role_dir": str(base), "missing": missing}


if __name__ == "__main__":
    result = validate_skill_files()
    print(f"skill_valid={result['valid']}")
    for item in result["missing"]:
        print(f"missing: {item}")
    sys.exit(0 if result["valid"] else 1)
