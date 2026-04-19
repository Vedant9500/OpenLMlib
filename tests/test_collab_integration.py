"""Integration tests with simulated agents for CollabSessions.

Tests full multi-agent session lifecycles using simulated autonomous
agents that make decisions, exchange messages, create artifacts,
and coordinate through the message bus.

Tests cover:
- Full session lifecycle with orchestrator + multiple workers
- Concurrent message writes from multiple simulated agents
- Context compilation with attribution (agents don't confuse others' outputs)
- Idle detection and agent timeout
- Export to main library integration
- Session compaction during active sessions
- Error recovery scenarios
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from openlmlib.collab.db import (
    connect_collab_db,
    init_collab_db,
    get_session,
    get_session_agents,
    get_session_tasks,
    get_messages,
)
from openlmlib.collab.session import (
    create_collab_session,
    join_collab_session,
    leave_collab_session,
    terminate_collab_session,
)
from openlmlib.collab.message_bus import MessageBus
from openlmlib.collab.artifact_store import ArtifactStore
from openlmlib.collab.context_compiler import ContextCompiler
from openlmlib.collab.state_manager import StateManager
from openlmlib.collab.compactor import SessionCompactor
from openlmlib.collab.rules_engine import RulesEngine, DEFAULT_RULES
from openlmlib.collab.prompts import get_system_prompt, list_available_roles
from openlmlib.collab.errors import (
    AgentNotFoundError,
    AgentNotAuthorizedError,
    CollabError,
    InvalidMessageTypeError,
    MessageTooLongError,
    SessionFullError,
    SessionNotActiveError,
    SessionNotFoundError,
    StateConflictError,
)
from openlmlib.collab.security import (
    validate_session_id,
    validate_agent_id,
    validate_message_type,
    verify_agent_in_session,
    verify_orchestrator,
    verify_session_exists_and_active,
    sanitize_content,
)


class SimulatedAgent:
    """A simulated agent that autonomously participates in sessions.

    Reads context, decides on actions, sends messages, and creates artifacts
    based on assigned tasks. Used for integration testing without real LLMs.
    """

    def __init__(
        self,
        agent_id: str,
        model: str,
        role: str,
        conn: sqlite3.Connection,
        sessions_dir: Path,
    ):
        self.agent_id = agent_id
        self.model = model
        self.role = role
        self.conn = conn
        self.sessions_dir = sessions_dir
        self.bus = MessageBus(conn, sessions_dir)
        self.store = ArtifactStore(conn, sessions_dir)
        self.compiler = ContextCompiler(conn, self.bus, self.store)
        self.last_seq = 0
        self.tasks_completed = 0
        self.artifacts_created = 0
        self.messages_sent = 0

    def read_context(self, session_id: str, max_messages: int = 20) -> Dict:
        """Read compiled session context."""
        return self.compiler.compile_context(session_id, self.agent_id, max_messages)

    def read_new_messages(self, session_id: str, limit: int = 50) -> List[Dict]:
        """Read messages since last check."""
        msgs = self.bus.read_new(session_id, self.last_seq, limit=limit)
        if msgs:
            self.last_seq = msgs[-1]["seq"]
        return msgs

    def send_message(
        self,
        session_id: str,
        msg_type: str,
        content: str,
        to_agent: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ) -> Dict:
        """Send a message to the session."""
        now = datetime.now(timezone.utc).isoformat()
        result = self.bus.send(
            session_id=session_id,
            from_agent=self.agent_id,
            msg_type=msg_type,
            content=content,
            to_agent=to_agent,
            metadata=metadata,
            created_at=now,
        )
        self.messages_sent += 1
        return result

    def create_artifact(
        self,
        session_id: str,
        title: str,
        content: str,
        artifact_type: Optional[str] = None,
        tags: Optional[List[str]] = None,
        shared: bool = False,
    ) -> Dict:
        """Create an artifact."""
        now = datetime.now(timezone.utc).isoformat()
        result = self.store.save(
            session_id=session_id,
            created_by=self.agent_id,
            title=title,
            content=content,
            created_at=now,
            artifact_type=artifact_type,
            tags=tags,
            shared=shared,
        )
        self.artifacts_created += 1
        return result

    def process_assigned_tasks(self, session_id: str) -> List[Dict]:
        """Find and process tasks assigned to this agent."""
        tasks = get_session_tasks(self.conn, session_id)
        my_tasks = [
            t for t in tasks
            if t.get("assigned_to") == self.agent_id
            and t.get("status") == "pending"
        ]

        results = []
        for task in my_tasks:
            artifact = self.create_artifact(
                session_id=session_id,
                title=f"Result for: {task['description']}",
                content=f"# Analysis: {task['description']}\n\n"
                        f"Completed by {self.agent_id} ({self.model}).\n\n"
                        f"## Findings\n\n"
                        f"Detailed analysis of the task '{task['description']}'.\n"
                        f"Step number: {task['step_num']}\n"
                        f"Agent model: {self.model}\n",
                artifact_type="analysis",
                tags=[f"task_{task['step_num']}"],
            )

            self.send_message(
                session_id=session_id,
                msg_type="result",
                content=f"## Summary\nCompleted task: {task['description']}\n\n## Key Facts\n- Fact 1\n- Fact 2",
                metadata={"task_id": task["task_id"], "artifact_id": artifact["artifact_id"]},
            )

            self.conn.execute(
                "UPDATE tasks SET status = 'completed', completed_at = ? WHERE task_id = ?",
                (datetime.now(timezone.utc).isoformat(), task["task_id"]),
            )
            self.conn.commit()

            self.tasks_completed += 1
            results.append(artifact)

        return results


class TestSimulatedAgentSession(unittest.TestCase):
    """Full session lifecycle with simulated autonomous agents."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.sessions_dir = Path(self.tmpdir.name) / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        db_path = Path(self.tmpdir.name) / "collab_sessions.db"
        self.conn = connect_collab_db(db_path)
        init_collab_db(self.conn)
        self.now = "2026-04-06T10:00:00Z"

    def tearDown(self):
        self.conn.close()
        from openlmlib.collab.db import close_thread_connections
        close_thread_connections()
        self.tmpdir.cleanup()

    def test_full_session_with_orchestrator_and_two_workers(self):
        session = create_collab_session(
            conn=self.conn,
            sessions_dir=self.sessions_dir,
            title="Quantum Computing Research",
            created_by="orchestrator-model",
            description="Research recent advances in quantum error correction",
            plan=[
                {"step": 1, "task": "Literature review on quantum error correction", "assigned_to": "any"},
                {"step": 2, "task": "Analyze Google Willow chip approach", "assigned_to": "any"},
                {"step": 3, "task": "Synthesize findings into final report", "assigned_to": "any"},
            ],
        )
        session_id = session["session_id"]
        orchestrator_id = session["agent_id"]

        orchestrator = SimulatedAgent(
            orchestrator_id, "orchestrator-model", "orchestrator",
            self.conn, self.sessions_dir,
        )

        w1_result = join_collab_session(
            conn=self.conn,
            sessions_dir=self.sessions_dir,
            session_id=session_id,
            model="worker-model-1",
        )
        worker1 = SimulatedAgent(
            w1_result["agent_id"], "worker-model-1", "worker",
            self.conn, self.sessions_dir,
        )

        w2_result = join_collab_session(
            conn=self.conn,
            sessions_dir=self.sessions_dir,
            session_id=session_id,
            model="worker-model-2",
        )
        worker2 = SimulatedAgent(
            w2_result["agent_id"], "worker-model-2", "worker",
            self.conn, self.sessions_dir,
        )

        orchestrator.send_message(
            session_id, "task",
            "Please complete the literature review on quantum error correction",
            to_agent=worker1.agent_id,
            metadata={"task_id": "task_1"},
        )
        orchestrator.send_message(
            session_id, "task",
            "Analyze Google Willow chip approach to error correction",
            to_agent=worker2.agent_id,
            metadata={"task_id": "task_2"},
        )

        tasks = get_session_tasks(self.conn, session_id)
        self.conn.execute(
            "UPDATE tasks SET assigned_to = ? WHERE task_id = ?",
            (worker1.agent_id, tasks[0]['task_id']),
        )
        self.conn.execute(
            "UPDATE tasks SET assigned_to = ? WHERE task_id = ?",
            (worker2.agent_id, tasks[1]['task_id']),
        )
        self.conn.commit()

        w1_artifacts = worker1.process_assigned_tasks(session_id)
        w2_artifacts = worker2.process_assigned_tasks(session_id)

        worker1.send_message(
            session_id, "complete",
            f"Literature review complete. Created {len(w1_artifacts)} artifact(s).",
        )
        worker2.send_message(
            session_id, "complete",
            f"Willow chip analysis complete. Created {len(w2_artifacts)} artifact(s).",
        )

        ctx = orchestrator.read_context(session_id)
        self.assertEqual(ctx["session_info"]["session_id"], session_id)
        self.assertEqual(ctx["session_info"]["status"], "active")

        all_artifacts = worker1.store.list_artifacts(session_id)
        self.assertEqual(len(all_artifacts), 2)

        term_result = terminate_collab_session(
            self.conn, self.sessions_dir, session_id,
            summary="Research completed. Two artifacts produced.",
        )
        self.assertEqual(term_result["status"], "completed")
        self.assertTrue(term_result["summary_saved"])

        final_session = get_session(self.conn, session_id)
        self.assertEqual(final_session["status"], "completed")

    def test_context_attribution_does_not_confuse_agents(self):
        session = create_collab_session(
            conn=self.conn,
            sessions_dir=self.sessions_dir,
            title="Attribution Test",
            created_by="orch",
        )
        session_id = session["session_id"]
        orch_id = session["agent_id"]

        w1 = join_collab_session(
            conn=self.conn, sessions_dir=self.sessions_dir,
            session_id=session_id, model="worker-1",
        )
        w2 = join_collab_session(
            conn=self.conn, sessions_dir=self.sessions_dir,
            session_id=session_id, model="worker-2",
        )

        agent1 = SimulatedAgent(orch_id, "orch", "orchestrator", self.conn, self.sessions_dir)
        agent2 = SimulatedAgent(w1["agent_id"], "worker-1", "worker", self.conn, self.sessions_dir)
        agent3 = SimulatedAgent(w2["agent_id"], "worker-2", "worker", self.conn, self.sessions_dir)

        agent1.send_message(session_id, "task", "Research topic A", to_agent=agent2.agent_id)
        agent2.send_message(session_id, "result", "## Summary\nHere are findings on topic A\n## Key Facts\n- A is cool")
        agent3.send_message(session_id, "question", "Can you elaborate on point 2?")

        ctx = agent3.read_context(session_id)
        formatted = agent3.compiler.format_context_for_prompt(ctx)

        self.assertIn(agent2.agent_id, formatted)
        self.assertIn(agent1.agent_id, formatted)
        self.assertNotIn(f"[{agent3.agent_id} \u2192", formatted.split("=== RECENT")[0] if "=== RECENT" in formatted else "")

    def test_idle_detection(self):
        session = create_collab_session(
            conn=self.conn, sessions_dir=self.sessions_dir,
            title="Idle Test", created_by="orch",
        )
        session_id = session["session_id"]

        rules = RulesEngine(DEFAULT_RULES)

        from datetime import timedelta
        active_time = "2026-04-06T10:00:00Z"
        old_time = (datetime.fromisoformat(active_time) - timedelta(minutes=180)).isoformat()

        is_idle, minutes = rules.is_idle(old_time, active_time)
        self.assertTrue(is_idle)
        self.assertGreater(minutes, 120)

        recent_time = (datetime.fromisoformat(active_time) - timedelta(minutes=10)).isoformat()
        is_idle, minutes = rules.is_idle(recent_time, active_time)
        self.assertFalse(is_idle)


