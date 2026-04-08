#!/usr/bin/env python3
"""Validate MCP connections for Dice and Indeed using OpenCode."""

import os
import subprocess
import sys


OPENCODE_BIN = os.environ.get(
    "OPENCODE_BIN", "/Users/vikashmediboina/.opencode/bin/opencode"
)


def check_mcp_tool(mcp_name: str, tool_name: str) -> dict:
    """Check if an MCP tool is available in OpenCode."""
    result = {"connected": False, "message": "", "tools": []}

    try:
        proc = subprocess.run(
            [OPENCODE_BIN, "mcp", "list"], capture_output=True, text=True, timeout=30
        )

        output = proc.stdout + proc.stderr
        mcp_lower = mcp_name.lower()

        # Check if MCP name appears in output with ● and not marked as failed
        found = False
        is_failed = False
        for line in output.split("\n"):
            if "●" in line and mcp_lower in line.lower():
                if "✗" in line or "failed" in line.lower():
                    is_failed = True
                else:
                    found = True
                break

        if found:
            result["connected"] = True
            result["message"] = f"{mcp_name} MCP is connected"
            result["tools"].append(tool_name)
        elif is_failed:
            result["message"] = (
                f"{mcp_name} MCP is configured but failed. Run: opencode mcp auth {mcp_name}"
            )
        else:
            result["message"] = (
                f"{mcp_name} MCP not found in OpenCode. Run: opencode mcp auth {mcp_name}"
            )

    except FileNotFoundError:
        result["message"] = f"OpenCode not found at {OPENCODE_BIN}"
    except subprocess.TimeoutExpired:
        result["message"] = "Timeout checking OpenCode MCP connections."
    except Exception as e:
        result["message"] = f"Error checking OpenCode MCP: {str(e)}"

    return result


def validate_dice_mcp() -> dict:
    """Validate Dice MCP connection."""
    return check_mcp_tool("dice", "job_search")


def validate_indeed_mcp() -> dict:
    """Validate Indeed MCP connection."""
    return check_mcp_tool("indeed", "job_search")


def validate_all_mcps() -> dict:
    """Validate MCP connections.

    We prefer both Dice and Indeed, but allow running if at least one
    is available so the skill still works when a single source is down.
    """
    dice = validate_dice_mcp()
    indeed = validate_indeed_mcp()

    dice_ok = dice["connected"]
    indeed_ok = indeed["connected"]

    return {
        # Allow execution if at least one source is connected
        "valid": dice_ok or indeed_ok,
        "dice": dice,
        "indeed": indeed,
        "message": (
            "All MCPs connected"
            if (dice_ok and indeed_ok)
            else "Some MCPs missing, continuing with available sources"
        ),
    }


if __name__ == "__main__":
    result = validate_all_mcps()

    if result["valid"]:
        print("✓ All MCPs connected (Dice, Indeed)")
        sys.exit(0)
    else:
        print("✗ MCP Validation Failed (OpenCode):")
        print(f"  Dice: {result['dice']['message']}")
        print(f"  Indeed: {result['indeed']['message']}")

        print("\n--- Setup ---")
        print("To authenticate MCPs, run:")
        print("  Dice:   opencode mcp auth dice")
        print("  Indeed: opencode mcp auth indeed")
        print("\nThen verify with: opencode mcp list")

        sys.exit(1)
