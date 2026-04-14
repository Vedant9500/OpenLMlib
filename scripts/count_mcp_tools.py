#!/usr/bin/env python3
"""
Quick MCP tool counter - run this in the installed environment.
This will tell you exactly how many tools are registered.

Tools breakdown:
- Core tools: 11 (openlmlib_*)
- Memory tools: 10 (memory_*)
- Collab tools: 31 (collab_*)
- Total: 52 tools
"""
import sys

try:
    # Try to import and count
    from openlmlib.mcp_server import mcp
    tools = mcp._tool_manager._tools

    core = [n for n in tools if n.startswith('openlmlib_')]
    memory = [n for n in tools if n.startswith('memory_')]
    collab = [n for n in tools if n.startswith('collab_')]

    print(f"Total MCP tools: {len(tools)}")
    print(f"  Core tools: {len(core)}")
    print(f"  Memory tools: {len(memory)}")
    print(f"  Collab tools: {len(collab)}")

    # Expected tool counts
    EXPECTED_CORE = 11
    EXPECTED_MEMORY = 10
    EXPECTED_COLLAB = 31
    EXPECTED_TOTAL = EXPECTED_CORE + EXPECTED_MEMORY + EXPECTED_COLLAB  # 52

    if len(tools) < EXPECTED_TOTAL:
        print(f"\n⚠ WARNING: Expected {EXPECTED_TOTAL} tools but found {len(tools)}!")
        
        if len(memory) == 0:
            print("  → Memory tools are NOT registered!")
            print("  → This is likely because _register_memory_tools() wasn't called")
        
        if len(collab) == 0:
            print("  → Collab tools are NOT registered!")
            print("  → This is likely an import error in collab module")
        
        if len(core) < EXPECTED_CORE:
            print(f"  → Core tools missing: expected {EXPECTED_CORE}, found {len(core)}")
        
        print(f"\nMissing tools:")
        all_expected = set()
        
        # Core tools
        all_expected.update([
            'openlmlib_init', 'openlmlib_add_finding', 'openlmlib_list_findings',
            'openlmlib_get_finding', 'openlmlib_search_fts', 'openlmlib_retrieve',
            'openlmlib_retrieve_context', 'openlmlib_delete_finding', 'openlmlib_health',
            'openlmlib_evaluate_dataset', 'openlmlib_help',
        ])
        
        # Memory tools
        all_expected.update([
            'memory_session_start', 'memory_session_end', 'memory_log_observation',
            'memory_search', 'memory_timeline', 'memory_get_observations',
            'memory_inject_context', 'memory_quick_recap', 'memory_detailed_context',
            'memory_retroactive_ingest',
        ])
        
        # Collab tools
        all_expected.update([
            'collab_create_session', 'collab_join_session', 'collab_list_sessions',
            'collab_get_session_state', 'collab_update_session_state', 'collab_send_message',
            'collab_read_messages', 'collab_poll_messages', 'collab_tail_messages',
            'collab_read_message_range', 'collab_grep_messages', 'collab_get_session_context',
            'collab_add_artifact', 'collab_list_artifacts', 'collab_get_artifact',
            'collab_grep_artifacts', 'collab_leave_session', 'collab_terminate_session',
            'collab_export_to_library', 'collab_list_templates', 'collab_get_template',
            'collab_create_session_from_template', 'collab_get_agent_sessions',
            'collab_get_active_sessions_summary', 'collab_search_sessions',
            'collab_get_session_relationships', 'collab_get_session_statistics',
            'collab_list_openrouter_models', 'collab_get_openrouter_model_details',
            'collab_get_recommended_models', 'collab_help'
        ])
        
        found = set(tools.keys())
        missing = all_expected - found
        for tool in sorted(missing):
            print(f"  - {tool}")
    else:
        print(f"\n✅ All {EXPECTED_TOTAL} tools registered successfully!")
        
        # Show tool lists
        print(f"\nCore tools ({len(core)}):")
        for tool in sorted(core):
            print(f"  ✓ {tool}")
        
        print(f"\nMemory tools ({len(memory)}):")
        for tool in sorted(memory):
            print(f"  ✓ {tool}")
        
        print(f"\nCollab tools ({len(collab)}):")
        for tool in sorted(collab):
            print(f"  ✓ {tool}")

    sys.exit(0 if len(tools) >= EXPECTED_TOTAL else 1)

except ImportError as e:
    print(f"ERROR: Failed to import openlmlib.mcp_server")
    print(f"  {e}")
    print(f"\nThis means the package isn't installed correctly.")
    print(f"Try: pip install -e D:\\LMlib")
    sys.exit(1)
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
