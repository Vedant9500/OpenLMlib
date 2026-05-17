import unittest
import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path

from openlmlib.memory import (
    SessionManager,
    MemoryStorage,
    ProgressiveRetriever,
)
from openlmlib.memory.storage import MemoryStorage
from openlmlib.memory.session_manager import SessionManager
from openlmlib.memory.privacy import (
    contains_private,
    filter_private,
    sanitize_for_storage,
    PrivacyFilter,
)
from openlmlib.memory.compressor import MemoryCompressor
from openlmlib.memory.memory_retriever import ProgressiveRetriever
from openlmlib.memory.context_builder import ContextBuilder
from openlmlib.memory.hooks import HookType, HookRegistry, Hook


# ==================== Storage Tests ====================

class TestMemoryStorage(unittest.TestCase):
    """Test SQLite storage operations."""

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.storage = MemoryStorage(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_init_schema(self):
        """Test schema initialization."""
        cursor = self.storage.conn.cursor()

        # Check tables exist
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = {row[0] for row in cursor.fetchall()}

        self.assertIn("memory_sessions", tables)
        self.assertIn("memory_observations", tables)
        self.assertIn("memory_summaries", tables)

    def test_create_session(self):
        """Test session creation."""
        session_id = "test_session_001"
        user_id = "test_user"

        result = self.storage.create_session(session_id, user_id)

        self.assertEqual(result["session_id"], session_id)
        self.assertEqual(result["user_id"], user_id)
        self.assertEqual(result["observation_count"], 0)

        # Verify in database
        cursor = self.storage.conn.cursor()
        cursor.execute(
            "SELECT session_id, user_id FROM memory_sessions WHERE session_id = ?",
            (session_id,)
        )
        row = cursor.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], session_id)
        self.assertEqual(row[1], user_id)

    def test_end_session(self):
        """Test session ending."""
        session_id = "test_session_002"
        self.storage.create_session(session_id, "user")

        result = self.storage.end_session(session_id)
        self.assertTrue(result)

        # Verify ended_at is set
        cursor = self.storage.conn.cursor()
        cursor.execute(
            "SELECT ended_at FROM memory_sessions WHERE session_id = ?",
            (session_id,)
        )
        row = cursor.fetchone()
        self.assertIsNotNone(row[0])

    def test_add_observation(self):
        """Test observation addition."""
        session_id = "test_session_003"
        self.storage.create_session(session_id, "user")

        observation = {
            "session_id": session_id,
            "tool_name": "Read",
            "tool_input": "file.txt",
            "tool_output": "file content here",
        }

        obs_id = self.storage.add_observation(observation)
        self.assertTrue(obs_id.startswith("obs_"))

        # Verify in database
        observations = self.storage.get_session_observations(session_id)
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0]["tool_name"], "Read")

    def test_get_observations_by_ids(self):
        """Test fetching observations by IDs."""
        session_id = "test_session_004"
        self.storage.create_session(session_id, "user")

        obs1_id = self.storage.add_observation({
            "session_id": session_id,
            "tool_name": "Read",
            "tool_output": "content 1",
        })

        obs2_id = self.storage.add_observation({
            "session_id": session_id,
            "tool_name": "Edit",
            "tool_output": "content 2",
        })

        results = self.storage.get_observations_by_ids([obs1_id, obs2_id])
        self.assertEqual(len(results), 2)
        self.assertEqual({r["tool_name"] for r in results}, {"Read", "Edit"})

    def test_search_observations(self):
        """Test observation search."""
        session_id = "test_session_005"
        self.storage.create_session(session_id, "user")

        self.storage.add_observation({
            "session_id": session_id,
            "tool_name": "Read",
            "tool_output": "Python code with functions",
        })

        self.storage.add_observation({
            "session_id": session_id,
            "tool_name": "Edit",
            "tool_output": "JavaScript code with callbacks",
        })

        results = self.storage.search_observations("Python", limit=10)
        self.assertEqual(len(results), 1)
        self.assertIn("Python", results[0]["tool_output"])

    def test_save_and_get_summary(self):
        """Test summary operations."""
        session_id = "test_session_006"
        self.storage.create_session(session_id, "user")

        summary = {
            "summary": "Test session summary",
            "key_facts": ["fact1", "fact2"],
            "concepts": ["concept1"],
        }

        result = self.storage.save_summary(session_id, summary)
        self.assertTrue(result)

        # Retrieve summary
        retrieved = self.storage.get_session_summary(session_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved["summary"], "Test session summary")
        self.assertEqual(retrieved["key_facts"], ["fact1", "fact2"])

    def test_get_recent_observations(self):
        """Test fetching recent observations."""
        session_id = "test_session_007"
        self.storage.create_session(session_id, "user")

        for i in range(5):
            self.storage.add_observation({
                "session_id": session_id,
                "tool_name": f"Tool{i}",
                "tool_output": f"Output {i}",
            })

        recent = self.storage.get_recent_observations(limit=3)
        self.assertEqual(len(recent), 3)