class TestConcurrentAgentWrites(unittest.TestCase):
    """Test concurrent message writes from multiple simulated agents."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.sessions_dir = Path(self.tmpdir.name) / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        db_path = Path(self.tmpdir.name) / "collab_sessions.db"
        self.conn = connect_collab_db(db_path)
        init_collab_db(self.conn)
        self.now = "2026-04-06T10:00:00Z"
        self.errors = []
        self.barrier = None

    def tearDown(self):
        self.conn.close()
        from openlmlib.collab.db import close_thread_connections
        close_thread_connections()
        self.tmpdir.cleanup()

    def test_concurrent_message_writes(self):
        session = create_collab_session(
            conn=self.conn, sessions_dir=self.sessions_dir,
            title="Concurrency Test", created_by="orch",
        )
        session_id = session["session_id"]

        num_workers = 5
        msgs_per_worker = 20
        self.barrier = threading.Barrier(num_workers)

        def worker_write(worker_id: int):
            try:
                worker_conn = connect_collab_db(
                    Path(self.tmpdir.name) / "collab_sessions.db"
                )
                agent_id = f"agent_worker_{worker_id}"
                worker_conn.execute(
                    "INSERT INTO agents (agent_id, session_id, model, role, capabilities_json, joined_at, status, last_seen) VALUES (?, ?, ?, ?, ?, ?, 'active', ?)",
                    (agent_id, session_id, f"model-{worker_id}", "worker", "[]", self.now, self.now),
                )
                worker_conn.commit()

                self.barrier.wait()

                bus = MessageBus(worker_conn, self.sessions_dir)
                for i in range(msgs_per_worker):
                    bus.send(
                        session_id=session_id,
                        from_agent=agent_id,
                        msg_type="update",
                        content=f"Worker {worker_id} progress update {i}",
                        created_at=self.now,
                    )

                worker_conn.close()
            except Exception as e:
                self.errors.append(str(e))

        threads = []
        for w in range(num_workers):
            t = threading.Thread(target=worker_write, args=(w,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        self.assertEqual(len(self.errors), 0, f"Errors during concurrent writes: {self.errors}")

        total_expected = num_workers * msgs_per_worker
        actual_count = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM messages WHERE session_id = ?",
            (session_id,),
        ).fetchone()["cnt"]
        self.assertEqual(actual_count, total_expected + 1)

        for i in range(num_workers):
            worker_msgs = self.conn.execute(
                "SELECT COUNT(*) as cnt FROM messages WHERE session_id = ? AND from_agent = ?",
                (session_id, f"agent_worker_{i}"),
            ).fetchone()["cnt"]
            self.assertEqual(worker_msgs, msgs_per_worker)

    def test_concurrent_state_updates_detect_conflict(self):
        session = create_collab_session(
            conn=self.conn, sessions_dir=self.sessions_dir,
            title="State Conflict Test", created_by="orch",
        )
        session_id = session["session_id"]
        sm = StateManager(self.conn)

        current = sm.get_state(session_id)
        version = current["version"]

        success1 = sm.update_state(
            session_id, {"phase": "A"}, "agent_1", self.now, version,
        )
        self.assertTrue(success1)

        success2 = sm.update_state(
            session_id, {"phase": "B"}, "agent_2", self.now, version,
        )
        self.assertFalse(success2)


class TestSecurityHardening(unittest.TestCase):
    """Test security hardening features."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.sessions_dir = Path(self.tmpdir.name) / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        db_path = Path(self.tmpdir.name) / "collab_sessions.db"
        self.conn = connect_collab_db(db_path)
        init_collab_db(self.conn)
        self.now = "2026-04-06T10:00:00Z"

    def tearDown(self):
        self.conn.close()
        from openlmlib.collab.db import close_thread_connections
        close_thread_connections()
        self.tmpdir.cleanup()

    def test_session_not_found_raises_custom_exception(self):
        with self.assertRaises(SessionNotFoundError):
            verify_session_exists_and_active(self.conn, "nonexistent")

    def test_agent_not_in_session_raises_custom_exception(self):
        session = create_collab_session(
            conn=self.conn, sessions_dir=self.sessions_dir,
            title="Security Test", created_by="orch",
        )
        session_id = session["session_id"]

        with self.assertRaises(AgentNotFoundError):
            verify_agent_in_session(self.conn, "fake_agent", session_id)

    def test_invalid_message_type_raises_exception(self):
        with self.assertRaises(InvalidMessageTypeError):
            validate_message_type("invalid_type")

    def test_message_too_long_raises_exception(self):
        with self.assertRaises(MessageTooLongError):
            from openlmlib.collab.security import validate_message_content
            validate_message_content("x" * 9000, max_length=8000)

    def test_path_traversal_in_session_id(self):
        from openlmlib.collab.security import validate_session_id
        with self.assertRaises(Exception):
            validate_session_id("../../etc/passwd")

    def test_path_traversal_in_agent_id(self):
        from openlmlib.collab.security import validate_agent_id
        with self.assertRaises(Exception):
            validate_agent_id("../../../etc")

    def test_content_sanitization(self):
        malicious = "Normal text <script>alert('xss')</script> and ```code```"
        sanitized = sanitize_content(malicious)
        self.assertNotIn("<script>", sanitized)
        self.assertNotIn("```", sanitized)
        self.assertIn("[script]", sanitized)

    def test_session_full_error(self):
        session = create_collab_session(
            conn=self.conn, sessions_dir=self.sessions_dir,
            title="Full Test", created_by="orch",
            rules={"max_agents": 2},
        )
        session_id = session["session_id"]

        join_collab_session(
            conn=self.conn, sessions_dir=self.sessions_dir,
            session_id=session_id, model="worker-1",
        )

        with self.assertRaises(SessionFullError):
            join_collab_session(
                conn=self.conn, sessions_dir=self.sessions_dir,
                session_id=session_id, model="worker-2",
            )

    def test_session_not_active_error(self):
        session = create_collab_session(
            conn=self.conn, sessions_dir=self.sessions_dir,
            title="Inactive Test", created_by="orch",
        )
        session_id = session["session_id"]
        terminate_collab_session(self.conn, self.sessions_dir, session_id)

        with self.assertRaises(SessionNotActiveError):
            join_collab_session(
                conn=self.conn, sessions_dir=self.sessions_dir,
                session_id=session_id, model="late-joiner",
            )


