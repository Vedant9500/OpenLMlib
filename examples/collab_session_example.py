"""Example: Running a multi-agent collaboration session programmatically.

This script demonstrates the full lifecycle of a CollabSessions session:
1. Create a session with a plan
2. Spawn worker agents
3. Orchestrator assigns tasks
4. Workers complete tasks and create artifacts
5. Session is terminated and results summarized

Usage:
    python examples/collab_session_example.py
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openlmlib.collab.db import connect_collab_db, init_collab_db, get_session_tasks
from openlmlib.collab.session import (
    create_collab_session,
    join_collab_session,
    terminate_collab_session,
)
from openlmlib.collab.message_bus import MessageBus
from openlmlib.collab.artifact_store import ArtifactStore
from openlmlib.collab.context_compiler import ContextCompiler
from openlmlib.collab.state_manager import StateManager
from openlmlib.collab.prompts import get_system_prompt


def main():
    tmpdir = tempfile.mkdtemp()
    sessions_dir = Path(tmpdir) / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    db_path = Path(tmpdir) / "collab_sessions.db"

    conn = connect_collab_db(db_path)
    init_collab_db(conn)
    now = datetime.now(timezone.utc).isoformat()

    print("=" * 60)
    print("CollabSessions Example: Multi-Agent Research Session")
    print("=" * 60)

    # Step 1: Create session
    print("\n[1] Creating session...")
    session = create_collab_session(
        conn=conn,
        sessions_dir=sessions_dir,
        title="AI Safety Research",
        created_by="claude-sonnet-4",
        description="Research recent advances in AI alignment and safety",
        plan=[
            {"step": 1, "task": "Survey current AI alignment approaches", "assigned_to": "any"},
            {"step": 2, "task": "Analyze RLHF and DPO methods", "assigned_to": "any"},
            {"step": 3, "task": "Compile findings into summary report", "assigned_to": "any"},
        ],
    )
    session_id = session["session_id"]
    orchestrator_id = session["agent_id"]
    print(f"    Session: {session_id}")
    print(f"    Orchestrator: {orchestrator_id}")

    # Step 2: Workers join
    print("\n[2] Workers joining...")
    w1 = join_collab_session(
        conn=conn, sessions_dir=sessions_dir,
        session_id=session_id, model="gpt-codex",
    )
    w2 = join_collab_session(
        conn=conn, sessions_dir=sessions_dir,
        session_id=session_id, model="gemini-pro",
    )
    print(f"    Worker 1: {w1['agent_id']}")
    print(f"    Worker 2: {w2['agent_id']}")

    # Step 3: Show system prompts
    print("\n[3] System prompts...")
    orch_prompt = get_system_prompt("orchestrator", session_id, "AI Safety Research")
    print(f"    Orchestrator prompt: {len(orch_prompt)} chars")
    worker_prompt = get_system_prompt("worker", session_id, "AI Safety Research", w1["agent_id"])
    print(f"    Worker prompt: {len(worker_prompt)} chars")

    # Step 4: Orchestrator assigns tasks
    print("\n[4] Assigning tasks...")
    bus = MessageBus(conn, sessions_dir)
    bus.send(
        session_id=session_id, from_agent=orchestrator_id,
        msg_type="task", content="Survey current AI alignment approaches",
        to_agent=w1["agent_id"], created_at=now,
    )
    bus.send(
        session_id=session_id, from_agent=orchestrator_id,
        msg_type="task", content="Analyze RLHF and DPO methods",
        to_agent=w2["agent_id"], created_at=now,
    )

    # Step 5: Workers complete tasks
    print("\n[5] Workers completing tasks...")
    store = ArtifactStore(conn, sessions_dir)

    store.save(
        session_id=session_id, created_by=w1["agent_id"],
        title="AI Alignment Survey",
        content="# AI Alignment Approaches\n\nSurvey of current methods...",
        created_at=now, artifact_type="research_summary",
        tags=["alignment", "survey"],
    )
    bus.send(
        session_id=session_id, from_agent=w1["agent_id"],
        msg_type="result", content="Alignment survey complete",
        created_at=now,
    )

    store.save(
        session_id=session_id, created_by=w2["agent_id"],
        title="RLHF vs DPO Analysis",
        content="# RLHF vs DPO\n\nComparative analysis...",
        created_at=now, artifact_type="analysis",
        tags=["rlhf", "dpo"],
    )
    bus.send(
        session_id=session_id, from_agent=w2["agent_id"],
        msg_type="result", content="RLHF/DPO analysis complete",
        created_at=now,
    )

    # Step 6: Read context
    print("\n[6] Reading session context...")
    compiler = ContextCompiler(conn, bus, store)
    ctx = compiler.compile_context(session_id, orchestrator_id)
    formatted = compiler.format_context_for_prompt(ctx)
    print(f"    Context: {len(formatted)} chars")
    print(f"    Artifacts: {len(ctx['artifacts'])}")

    # Step 7: Terminate
    print("\n[7] Terminating session...")
    result = terminate_collab_session(
        conn, sessions_dir, session_id,
        summary="Research completed. Two artifacts produced: alignment survey and RLHF/DPO analysis.",
    )
    print(f"    Status: {result['status']}")
    print(f"    Summary saved: {result['summary_saved']}")

    # Summary
    artifacts = store.list_artifacts(session_id)
    print(f"\n{'=' * 60}")
    print(f"Session complete: {len(artifacts)} artifacts created")
    for art in artifacts:
        print(f"  - {art['artifact_id']}: {art['title']} ({art['word_count']} words)")
    print(f"{'=' * 60}")

    conn.close()
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    main()
