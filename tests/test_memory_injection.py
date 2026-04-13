"""
Tests for memory injection module.

Tests cover:
- Storage (SQLite schema, CRUD operations)
- Session manager (lifecycle, hooks)
- Privacy filtering (detection, sanitization)
- Compression (observation summarization)
- Progressive retriever (3-layer disclosure)
- Context builder (formatting for LLM)
"""

import pytest
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


@pytest.fixture
def db_conn():
    """Create in-memory SQLite database for testing."""
    conn = sqlite3.connect(":memory:")
    yield conn
    conn.close()


@pytest.fixture
def storage(db_conn):
    """Create MemoryStorage instance."""
    return MemoryStorage(db_conn)


@pytest.fixture
def session_manager(storage):
    """Create SessionManager instance."""
    return SessionManager(storage)


@pytest.fixture
def compressor():
    """Create MemoryCompressor instance."""
    return MemoryCompressor()


@pytest.fixture
def retriever(storage):
    """Create ProgressiveRetriever instance."""
    return ProgressiveRetriever(storage)


@pytest.fixture
def context_builder(retriever):
    """Create ContextBuilder instance."""
    return ContextBuilder(retriever)


# ==================== Storage Tests ====================

class TestMemoryStorage:
    """Test SQLite storage operations."""

    def test_init_schema(self, storage):
        """Test schema initialization."""
        cursor = storage.conn.cursor()

        # Check tables exist
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = {row[0] for row in cursor.fetchall()}

        assert "memory_sessions" in tables
        assert "memory_observations" in tables
        assert "memory_summaries" in tables

    def test_create_session(self, storage):
        """Test session creation."""
        session_id = "test_session_001"
        user_id = "test_user"

        result = storage.create_session(session_id, user_id)

        assert result["session_id"] == session_id
        assert result["user_id"] == user_id
        assert result["observation_count"] == 0

        # Verify in database
        cursor = storage.conn.cursor()
        cursor.execute(
            "SELECT session_id, user_id FROM memory_sessions WHERE session_id = ?",
            (session_id,)
        )
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == session_id
        assert row[1] == user_id

    def test_end_session(self, storage):
        """Test session ending."""
        session_id = "test_session_002"
        storage.create_session(session_id, "user")

        result = storage.end_session(session_id)
        assert result is True

        # Verify ended_at is set
        cursor = storage.conn.cursor()
        cursor.execute(
            "SELECT ended_at FROM memory_sessions WHERE session_id = ?",
            (session_id,)
        )
        row = cursor.fetchone()
        assert row[0] is not None

    def test_add_observation(self, storage):
        """Test observation addition."""
        session_id = "test_session_003"
        storage.create_session(session_id, "user")

        observation = {
            "session_id": session_id,
            "tool_name": "Read",
            "tool_input": "file.txt",
            "tool_output": "file content here",
        }

        obs_id = storage.add_observation(observation)
        assert obs_id.startswith("obs_")

        # Verify in database
        observations = storage.get_session_observations(session_id)
        assert len(observations) == 1
        assert observations[0]["tool_name"] == "Read"

    def test_get_observations_by_ids(self, storage):
        """Test fetching observations by IDs."""
        session_id = "test_session_004"
        storage.create_session(session_id, "user")

        obs1_id = storage.add_observation({
            "session_id": session_id,
            "tool_name": "Read",
            "tool_output": "content 1",
        })

        obs2_id = storage.add_observation({
            "session_id": session_id,
            "tool_name": "Edit",
            "tool_output": "content 2",
        })

        results = storage.get_observations_by_ids([obs1_id, obs2_id])
        assert len(results) == 2
        assert {r["tool_name"] for r in results} == {"Read", "Edit"}

    def test_search_observations(self, storage):
        """Test observation search."""
        session_id = "test_session_005"
        storage.create_session(session_id, "user")

        storage.add_observation({
            "session_id": session_id,
            "tool_name": "Read",
            "tool_output": "Python code with functions",
        })

        storage.add_observation({
            "session_id": session_id,
            "tool_name": "Edit",
            "tool_output": "JavaScript code with callbacks",
        })

        results = storage.search_observations("Python", limit=10)
        assert len(results) == 1
        assert "Python" in results[0]["tool_output"]

    def test_save_and_get_summary(self, storage):
        """Test summary operations."""
        session_id = "test_session_006"
        storage.create_session(session_id, "user")

        summary = {
            "summary": "Test session summary",
            "key_facts": ["fact1", "fact2"],
            "concepts": ["concept1"],
        }

        result = storage.save_summary(session_id, summary)
        assert result is True

        # Retrieve summary
        retrieved = storage.get_session_summary(session_id)
        assert retrieved is not None
        assert retrieved["summary"] == "Test session summary"
        assert retrieved["key_facts"] == ["fact1", "fact2"]

    def test_get_recent_observations(self, storage):
        """Test fetching recent observations."""
        session_id = "test_session_007"
        storage.create_session(session_id, "user")

        for i in range(5):
            storage.add_observation({
                "session_id": session_id,
                "tool_name": f"Tool{i}",
                "tool_output": f"Output {i}",
            })

        recent = storage.get_recent_observations(limit=3)
        assert len(recent) == 3