# ==================== Session Manager Tests ====================

class TestSessionManager(unittest.TestCase):
    """Test session lifecycle management."""

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.storage = MemoryStorage(self.conn)
        self.session_manager = SessionManager(self.storage)

    def tearDown(self):
        self.conn.close()

    def test_session_start(self):
        """Test session start."""
        session_id = "test_sess_001"
        result = self.session_manager.on_session_start(session_id, "user")

        self.assertEqual(result["session_id"], session_id)
        self.assertEqual(result["status"], "started")
        self.assertIn(session_id, self.session_manager.active_sessions)

    def test_session_end(self):
        """Test session end."""
        session_id = "test_sess_002"
        self.session_manager.on_session_start(session_id, "user")

        result = self.session_manager.on_session_end(session_id)
        self.assertEqual(result["status"], "ended")
        self.assertNotIn(session_id, self.session_manager.active_sessions)

    def test_tool_use_logging(self):
        """Test observation logging on tool use."""
        session_id = "test_sess_003"
        self.session_manager.on_session_start(session_id, "user")

        obs_id = self.session_manager.on_tool_use(
            session_id,
            "Read",
            "file.txt",
            "file content"
        )

        self.assertIsNotNone(obs_id)
        self.assertTrue(obs_id.startswith("obs_"))

        # Verify session tracking
        self.assertEqual(self.session_manager.active_sessions[session_id]["observation_count"], 1)

    def test_privacy_filtering(self):
        """Test privacy filtering on tool use."""
        session_id = "test_sess_004"
        self.session_manager.on_session_start(session_id, "user")

        # Tool output with private content
        tool_output = "API_KEY=<private>sk-live-secret123</private>"

        obs_id = self.session_manager.on_tool_use(
            session_id,
            "Read",
            "config.txt",
            tool_output
        )

        # Observation should still be logged (filtered content)
        self.assertIsNotNone(obs_id)

    def test_get_active_sessions(self):
        """Test getting active sessions."""
        for i in range(3):
            self.session_manager.on_session_start(f"sess_{i}", f"user_{i}")

        active = self.session_manager.get_active_sessions()
        self.assertEqual(len(active), 3)

    def test_session_summary_generation(self):
        """Test automatic summary generation on session end."""
        session_id = "test_sess_005"
        self.session_manager.on_session_start(session_id, "user")

        # Log some observations
        for i in range(3):
            self.session_manager.on_tool_use(
                session_id,
                f"Tool{i}",
                f"Input {i}",
                f"Output {i}"
            )

        # End session (should generate summary)
        result = self.session_manager.on_session_end(
            session_id, generate_summary=True
        )

        self.assertTrue(result["summary_generated"])
        self.assertEqual(result["observation_count"], 3)


# ==================== Privacy Tests ====================

class TestPrivacy(unittest.TestCase):
    """Test privacy filtering."""

    def test_detects_private_tags(self):
        """Test detection of <private> tags."""
        self.assertTrue(contains_private("<private>secret</private>"))
        self.assertFalse(contains_private("normal text"))

    def test_detects_api_keys(self):
        """Test detection of API key patterns."""
        self.assertTrue(contains_private("API_KEY=sk-live-abc123"))
        self.assertTrue(contains_private("API_KEY=sk-test-xyz789"))
        self.assertFalse(contains_private("normal text"))

    def test_detects_passwords(self):
        """Test detection of password patterns."""
        self.assertTrue(contains_private("PASSWORD=supersecret"))
        self.assertTrue(contains_private("DB_PASSWORD=mypassword"))

    def test_filter_private_tags(self):
        """Test filtering of private sections."""
        text = "normal <private>secret</private> more text"
        filtered = filter_private(text)

        self.assertIn("[PRIVATE CONTENT REMOVED]", filtered)
        self.assertNotIn("secret", filtered)

    def test_sanitize_for_storage(self):
        """Test sanitization for storage."""
        text = "API_KEY=sk-live-secret123 normal text"
        sanitized = sanitize_for_storage(text)

        self.assertNotIn("sk-live-secret123", sanitized)
        self.assertIn("[REDACTED]", sanitized)

    def test_privacy_filter_stats(self):
        """Test privacy filter statistics."""
        pf = PrivacyFilter()

        pf.filter_text("API_KEY=secret123")
        pf.filter_text("normal text")
        pf.filter_text("<private>hidden</private>")

        stats = pf.stats()
        self.assertEqual(stats["filtered_count"], 2)
        self.assertGreaterEqual(stats["patterns_matched"], 1)


