#!/usr/bin/env python3
"""Validate that user profile and role folders exist."""

import sys
from pathlib import Path

from paths import candidate_root, repo_root, role_root


def validate_profile(username: str, role: str) -> dict:
    """
    Validate that profile folder and required files exist.

    Args:
        username: FirstName_LastName format
        role: Role name (e.g., AIMLEngineer)

    Returns:
        dict with 'valid' (bool), 'message' (str), 'paths' (dict)
    """
    result = {"valid": False, "message": "", "paths": {}}

    user_dir = candidate_root(username)
    role_dir = role_root(username, role)

    required_files = [
        "profile.md",
        "scoring.md",
        "searchterms.md",
        "role_qna.md",
        "generation.md",
    ]

    if not user_dir.exists():
        result["message"] = (
            f"User profile not found: {username}. Please run resume-profile-generator first."
        )
        return result

    if not role_dir.exists():
        result["message"] = (
            f"Role folder not found: {role}. Please setup this role in your profile first."
        )
        return result

    missing_files = []
    existing_files = {}
    for filename in required_files:
        filepath = role_dir / filename
        if filepath.exists():
            existing_files[filename] = str(filepath)
        else:
            missing_files.append(filename)

    if missing_files:
        result["message"] = (
            f"Missing required files in {role_dir}: {', '.join(missing_files)}"
        )
        return result

    user_qna = candidate_root(username) / "user_qna.md"
    if not user_qna.exists():
        result["message"] = (
            f"Missing required file in {candidate_root(username)}: user_qna.md"
        )
        return result

    result["valid"] = True
    result["message"] = f"Profile validated for {username}/{role}"
    result["paths"] = {
        "user_dir": str(user_dir),
        "role_dir": str(role_dir),
        "user_qna": str(user_qna),
        "files": existing_files,
    }
    return result


def get_role_paths(username: str, role: str) -> dict:
    """Get all relevant file paths for a role."""
    role_dir = role_root(username, role)

    return {
        "profile": str(role_dir / "profile.md"),
        "scoring": str(role_dir / "scoring.md"),
        "searchterms": str(role_dir / "searchterms.md"),
        "generation": str(role_dir / "generation.md"),
        "role_dir": str(role_dir),
    }


def list_available_roles(username: str) -> list:
    """List all available roles for a user."""
    user_dir = candidate_root(username)

    if not user_dir.exists():
        return []

    roles = []
    for item in user_dir.iterdir():
        if item.is_dir() and item.name != "pdf":
            roles.append(item.name)

    return sorted(roles)


def list_all_profiles() -> list:
    """List all available user profiles."""
    root = repo_root()
    if not root.exists():
        return []

    profiles = []
    for item in root.iterdir():
        if item.is_dir() and (item / "profile.md").exists():
            profiles.append(item.name)

    return sorted(profiles)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python validate_profile.py <username> <role>")
        sys.exit(1)

    username = sys.argv[1]
    role = sys.argv[2]

    result = validate_profile(username, role)

    if result["valid"]:
        print(f"✓ {result['message']}")
        sys.exit(0)
    else:
        print(f"✗ {result['message']}")
        sys.exit(1)
