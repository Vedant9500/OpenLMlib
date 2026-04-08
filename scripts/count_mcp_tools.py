#!/usr/bin/env python3
"""
Quick MCP tool counter - run this in the installed environment.
This will tell you exactly how many tools are registered.
"""
import sys

try:
    # Try to import and count
    from openlmlib.mcp_server import mcp
    tools = mcp._tool_manager._tools
    
    core = [n for n in tools if n.startswith('openlmlib_')]
    collab = [n for n in tools if n.startswith('collab_')]
    
    print(f"Total MCP tools: {len(tools)}")
    print(f"  Core tools: {len(core)}")
    print(f"  Collab tools: {len(collab)}")
    
    if len(tools) < 41:
        print(f"\n⚠ WARNING: Expected 41 tools but found {len(tools)}!")
        if len(collab) == 0:
            print("  → Collab tools are NOT registered!")
            print("  → This is likely an import error in collab module")
        print(f"\nMissing tools:")
        all_expected = set([
            'openlmlib_init', 'openlmlib_add_finding', 'openlmlib_list_findings',
            'openlmlib_get_finding', 'openlmlib_search_fts', 'openlmlib_retrieve',
            'openlmlib_retrieve_context', 'openlmlib_delete_finding', 'openlmlib_health',
            'openlmlib_evaluate_dataset', 'openlmlib_help',
            'collab_create_session', 'collab_join_session', 'collab_list_sessions',
            'collab_get_session_state', 'collab_update_session_state', 'collab_send_message',
            'collab_read_messages', 'collab_tail_messages', 'collab_read_message_range',
            'collab_grep_messages', 'collab_get_session_context', 'collab_add_artifact',
            'collab_list_artifacts', 'collab_get_artifact', 'collab_grep_artifacts',
            'collab_leave_session', 'collab_terminate_session', 'collab_export_to_library',
            'collab_list_templates', 'collab_get_template', 'collab_create_session_from_template',
            'collab_get_agent_sessions', 'collab_get_active_sessions_summary',
            'collab_search_sessions', 'collab_get_session_relationships',
            'collab_get_session_statistics', 'collab_list_openrouter_models',
            'collab_get_openrouter_model_details', 'collab_get_recommended_models',
            'collab_help'
        ])
        found = set(tools.keys())
        missing = all_expected - found
        for tool in sorted(missing):
            print(f"  - {tool}")
    
    sys.exit(0 if len(tools) == 41 else 1)
    
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
