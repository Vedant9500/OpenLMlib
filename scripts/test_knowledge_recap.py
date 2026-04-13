#!/usr/bin/env python
"""
Test the new progressive knowledge recap flow:
1. memory_quick_recap → synthesized overview (~150-250 tokens)
2. memory_detailed_context(topic) → targeted deep dive (~500-800 tokens)
3. memory_get_observations(ids) → raw observation details (existing)

Demonstrates the knowledge-level progressive disclosure.
"""

from pathlib import Path
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(Path.cwd()))

from openlmlib.memory import SessionManager, MemoryStorage, extract_knowledge
from openlmlib.runtime import get_runtime


def main():
    print("="*60)
    print("  PROGRESSIVE KNOWLEDGE RECAP TEST")
    print("="*60)

    # Initialize
    runtime = get_runtime(Path("config/settings.json"))
    storage = MemoryStorage(runtime.conn)
    session_mgr = SessionManager(storage)

    print("\n1. Starting test session...")
    session_id = f"recap_test_{datetime.now(timezone.utc).strftime('%H%M%S')}"
    session_mgr.on_session_start(session_id, "test", "Test knowledge recap flow")
    print("   ✓ Session started")

    # Log diverse observations
    print("\n2. Logging observations with diverse content...")

    # Observation 1: Architecture decision
    session_mgr.on_tool_use(
        session_id, "Read",
        "openlmlib/mcp_server.py",
        "File read successfully. Decided to use FastMCP with lazy tool registration "
        "to avoid slow startup. The pattern uses closure to capture instances."
    )

    # Observation 2: Code modification
    session_mgr.on_tool_use(
        session_id, "Edit",
        "openlmlib/memory/storage.py",
        "Modified storage.py. Added ON DELETE CASCADE to foreign keys. "
        "Chose SQLite with PRAGMA foreign_keys = ON for cascade behavior. "
        "Follows the convention of explicit schema management."
    )

    # Observation 3: Shell command with error
    session_mgr.on_tool_use(
        session_id, "run_shell_command",
        "pytest tests/",
        "Error: ImportError: cannot import name 'KnowledgeExtractor'. "
        "Next steps: need to fix the import and add to __init__.py."
    )

    # Observation 4: File creation
    session_mgr.on_tool_use(
        session_id, "write_file",
        "openlmlib/memory/knowledge_extractor.py",
        "Created knowledge_extractor.py. Uses dataclasses for structured data. "
        "Follows the pattern of extractive summarization used in compressor.py."
    )

    print("   ✓ 4 observations logged")

    # End session (triggers knowledge synthesis)
    print("\n3. Ending session (auto-synthesizes knowledge)...")
    result = session_mgr.on_session_end(session_id)
    print(f"   ✓ Session ended: {result['observation_count']} observations")

    # Test knowledge extraction
    print("\n4. Checking synthesized knowledge...")
    knowledge_entries = storage.get_knowledge(session_id)
    if knowledge_entries:
        entry = knowledge_entries[0]
        knowledge_data = entry.get("knowledge", {})
        from openlmlib.memory.knowledge_extractor import SessionKnowledge
        sk = SessionKnowledge.from_dict(knowledge_data)

        print(f"   Summary: {sk.summary}")
        print(f"   Files touched: {len(sk.files_touched)}")
        for f in sk.files_touched:
            print(f"     - {f['path']} ({f['action']})")
        print(f"   Decisions: {len(sk.decisions_made)}")
        for d in sk.decisions_made[:3]:
            print(f"     - {d[:80]}")
        print(f"   Next steps: {len(sk.next_steps)}")
        for n in sk.next_steps:
            print(f"     - {n}")

        # Test recap formatting
        print("\n5. Testing quick recap format (~150-250 tokens)...")
        recap = sk.format_quick_recap()
        words = len(recap.split())
        tokens = int(words * 1.3)
        print(f"   Recap size: {words} words, ~{tokens} tokens")
        print(f"\n   {recap}")

        # Test detailed context
        print("\n6. Testing detailed context for topic 'storage'...")
        detailed = sk.format_detailed_context(topic="storage")
        words = len(detailed.split())
        tokens = int(words * 1.3)
        print(f"   Detailed size: {words} words, ~{tokens} tokens")
        print(f"\n   {detailed}")
    else:
        print("   ✗ No knowledge entries found (extraction may have failed)")

    print("\n" + "="*60)
    print("  KNOWLEDGE RECAP TEST COMPLETE")
    print("="*60)
    print("\n  Progressive flow:")
    print("  1. memory_quick_recap → structured overview (~200 tokens)")
    print("  2. memory_detailed_context(topic='X') → deep dive (~500-800 tokens)")
    print("  3. memory_get_observations(ids) → raw details (~750 tokens)")
    print("="*60)


if __name__ == "__main__":
    main()
