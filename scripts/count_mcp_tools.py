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
            'init_library', 'save_finding', 'list_findings',
            'get_finding', 'search_findings', 'retrieve_findings',
            'retrieve_context', 'delete_finding', 'health',
            'evaluate_retrieval', 'help_library',
        ])
        
        # Memory tools
        all_expected.update([
            'session_start', 'session_end', 'log_observation',
            'search_memory', 'memory_timeline', 'get_observations',
            'inject_context', 'session_recap', 'topic_context',
            'ingest_git_history',
        ])
        
        # Collab tools
        all_expected.update([
            'create_session', 'join_session', 'list_sessions',
            'get_session_state', 'update_session_state', 'send_message',
            'read_messages', 'poll_messages', 'tail_messages',
            'read_message_range', 'grep_messages', 'session_context',
            'save_artifact', 'list_artifacts', 'get_artifact',
            'grep_artifacts', 'leave_session', 'terminate_session',
            'export_to_library', 'list_templates', 'get_template',
            'create_from_template', 'get_agent_sessions',
            'sessions_summary', 'search_sessions',
            'session_relationships', 'session_statistics',
            'list_models', 'get_model_details',
            'recommended_models', 'help_collab'
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
