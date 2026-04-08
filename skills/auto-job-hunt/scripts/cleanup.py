#!/usr/bin/env python3
"""Cleanup module - removes temp directory after execution."""

import shutil
from pathlib import Path

from paths import jobs_dir, jobs_status_dir, temp_dir


def cleanup_temp(temp_path: str | Path | None = None) -> dict:
    """
    Remove temp directory after job scraping complete.

    Args:
        temp_dir: Path to temp directory

    Returns:
        dict with 'success' (bool), 'message' (str), 'files_removed' (int)
    """
    result = {"success": False, "message": "", "files_removed": 0}

    temp_path = Path(temp_path) if temp_path else temp_dir()

    if not temp_path.exists():
        result["success"] = True
        result["message"] = "Temp directory does not exist, nothing to clean"
        return result

    # Count files before deletion
    try:
        file_count = sum(1 for _ in temp_path.rglob("*") if _.is_file())

        # Remove temp directory
        shutil.rmtree(temp_path)

        result["success"] = True
        result["message"] = f"Successfully cleaned {file_count} files from temp"
        result["files_removed"] = file_count

    except Exception as e:
        result["message"] = f"Error cleaning temp: {str(e)}"

    return result


def ensure_jobs_dir(jobs_path: str | Path | None = None) -> str:
    """
    Ensure jobs directory exists.

    Args:
        jobs_dir: Path to jobs directory

    Returns:
        Path to jobs directory
    """
    jobs_path = Path(jobs_path) if jobs_path else jobs_dir()
    jobs_path.mkdir(parents=True, exist_ok=True)

    # Also create status subdirectory
    status_dir = jobs_status_dir()
    status_dir.mkdir(parents=True, exist_ok=True)

    return str(jobs_path)


def get_output_paths(timestamp: str) -> dict:
    """
    Get output file paths for a given timestamp.

    Args:
        timestamp: Timestamp string (YYYY-MM-DD_HH-MM-SS)

    Returns:
        dict with 'xlsx' and 'status' paths
    """
    from paths import jobs_by_timestamp

    return jobs_by_timestamp(timestamp)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        temp_path = sys.argv[1]
    else:
        temp_path = temp_dir()

    result = cleanup_temp(temp_path)

    if result["success"]:
        print(f"✓ {result['message']}")
        sys.exit(0)
    else:
        print(f"✗ {result['message']}")
        sys.exit(1)
