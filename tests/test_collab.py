"""Tests for CollabSessions core operations."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openlmlib.collab.db import (
    connect_collab_db,
    init_collab_db,
    create_session,
    get_session,
    list_sessions,
    update_session_status,
    insert_agent,
    get_session_agents,
    insert_message,
    get_messages,
    get_messages_since,
    get_messages_tail,
    get_message_range,
    grep_messages,
    get_max_seq,
    insert_task,
    update_task_status,
    complete_tasks_for_artifact_type,
    get_session_tasks,
    insert_artifact,
    get_session_artifacts,
    get_session_state,
    update_session_state,
)
from openlmlib.collab.message_bus import MessageBus
from openlmlib.collab.artifact_store import ArtifactStore
from openlmlib.collab.state_manager import StateManager
from openlmlib.collab.context_compiler import ContextCompiler
from openlmlib.collab.session import (
    create_collab_session,
    join_collab_session,
    leave_collab_session,
    terminate_collab_session,
)
from openlmlib.collab.errors import SecurityError


class TestCollabDB(unittest.TestCase):
    """Test database CRUD operations."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test_collab.db"
        self.conn = connect_collab_db(self.db_path)
        init_collab_db(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_create_and_get_session(self):
        result = create_session(
            self.conn,
            session_id="sess_test_001",
            title="Test Session",
            created_by="test-llm",
            created_at="2026-04-05T10:00:00Z",
            description="A test session",
        )
        self.assertEqual(result["session_id"], "sess_test_001")
        self.assertEqual(result["status"], "active")

        session = get_session(self.conn, "sess_test_001")
        self.assertIsNotNone(session)
        self.assertEqual(session["title"], "Test Session")

    def test_list_sessions(self):
        for i in range(3):
            create_session(
                self.conn,
                session_id=f"sess_{i}",
                title=f"Session {i}",
                created_by="test",
                created_at=f"2026-04-05T10:0{i}:00Z",
            )

        sessions = list_sessions(self.conn)
        self.assertEqual(len(sessions), 3)

        active = list_sessions(self.conn, status="active")
        self.assertEqual(len(active), 3)

    def test_update_session_status(self):
        create_session(
            self.conn,
            session_id="sess_001",
            title="Test",
            created_by="test",
            created_at="2026-04-05T10:00:00Z",
        )
        ok = update_session_status(
            self.conn, "sess_001", "completed", "2026-04-05T11:00:00Z"
        )
        self.assertTrue(ok)
        session = get_session(self.conn, "sess_001")
        self.assertEqual(session["status"], "completed")

    def test_agent_crud(self):
        create_session(
            self.conn,
            session_id="sess_001",
            title="Test",
            created_by="test",
            created_at="2026-04-05T10:00:00Z",
        )
        insert_agent(
            self.conn,
            agent_id="agent_001",
            session_id="sess_001",
            model="gpt-4",
            role="worker",
            joined_at="2026-04-05T10:01:00Z",
            capabilities=["research"],
        )
        agents = get_session_agents(self.conn, "sess_001")
        self.assertEqual(len(agents), 1)
        self.assertEqual(agents[0]["model"], "gpt-4")
        self.assertEqual(agents[0]["capabilities"], ["research"])

    def test_message_append_and_read(self):
        create_session(
            self.conn,
            session_id="sess_001",
            title="Test",
            created_by="test",
            created_at="2026-04-05T10:00:00Z",
        )
        for i in range(5):
            insert_message(
                self.conn,
                msg_id=f"msg_{i}",
                session_id="sess_001",
                seq=i + 1,
                from_agent="agent_001",
                msg_type="task" if i == 0 else "result",
                content=f"Message {i}",
                created_at=f"2026-04-05T10:0{i}:00Z",
            )

        self.assertEqual(get_max_seq(self.conn, "sess_001"), 5)

        msgs = get_messages(self.conn, "sess_001", limit=10)
        self.assertEqual(len(msgs), 5)
        self.assertEqual(msgs[0]["content"], "Message 0")

        msgs = get_messages_tail(self.conn, "sess_001", 2)
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0]["content"], "Message 3")

        msgs = get_messages_since(self.conn, "sess_001", last_seq=3)
        self.assertEqual(len(msgs), 2)

        msgs = get_message_range(self.conn, "sess_001", 2, 4)
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0]["seq"], 2)

    def test_grep_messages(self):
        create_session(
            self.conn,
            session_id="sess_001",
            title="Test",
            created_by="test",
            created_at="2026-04-05T10:00:00Z",
        )
        insert_message(
            self.conn,
            msg_id="msg_001",
            session_id="sess_001",
            seq=1,
            from_agent="agent_001",
            msg_type="result",
            content="Found quantum computing papers on error correction",
            created_at="2026-04-05T10:01:00Z",
        )
        insert_message(
            self.conn,
            msg_id="msg_002",
            session_id="sess_001",
            seq=2,
            from_agent="agent_002",
            msg_type="result",
            content="Analyzed market trends in AI",
            created_at="2026-04-05T10:02:00Z",
        )

        results = grep_messages(self.conn, "sess_001", "quantum")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["msg_id"], "msg_001")

        hyphen_results = grep_messages(self.conn, "sess_001", "error-correction")
        self.assertEqual(len(hyphen_results), 1)
        self.assertEqual(hyphen_results[0]["msg_id"], "msg_001")

        self.assertEqual(grep_messages(self.conn, "sess_001", "!!!"), [])

    def test_task_crud(self):
        create_session(
            self.conn,
            session_id="sess_001",
            title="Test",
            created_by="test",
            created_at="2026-04-05T10:00:00Z",
        )
        insert_task(
            self.conn,
            task_id="task_001",
            session_id="sess_001",
            step_num=1,
            description="Research task",
            created_at="2026-04-05T10:00:00Z",
            assigned_to="agent_001",
        )
        tasks = get_session_tasks(self.conn, "sess_001")
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["status"], "pending")

        update_task_status(
            self.conn, "task_001", "in_progress",
            started_at="2026-04-05T10:01:00Z",
        )
        tasks = get_session_tasks(self.conn, "sess_001", status="in_progress")
        self.assertEqual(len(tasks), 1)

    def test_complete_tasks_for_artifact_type(self):
        create_session(
            self.conn,
            session_id="sess_001",
            title="Test",
            created_by="test",
            created_at="2026-04-05T10:00:00Z",
        )
        insert_task(
            self.conn,
            task_id="task_001",
            session_id="sess_001",
            step_num=1,
            description="Save artifact_type `evidence_verification` with citations.",
            created_at="2026-04-05T10:00:00Z",
            assigned_to="any",
        )
        insert_task(
            self.conn,
            task_id="task_002",
            session_id="sess_001",
            step_num=2,
            description="Unrelated analysis task.",
            created_at="2026-04-05T10:00:00Z",
            assigned_to="any",
        )

        completed = complete_tasks_for_artifact_type(
            self.conn,
            "sess_001",
            "evidence_verification",
            "2026-04-05T10:10:00Z",
            completed_by="agent_001",
        )
        tasks = get_session_tasks(self.conn, "sess_001")
        statuses = {task["task_id"]: task["status"] for task in tasks}

        self.assertEqual([task["task_id"] for task in completed], ["task_001"])
        self.assertEqual(statuses["task_001"], "completed")
        self.assertEqual(statuses["task_002"], "pending")
        self.assertEqual(tasks[0]["assigned_to"], "agent_001")

    def test_artifact_crud(self):
        create_session(
            self.conn,
            session_id="sess_001",
            title="Test",
            created_by="test",
            created_at="2026-04-05T10:00:00Z",
        )
        insert_artifact(
            self.conn,
            artifact_id="art_001",
            session_id="sess_001",
            created_by="agent_001",
            title="Research Summary",
            file_path="/path/to/art_001.md",
            created_at="2026-04-05T10:01:00Z",
            artifact_type="research_summary",
            tags=["quantum", "research"],
            word_count=500,
        )
        artifacts = get_session_artifacts(self.conn, "sess_001")
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0]["tags"], ["quantum", "research"])

    def test_session_state_versioning(self):
        create_session(
            self.conn,
            session_id="sess_001",
            title="Test",
            created_by="test",
            created_at="2026-04-05T10:00:00Z",
        )
        state = get_session_state(self.conn, "sess_001")
        self.assertIsNotNone(state)
        self.assertEqual(state["version"], 1)

        ok = update_session_state(
            self.conn,
            session_id="sess_001",
            state={"status": "active", "phase": "research"},
            updated_by="test",
            updated_at="2026-04-05T10:01:00Z",
            expected_version=1,
        )
        self.assertTrue(ok)

        state = get_session_state(self.conn, "sess_001")
        self.assertEqual(state["version"], 2)

        ok = update_session_state(
            self.conn,
            session_id="sess_001",
            state={"status": "active", "phase": "research"},
            updated_by="test",
            updated_at="2026-04-05T10:02:00Z",
            expected_version=1,
        )
        self.assertFalse(ok)


