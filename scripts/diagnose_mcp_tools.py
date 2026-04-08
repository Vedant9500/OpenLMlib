#!/usr/bin/env python3
"""Diagnostic script to count registered MCP tools."""
import sys
import os
import traceback

print("Testing MCP tool registration...", file=sys.stderr)
print("="*60, file=sys.stderr)

# Test 1: Try importing just the core mcp_server
print("\n[Test 1] Import mcp_server module...", file=sys.stderr)
try:
    from openlmlib import mcp_server
    print("  ✓ mcp_server imported", file=sys.stderr)
except Exception as e:
    print(f"  ✗ Failed: {e}", file=sys.stderr)
    traceback.print_exc()
    sys.exit(1)

# Test 2: Try importing collab module  
print("\n[Test 2] Import collab.collab_mcp...", file=sys.stderr)
try:
    from openlmlib.collab import collab_mcp
    print("  ✓ collab_mcp imported", file=sys.stderr)
except Exception as e:
    print(f"  ✗ Failed: {e}", file=sys.stderr)
    traceback.print_exc()
    print("\n  >>> THIS IS LIKELY THE ISSUE! <<<", file=sys.stderr)

# Test 3: Count registered tools
print("\n[Test 3] Count registered MCP tools...", file=sys.stderr)
try:
    from openlmlib.mcp_server import mcp
    
    tool_manager = mcp._tool_manager if hasattr(mcp, '_tool_manager') else None
    if tool_manager and hasattr(tool_manager, '_tools'):
        tools = tool_manager._tools
    else:
        print("  ✗ Cannot access tool manager structure", file=sys.stderr)
        sys.exit(1)
    
    print(f"  ✓ Total registered: {len(tools)}", file=sys.stderr)
    
    # Print all tools
    core_tools = sorted([name for name in tools.keys() if name.startswith('openlmlib_')])
    collab_tools = sorted([name for name in tools.keys() if name.startswith('collab_')])
    
    print(f"\n  Core tools ({len(core_tools)}):", file=sys.stderr)
    for name in core_tools:
        print(f"    - {name}", file=sys.stderr)
    
    print(f"\n  Collab tools ({len(collab_tools)}):", file=sys.stderr)
    for name in collab_tools:
        print(f"    - {name}", file=sys.stderr)
    
    # Summary for the user
    print("\n" + "="*60, file=sys.stderr)
    if len(tools) == 41:
        print("✓ ALL 41 TOOLS REGISTERED SUCCESSFULLY", file=sys.stderr)
    elif len(tools) < 15:
        print(f"⚠ ONLY {len(tools)} TOOLS REGISTERED (expected 41)", file=sys.stderr)
        print("  This suggests collab module import failed!", file=sys.stderr)
    else:
        print(f"⚠ {len(tools)} TOOLS REGISTERED (expected 41)", file=sys.stderr)
    
except Exception as e:
    print(f"  ✗ Failed: {e}", file=sys.stderr)
    traceback.print_exc()
    sys.exit(1)

# Test 4: Simulate MCP server module load
print("\n[Test 4] Full module load simulation (like mcp_server:main)...", file=sys.stderr)
try:
    # This simulates what happens when `python -m openlmlib.mcp_server` runs
    import importlib
    mod = importlib.import_module('openlmlib.mcp_server')
    if hasattr(mod, 'mcp') and hasattr(mod.mcp, '_tool_manager'):
        tool_mgr = mod.mcp._tool_manager
        if hasattr(tool_mgr, '_tools'):
            count = len(tool_mgr._tools)
            print(f"  ✓ Module loaded with {count} tools", file=sys.stderr)
            if count < 41:
                print(f"  ⚠ Expected 41 tools but got {count}!", file=sys.stderr)
        else:
            print("  ⚠ Tool manager has no _tools attribute", file=sys.stderr)
    else:
        print("  ⚠ Module doesn't have expected attributes", file=sys.stderr)
except Exception as e:
    print(f"  ✗ Failed: {e}", file=sys.stderr)
    traceback.print_exc()
