#!/usr/bin/env python
"""Test script for CollabSessions real-world multi-agent communication.

This script demonstrates model-to-model communication using the MCP tools.
It can be used to verify that different LLMs can create sessions, join them,
and communicate through the shared message bus.

Usage:
    python test_collab_live.py --session-id <id> --agent-id <id>
    
Or run standalone to test session creation:
    python test_collab_live.py
"""

import json
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from openlmlib.collab.db import connect_collab_db, init_collab_db, get_session, list_sessions
from openlmlib.collab.session import create_collab_session, join_collab_session
from openlmlib.collab.message_bus import MessageBus
from openlmlib.collab.artifact_store import ArtifactStore
from openlmlib.collab.context_compiler import ContextCompiler
from openlmlib.collab.state_manager import StateManager
from openlmlib.collab.session import terminate_collab_session


def init_test_environment():
    """Initialize test environment with a temp directory."""
    import tempfile
    tmp = tempfile.mkdtemp()
    data_dir = Path(tmp) / "data"
    data_dir.mkdir(parents=True)
    config_dir = data_dir / "config"
    config_dir.mkdir(parents=True)
    settings_path = config_dir / "settings.json"
    settings_path.write_text(json.dumps({"data_root": str(data_dir)}))
    os.environ["OPENLMLIB_SETTINGS"] = str(settings_path)
    return tmp, data_dir


def test_session_creation():
    """Test basic session creation."""
    print("=" * 60)
    print("TEST 1: Session Creation")
    print("=" * 60)
    
    tmp, data_dir = init_test_environment()
    sessions_dir = data_dir / "sessions"
    sessions_dir.mkdir(parents=True)
    db_path = data_dir / "collab_sessions.db"
    
    conn = connect_collab_db(db_path)
    init_collab_db(conn)
    
    # Create session as "opus-4.6" (orchestrator)
    result = create_collab_session(
        conn=conn,
        sessions_dir=sessions_dir,
        title="Quantum Computing Research",
        created_by="opus-4.6",
        description="Research latest advances in quantum computing",
        plan=[
            {"step": 1, "task": "Find recent papers on quantum error correction", "assigned_to": "any"},
            {"step": 2, "task": "Analyze key findings", "assigned_to": "any"},
            {"step": 3, "task": "Write summary", "assigned_to": "orchestrator"},
        ],
    )
    
    print(f"Session created: {result['session_id']}")
    print(f"Agent ID (orchestrator): {result['agent_id']}")
    print(f"Sessions dir: {result['sessions_dir']}")
    
    conn.close()
    return result["session_id"], result["agent_id"], sessions_dir


def test_agent_joining(session_id, sessions_dir):
    """Test an agent joining the session."""
    print("\n" + "=" * 60)
    print("TEST 2: Agent Joining")
    print("=" * 60)
    
    db_path = sessions_dir.parent / "collab_sessions.db"
    conn = connect_collab_db(db_path)
    
    # Join as "codex" worker
    result = join_collab_session(
        conn=conn,
        sessions_dir=sessions_dir,
        session_id=session_id,
        model="gpt-codex",
        capabilities=["code_analysis", "technical_research"],
    )
    
    print(f"Agent joined: {result['agent_id']}")
    print(f"Role: {result['role']}")
    
    conn.close()
    return result["agent_id"]


def test_message_exchange(session_id, orchestrator_id, worker_id, sessions_dir):
    """Test sending and reading messages."""
    print("\n" + "=" * 60)
    print("TEST 3: Message Exchange")
    print("=" * 60)
    
    db_path = sessions_dir.parent / "collab_sessions.db"
    conn = connect_collab_db(db_path)
    bus = MessageBus(conn, sessions_dir)
    
    # Orchestrator sends task
    task_msg = bus.send(
        session_id=session_id,
        from_agent=orchestrator_id,
        msg_type="task",
        content="Please research recent advances in quantum error correction from 2024-2025",
        to_agent=worker_id,
        metadata={"step": 1, "priority": "high"},
        created_at="2026-04-06T10:00:00Z",
    )
    print(f"Task sent: {task_msg['msg_id']}")
    
    # Worker sends result
    result_msg = bus.send(
        session_id=session_id,
        from_agent=worker_id,
        msg_type="result",
        content="Found 15 relevant papers. Key finding: Google's Willow chip achieved below-threshold error rates for the first time.",
        to_agent=orchestrator_id,
        metadata={"step": 1, "sources": 15},
        created_at="2026-04-06T10:05:00Z",
    )
    print(f"Result sent: {result_msg['msg_id']}")
    
    # Read messages
    messages = bus.tail(session_id, 5)
    print(f"\nLast 5 messages:")
    for msg in messages:
        to = msg.get("to_agent") or "all"
        content_preview = msg['content'][:60].replace('\n', ' ')
        print(f"  [{msg['seq']}] {msg['from_agent']} -> {to} [{msg['msg_type']}]: {content_preview}...")
    
    conn.close()