class TestMessageBus(unittest.TestCase):
    """Test message bus with JSONL shadow logging."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sessions_dir = Path(self.tmp.name) / "sessions"
        self.sessions_dir.mkdir(parents=True)
        self.db_path = Path(self.tmp.name) / "test.db"
        self.conn = connect_collab_db(self.db_path)
        init_collab_db(self.conn)
        self.bus = MessageBus(self.conn, self.sessions_dir)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_send_and_read(self):
        create_session(
            self.conn,
            session_id="sess_001",
            title="Test",
            created_by="test",
            created_at="2026-04-05T10:00:00Z",
        )
        self.bus.send(
            session_id="sess_001",
            from_agent="agent_001",
            msg_type="task",
            content="Research quantum computing",
            created_at="2026-04-05T10:01:00Z",
        )
        self.bus.send(
            session_id="sess_001",
            from_agent="agent_002",
            msg_type="result",
            content="## Summary\nFound 5 papers\n\n## Key Facts\nNone",
            created_at="2026-04-05T10:02:00Z",
        )

        msgs = self.bus.read_new("sess_001", last_seq=0)
        self.assertEqual(len(msgs), 2)
        state = get_session_state(self.conn, "sess_001")
        self.assertEqual(state["state"]["message_count"], 2)

    def test_jsonl_shadow_log(self):
        create_session(
            self.conn,
            session_id="sess_001",
            title="Test",
            created_by="test",
            created_at="2026-04-05T10:00:00Z",
        )
        self.bus.send(
            session_id="sess_001",
            from_agent="agent_001",
            msg_type="task",
            content="Test message",
            created_at="2026-04-05T10:01:00Z",
        )

        jsonl_path = self.sessions_dir / "sess_001" / "messages.jsonl"
        self.assertTrue(jsonl_path.exists())
        lines = jsonl_path.read_text().strip().split("\n")
        self.assertEqual(len(lines), 1)
        entry = json.loads(lines[0])
        self.assertEqual(entry["content"], "Test message")

    def test_offset_tracking(self):
        create_session(
            self.conn,
            session_id="sess_001",
            title="Test",
            created_by="test",
            created_at="2026-04-05T10:00:00Z",
        )
        for i in range(5):
            self.bus.send(
                session_id="sess_001",
                from_agent="agent_001",
                msg_type="update",
                content=f"Update {i}",
                created_at=f"2026-04-05T10:0{i}:00Z",
            )

        self.bus.save_offset("sess_001", "agent_002", 3)
        offset = self.bus.load_offset("sess_001", "agent_002")
        self.assertEqual(offset, 3)

        msgs = self.bus.read_new("sess_001", last_seq=3)
        self.assertEqual(len(msgs), 2)

    def test_send_enforces_session_rules_without_mcp(self):
        from openlmlib.collab.errors import RulesViolationError

        create_session(
            self.conn,
            session_id="sess_rules",
            title="Rules",
            created_by="test",
            created_at="2026-04-05T10:00:00Z",
            rules={"require_artifact_for_results": True, "require_assignment": True},
        )
        with self.assertRaises(RulesViolationError):
            self.bus.send(
                session_id="sess_rules",
                from_agent="agent_001",
                msg_type="result",
                content="## Summary\nNo artifact\n## Key Facts\n- x",
                created_at="2026-04-05T10:01:00Z",
            )
        with self.assertRaises(RulesViolationError):
            self.bus.send(
                session_id="sess_rules",
                from_agent="agent_001",
                msg_type="task",
                content="No target",
                created_at="2026-04-05T10:02:00Z",
                to_agent=None,
            )
        ok = self.bus.send(
            session_id="sess_rules",
            from_agent="agent_001",
            msg_type="task",
            content="Open task",
            created_at="2026-04-05T10:03:00Z",
            to_agent="any",
        )
        self.assertEqual(ok["to_agent"], "any")

    def test_tail_and_grep(self):
        create_session(
            self.conn,
            session_id="sess_001",
            title="Test",
            created_by="test",
            created_at="2026-04-05T10:00:00Z",
        )
        self.bus.send(
            session_id="sess_001",
            from_agent="agent_001",
            msg_type="result",
            content="## Summary\nQuantum error correction advances\n## Key Facts\n- fact 1",
            created_at="2026-04-05T10:01:00Z",
        )
        self.bus.send(
            session_id="sess_001",
            from_agent="agent_001",
            msg_type="result",
            content="## Summary\nMarket analysis report\n## Key Facts\n- fact 2",
            created_at="2026-04-05T10:02:00Z",
        )

        tail = self.bus.tail("sess_001", 1)
        self.assertEqual(len(tail), 1)
        self.assertIn("Market analysis report", tail[0]["content"])

        grep = self.bus.grep("sess_001", "quantum")
        self.assertEqual(len(grep), 1)


class TestArtifactStore(unittest.TestCase):
    """Test file-based artifact storage."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sessions_dir = Path(self.tmp.name) / "sessions"
        self.sessions_dir.mkdir(parents=True)
        self.db_path = Path(self.tmp.name) / "test.db"
        self.conn = connect_collab_db(self.db_path)
        init_collab_db(self.conn)
        self.store = ArtifactStore(self.conn, self.sessions_dir)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_save_and_retrieve(self):
        create_session(
            self.conn,
            session_id="sess_001",
            title="Test",
            created_by="test",
            created_at="2026-04-05T10:00:00Z",
        )
        result = self.store.save(
            session_id="sess_001",
            created_by="agent_001",
            title="Research Summary",
            content="# Quantum Computing Research\n\nKey findings...",
            created_at="2026-04-05T10:01:00Z",
            artifact_type="research_summary",
            tags=["quantum"],
        )

        self.assertIsNotNone(result["artifact_id"])
        self.assertGreater(result["word_count"], 0)

        content = self.store.get_content_by_id("sess_001", result["artifact_id"])
        self.assertIn("Quantum Computing Research", content)
        state = get_session_state(self.conn, "sess_001")
        self.assertEqual(state["state"]["artifact_count"], 1)

    def test_save_rejects_invalid_custom_artifact_id(self):
        create_session(
            self.conn,
            session_id="sess_001",
            title="Test",
            created_by="test",
            created_at="2026-04-05T10:00:00Z",
        )

        with self.assertRaises(SecurityError):
            self.store.save(
                session_id="sess_001",
                created_by="agent_001",
                title="Escaping Artifact",
                content="content",
                created_at="2026-04-05T10:01:00Z",
                artifact_id="../art_abcdef12",
            )

    def test_shared_artifact(self):
        create_session(
            self.conn,
            session_id="sess_001",
            title="Test",
            created_by="test",
            created_at="2026-04-05T10:00:00Z",
        )
        result = self.store.save(
            session_id="sess_001",
            created_by="agent_001",
            title="Shared Analysis",
            content="Shared content",
            created_at="2026-04-05T10:01:00Z",
            shared=True,
        )
        self.assertTrue(result["shared"])
        self.assertIn("shared", result["file_path"])

    def test_grep_artifacts(self):
        create_session(
            self.conn,
            session_id="sess_001",
            title="Test",
            created_by="test",
            created_at="2026-04-05T10:00:00Z",
        )
        self.store.save(
            session_id="sess_001",
            created_by="agent_001",
            title="Quantum Review",
            content="Quantum error correction is advancing rapidly.",
            created_at="2026-04-05T10:01:00Z",
        )
        self.store.save(
            session_id="sess_001",
            created_by="agent_001",
            title="Market Report",
            content="AI market trends show growth.",
            created_at="2026-04-05T10:02:00Z",
        )

        matches = self.store.grep_artifacts("sess_001", "quantum")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["title"], "Quantum Review")

    def test_summary_save(self):
        create_session(
            self.conn,
            session_id="sess_001",
            title="Test",
            created_by="test",
            created_at="2026-04-05T10:00:00Z",
        )
        self.store.save_summary("sess_001", "Session summary text", "2026-04-05T10:05:00Z")
        latest = self.store.get_latest_summary("sess_001")
        self.assertEqual(latest, "Session summary text")