# ==================== Session Manager Tests ====================

class TestSessionManager:
    """Test session lifecycle management."""

    def test_session_start(self, session_manager):
        """Test session start."""
        session_id = "test_sess_001"
        result = session_manager.on_session_start(session_id, "user")

        assert result["session_id"] == session_id
        assert result["status"] == "started"
        assert session_id in session_manager.active_sessions

    def test_session_end(self, session_manager):
        """Test session end."""
        session_id = "test_sess_002"
        session_manager.on_session_start(session_id, "user")

        result = session_manager.on_session_end(session_id)
        assert result["status"] == "ended"
        assert session_id not in session_manager.active_sessions

    def test_tool_use_logging(self, session_manager):
        """Test observation logging on tool use."""
        session_id = "test_sess_003"
        session_manager.on_session_start(session_id, "user")

        obs_id = session_manager.on_tool_use(
            session_id,
            "Read",
            "file.txt",
            "file content"
        )

        assert obs_id is not None
        assert obs_id.startswith("obs_")

        # Verify session tracking
        assert session_manager.active_sessions[session_id]["observation_count"] == 1

    def test_privacy_filtering(self, session_manager):
        """Test privacy filtering on tool use."""
        session_id = "test_sess_004"
        session_manager.on_session_start(session_id, "user")

        # Tool output with private content
        tool_output = "API_KEY=<private>sk-live-secret123</private>"

        obs_id = session_manager.on_tool_use(
            session_id,
            "Read",
            "config.txt",
            tool_output
        )

        # Observation should still be logged (filtered content)
        assert obs_id is not None

    def test_get_active_sessions(self, session_manager):
        """Test getting active sessions."""
        for i in range(3):
            session_manager.on_session_start(f"sess_{i}", f"user_{i}")

        active = session_manager.get_active_sessions()
        assert len(active) == 3

    def test_session_summary_generation(self, session_manager):
        """Test automatic summary generation on session end."""
        session_id = "test_sess_005"
        session_manager.on_session_start(session_id, "user")

        # Log some observations
        for i in range(3):
            session_manager.on_tool_use(
                session_id,
                f"Tool{i}",
                f"Input {i}",
                f"Output {i}"
            )

        # End session (should generate summary)
        result = session_manager.on_session_end(
            session_id, generate_summary=True
        )

        assert result["summary_generated"] is True
        assert result["observation_count"] == 3


# ==================== Privacy Tests ====================

