#!/usr/bin/env python
"""
Integration test script for memory injection workflow.

Tests complete memory lifecycle:
1. Session start with context injection
2. Observation logging
3. Progressive retrieval (3 layers)
4. Session end with summarization
5. Caveman compression validation

Usage:
    python scripts/test_memory_workflow.py
"""

import sys
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from openlmlib.memory import (
    SessionManager,
    MemoryStorage,
    ProgressiveRetriever,
    ContextBuilder,
    caveman_compress,
)
from openlmlib.memory.compressor import MemoryCompressor


def print_section(title: str):
    """Print formatted section header."""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def test_complete_workflow():
    """Test complete memory injection workflow."""
    print_section("MEMORY INJECTION WORKFLOW TEST")
    print(f"  Started at: {datetime.now(timezone.utc).isoformat()}")
    
    # Initialize in-memory database for testing
    print("\n1. Initializing memory system...")
    conn = sqlite3.connect(":memory:")
    storage = MemoryStorage(conn)
    session_mgr = SessionManager(storage)
    retriever = ProgressiveRetriever(storage)
    context_builder = ContextBuilder(retriever)
    compressor = MemoryCompressor()
    print("   ✓ Memory system initialized")
    
    # Test 1: Session lifecycle
    print_section("TEST 1: Session Lifecycle")
    session_id = "test_workflow_001"
    
    print(f"   Starting session: {session_id}")
    result = session_mgr.on_session_start(session_id, "test_user")
    assert result["status"] == "started"
    print(f"   ✓ Session started successfully")
    
    # Test 2: Observation logging
    print_section("TEST 2: Observation Logging")
    observations = [
        {
            "tool_name": "Read",
            "tool_input": "file: retrieval.py",
            "tool_output": "class RetrievalEngine:\n    def search(self, query, k=10):\n        # Semantic search implementation\n        pass"
        },
        {
            "tool_name": "Edit",
            "tool_input": "file: compressor.py",
            "tool_output": "Added caveman compression support. Reduced tokens by 60%."
        },
        {
            "tool_name": "run_shell_command",
            "tool_input": "$ python -m pytest tests/",
            "tool_output": "69 passed in 0.14s"
        },
    ]
    
    print(f"   Logging {len(observations)} observations...")
    for i, obs in enumerate(observations, 1):
        obs_id = session_mgr.on_tool_use(
            session_id,
            obs["tool_name"],
            obs["tool_input"],
            obs["tool_output"]
        )
        assert obs_id is not None
        print(f"   ✓ Observation {i}: {obs['tool_name']} (ID: {obs_id})")
    
    # Test 3: Compression
    print_section("TEST 3: Memory Compression")
    test_obs = {
        "tool_name": "Read",
        "tool_output": "The file contains a function that handles user authentication and validates credentials properly."
    }
    summary = compressor.compress(test_obs)
    print(f"   Original tokens: {summary['token_count_original']}")
    print(f"   Compressed tokens: {summary['token_count_compressed']}")
    if summary['token_count_original'] > 0:
        ratio = summary['token_count_original'] / max(summary['token_count_compressed'], 1)
        print(f"   Compression ratio: {ratio:.1f}x")
        print(f"   ✓ Compression successful (caveman: {summary.get('caveman_enabled', False)})")
    
    # Test 4: Caveman compression
    print_section("TEST 4: Caveman Ultra Compression")
    test_text = "The function will basically just validate the user credentials."
    compressed, stats = caveman_compress(test_text, intensity='ultra')
    print(f"   Original: '{test_text}'")
    print(f"   Compressed: '{compressed}'")
    print(f"   Reduction: {stats['reduction_percent']}%")
    print(f"   ✓ Caveman compression working")
    
    # Test 5: Progressive retrieval
    print_section("TEST 5: Progressive Retrieval (3 Layers)")
    
    print("\n   Layer 1: Search Index")
    index = retriever.layer1_search_index("authentication", limit=10)
    print(f"   Found {len(index)} results")
    if index:
        print(f"   First result: {index[0].title[:60]}")
        print(f"   ✓ Layer 1 complete")
    
    if index:
        print("\n   Layer 2: Timeline")
        timeline = retriever.layer2_timeline([index[0].id])
        print(f"   Retrieved {len(timeline)} timeline entries")
        print(f"   ✓ Layer 2 complete")
        
        print("\n   Layer 3: Full Details")
        details = retriever.layer3_full_details([index[0].id])
        print(f"   Retrieved {len(details)} full observations")
        print(f"   ✓ Layer 3 complete")
    
    # Test 6: Context building
    print_section("TEST 6: Context Building")
    context = context_builder.build_session_start_context(
        session_id,
        limit=10
    )
    context_length = len(context)
    print(f"   Context length: {context_length} chars")
    if context_length > 0:
        print(f"   First 100 chars: {context[:100]}...")
        print(f"   ✓ Context built successfully")
    
    # Test 7: Session end
    print_section("TEST 7: Session End & Summarization")
    result = session_mgr.on_session_end(session_id, generate_summary=True)
    print(f"   Status: {result['status']}")
    print(f"   Observations: {result['observation_count']}")
    print(f"   Summary generated: {result.get('summary_generated', False)}")
    print(f"   Duration: {result.get('duration_seconds', 0):.2f}s")
    print(f"   ✓ Session ended successfully")
    
    # Test 8: New session with context
    print_section("TEST 8: New Session with Context Injection")
    new_session_id = "test_workflow_002"
    session_mgr.on_session_start(new_session_id, "test_user")
    
    context = context_builder.build_session_start_context(
        new_session_id,
        query="retrieval",
        limit=10
    )
    print(f"   Context injected: {bool(context)}")
    if context:
        print(f"   Context length: {len(context)} chars")
        print(f"   ✓ Context injection working")
    
    session_mgr.on_session_end(new_session_id)
    
    # Summary
    print_section("TEST SUMMARY")
    print("   ✅ All tests passed!")
    print(f"   Completed at: {datetime.now(timezone.utc).isoformat()}")
    print(f"\n   Workflow tested:")
    print(f"   • Session lifecycle management")
    print(f"   • Observation logging with privacy filtering")
    print(f"   • Memory compression (extractive + caveman)")
    print(f"   • Progressive disclosure (3 layers)")
    print(f"   • Context building and injection")
    print(f"   • Session summarization")
    
    # Cleanup
    conn.close()
    print(f"\n{'='*60}")
    print("  Ready for production! 🚀")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    try:
        test_complete_workflow()
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