class TestContextCompiler(unittest.TestCase):
    """Test context compilation for agents."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sessions_dir = Path(self.tmp.name) / "sessions"
        self.sessions_dir.mkdir(parents=True)
        self.db_path = Path(self.tmp.name) / "test.db"
        self.conn = connect_collab_db(self.db_path)
        init_collab_db(self.conn)
        self.bus = MessageBus(self.conn, self.sessions_dir)
        self.store = ArtifactStore(self.conn, self.sessions_dir)
        self.compiler = ContextCompiler(self.conn, self.bus, self.store)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_compile_context(self):
        create_session(
            self.conn,
            session_id="sess_001",
            title="Research",
            created_by="opus-4.6",
            created_at="2026-04-05T10:00:00Z",
        )
        insert_task(
            self.conn,
            task_id="task_001",
            session_id="sess_001",
            step_num=1,
            description="Literature review",
            created_at="2026-04-05T10:00:00Z",
            assigned_to="any",
        )
        insert_task(
            self.conn,
            task_id="task_002",
            session_id="sess_001",
            step_num=2,
            description="Analysis",
            created_at="2026-04-05T10:00:00Z",
            assigned_to="agent_codex",
        )
        self.bus.send(
            session_id="sess_001",
            from_agent="agent_opus_001",
            msg_type="task",
            content="Please do literature review",
            created_at="2026-04-05T10:01:00Z",
            to_agent="any",
        )
        self.bus.send(
            session_id="sess_001",
            from_agent="agent_codex",
            msg_type="result",
            content="## Summary\nFound 12 papers on the topic\n\n## Key Facts\n- The topic is hot.",
            created_at="2026-04-05T10:02:00Z",
            to_agent="agent_opus_001",
            metadata={"artifact_refs": ["art_001"]},
        )

        context = self.compiler.compile_context("sess_001", "agent_codex")

        self.assertEqual(context["session_info"]["title"], "Research")
        self.assertEqual(len(context["recent_messages"]), 2)
        self.assertIn("art_001", context["recent_messages"][1])
        self.assertEqual(len(context["my_tasks"]), 1)
        self.assertEqual(context["my_tasks"][0]["description"], "Analysis")

    def test_format_context_for_prompt(self):
        create_session(
            self.conn,
            session_id="sess_001",
            title="Research",
            created_by="opus-4.6",
            created_at="2026-04-05T10:00:00Z",
        )
        self.bus.send(
            session_id="sess_001",
            from_agent="agent_001",
            msg_type="task",
            content="Research quantum computing",
            created_at="2026-04-05T10:01:00Z",
        )
        context = self.compiler.compile_context("sess_001", "agent_001")
        formatted = self.compiler.format_context_for_prompt(context)

        self.assertIn("[Session: Research]", formatted)
        self.assertIn("[agent_001 → all]", formatted)
        self.assertIn("Research quantum computing", formatted)


class TestSessionLifecycle(unittest.TestCase):
    """Test full session lifecycle operations."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sessions_dir = Path(self.tmp.name) / "sessions"
        self.sessions_dir.mkdir(parents=True)
        self.db_path = Path(self.tmp.name) / "test.db"
        self.conn = connect_collab_db(self.db_path)
        init_collab_db(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_full_lifecycle(self):
        result = create_collab_session(
            self.conn, self.sessions_dir,
            title="Quantum Research",
            created_by="opus-4.6",
            description="Research quantum computing advances",
            plan=[
                {"step": 1, "task": "Literature review", "assigned_to": "any"},
                {"step": 2, "task": "Technical analysis", "assigned_to": None},
            ],
        )
        session_id = result["session_id"]
        self.assertIsNotNone(session_id)
        self.assertTrue(session_id.startswith("sess_"))
        session = get_session(self.conn, session_id)
        self.assertEqual(session["orchestrator"], result["agent_id"])

        join_result = join_collab_session(
            self.conn, self.sessions_dir,
            session_id=session_id,
            model="gpt-codex",
            capabilities=["code_analysis"],
        )
        self.assertIsNotNone(join_result["agent_id"])

        agents = get_session_agents(self.conn, session_id)
        self.assertEqual(len(agents), 2)

        session_dir = self.sessions_dir / session_id
        self.assertTrue((session_dir / "artifacts" / "shared").exists())
        self.assertTrue((session_dir / "messages.jsonl").exists())

        leave_collab_session(
            self.conn, self.sessions_dir,
            agent_id=join_result["agent_id"],
            reason="Task complete",
        )
        agents = get_session_agents(self.conn, session_id)
        left_agents = [a for a in agents if a["status"] == "left"]
        self.assertEqual(len(left_agents), 1)

        term_result = terminate_collab_session(
            self.conn, self.sessions_dir,
            session_id=session_id,
            summary="Research completed successfully",
        )
        self.assertEqual(term_result["status"], "terminated")

        session = get_session(self.conn, session_id)
        self.assertEqual(session["status"], "terminated")

    def test_orchestrator_assignments_use_real_agent_id(self):
        result = create_collab_session(
            self.conn, self.sessions_dir,
            title="Template Session",
            created_by="opus-4.6",
            plan=[
                {"step": 1, "task": "Write final synthesis", "assigned_to": "orchestrator"},
            ],
        )
        context = ContextCompiler(
            self.conn,
            MessageBus(self.conn, self.sessions_dir),
            ArtifactStore(self.conn, self.sessions_dir),
        ).compile_context(result["session_id"], result["agent_id"])
        self.assertEqual(len(context["my_tasks"]), 1)
        self.assertEqual(context["my_tasks"][0]["assigned_to"], result["agent_id"])

    def test_join_nonexistent_session(self):
        from openlmlib.collab.errors import SessionNotFoundError
        with self.assertRaises(SessionNotFoundError):
            join_collab_session(
                self.conn, self.sessions_dir,
                session_id="nonexistent",
                model="gpt-4",
            )

    def test_join_completed_session(self):
        result = create_collab_session(
            self.conn, self.sessions_dir,
            title="Test",
            created_by="test",
        )
        terminate_collab_session(
            self.conn, self.sessions_dir,
            session_id=result["session_id"],
        )
        from openlmlib.collab.errors import SessionNotActiveError
        with self.assertRaises(SessionNotActiveError):
            join_collab_session(
                self.conn, self.sessions_dir,
                session_id=result["session_id"],
                model="gpt-4",
            )


class TestRulesEngine(unittest.TestCase):
    """Test session rules engine."""

    def setUp(self):
        from openlmlib.collab.rules_engine import RulesEngine, DEFAULT_RULES
        self.RulesEngine = RulesEngine
        self.DEFAULT_RULES = DEFAULT_RULES

    def test_default_rules(self):
        engine = self.RulesEngine()
        self.assertEqual(engine.rules["max_agents"], 10)
        self.assertEqual(engine.rules["max_message_length"], 8000)

    def test_custom_rules_override(self):
        engine = self.RulesEngine({"max_agents": 5})
        self.assertEqual(engine.rules["max_agents"], 5)
        self.assertEqual(engine.rules["max_message_length"], 8000)

    def test_validate_join(self):
        engine = self.RulesEngine({"max_agents": 3})
        ok, err = engine.validate_join(2)
        self.assertTrue(ok)
        self.assertIsNone(err)

        ok, err = engine.validate_join(3)
        self.assertFalse(ok)
        self.assertIn("full", err)

    def test_validate_message_length(self):
        engine = self.RulesEngine({"max_message_length": 100})
        ok, warnings = engine.validate_message("x" * 50, "task")
        self.assertTrue(ok)

        ok, warnings = engine.validate_message("x" * 200, "task")
        self.assertFalse(ok)
        self.assertTrue(len(warnings) > 0)

    def test_validate_message_artifact_required(self):
        engine = self.RulesEngine({"require_artifact_for_results": True})
        ok, warnings = engine.validate_message("result without artifact", "result")
        self.assertFalse(ok)
        self.assertTrue(len(warnings) > 0)

        ok, warnings = engine.validate_message("result with artifact", "result", has_artifact_ref=True)
        self.assertTrue(ok)
        self.assertEqual(len(warnings), 0)

    def test_validate_task_assignment_require_assignment(self):
        engine = self.RulesEngine({"require_assignment": True})
        ok, err = engine.validate_task_assignment(None, 0)
        self.assertFalse(ok)
        self.assertIn("assignment", err.lower())
        # Open pool "any" is a valid assignment target for claimable work.
        ok, err = engine.validate_task_assignment("any", 0)
        self.assertTrue(ok)
        self.assertIsNone(err)
        ok, err = engine.validate_task_assignment("agent_worker_abc123", 0)
        self.assertTrue(ok)
        self.assertIsNone(err)

    def test_should_compact(self):
        engine = self.RulesEngine({"auto_compact_after_messages": 10})
        self.assertFalse(engine.should_compact(5, 0))
        self.assertTrue(engine.should_compact(15, 0))
        self.assertFalse(engine.should_compact(15, 10))
        self.assertTrue(engine.should_compact(20, 10))

    def test_is_idle(self):
        engine = self.RulesEngine({"auto_archive_after_idle_minutes": 30})
        is_idle, minutes = engine.is_idle(
            "2026-04-05T10:00:00+00:00",
            "2026-04-05T10:20:00+00:00",
        )
        self.assertFalse(is_idle)
        self.assertAlmostEqual(minutes, 20, delta=1)

        is_idle, minutes = engine.is_idle(
            "2026-04-05T10:00:00+00:00",
            "2026-04-05T11:00:00+00:00",
        )
        self.assertTrue(is_idle)
        self.assertAlmostEqual(minutes, 60, delta=1)

    def test_rules_summary(self):
        engine = self.RulesEngine({"max_agents": 5})
        summary = engine.get_rules_summary()
        self.assertIn("max_agents: 5 (custom)", summary)
        self.assertIn("max_message_length: 8000", summary)


class TestSessionCompactor(unittest.TestCase):
    """Test session summarization and compaction."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sessions_dir = Path(self.tmp.name) / "sessions"
        self.sessions_dir.mkdir(parents=True)
        self.db_path = Path(self.tmp.name) / "test.db"
        self.conn = connect_collab_db(self.db_path)
        init_collab_db(self.conn)
        self.bus = MessageBus(self.conn, self.sessions_dir)
        self.store = ArtifactStore(self.conn, self.sessions_dir)
        self.sm = StateManager(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def _make_session(self):
        create_session(
            self.conn,
            session_id="sess_001",
            title="Research",
            created_by="opus-4.6",
            created_at="2026-04-05T10:00:00Z",
        )
        for i in range(5):
            self.bus.send(
                session_id="sess_001",
                from_agent="agent_001",
                msg_type="task" if i == 0 else "result",
                content=f"Message {i}: Start research" if i == 0 else f"## Summary\nFound {i * 3} papers\n## Key Facts\n- fact {i}",
                created_at=f"2026-04-05T10:0{i}:00Z",
            )

    def test_generate_summary(self):
        from openlmlib.collab.compactor import SessionCompactor
        self._make_session()
        compactor = SessionCompactor(self.conn, self.sessions_dir, self.bus, self.store, self.sm)
        summary = compactor.generate_summary("sess_001")
        self.assertIsNotNone(summary)
        self.assertIn("Session Overview", summary)
        self.assertIn("Message types:", summary)
        self.assertIn("Activity by agent:", summary)

    def test_compact_session(self):
        from openlmlib.collab.compactor import SessionCompactor
        self._make_session()
        compactor = SessionCompactor(self.conn, self.sessions_dir, self.bus, self.store, self.sm)
        result = compactor.compact_session("sess_001")
        self.assertIsNotNone(result)
        self.assertIn("file_path", result)
        self.assertIn("compacted_at", result)

        summaries = self.store.list_summaries("sess_001")
        self.assertEqual(len(summaries), 1)
        state = self.sm.get_state("sess_001")
        self.assertEqual(state["state"]["last_compact_seq"], get_max_seq(self.conn, "sess_001"))

    def test_check_and_compact_below_threshold(self):
        from openlmlib.collab.compactor import SessionCompactor
        self._make_session()
        compactor = SessionCompactor(self.conn, self.sessions_dir, self.bus, self.store, self.sm)
        result = compactor.check_and_compact("sess_001", auto_compact_threshold=50)
        self.assertIsNone(result)

    def test_check_and_compact_above_threshold(self):
        from openlmlib.collab.compactor import SessionCompactor
        self._make_session()

        # Insert 60 messages so get_max_seq() returns 60
        for i in range(60):
            self.bus.send(
                session_id="sess_001",
                from_agent="agent_test_001",
                msg_type="system",
                content=f"Message {i}",
                created_at="2026-04-05T10:00:00Z",
            )

        compactor = SessionCompactor(self.conn, self.sessions_dir, self.bus, self.store, self.sm)
        result = compactor.check_and_compact("sess_001", auto_compact_threshold=50)
        self.assertIsNotNone(result)


class TestSessionTemplates(unittest.TestCase):
    """Test session templates."""

    def test_list_templates(self):
        from openlmlib.collab.templates import list_templates
        templates = list_templates()
        self.assertGreater(len(templates), 0)
        self.assertIn("deep_research", [t["template_id"] for t in templates])

    def test_get_template(self):
        from openlmlib.collab.templates import get_template
        tpl = get_template("deep_research")
        self.assertIsNotNone(tpl)
        self.assertEqual(tpl["name"], "Deep Research")
        self.assertIn("plan", tpl)
        self.assertIn("rules", tpl)

    def test_get_nonexistent_template(self):
        from openlmlib.collab.templates import get_template
        tpl = get_template("nonexistent")
        self.assertIsNone(tpl)

    def test_custom_templates_resolve_data_root_against_settings_parent(self):
        import json
        import os
        import openlmlib.collab.templates as templates_mod

        tmp = tempfile.TemporaryDirectory()
        try:
            settings_path = Path(tmp.name) / "cfg" / "settings.json"
            settings_path.parent.mkdir(parents=True)
            settings_path.write_text(json.dumps({"data_root": "data"}), encoding="utf-8")
            prev = os.environ.get("OPENLMLIB_SETTINGS")
            os.environ["OPENLMLIB_SETTINGS"] = str(settings_path)
            templates_mod._custom_templates_dir = None
            templates_mod._clear_template_cache()

            tpl_dir = templates_mod._get_custom_templates_dir()
            expected = (settings_path.parent / "data" / "collab_templates").resolve()
            self.assertEqual(tpl_dir.resolve(), expected)

            templates_mod.create_template(
                "unit_custom_tpl",
                "Unit Custom",
                "desc",
                [{"step": 1, "task": "do work", "assigned_to": "any"}],
            )
            self.assertTrue((expected / "unit_custom_tpl.json").exists())
        finally:
            templates_mod._custom_templates_dir = None
            templates_mod._clear_template_cache()
            if prev is None:
                os.environ.pop("OPENLMLIB_SETTINGS", None)
            else:
                os.environ["OPENLMLIB_SETTINGS"] = prev
            tmp.cleanup()

    def test_create_template_rejects_path_escaping_id(self):
        from openlmlib.collab.templates import create_template

        with self.assertRaises(ValueError):
            create_template(
                "..\\evil",
                "Evil",
                "desc",
                [{"step": 1, "task": "x", "assigned_to": "any"}],
            )


class TestMultiSession(unittest.TestCase):
    """Test multi-session support."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        from openlmlib.collab.db import connect_collab_db, init_collab_db, create_session
        from openlmlib.collab.session import create_collab_session, join_collab_session

        self.tmp = tempfile.TemporaryDirectory()
        self.sessions_dir = Path(self.tmp.name) / "sessions"
        self.sessions_dir.mkdir(parents=True)
        self.db_path = Path(self.tmp.name) / "test.db"
        self.conn = connect_collab_db(self.db_path)
        init_collab_db(self.conn)

        self.r1 = create_collab_session(self.conn, self.sessions_dir, "Research 1", "opus", "Task 1")
        self.r2 = create_collab_session(self.conn, self.sessions_dir, "Research 2", "opus", "Task 2")
        self.worker = join_collab_session(
            self.conn,
            self.sessions_dir,
            self.r1["session_id"],
            "codex",
            capabilities=["code"],
        )

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_get_agent_sessions(self):
        from openlmlib.collab.multi_session import get_agent_sessions
        sessions = get_agent_sessions(self.conn, self.worker["agent_id"])
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["session_id"], self.r1["session_id"])

    def test_get_session_participants(self):
        from openlmlib.collab.multi_session import get_session_relationships
        result = get_session_relationships(self.conn, self.r1["session_id"])
        self.assertIn("by_shared_agents", result)
        self.assertGreaterEqual(len(result["by_orchestrator"]), 1)

    def test_search_sessions_by_content_normalizes_user_query(self):
        from openlmlib.collab.message_bus import MessageBus
        from openlmlib.collab.multi_session import search_sessions_by_content

        bus = MessageBus(self.conn, self.sessions_dir)
        bus.send(
            session_id=self.r1["session_id"],
            from_agent="system",
            msg_type="system",
            content="Found papers on error correction and fault tolerance",
            created_at="2026-04-05T10:00:00Z",
        )

        results = search_sessions_by_content(self.conn, "error-correction")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["session_id"], self.r1["session_id"])
        self.assertEqual(search_sessions_by_content(self.conn, "!!!"), [])


