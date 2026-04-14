#!/usr/bin/env python
"""
Test retroactive git-based ingestion for the current session.
This should pick up all files we modified today WITHOUT manual logging.
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path.cwd()))

from openlmlib.memory import MemoryStorage, retroactive_ingest
from openlmlib.runtime import get_runtime


def main():
    print("="*60)
    print("  RETROACTIVE GIT INGESTION TEST")
    print("="*60)

    runtime = get_runtime(Path("config/settings.json"))
    storage = MemoryStorage(runtime.conn)

    print("\n1. Ingesting today's session activity from git history...")
    result = retroactive_ingest(
        session_id="retro_test_current_session",
        time_window_hours=2,  # Last 2 hours
        include_uncommitted=True,
    )

    print(f"\n   Files found: {len(result.get('files_found', []))}")
    for f in result.get('files_found', [])[:10]:
        print(f"     - {f['path']} ({f['action']})")
    if len(result.get('files_found', [])) > 10:
        print(f"     ... and {len(result['files_found']) - 10} more")

    print(f"\n   Commits found: {len(result.get('commits_found', []))}")
    for c in result.get('commits_found', [])[:5]:
        print(f"     - {c['short_hash']}: {c['message'][:60]}")
    if len(result.get('commits_found', [])) > 5:
        print(f"     ... and {len(result['commits_found']) - 5} more")

    print(f"\n   Observations created: {result.get('observations_created', 0)}")
    
    if 'knowledge' in result:
        knowledge = result['knowledge']
        print(f"\n2. Synthesized knowledge:")
        print(f"   Summary: {knowledge.get('summary', 'N/A')}")
        print(f"   Files touched: {len(knowledge.get('files_touched', []))}")
        for f in knowledge.get('files_touched', [])[:5]:
            print(f"     - {f['path']} ({f['action']}): {f.get('reason', 'N/A')}")
        print(f"   Decisions: {len(knowledge.get('decisions_made', []))}")
        for d in knowledge.get('decisions_made', [])[:3]:
            print(f"     - {d[:80]}")
        print(f"   Next steps: {len(knowledge.get('next_steps', []))}")
        for n in knowledge.get('next_steps', [])[:3]:
            print(f"     - {n}")
        print(f"   Knowledge saved: {result.get('knowledge_saved', False)}")

    # Now test quick recap
    print("\n4. Testing quick recap after retroactive ingestion...")
    knowledge_entries = storage.get_knowledge("retro_test_current_session")
    if knowledge_entries:
        from openlmlib.memory.knowledge_extractor import SessionKnowledge
        sk = SessionKnowledge.from_dict(knowledge_entries[0]['knowledge'])
        recap = sk.format_quick_recap()
        print(f"\n   Quick Recap (~{int(len(recap.split()) * 1.3)} tokens):")
        print(f"   {'-'*60}")
        print(f"   {recap}")
        print(f"   {'-'*60}")

    print("\n" + "="*60)
    print("  RETROACTIVE INGESTION COMPLETE!")
    print("="*60)
    print("\n  This demonstrates:")
    print("  - No manual logging needed during session")
    print("  - Git history reconstructs all activity")
    print("  - Knowledge is synthesized automatically")
    print("  - Quick recap gives structured overview")
    print("="*60)


if __name__ == "__main__":
    main()
