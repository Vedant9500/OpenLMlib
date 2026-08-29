#!/usr/bin/env python
"""
Retrieve memories logged from the previous development session.
Tests if memory injection persists across sessions.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

from openlmlib.memory import (
    ContextBuilder,
    MemoryStorage,
    ProgressiveRetriever,
    SessionManager,
)
from openlmlib.runtime import get_runtime


def main():
    print("="*60)
    print("RETRIEVING MEMORIES FROM PREVIOUS SESSION")
    print("="*60)
    
    # Initialize
    runtime = get_runtime(Path("config/settings.json"))
    storage = MemoryStorage(runtime.conn)
    session_mgr = SessionManager(storage)
    retriever = ProgressiveRetriever(storage)
    context_builder = ContextBuilder(retriever)
    
    # Start new session (use unique ID to avoid conflicts)
    new_session_id = f"retrieval_test_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    print("\n1. Starting new session...")
    result = session_mgr.on_session_start(new_session_id, "developer", "Retrieve previous session memories")
    print(f"   ✓ Session started: {result['status']}")
    
    # Test 1: Auto-inject context (should retrieve from previous session)
    print("\n2. Auto-injecting context from previous sessions...")
    context = context_builder.build_session_start_context(
        new_session_id,
        query="memory injection implementation",
        limit=20
    )
    
    if context:
        print(f"   ✓ Context retrieved! ({len(context)} chars)")
        print("\n   First 300 chars of injected context:")
        print(f"   {'-'*60}")
        print(f"   {context[:300]}...")
        print(f"   {'-'*60}")
    else:
        print("   ✗ No context retrieved")
    
    # Test 2: Layer 1 search
    print("\n3. Layer 1: Searching memory index...")
    index = retriever.layer1_search_index("claude-mem architecture research", limit=10)
    print(f"   Found {len(index)} results")
    for i, item in enumerate(index[:3], 1):
        print(f"   {i}. {item.title[:70]} (ID: {item.id})")
    
    # Test 3: Layer 3 full details
    if index:
        print("\n4. Layer 3: Fetching full observation details...")
        details = retriever.layer3_full_details([index[0].id])
        if details:
            detail = details[0]
            print(f"   Tool: {detail.tool_name}")
            print(f"   Type: {detail.obs_type}")
            print(f"   Summary: {detail.compressed_summary[:150] if detail.compressed_summary else 'N/A'}")
            print("   ✓ Full details retrieved")
    
    # Test 4: Search for specific topics
    print("\n5. Searching for specific topics...")
    topics = ["caveman compression", "MCP integration", "Phase 1-3"]
    for topic in topics:
        results = retriever.layer1_search_index(topic, limit=5)
        print(f"   '{topic}': {len(results)} results")
    
    # End session
    print("\n6. Ending session...")
    result = session_mgr.on_session_end(new_session_id)
    print("   ✓ Session ended")
    
    print("\n" + "="*60)
    print("RETRIEVAL COMPLETE!")
    print("="*60)
    print("\nIf you see context above, memory injection is working!")
    print("The memories from session_20260413_memory_dev_v2 persisted.")
    print("="*60)


if __name__ == "__main__":
    main()