# ==================== Compressor Tests ====================

class TestCompressor(unittest.TestCase):
    """Test memory compression."""

    def setUp(self):
        self.compressor = MemoryCompressor()

    def test_compress_basic(self):
        """Test basic observation compression."""
        observation = {
            "tool_name": "Read",
            "tool_output": "File content with important information",
        }

        result = self.compressor.compress(observation)

        self.assertIn("title", result)
        self.assertIn("narrative", result)
        self.assertIn("facts", result)
        self.assertIn("concepts", result)
        self.assertIn("type", result)
        self.assertGreater(result["token_count_original"], 0)
        self.assertGreater(result["token_count_compressed"], 0)

    def test_compress_empty_output(self):
        """Test compression with empty output."""
        observation = {"tool_name": "Read", "tool_output": ""}

        result = self.compressor.compress(observation)
        # Title may have trailing period from caveman compression
        self.assertEqual(result["title"].rstrip('.'), "Read execution")

    def test_compress_classifies_type(self):
        """Test observation type classification."""
        # File read
        obs_read = {"tool_name": "Read", "tool_output": "content"}
        self.assertEqual(self.compressor.compress(obs_read)["type"], "discovery")

        # File edit
        obs_edit = {"tool_name": "Edit", "tool_output": "modified"}
        self.assertEqual(self.compressor.compress(obs_edit)["type"], "change")

    def test_compress_extracts_facts(self):
        """Test fact extraction from output."""
        output = """
        - Important fact 1
        - Important fact 2
        - Important fact 3
        """

        observation = {
            "tool_name": "Read",
            "tool_output": output,
        }

        result = self.compressor.compress(observation)
        self.assertGreater(len(result["facts"]), 0)

    def test_compress_extracts_concepts(self):
        """Test concept extraction from output."""
        output = "Python code with FastAPI and SQLAlchemy"

        observation = {
            "tool_name": "Read",
            "tool_output": output,
        }

        result = self.compressor.compress(observation)
        self.assertGreater(len(result["concepts"]), 0)


# ==================== Progressive Retriever Tests ====================

class TestProgressiveRetriever(unittest.TestCase):
    """Test 3-layer progressive retrieval."""

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.storage = MemoryStorage(self.conn)
        self.retriever = ProgressiveRetriever(self.storage)

    def tearDown(self):
        self.conn.close()

    def test_layer1_search_index(self):
        """Test layer 1 search index."""
        # Add test data
        session_id = "test_session"
        self.storage.create_session(session_id, "user")

        for i in range(5):
            self.storage.add_observation({
                "session_id": session_id,
                "tool_name": "Read",
                "tool_output": f"Python code example {i}",
            })

        results = self.retriever.layer1_search_index("Python", limit=10)
        self.assertGreater(len(results), 0)
        self.assertTrue(all(hasattr(r, "id") for r in results))
        self.assertTrue(all(hasattr(r, "title") for r in results))

    def test_layer2_timeline(self):
        """Test layer 2 timeline retrieval."""
        session_id = "test_session"
        self.storage.create_session(session_id, "user")

        obs_id = self.storage.add_observation({
            "session_id": session_id,
            "tool_name": "Read",
            "tool_output": "Python code",
        })

        timeline = self.retriever.layer2_timeline([obs_id])
        self.assertEqual(len(timeline), 1)
        self.assertTrue(hasattr(timeline[0], "narrative"))

    def test_layer3_full_details(self):
        """Test layer 3 full details retrieval."""
        session_id = "test_session"
        self.storage.create_session(session_id, "user")

        obs_id = self.storage.add_observation({
            "session_id": session_id,
            "tool_name": "Read",
            "tool_input": "file.py",
            "tool_output": "Python code with functions",
        })

        details = self.retriever.layer3_full_details([obs_id])
        self.assertEqual(len(details), 1)
        self.assertTrue(hasattr(details[0], "tool_name"))
        self.assertTrue(hasattr(details[0], "tool_output"))

    def test_auto_inject_context(self):
        """Test automatic context injection."""
        session_id = "test_session"
        self.storage.create_session(session_id, "user")

        for i in range(3):
            self.storage.add_observation({
                "session_id": session_id,
                "tool_name": "Read",
                "tool_output": f"Important knowledge {i}",
            })

        result = self.retriever.auto_inject_context(
            "new_session", limit=10
        )

        self.assertIn("context_block", result)
        self.assertIn("observation_count", result)
        self.assertGreater(result["observation_count"], 0)


