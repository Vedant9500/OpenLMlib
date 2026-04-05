"""Tests for CollabSessions core operations."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

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
            content="Found 5 papers",
            created_at="2026-04-05T10:02:00Z",
        )

        msgs = self.bus.read_new("sess_001", last_seq=0)
        self.assertEqual(len(msgs), 2)

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
            content="Quantum error correction advances",
            created_at="2026-04-05T10:01:00Z",
        )
        self.bus.send(
            session_id="sess_001",
            from_agent="agent_001",
            msg_type="result",
            content="Market analysis report",
            created_at="2026-04-05T10:02:00Z",
        )

        tail = self.bus.tail("sess_001", 1)
        self.assertEqual(len(tail), 1)
        self.assertEqual(tail[0]["content"], "Market analysis report")

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
            content="Found 12 papers on the topic",
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
        self.assertEqual(term_result["status"], "completed")

        session = get_session(self.conn, session_id)
        self.assertEqual(session["status"], "completed")

    def test_join_nonexistent_session(self):
        with self.assertRaises(ValueError):
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
        with self.assertRaises(ValueError):
            join_collab_session(
                self.conn, self.sessions_dir,
                session_id=result["session_id"],
                model="gpt-4",
            )


if __name__ == "__main__":
    unittest.main()
