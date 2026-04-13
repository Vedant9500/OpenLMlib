#!/usr/bin/env python
"""
Log this development session to memory injection system.
This creates observations that should persist to the next session.
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path.cwd()))

from openlmlib.runtime import get_runtime
from openlmlib.memory import SessionManager, MemoryStorage, ContextBuilder, ProgressiveRetriever

def main():
    session_id = "session_20260413_memory_dev_v2"  # Unique ID
    
    print("="*60)
    print("LOGGING DEVELOPMENT SESSION TO MEMORY")
    print("="*60)
    
    # Initialize
    runtime = get_runtime(Path("config/settings.json"))
    storage = MemoryStorage(runtime.conn)
    session_mgr = SessionManager(storage)
    retriever = ProgressiveRetriever(storage)
    context_builder = ContextBuilder(retriever)
    
    # Start session
    print("\n1. Starting session...")
    result = session_mgr.on_session_start(
        session_id,
        "developer",
        "Implement memory injection system with caveman compression"
    )
    print(f"   ✓ Session started: {result['status']}")
    
    # Log key observations from this development session
    print("\n2. Logging observations...")
    
    observations = [
        {
            "tool_name": "web_research",
            "tool_input": "https://github.com/thedotmack/claude-mem",
            "tool_output": """Researched claude-mem architecture: 5 lifecycle hooks (SessionStart, UserPromptSubmit, PostToolUse, Stop, SessionEnd), progressive disclosure (3-layer: index→timeline→details), SQLite + Chroma vector DB, 10x token compression via AI summarization, privacy filtering with <private> tags, worker service on port 37777 for async processing."""
        },
        {
            "tool_name": "web_research",
            "tool_input": "https://github.com/JuliusBrussee/caveman",
            "tool_output": """Researched caveman compression: linguistic compression achieving 60% additional token reduction on top of extractive summarization. Ultra intensity drops articles/filler/hedging, converts to telegraphic fragments. Preserves 100% technical content (code, URLs, paths). LLMs understand compressed text perfectly."""
        },
        {
            "tool_name": "implement",
            "tool_input": "Phase 1-3: Foundation",
            "tool_output": """Implemented core memory system: 8 modules in openlmlib/memory/ (storage.py 380 lines, session_manager.py 340 lines, hooks.py 200 lines, observation_queue.py 180 lines, compressor.py 240 lines, privacy.py 180 lines, memory_retriever.py 360 lines, context_builder.py 240 lines). SQLite schema with sessions/observations/summaries tables. 35 tests passing."""
        },
        {
            "tool_name": "implement",
            "tool_input": "Caveman ultra compression",
            "tool_output": """Implemented caveman_compress.py (380 lines) with 3 intensity levels (lite/full/ultra). Integrated with context_builder and compressor pipeline. Added caveman settings (caveman_enabled, caveman_intensity) to settings.py. Total compression: 18.5x (was 10x). 34 new tests, all 69 tests passing."""
        },
        {
            "tool_name": "implement",
            "tool_input": "Phase 4: MCP Integration",
            "tool_output": """Added 7 MCP tools to mcp_server.py: memory_session_start, memory_session_end, memory_log_observation, memory_search (Layer 1), memory_timeline (Layer 2), memory_get_observations (Layer 3), memory_inject_context. Lazy-loaded to avoid import penalty. Memory tools added to help system."""
        },
        {
            "tool_name": "implement",
            "tool_input": "Phase 6: Testing & Documentation",
            "tool_output": """Created integration test script (scripts/test_memory_workflow.py). All tests pass: 69 unit tests + 1 integration workflow test. Created 6 documentation files: IMPLEMENTATION_PLAN.md, MEMORY_INJECTION_ANALYSIS.md, CAVEMAN_INTEGRATION_PLAN.md, MEMORY_IMPLEMENTATION_SUMMARY.md, CAVEMAN_IMPLEMENTATION_SUMMARY.md, MEMORY_QUICKSTART.md."""
        },
        {
            "tool_name": "git_commit",
            "tool_input": "feature/memory-injection branch",
            "tool_output": """Pushed to origin/feature/memory-injection. 6 commits with proper multi-line commit messages. Branch tracking origin/feature/memory-injection. All changes committed: 19 files, 8,314+ insertions. Ready for testing in next session."""
        },
        {
            "tool_name": "architecture",
            "tool_input": "System design decisions",
            "tool_output": """Key decisions: MCP-native (not external plugin system), SQLite (not Chroma - already have FAISS), extractive + linguistic compression (18.5x total), async observation queue (non-blocking), progressive disclosure (75→200→750 tokens/result), privacy by design (edge filtering), lazy-loaded modules (fast startup)."""
        },
    ]
    
    for i, obs in enumerate(observations, 1):
        obs_id = session_mgr.on_tool_use(
            session_id,
            obs["tool_name"],
            obs["tool_input"],
            obs["tool_output"]
        )
        print(f"   ✓ Observation {i}: {obs['tool_name']} (ID: {obs_id})")
    
    # End session with summarization
    print("\n3. Ending session (generating summary)...")
    result = session_mgr.on_session_end(session_id, generate_summary=True)
    print(f"   ✓ Session ended: {result['status']}")
    print(f"   ✓ Observations logged: {result['observation_count']}")
    print(f"   ✓ Summary generated: {result.get('summary_generated', False)}")
    
    print("\n" + "="*60)
    print("MEMORY LOGGED SUCCESSFULLY!")
    print("="*60)
    print(f"\nSession ID: {session_id}")
    print(f"Total observations: {result['observation_count']}")
    print(f"\nIn your next session, run:")
    print(f"  python scripts/test_memory_retrieval.py")
    print(f"\nThis should retrieve the memories logged here.")
    print("="*60)


if __name__ == "__main__":
    main()