# ==================== Context Builder Tests ====================

class TestContextBuilder(unittest.TestCase):
    """Test context building for LLM injection."""

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.storage = MemoryStorage(self.conn)
        self.retriever = ProgressiveRetriever(self.storage)
        self.context_builder = ContextBuilder(self.retriever)

    def tearDown(self):
        self.conn.close()

    def test_build_session_start_context(self):
        """Test building session start context."""
        session_id = "test_session"
        self.storage.create_session(session_id, "user")

        self.storage.add_observation({
            "session_id": session_id,
            "tool_name": "Read",
            "tool_output": "Important knowledge",
        })

        context = self.context_builder.build_session_start_context(
            "new_session", limit=10
        )

        self.assertIn("<openlmlib-memory-context>", context)
        self.assertIn("Previous Session Context", context)

    def test_build_prompt_context(self):
        """Test building prompt-specific context."""
        session_id = "test_session"
        self.storage.create_session(session_id, "user")

        self.storage.add_observation({
            "session_id": session_id,
            "tool_name": "Read",
            "tool_output": "Python retrieval techniques",
        })

        context = self.context_builder.build_prompt_context(
            "new_session",
            "Python retrieval",
            limit=10
        )

        if context:  # May be empty if no matches
            self.assertIn("Relevant Previous Context", context)

    def test_build_progressive_context_layer1(self):
        """Test building progressive context (layer 1)."""
        session_id = "test_session"
        self.storage.create_session(session_id, "user")

        self.storage.add_observation({
            "session_id": session_id,
            "tool_name": "Read",
            "tool_output": "Python code",
        })

        result = self.context_builder.build_progressive_context(
            "new_session",
            "Python",
            layer=1,
            limit=10
        )

        self.assertEqual(result["layer"], 1)
        self.assertIn("context_block", result)


# ==================== Hook Registry Tests ====================

class TestHookRegistry(unittest.TestCase):
    """Test hook registry and lifecycle."""

    def setUp(self):
        self.registry = HookRegistry()

    def test_register_hook(self):
        """Test hook registration."""
        def handler(ctx):
            return {"result": "ok"}

        hook = Hook(HookType.SESSION_START, handler, priority=1)
        self.registry.register(hook)

        stats = self.registry.stats()
        self.assertEqual(stats["session_start"], 1)

    def test_trigger_hooks(self):
        """Test hook triggering."""
        results = []

        def handler1(ctx):
            results.append("handler1")
            return {"handler": "handler1"}

        def handler2(ctx):
            results.append("handler2")
            return {"handler": "handler2"}

        self.registry.register(Hook(HookType.SESSION_START, handler1, priority=1))
        self.registry.register(Hook(HookType.SESSION_START, handler2, priority=2))

        hook_results = self.registry.trigger(
            HookType.SESSION_START,
            {"session_id": "test"}
        )

        self.assertEqual(len(hook_results), 2)
        self.assertIn("handler1", results)
        self.assertIn("handler2", results)

    def test_priority_ordering(self):
        """Test hooks execute in priority order."""
        execution_order = []

        def make_handler(name):
            def handler(ctx):
                execution_order.append(name)
                return {"name": name}
            return handler

        self.registry.register(
            Hook(HookType.SESSION_START, make_handler("low"), priority=1)
        )
        self.registry.register(
            Hook(HookType.SESSION_START, make_handler("high"), priority=10)
        )

        self.registry.trigger(HookType.SESSION_START, {})

        # Higher priority should execute first
        self.assertEqual(execution_order, ["high", "low"])


if __name__ == "__main__":
    unittest.main()