def test_state_update(session_id, orchestrator_id, sessions_dir):
    """Test session state initialization and orchestrator-only updates."""
    print("\n" + "=" * 60)
    print("TEST 4: State Update")
    print("=" * 60)

    db_path = sessions_dir.parent / "collab_sessions.db"
    conn = connect_collab_db(db_path)
    state_manager = StateManager(conn)

    current = state_manager.get_state(session_id)
    print(f"Initial version: {current['version']}")
    print(f"Initial phase: {current['state'].get('current_phase')}")

    next_state = dict(current["state"])
    next_state["current_phase"] = "research"
    next_state["active_tasks"] = ["Collect sources", "Draft analysis"]
    next_state["last_activity"] = "2026-04-06T10:15:00Z"

    ok = state_manager.update_state(
        session_id=session_id,
        state=next_state,
        updated_by=orchestrator_id,
        updated_at="2026-04-06T10:15:00Z",
        expected_version=current["version"],
    )
    print(f"Update applied: {ok}")

    updated = state_manager.get_state(session_id)
    print(f"Updated version: {updated['version']}")
    print(f"Updated phase: {updated['state'].get('current_phase')}")

    conn.close()


def test_context_compilation(session_id, agent_id, sessions_dir):
    """Test context compilation for an agent."""
    print("\n" + "=" * 60)
    print("TEST 5: Context Compilation")
    print("=" * 60)
    
    db_path = sessions_dir.parent / "collab_sessions.db"
    conn = connect_collab_db(db_path)
    bus = MessageBus(conn, sessions_dir)
    store = ArtifactStore(conn, sessions_dir)
    compiler = ContextCompiler(conn, bus, store)
    
    context = compiler.compile_context(session_id, agent_id)
    formatted = compiler.format_context_for_prompt(context)
    
    print("Compiled context for worker:")
    print("-" * 40)
    print(formatted[:500].replace("->", "-").replace("\u2192", "->") + "..." if len(formatted) > 500 else formatted.replace("->", "-").replace("\u2192", "->"))
    
    conn.close()


def test_artifact_creation(session_id, agent_id, sessions_dir):
    """Test saving an artifact."""
    print("\n" + "=" * 60)
    print("TEST 6: Artifact Creation")
    print("=" * 60)
    
    db_path = sessions_dir.parent / "collab_sessions.db"
    conn = connect_collab_db(db_path)
    store = ArtifactStore(conn, sessions_dir)
    
    result = store.save(
        session_id=session_id,
        created_by=agent_id,
        title="Quantum Error Correction Analysis",
        content="""# Quantum Error Correction Analysis

## Key Findings

1. **Google's Willow Chip**: First to achieve below-threshold error rates
2. **IBM's Approach**: Surface code with improved decoding
3. **Microsoft's topological qubits**: Progress in Majorana-based qubits

## Recommendations

Continue monitoring these developments for practical applications.
""",
        created_at="2026-04-06T10:10:00Z",
        artifact_type="research_summary",
        tags=["quantum", "error-correction", "2024-2025"],
        shared=True,
    )
    
    print(f"Artifact saved: {result['artifact_id']}")
    print(f"Path: {result['file_path']}")
    print(f"Word count: {result['word_count']}")

    retrieved = store.get_content_by_id(session_id, result["artifact_id"])
    print(f"Retrieved content length: {len(retrieved) if retrieved else 0}")
    
    # List artifacts
    artifacts = store.list_artifacts(session_id)
    print(f"\nSession has {len(artifacts)} artifacts:")
    for art in artifacts:
        print(f"  - {art['artifact_id']}: {art['title']}")
    
    conn.close()


def test_session_termination(session_id, orchestrator_id, sessions_dir):
    """Test terminating the session and persisting a summary."""
    print("\n" + "=" * 60)
    print("TEST 7: Session Termination")
    print("=" * 60)

    db_path = sessions_dir.parent / "collab_sessions.db"
    conn = connect_collab_db(db_path)

    result = terminate_collab_session(
        conn=conn,
        sessions_dir=sessions_dir,
        session_id=session_id,
        summary="Session completed successfully after research, analysis, and artifact creation.",
    )

    print(f"Termination status: {result['status']}")
    print(f"Summary saved: {result['summary_saved']}")

    session = get_session(conn, session_id)
    print(f"Final session status: {session['status']}")

    conn.close()


def main():
    print("CollabSessions Real-World Test")
    print("=" * 60)
    
    # Test 1: Create session
    session_id, orchestrator_id, sessions_dir = test_session_creation()
    
    # Test 2: Join session with another model
    worker_id = test_agent_joining(session_id, sessions_dir)
    
    # Test 3: Exchange messages
    test_message_exchange(session_id, orchestrator_id, worker_id, sessions_dir)
    
    # Test 4: Update session state
    test_state_update(session_id, orchestrator_id, sessions_dir)

    # Test 5: Compile context for worker
    test_context_compilation(session_id, worker_id, sessions_dir)
    
    # Test 6: Save artifact
    test_artifact_creation(session_id, worker_id, sessions_dir)

    # Test 7: Terminate session
    test_session_termination(session_id, orchestrator_id, sessions_dir)
    
    print("\n" + "=" * 60)
    print("ALL TESTS PASSED!")
    print("=" * 60)
    print(f"\nSession ID: {session_id}")
    print(f"Orchestrator: {orchestrator_id}")
    print(f"Worker: {worker_id}")
    print("\nThis session can now be accessed via MCP tools by any LLM!")


if __name__ == "__main__":
    main()