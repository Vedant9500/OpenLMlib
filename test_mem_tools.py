import os
import sys

# Set up paths
sys.path.insert(0, os.path.abspath("."))

from openlmlib.mcp_server import _register_memory_tools, _get_memory_state, mcp

def test_tools():
    print("Registering tools...")
    _register_memory_tools()
    print("Tools registered.")
    
    print("Getting memory state...")
    try:
        state = _get_memory_state()
        print("Memory state keys:", state.keys())
    except Exception as e:
        print("Error getting memory state:", e)
        return

    print("All memory features seem to initialize correctly!")

if __name__ == "__main__":
    test_tools()
