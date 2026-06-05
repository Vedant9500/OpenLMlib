#!/usr/bin/env python3
"""Diagnose OpenLMlib MCP tool registration.

This script is intentionally local and dependency-light. Run it with the same
Python executable used by the MCP client entry:

    .\\.venv\\Scripts\\python.exe scripts\\diagnose_mcp_tools.py
"""
from __future__ import annotations

import traceback
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if (REPO_ROOT / "openlmlib" / "mcp_server.py").exists():
    sys.path.insert(0, str(REPO_ROOT))

EXPECTED_TOTAL = 76
EXPECTED_CO_SCIENTIST = {
    "screen_co_scientist_scope",
    "create_co_scientist_run",
    "submit_hypothesis",
    "start_hypothesis_verification",
    "submit_verification",
    "get_co_scientist_report",
    "create_co_scientist_final_report",
    "evaluate_co_scientist_run",
}


def main() -> int:
    print("Testing MCP tool registration...")
    print("=" * 60)

    print("\n[Test 1] Import openlmlib.mcp_server")
    try:
        import openlmlib
        from openlmlib import mcp_server

        print("  OK: mcp_server imported")
        print(f"  Source: {openlmlib.__file__}")
    except Exception as exc:
        print(f"  FAIL: {exc}")
        traceback.print_exc()
        return 1

    print("\n[Test 2] Register memory and collaboration tools")
    try:
        mcp_server._register_memory_tools()
        mcp_server._register_collab_tools()
        print("  OK: registration completed")
    except Exception as exc:
        print(f"  FAIL: {exc}")
        traceback.print_exc()
        return 1

    print("\n[Test 3] Count registered tools")
    try:
        tools = set(mcp_server.mcp._tool_manager._tools)
    except Exception as exc:
        print(f"  FAIL: cannot inspect tool manager: {exc}")
        traceback.print_exc()
        return 1

    print(f"  Registered tools: {len(tools)}")
    if len(tools) < EXPECTED_TOTAL:
        print(f"  FAIL: expected at least {EXPECTED_TOTAL} tools")
        missing_core_hint = EXPECTED_CO_SCIENTIST - tools
        if missing_core_hint:
            print("  Missing Co-Scientist entry points:")
            for name in sorted(missing_core_hint):
                print(f"    - {name}")
        return 1

    print("  OK: expected tool count is present")

    print("\n[Test 4] Co-Scientist entry points")
    missing_co_scientist = EXPECTED_CO_SCIENTIST - tools
    if missing_co_scientist:
        print("  FAIL: missing Co-Scientist tools")
        for name in sorted(missing_co_scientist):
            print(f"    - {name}")
        return 1

    print("  OK: Co-Scientist workflow tools are registered")
    print("\nRegistered tool names:")
    for name in sorted(tools):
        print(f"  - {name}")

    print("\nOK: MCP tool registration looks complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