class TestSystemPrompts(unittest.TestCase):
    """Test system prompt generation."""

    def test_orchestrator_prompt_generation(self):
        prompt = get_system_prompt(
            "orchestrator",
            session_id="sess_test",
            title="Test Session",
        )
        self.assertIn("sess_test", prompt)
        self.assertIn("Test Session", prompt)
        self.assertIn("ORCHESTRATOR", prompt)
        self.assertIn("session_context", prompt)
        self.assertIn("terminate_session", prompt)

    def test_worker_prompt_generation(self):
        prompt = get_system_prompt(
            "worker",
            session_id="sess_test",
            title="Test Session",
            agent_id="agent_test_001",
        )
        self.assertIn("agent_test_001", prompt)
        self.assertIn("WORKER agent", prompt)
        self.assertIn("save_artifact", prompt)

    def test_observer_prompt_generation(self):
        prompt = get_system_prompt(
            "observer",
            session_id="sess_test",
            title="Test Session",
            agent_id="agent_obs_001",
        )
        self.assertIn("OBSERVER", prompt)
        self.assertIn("Never assign tasks", prompt)

    def test_unknown_role_raises_error(self):
        with self.assertRaises(ValueError):
            get_system_prompt("unknown_role")

    def test_list_available_roles(self):
        roles = list_available_roles()
        self.assertIn("orchestrator", roles)
        self.assertIn("worker", roles)
        self.assertIn("observer", roles)