class TestPrivacy:
    """Test privacy filtering."""

    def test_detects_private_tags(self):
        """Test detection of <private> tags."""
        assert contains_private("<private>secret</private>") is True
        assert contains_private("normal text") is False

    def test_detects_api_keys(self):
        """Test detection of API key patterns."""
        assert contains_private("API_KEY=sk-live-abc123") is True
        assert contains_private("API_KEY=sk-test-xyz789") is True
        assert contains_private("normal text") is False

    def test_detects_passwords(self):
        """Test detection of password patterns."""
        assert contains_private("PASSWORD=supersecret") is True
        assert contains_private("DB_PASSWORD=mypassword") is True

    def test_filter_private_tags(self):
        """Test filtering of private sections."""
        text = "normal <private>secret</private> more text"
        filtered = filter_private(text)

        assert "[PRIVATE CONTENT REMOVED]" in filtered
        assert "secret" not in filtered

    def test_sanitize_for_storage(self):
        """Test sanitization for storage."""
        text = "API_KEY=sk-live-secret123 normal text"
        sanitized = sanitize_for_storage(text)

        assert "sk-live-secret123" not in sanitized
        assert "[REDACTED]" in sanitized

    def test_privacy_filter_stats(self):
        """Test privacy filter statistics."""
        pf = PrivacyFilter()

        pf.filter_text("API_KEY=secret123")
        pf.filter_text("normal text")
        pf.filter_text("<private>hidden</private>")

        stats = pf.stats()
        assert stats["filtered_count"] == 2
        assert stats["patterns_matched"] >= 1


# ==================== Compressor Tests ====================

class TestCompressor:
    """Test memory compression."""

    def test_compress_basic(self, compressor):
        """Test basic observation compression."""
        observation = {
            "tool_name": "Read",
            "tool_output": "File content with important information",
        }

        result = compressor.compress(observation)

        assert "title" in result
        assert "narrative" in result
        assert "facts" in result
        assert "concepts" in result
        assert "type" in result
        assert result["token_count_original"] > 0
        assert result["token_count_compressed"] > 0

    def test_compress_empty_output(self, compressor):
        """Test compression with empty output."""
        observation = {"tool_name": "Read", "tool_output": ""}

        result = compressor.compress(observation)
        # Title may have trailing period from caveman compression
        assert result["title"].rstrip('.') == "Read execution"

    def test_compress_classifies_type(self, compressor):
        """Test observation type classification."""
        # File read
        obs_read = {"tool_name": "Read", "tool_output": "content"}
        assert compressor.compress(obs_read)["type"] == "discovery"

        # File edit
        obs_edit = {"tool_name": "Edit", "tool_output": "modified"}
        assert compressor.compress(obs_edit)["type"] == "change"

    def test_compress_extracts_facts(self, compressor):
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

        result = compressor.compress(observation)
        assert len(result["facts"]) > 0

    def test_compress_extracts_concepts(self, compressor):
        """Test concept extraction from output."""
        output = "Python code with FastAPI and SQLAlchemy"

        observation = {
            "tool_name": "Read",
            "tool_output": output,
        }

        result = compressor.compress(observation)
        assert len(result["concepts"]) > 0


# ==================== Progressive Retriever Tests ====================

class TestProgressiveRetriever:
    """Test 3-layer progressive retrieval."""

    def test_layer1_search_index(self, retriever, storage):
        """Test layer 1 search index."""
        # Add test data
        session_id = "test_session"
        storage.create_session(session_id, "user")

        for i in range(5):
            storage.add_observation({
                "session_id": session_id,
                "tool_name": "Read",
                "tool_output": f"Python code example {i}",
            })

        results = retriever.layer1_search_index("Python", limit=10)
        assert len(results) > 0
        assert all(hasattr(r, "id") for r in results)
        assert all(hasattr(r, "title") for r in results)

    def test_layer2_timeline(self, retriever, storage):
        """Test layer 2 timeline retrieval."""
        session_id = "test_session"
        storage.create_session(session_id, "user")

        obs_id = storage.add_observation({
            "session_id": session_id,
            "tool_name": "Read",
            "tool_output": "Python code",
        })

        timeline = retriever.layer2_timeline([obs_id])
        assert len(timeline) == 1
        assert hasattr(timeline[0], "narrative")

    def test_layer3_full_details(self, retriever, storage):
        """Test layer 3 full details retrieval."""
        session_id = "test_session"
        storage.create_session(session_id, "user")

        obs_id = storage.add_observation({
            "session_id": session_id,
            "tool_name": "Read",
            "tool_input": "file.py",
            "tool_output": "Python code with functions",
        })

        details = retriever.layer3_full_details([obs_id])
        assert len(details) == 1
        assert hasattr(details[0], "tool_name")
        assert hasattr(details[0], "tool_output")

    def test_auto_inject_context(self, retriever, storage):
        """Test automatic context injection."""
        session_id = "test_session"
        storage.create_session(session_id, "user")

        for i in range(3):
            storage.add_observation({
                "session_id": session_id,
                "tool_name": "Read",
                "tool_output": f"Important knowledge {i}",
            })

        result = retriever.auto_inject_context(
            "new_session", limit=10
        )

        assert "context_block" in result
        assert "observation_count" in result
        assert result["observation_count"] > 0