class TestExportBridge(unittest.TestCase):
    """Test export bridge."""

    def test_export_bridge_imports(self):
        from openlmlib.collab.export_bridge import export_session_to_library
        self.assertTrue(callable(export_session_to_library))

    def test_export_bridge_uses_supported_add_finding_args(self):
        from openlmlib.collab.export_bridge import export_session_to_library

        tmp = tempfile.TemporaryDirectory()
        conn = None
        try:
            sessions_dir = Path(tmp.name) / "sessions"
            sessions_dir.mkdir(parents=True)
            conn = connect_collab_db(Path(tmp.name) / "test.db")
            init_collab_db(conn)

            result = create_collab_session(
                conn,
                sessions_dir,
                title="Export Test",
                created_by="orch",
            )
            store = ArtifactStore(conn, sessions_dir)
            artifact = store.save(
                session_id=result["session_id"],
                created_by=result["agent_id"],
                title="Summary",
                content="Exportable content",
                created_at="2026-04-05T10:01:00Z",
            )

            with patch("openlmlib.collab.export_bridge.add_finding") as add_finding_mock:
                add_finding_mock.return_value = {"status": "ok", "id": "finding_001"}
                export_result = export_session_to_library(
                    settings_path=Path(tmp.name) / "settings.json",
                    session_id=result["session_id"],
                    collab_conn=conn,
                    sessions_dir=sessions_dir,
                )

            self.assertEqual(export_result["exported"], 1)
            add_finding_mock.assert_called_once()
            kwargs = add_finding_mock.call_args.kwargs
            self.assertTrue(kwargs["confirm"])
            self.assertNotIn("source", kwargs)
            # Short titles are expanded from artifact body so write-gate similarity can pass.
            self.assertTrue(kwargs["claim"])
            self.assertIn("Exportable content", kwargs["evidence"][0])
            self.assertGreaterEqual(len(kwargs["reasoning"]), 50)
        finally:
            if conn is not None:
                conn.close()
            tmp.cleanup()

    def test_export_bridge_rejects_invalid_artifact_filter_id(self):
        from openlmlib.collab.export_bridge import export_session_to_library

        tmp = tempfile.TemporaryDirectory()
        conn = None
        try:
            sessions_dir = Path(tmp.name) / "sessions"
            sessions_dir.mkdir(parents=True)
            conn = connect_collab_db(Path(tmp.name) / "test.db")
            init_collab_db(conn)
            result = create_collab_session(
                conn,
                sessions_dir,
                title="Export Test",
                created_by="orch",
            )

            export_result = export_session_to_library(
                settings_path=Path(tmp.name) / "settings.json",
                session_id=result["session_id"],
                collab_conn=conn,
                sessions_dir=sessions_dir,
                artifact_ids=["../art_abcdef12"],
            )

            self.assertEqual(export_result["exported"], 0)
            self.assertEqual(export_result["error_type"], "validation_error")
        finally:
            if conn is not None:
                conn.close()
            tmp.cleanup()

    def test_export_bridge_surfaces_write_gate_issues(self):
        from openlmlib.collab.export_bridge import export_session_to_library

        tmp = tempfile.TemporaryDirectory()
        conn = None
        try:
            sessions_dir = Path(tmp.name) / "sessions"
            sessions_dir.mkdir(parents=True)
            conn = connect_collab_db(Path(tmp.name) / "test.db")
            init_collab_db(conn)
            result = create_collab_session(
                conn,
                sessions_dir,
                title="Export Test",
                created_by="orch",
            )
            store = ArtifactStore(conn, sessions_dir)
            store.save(
                session_id=result["session_id"],
                created_by=result["agent_id"],
                title="Summary",
                content="Exportable content",
                created_at="2026-04-05T10:01:00Z",
            )

            with patch("openlmlib.collab.export_bridge.add_finding") as add_finding_mock:
                add_finding_mock.return_value = {
                    "status": "rejected",
                    "issues": [
                        {
                            "field": "claim_evidence_sim",
                            "message": "Claim/evidence similarity 0.20 below threshold 0.70",
                        }
                    ],
                }
                export_result = export_session_to_library(
                    settings_path=Path(tmp.name) / "settings.json",
                    session_id=result["session_id"],
                    collab_conn=conn,
                    sessions_dir=sessions_dir,
                )

            self.assertEqual(export_result["exported"], 0)
            self.assertEqual(export_result["failed"], 1)
            failure = export_result["failures"][0]
            self.assertEqual(failure["status"], "rejected")
            self.assertIn("similarity", failure["reason"].lower())
            self.assertEqual(failure["issues"][0]["field"], "claim_evidence_sim")
        finally:
            if conn is not None:
                conn.close()
            tmp.cleanup()