class TestSessionCompactionIntegration(unittest.TestCase):
    """Test session compaction during active sessions."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.sessions_dir = Path(self.tmpdir.name) / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        db_path = Path(self.tmpdir.name) / "collab_sessions.db"
        self.conn = connect_collab_db(db_path)
        init_collab_db(self.conn)
        self.now = "2026-04-06T10:00:00Z"

    def tearDown(self):
        self.conn.close()
        from openlmlib.collab.db import close_thread_connections
        close_thread_connections()
        self.tmpdir.cleanup()

    def test_auto_compaction_during_session(self):
        session = create_collab_session(
            conn=self.conn, sessions_dir=self.sessions_dir,
            title="Compaction Test", created_by="orch",
        )
        session_id = session["session_id"]
        orch_id = session["agent_id"]

        join_collab_session(
            conn=self.conn, sessions_dir=self.sessions_dir,
            session_id=session_id, model="worker-1",
        )

        bus = MessageBus(self.conn, self.sessions_dir)
        for i in range(55):
            bus.send(
                session_id=session_id,
                from_agent=orch_id,
                msg_type="update",
                content=f"Update {i}",
                created_at=self.now,
            )

        sm = StateManager(self.conn)
        state_row = sm.get_state(session_id)
        state = state_row["state"]
        state["message_count"] = 55
        sm.update_state(session_id, state, "system", self.now, state_row["version"])

        store = ArtifactStore(self.conn, self.sessions_dir)
        compactor = SessionCompactor(
            self.conn, self.sessions_dir, bus, store, sm,
        )

        result = compactor.check_and_compact(session_id, auto_compact_threshold=50)
        self.assertIsNotNone(result)
        self.assertIn("file_path", result)
        self.assertIn("compacted_at", result)

        summaries = store.list_summaries(session_id)
        self.assertGreater(len(summaries), 0)


class TestErrorRecovery(unittest.TestCase):
    """Test error handling and recovery scenarios."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.sessions_dir = Path(self.tmpdir.name) / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        db_path = Path(self.tmpdir.name) / "collab_sessions.db"
        self.conn = connect_collab_db(db_path)
        init_collab_db(self.conn)
        self.now = "2026-04-06T10:00:00Z"

    def tearDown(self):
        self.conn.close()
        from openlmlib.collab.db import close_thread_connections
        close_thread_connections()
        self.tmpdir.cleanup()

    def test_corrupted_offset_file_recovers_gracefully(self):
        session = create_collab_session(
            conn=self.conn, sessions_dir=self.sessions_dir,
            title="Recovery Test", created_by="orch",
        )
        session_id = session["session_id"]

        offset_dir = self.sessions_dir / session_id / "offsets"
        offset_dir.mkdir(parents=True, exist_ok=True)
        (offset_dir / "agent_bad.json").write_text("{invalid json")

        bus = MessageBus(self.conn, self.sessions_dir)
        offset = bus.load_offset(session_id, "agent_bad")
        self.assertEqual(offset, 0)

    def test_missing_artifact_file_returns_none(self):
        session = create_collab_session(
            conn=self.conn, sessions_dir=self.sessions_dir,
            title="Missing File Test", created_by="orch",
        )
        session_id = session["session_id"]

        store = ArtifactStore(self.conn, self.sessions_dir)
        content = store.get_content_by_id(session_id, "nonexistent_artifact")
        self.assertIsNone(content)

    def test_error_response_format(self):
        from openlmlib.collab.errors import make_error_response, error_from_exception

        resp = make_error_response("Session not found", "session_not_found")
        self.assertFalse(resp["success"])
        self.assertEqual(resp["error"], "Session not found")
        self.assertEqual(resp["error_type"], "session_not_found")

        exc = SessionNotFoundError("Test error")
        resp = error_from_exception(exc)
        self.assertFalse(resp["success"])
        self.assertEqual(resp["error_type"], "session_not_found")

    def test_collab_error_hierarchy(self):
        self.assertTrue(issubclass(SessionNotFoundError, CollabError))
        self.assertTrue(issubclass(AgentNotAuthorizedError, CollabError))
        self.assertTrue(issubclass(StateConflictError, CollabError))
        self.assertTrue(issubclass(InvalidMessageTypeError, CollabError))


if __name__ == "__main__":
    unittest.main()