# ==================== Context Builder Tests ====================

class TestContextBuilder:
    """Test context building for LLM injection."""

    def test_build_session_start_context(self, context_builder, storage):
        """Test building session start context."""
        session_id = "test_session"
        storage.create_session(session_id, "user")

        storage.add_observation({
            "session_id": session_id,
            "tool_name": "Read",
            "tool_output": "Important knowledge",
        })

        context = context_builder.build_session_start_context(
            "new_session", limit=10
        )

        assert "<openlmlib-memory-context>" in context
        assert "Previous Session Context" in context

    def test_build_prompt_context(self, context_builder, storage):
        """Test building prompt-specific context."""
        session_id = "test_session"
        storage.create_session(session_id, "user")

        storage.add_observation({
            "session_id": session_id,
            "tool_name": "Read",
            "tool_output": "Python retrieval techniques",
        })

        context = context_builder.build_prompt_context(
            "new_session",
            "Python retrieval",
            limit=10
        )

        if context:  # May be empty if no matches
            assert "Relevant Previous Context" in context

    def test_build_progressive_context_layer1(self, context_builder, storage):
        """Test building progressive context (layer 1)."""
        session_id = "test_session"
        storage.create_session(session_id, "user")

        storage.add_observation({
            "session_id": session_id,
            "tool_name": "Read",
            "tool_output": "Python code",
        })

        result = context_builder.build_progressive_context(
            "new_session",
            "Python",
            layer=1,
            limit=10
        )

        assert result["layer"] == 1
        assert "context_block" in result


# ==================== Hook Registry Tests ====================

class TestHookRegistry:
    """Test hook registry and lifecycle."""

    def test_register_hook(self):
        """Test hook registration."""
        registry = HookRegistry()

        def handler(ctx):
            return {"result": "ok"}

        hook = Hook(HookType.SESSION_START, handler, priority=1)
        registry.register(hook)

        stats = registry.stats()
        assert stats["session_start"] == 1

    def test_trigger_hooks(self):
        """Test hook triggering."""
        registry = HookRegistry()

        results = []

        def handler1(ctx):
            results.append("handler1")
            return {"handler": "handler1"}

        def handler2(ctx):
            results.append("handler2")
            return {"handler": "handler2"}

        registry.register(Hook(HookType.SESSION_START, handler1, priority=1))
        registry.register(Hook(HookType.SESSION_START, handler2, priority=2))

        hook_results = registry.trigger(
            HookType.SESSION_START,
            {"session_id": "test"}
        )

        assert len(hook_results) == 2
        assert "handler1" in results
        assert "handler2" in results

    def test_priority_ordering(self):
        """Test hooks execute in priority order."""
        registry = HookRegistry()
        execution_order = []

        def make_handler(name):
            def handler(ctx):
                execution_order.append(name)
                return {"name": name}
            return handler

        registry.register(
            Hook(HookType.SESSION_START, make_handler("low"), priority=1)
        )
        registry.register(
            Hook(HookType.SESSION_START, make_handler("high"), priority=10)
        )

        registry.trigger(HookType.SESSION_START, {})

        # Higher priority should execute first
        assert execution_order == ["high", "low"]