class TestCollabMCP(unittest.TestCase):
    """Test MCP tool integrations that enforce auth and state invariants."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings_path = Path(self.tmp.name) / "config" / "settings.json"
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        data_root = Path(self.tmp.name) / "data"
        data_root.mkdir(parents=True, exist_ok=True)
        self.settings_path.write_text(json.dumps({"data_root": str(data_root)}), encoding="utf-8")
        self.prev_settings = os.environ.get("OPENLMLIB_SETTINGS")
        os.environ["OPENLMLIB_SETTINGS"] = str(self.settings_path)

        import openlmlib.collab.collab_mcp as collab_mcp_module

        collab_mcp_module._cached_paths = None
        collab_mcp_module._cached_paths_mtime = 0.0
        self.collab_mcp_module = collab_mcp_module

    def tearDown(self):
        from openlmlib.collab.db import close_thread_connections
        close_thread_connections()
        if self.prev_settings is None:
            os.environ.pop("OPENLMLIB_SETTINGS", None)
        else:
            os.environ["OPENLMLIB_SETTINGS"] = self.prev_settings
        self.tmp.cleanup()

    def test_orchestrator_can_update_state_with_returned_agent_id(self):
        create_resp = self.collab_mcp_module.create_session(
            title="MCP Session",
            task_description="Validate orchestrator auth",
            created_by="orch-model",
        )
        self.assertTrue(create_resp["success"])

        update_resp = self.collab_mcp_module.update_session_state(
            session_id=create_resp["session_id"],
            state={"current_phase": "running"},
            orchestrator_id=create_resp["your_agent_id"],
        )
        self.assertTrue(update_resp["success"])
        self.assertEqual(update_resp["state"]["current_phase"], "running")

    def test_read_messages_filtered_does_not_advance_stored_offset(self):
        create_resp = self.collab_mcp_module.create_session(
            title="Offset Session",
            task_description="Check filtered reads",
            created_by="orch-model",
        )
        join_resp = self.collab_mcp_module.join_session(
            session_id=create_resp["session_id"],
            model="worker-model",
        )

        self.collab_mcp_module.send_message(
            session_id=create_resp["session_id"],
            msg_type="task",
            content="Task message",
            from_agent=create_resp["your_agent_id"],
        )
        self.collab_mcp_module.send_message(
            session_id=create_resp["session_id"],
            msg_type="result",
            content="## Summary\nResult message\n## Key Facts\n- fact 1",
            from_agent=join_resp["agent_id"],
        )

        filtered = self.collab_mcp_module.read_messages(
            session_id=create_resp["session_id"],
            agent_id=join_resp["agent_id"],
            msg_types=["result"],
        )
        self.assertFalse(filtered["offset_updated"])

        unfiltered = self.collab_mcp_module.read_messages(
            session_id=create_resp["session_id"],
            agent_id=join_resp["agent_id"],
        )
        contents = [msg["content"] for msg in unfiltered["messages"]]
        self.assertIn("Task message", contents)
        self.assertIn("## Summary\nResult message\n## Key Facts\n- fact 1", contents)

    def test_send_message_sanitizes_content(self):
        create_resp = self.collab_mcp_module.create_session(
            title="Sanitize Session",
            task_description="Check message sanitization",
            created_by="orch-model",
        )
        send_resp = self.collab_mcp_module.send_message(
            session_id=create_resp["session_id"],
            msg_type="update",
            content="Unsafe <script>alert('x')</script> ```payload```",
            from_agent=create_resp["your_agent_id"],
        )
        self.assertTrue(send_resp["success"])

        tail_resp = self.collab_mcp_module.tail_messages(
            session_id=create_resp["session_id"],
            agent_id=create_resp["your_agent_id"],
            n=5,
        )
        stored = tail_resp["messages"][-1]["content"]
        self.assertNotIn("<script>", stored)
        self.assertNotIn("```", stored)

    def test_session_reads_require_membership(self):
        create_resp = self.collab_mcp_module.create_session(
            title="Auth Session",
            task_description="Check session read auth",
            created_by="orch-model",
        )
        outsider = self.collab_mcp_module.create_session(
            title="Other Session",
            task_description="Create outsider",
            created_by="outsider-model",
        )

        denied = self.collab_mcp_module.get_session_state(
            session_id=create_resp["session_id"],
            agent_id=outsider["your_agent_id"],
        )
        self.assertFalse(denied["success"])
        self.assertEqual(denied["error_type"], "agent_not_authorized")

    def test_model_dots_colons_generate_valid_agent_ids(self):
        create_resp = self.collab_mcp_module.create_session(
            title="Model ID Session",
            task_description="Sanitize model names",
            created_by="gpt-4.1",
        )
        self.assertTrue(create_resp.get("success", True) or "session_id" in create_resp)
        agent_id = create_resp["your_agent_id"]
        self.assertNotIn(".", agent_id)
        self.assertNotIn(":", agent_id)
        from openlmlib.collab.security import validate_agent_id
        validate_agent_id(agent_id)

        send_resp = self.collab_mcp_module.send_message(
            session_id=create_resp["session_id"],
            msg_type="update",
            content="hello from dotted model",
            from_agent=agent_id,
        )
        self.assertTrue(send_resp["success"], send_resp)

        join_resp = self.collab_mcp_module.join_session(
            session_id=create_resp["session_id"],
            model="qwen2.5-coder:7b",
        )
        self.assertNotIn(".", join_resp["agent_id"])
        self.assertNotIn(":", join_resp["agent_id"])
        validate_agent_id(join_resp["agent_id"])

    def test_send_message_allows_to_agent_any(self):
        create_resp = self.collab_mcp_module.create_session(
            title="Any Target Session",
            task_description="Open task assignment",
            created_by="orch-model",
        )
        send_resp = self.collab_mcp_module.send_message(
            session_id=create_resp["session_id"],
            msg_type="task",
            content="Open work for anyone",
            to_agent="any",
            from_agent=create_resp["your_agent_id"],
        )
        self.assertTrue(send_resp["success"], send_resp)

    def test_rules_engine_enforced_on_send_message(self):
        create_resp = self.collab_mcp_module.create_session(
            title="Rules Session",
            task_description="Enforce rules",
            created_by="orch-model",
            rules={
                "require_artifact_for_results": True,
                "require_assignment": True,
                "max_pending_tasks": 1,
            },
        )
        denied = self.collab_mcp_module.send_message(
            session_id=create_resp["session_id"],
            msg_type="result",
            content="## Summary\nNo artifact\n## Key Facts\n- none",
            from_agent=create_resp["your_agent_id"],
        )
        self.assertFalse(denied["success"])
        self.assertEqual(denied["error_type"], "rules_error")

        unassigned = self.collab_mcp_module.send_message(
            session_id=create_resp["session_id"],
            msg_type="task",
            content="Unassigned task",
            to_agent=None,
            from_agent=create_resp["your_agent_id"],
        )
        self.assertFalse(unassigned["success"])
        self.assertEqual(unassigned["error_type"], "rules_error")

        open_pool = self.collab_mcp_module.send_message(
            session_id=create_resp["session_id"],
            msg_type="task",
            content="Open claimable task",
            to_agent="any",
            from_agent=create_resp["your_agent_id"],
        )
        self.assertTrue(open_pool["success"], open_pool)

    def test_terminate_writes_terminated_status(self):
        create_resp = self.collab_mcp_module.create_session(
            title="Terminate Session",
            task_description="End cleanly",
            created_by="orch-model",
        )
        term = self.collab_mcp_module.terminate_session(
            session_id=create_resp["session_id"],
            orchestrator_id=create_resp["your_agent_id"],
            summary="done",
        )
        self.assertTrue(term["success"], term)
        self.assertEqual(term["status"], "terminated")

        listed = self.collab_mcp_module.list_sessions(status="terminated")
        ids = [s["session_id"] for s in listed.get("sessions", listed if isinstance(listed, list) else [])]
        if "sessions" in listed:
            ids = [s["session_id"] for s in listed["sessions"]]
        self.assertIn(create_resp["session_id"], ids)

    def test_poll_messages_filtered_does_not_advance_stored_offset(self):
        create_resp = self.collab_mcp_module.create_session(
            title="Poll Offset Session",
            task_description="Check filtered polls",
            created_by="orch-model",
        )
        join_resp = self.collab_mcp_module.join_session(
            session_id=create_resp["session_id"],
            model="worker-model",
        )
        self.collab_mcp_module.send_message(
            session_id=create_resp["session_id"],
            msg_type="task",
            content="Task message for poll",
            from_agent=create_resp["your_agent_id"],
        )
        self.collab_mcp_module.send_message(
            session_id=create_resp["session_id"],
            msg_type="result",
            content="## Summary\nResult for poll\n## Key Facts\n- fact",
            from_agent=join_resp["agent_id"],
        )
        filtered = self.collab_mcp_module.poll_messages(
            session_id=create_resp["session_id"],
            agent_id=join_resp["agent_id"],
            timeout=0,
            msg_types=["result"],
        )
        self.assertTrue(filtered["success"])
        self.assertFalse(filtered.get("offset_updated", True))
        self.assertGreater(filtered["count"], 0)

        unfiltered = self.collab_mcp_module.poll_messages(
            session_id=create_resp["session_id"],
            agent_id=join_resp["agent_id"],
            timeout=0,
        )
        contents = [msg["content"] for msg in unfiltered["messages"]]
        self.assertIn("Task message for poll", contents)

    def test_session_context_allows_terminated_sessions(self):
        create_resp = self.collab_mcp_module.create_session(
            title="Context After Terminate",
            task_description="Review completed work",
            created_by="orch-model",
        )
        term = self.collab_mcp_module.terminate_session(
            session_id=create_resp["session_id"],
            orchestrator_id=create_resp["your_agent_id"],
            summary="done",
        )
        self.assertTrue(term["success"], term)

        ctx = self.collab_mcp_module.session_context(
            session_id=create_resp["session_id"],
            agent_id=create_resp["your_agent_id"],
        )
        self.assertNotIn("error", ctx)
        self.assertEqual(ctx.get("session_status"), "terminated")
        self.assertIn("formatted_context", ctx)

    def test_send_message_auto_compacts_when_threshold_hit(self):
        create_resp = self.collab_mcp_module.create_session(
            title="Auto Compact Session",
            task_description="Trigger compaction",
            created_by="orch-model",
            rules={"auto_compact_after_messages": 2, "require_artifact_for_results": False},
        )
        session_id = create_resp["session_id"]
        agent_id = create_resp["your_agent_id"]

        # create_session already inserts a system message (seq=1); next send
        # reaches threshold 2 and should auto-compact.
        first = self.collab_mcp_module.send_message(
            session_id=session_id,
            msg_type="update",
            content="First update triggers compact",
            from_agent=agent_id,
        )
        self.assertTrue(first["success"], first)
        self.assertIn("compacted", first)
        self.assertIn("compacted_at", first["compacted"])


if __name__ == "__main__":
    unittest.main()
