#!/usr/bin/env python3
"""
Install script for jobs-skill bundle.

Usage:
    python3 scripts/install.py [--dry-run] [--scope global|local] [--force]

This script:
1. Clones the source repo to a temp location
2. Asks for scope (global/local) if not provided
3. Installs skills, commands, and flows to the appropriate locations
4. Reports what was installed where

Run dependencies one by one as they depend on each other.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

BUNDLE_NAME = "jobs-skill"
MANIFEST_PATH = Path(__file__).parent / "manifest.json"

# For testing without cloning
REPO_URL = None  # Set to a URL to clone, or None to use local repo
LOCAL_REPO = Path(__file__).parent.parent  # Use this repo directly

# Default MCP config to add (only Playwright - others need API keys/OAuth)
DEFAULT_MCP_CONFIG = {
    "playwright": {
        "type": "local",
        "command": ["npx", "-y", "@anthropic/mcp-server-playwright"],
        "enabled": True,
    }
}


def get_user_home() -> Path:
    return Path.home()


def get_opencode_config_dir() -> Path:
    return get_user_home() / ".config" / "opencode"


def get_opencode_commands_dir() -> Path:
    return get_opencode_config_dir() / "commands"


def get_agents_dir() -> Path:
    return get_user_home() / ".agents"


def load_manifest() -> dict:
    if not MANIFEST_PATH.exists():
        print(f"ERROR: manifest not found at {MANIFEST_PATH}")
        sys.exit(1)
    return json.loads(MANIFEST_PATH.read_text())


def get_default_branch(repo_url: str) -> str:
    """Detect the default branch of a repo."""
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--symref", repo_url, "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        for line in result.stdout.split("\n"):
            if "HEAD" in line and "ref: refs/heads/" in line:
                branch = line.split("ref: refs/heads/")[1].split()[0]
                return branch
    except subprocess.CalledProcessError:
        pass
    return "main"


def clone_repo(temp_dir: Path, branch: str = None) -> Path:
    if REPO_URL is None:
        print(f"Using local repo directly: {LOCAL_REPO}")
        return LOCAL_REPO

    repo_dir = temp_dir / BUNDLE_NAME
    if repo_dir.exists():
        shutil.rmtree(repo_dir)

    if branch is None:
        branch = get_default_branch(REPO_URL)
        print(f"Detected default branch: {branch}")

    print(f"Cloning {REPO_URL} (branch: {branch}) into {repo_dir}...")
    try:
        subprocess.run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--branch",
                branch,
                REPO_URL,
                str(repo_dir),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"ERROR: clone failed: {e.stderr}")
        print("Trying with 'main' branch...")
        try:
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--depth",
                    "1",
                    "--branch",
                    "main",
                    REPO_URL,
                    str(repo_dir),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e2:
            print(f"ERROR: clone failed with main too: {e2.stderr}")
            sys.exit(1)

    return repo_dir


def resolve_target_path(target: str, is_global: bool) -> Path:
    if is_global:
        if target.startswith(".config/opencode/"):
            return get_user_home() / target.replace(
                ".config/opencode/", ".config/opencode/"
            )
        elif target.startswith(".agents/"):
            return get_agents_dir() / target.replace(".agents/", "")
        else:
            return get_user_home() / ".config" / target
    else:
        return Path.cwd() / target


def install_item(
    source_path: Path,
    target_path: Path,
    item_type: str,
    dry_run: bool = False,
    force: bool = False,
) -> bool:
    if not source_path.exists():
        print(f"  SKIP: {item_type} source not found: {source_path}")
        return False

    target_path.parent.mkdir(parents=True, exist_ok=True)

    if target_path.exists() and not force:
        print(
            f"  SKIP: {item_type} already exists (use --force to overwrite): {target_path}"
        )
        return False

    if dry_run:
        print(f"  [DRY-RUN] {item_type}: {source_path} -> {target_path}")
        return True

    if source_path.is_dir():
        if target_path.exists():
            shutil.rmtree(target_path)
        shutil.copytree(source_path, target_path, dirs_exist_ok=True)
    else:
        shutil.copy2(source_path, target_path)

    print(f"  INSTALLED: {item_type}: {target_path}")
    return True


def install_skill(
    source_base: Path,
    skill_name: str,
    skill_info: dict,
    is_global: bool,
    dry_run: bool = False,
    force: bool = False,
) -> bool:
    source_path = source_base / skill_info["source"]
    target = skill_info["target"]

    if is_global:
        target_path = get_opencode_config_dir() / "skills" / skill_name
    else:
        target_path = Path.cwd() / "skills" / skill_name

    return install_item(source_path, target_path, f"skill:{skill_name}", dry_run, force)


def install_command(
    source_base: Path,
    cmd_info: dict,
    is_global: bool,
    dry_run: bool = False,
    force: bool = False,
) -> bool:
    source_path = source_base / cmd_info["source"]
    cmd_name = cmd_info["name"]

    if is_global:
        target_path = get_opencode_commands_dir() / f"{cmd_name}.md"
    else:
        target_path = Path.cwd() / "commands" / f"{cmd_name}.md"

    return install_item(source_path, target_path, f"command:{cmd_name}", dry_run, force)


def install_flows(
    source_base: Path,
    flow_info: dict,
    is_global: bool,
    dry_run: bool = False,
    force: bool = False,
) -> bool:
    source_path = source_base / flow_info["source"]

    if is_global:
        target_path = get_agents_dir() / "skills" / "flow-applicator" / "flows"
    else:
        target_path = Path.cwd() / "skills" / "flow-applicator" / "flows"

    target_path.parent.mkdir(parents=True, exist_ok=True)
    return install_item(source_path, target_path, "flows", dry_run, force)


def install_all(
    repo_dir: Path,
    scope: str,
    dry_run: bool = False,
    force: bool = False,
) -> dict:
    is_global = scope == "global"
    manifest = load_manifest()
    install_key = "global" if is_global else "local"
    installs = manifest.get("installs", {}).get(install_key, {})

    results = {
        "skills": [],
        "commands": [],
        "flows": [],
        "errors": [],
    }

    print(f"\n{'=' * 60}")
    print(f"Installing in {scope} mode (dry_run={dry_run})")
    print(f"{'=' * 60}\n")

    source_base = repo_dir

    for skill_info in installs.get("skills", []):
        skill_name = Path(skill_info["source"]).name
        try:
            success = install_skill(
                source_base, skill_name, skill_info, is_global, dry_run, force
            )
            results["skills"].append({"name": skill_name, "success": success})
        except Exception as e:
            results["errors"].append(f"skill:{skill_name} - {e}")

    for cmd_info in installs.get("commands", []):
        try:
            success = install_command(source_base, cmd_info, is_global, dry_run, force)
            results["commands"].append({"name": cmd_info["name"], "success": success})
        except Exception as e:
            results["errors"].append(f"command:{cmd_info['name']} - {e}")

    for flow_info in installs.get("flows", []):
        try:
            success = install_flows(source_base, flow_info, is_global, dry_run, force)
            results["flows"].append({"source": flow_info["source"], "success": success})
        except Exception as e:
            results["errors"].append(f"flows - {e}")

    return results


def ask_scope() -> str:
    print("\nChoose installation scope:")
    print("  [1] global  - Install to ~/.config/opencode/ and ~/.agents/")
    print("  [2] local   - Install to current workspace (./skills/, ./commands/)")
    print("\n  Enter 1 or 2: ", end="")
    choice = input().strip()

    if choice == "1":
        return "global"
    elif choice == "2":
        return "local"
    else:
        print("Invalid choice, defaulting to global.")
        return "global"


def print_summary(results: dict) -> None:
    print(f"\n{'=' * 60}")
    print("INSTALL SUMMARY")
    print(f"{'=' * 60}")

    installed = 0
    for skill in results.get("skills", []):
        status = "OK" if skill["success"] else "SKIP"
        print(f"  skill:{skill['name']:<30} {status}")
        if skill["success"]:
            installed += 1

    for cmd in results.get("commands", []):
        status = "OK" if cmd["success"] else "SKIP"
        print(f"  command:{cmd['name']:<30} {status}")
        if cmd["success"]:
            installed += 1

    for flow in results.get("flows", []):
        status = "OK" if flow["success"] else "SKIP"
        print(f"  flows:{flow['source']:<30} {status}")
        if flow["success"]:
            installed += 1

    if results.get("errors"):
        print("\nERRORS:")
        for err in results["errors"]:
            print(f"  - {err}")

    print(f"\nTotal installed: {installed}")


def get_opencode_config_path() -> Path:
    return get_user_home() / ".config" / "opencode" / "opencode.json"


def ensure_opencode_config_dir() -> Path:
    config_dir = get_user_home() / ".config" / "opencode"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def load_opencode_config() -> dict:
    config_path = get_opencode_config_path()
    if config_path.exists():
        try:
            return json.loads(config_path.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def save_opencode_config(config: dict) -> None:
    config_path = get_opencode_config_path()
    ensure_opencode_config_dir()
    config_path.write_text(json.dumps(config, indent=2) + "\n")
    print(f"  Updated: {config_path}")


def add_mcp_config(
    mcp_names: list = None, dry_run: bool = False, force: bool = False
) -> dict:
    """Add MCP configuration to opencode.json"""
    config = load_opencode_config()

    if "$schema" not in config:
        config["$schema"] = "https://opencode.ai/config.json"

    if "mcp" not in config:
        config["mcp"] = {}

    if mcp_names is None:
        mcp_names = list(DEFAULT_MCP_CONFIG.keys())

    for mcp_name in mcp_names:
        if mcp_name in DEFAULT_MCP_CONFIG:
            if mcp_name not in config["mcp"] or force:
                config["mcp"][mcp_name] = DEFAULT_MCP_CONFIG[mcp_name]
                if not dry_run:
                    print(f"  Added MCP: {mcp_name}")
            else:
                print(
                    f"  SKIP: MCP {mcp_name} already exists (use --mcp-force to overwrite)"
                )

    if not dry_run:
        save_opencode_config(config)

    return config


def main() -> None:
    parser = argparse.ArgumentParser(description="Install jobs-skill bundle")
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be installed"
    )
    parser.add_argument(
        "--scope", choices=["global", "local"], help="Installation scope"
    )
    parser.add_argument("--force", action="store_true", help="Overwrite existing files")
    parser.add_argument("--branch", default="main", help="Git branch to clone")
    parser.add_argument(
        "--mcp", action="store_true", help="Add Playwright MCP to opencode.json"
    )
    parser.add_argument(
        "--mcp-only",
        action="store_true",
        help="Only add MCP config, skip skill install",
    )
    parser.add_argument(
        "--mcp-force", action="store_true", help="Force overwrite existing MCP config"
    )
    args = parser.parse_args()

    if args.mcp or args.mcp_only:
        print("\nAdding Playwright MCP configuration...")
        add_mcp_config(dry_run=args.dry_run, force=args.mcp_force)
        if args.mcp_only:
            return

    scope = args.scope if args.scope else ask_scope()

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        repo_dir = clone_repo(temp_path, args.branch)
        results = install_all(repo_dir, scope, args.dry_run, args.force)

    print_summary(results)

    if results.get("errors"):
        sys.exit(1)


if __name__ == "__main__":
    main()
