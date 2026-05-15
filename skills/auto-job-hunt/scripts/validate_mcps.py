#!/usr/bin/env python3
"""MCP availability check — non-blocking, informational only.

MCP validation is intentionally disabled. The skill starts immediately
without checking whether Dice or Indeed MCPs are connected. Sources that
are unavailable are silently skipped during execution.
"""


def validate_dice_mcp() -> dict:
    return {
        "connected": True,
        "message": "MCP validation disabled",
        "tools": ["job_search"],
    }


def validate_indeed_mcp() -> dict:
    return {
        "connected": True,
        "message": "MCP validation disabled",
        "tools": ["job_search"],
    }


def validate_all_mcps() -> dict:
    return {
        "valid": True,
        "dice": validate_dice_mcp(),
        "indeed": validate_indeed_mcp(),
        "message": "MCP validation disabled — proceeding with all sources",
    }


if __name__ == "__main__":
    print("✓ MCP validation disabled — skill will start without MCP checks")
