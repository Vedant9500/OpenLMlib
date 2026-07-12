import unittest
import os
from pathlib import Path
from unittest.mock import patch

from openlmlib import mcp_server


class TestMcpServerTools(unittest.TestCase):
    def test_save_finding_includes_session_warning(self):
        settings_path = Path("config/settings.json")
        with patch.object(mcp_server, "_settings_path", return_value=settings_path), \
             patch.object(mcp_server, "search_fts", return_value={"status": "ok", "items": []}), \
             patch.object(mcp_server, "_check_active_sessions", return_value="No active session"), \
             patch.object(mcp_server, "add_finding", return_value={"status": "ok", "id": "f-1"}) as add, \
             patch.object(mcp_server, "get_runtime") as get_runtime:
            get_runtime.return_value.conn = object()
            with patch("openlmlib.usage_analytics.log_tool_call"):
                result = mcp_server.save_finding(
                    project="demo",
                    claim="A finding claim",
                    confidence=0.9,
                    confirm=True,
                )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["session_warning"], "No active session")
        add.assert_called_once()

    def test_ensure_tools_registered_is_idempotent(self):
        mcp_server._memory_registered = False
        mcp_server._collab_registered = False
        with patch.object(mcp_server, "_register_memory_tools") as mem, \
             patch.object(mcp_server, "_register_collab_tools") as collab:
            mcp_server.ensure_tools_registered()
            mcp_server.ensure_tools_registered()
        self.assertEqual(mem.call_count, 2)
        self.assertEqual(collab.call_count, 2)

    def test_search_knowledge_uses_hybrid_retriever(self):
        settings_path = Path("config/settings.json")
        hybrid_payload = {
            "status": "ok",
            "items": [{"id": "f-1", "claim": "Hybrid result"}],
        }

        with patch.object(mcp_server, "_settings_path", return_value=settings_path), \
             patch.object(mcp_server, "lib_retrieve_findings", return_value=hybrid_payload) as hybrid, \
             patch.object(mcp_server, "search_fts") as keyword:
            result = mcp_server.search_knowledge("cache latency", limit=3)

        hybrid.assert_called_once_with(
            settings_path=settings_path,
            query="cache latency",
            final_k=3,
        )
        keyword.assert_not_called()
        self.assertEqual(result["source"], "hybrid")
        self.assertEqual(result["items"], hybrid_payload["items"])

    def test_preimport_embedding_dependencies_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(mcp_server.importlib, "import_module") as import_module:
            result = mcp_server._preimport_embedding_dependencies()

        self.assertFalse(result)
        import_module.assert_not_called()

    def test_preimport_embedding_dependencies_can_be_explicitly_disabled(self):
        with patch.dict(os.environ, {"OPENLMLIB_MCP_PREIMPORT_EMBEDDINGS": "0"}), \
             patch.object(mcp_server.importlib, "import_module") as import_module:
            result = mcp_server._preimport_embedding_dependencies()

        self.assertFalse(result)
        import_module.assert_not_called()

    def test_preimport_embedding_dependencies_imports_sentence_transformers_when_enabled(self):
        with patch.dict(os.environ, {"OPENLMLIB_MCP_PREIMPORT_EMBEDDINGS": "1"}, clear=True), \
             patch.object(mcp_server.importlib, "import_module", return_value=object()) as import_module:
            result = mcp_server._preimport_embedding_dependencies()

        self.assertTrue(result)
        import_module.assert_called_once_with("sentence_transformers")

    def test_runtime_background_prewarm_delayed_by_default(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch("threading.Thread") as thread_cls:
            result = mcp_server._ensure_runtime_background()

        thread_cls.assert_called_once_with(
            target=mcp_server._ensure_runtime_after_delay,
            args=(5.0,),
            daemon=True,
            name="openlmlib-runtime-prewarm",
        )
        thread_cls.return_value.start.assert_called_once_with()
        self.assertIs(result, thread_cls.return_value)

    def test_runtime_background_prewarm_can_be_disabled(self):
        with patch.dict(os.environ, {"OPENLMLIB_MCP_PREWARM": "0"}, clear=True), \
             patch("threading.Thread") as thread_cls:
            result = mcp_server._ensure_runtime_background()

        self.assertIsNone(result)
        thread_cls.assert_not_called()

    def test_runtime_background_prewarm_uses_configured_delay(self):
        with patch.dict(
            os.environ,
            {
                "OPENLMLIB_MCP_PREWARM": "1",
                "OPENLMLIB_MCP_PREWARM_DELAY_SEC": "0.25",
            },
            clear=True,
        ), \
             patch("threading.Thread") as thread_cls:
            result = mcp_server._ensure_runtime_background()

        thread_cls.assert_called_once_with(
            target=mcp_server._ensure_runtime_after_delay,
            args=(0.25,),
            daemon=True,
            name="openlmlib-runtime-prewarm",
        )
        thread_cls.return_value.start.assert_called_once_with()
        self.assertIs(result, thread_cls.return_value)

    def test_full_registration_includes_co_scientist_discovery_surface(self):
        mcp_server._register_memory_tools()
        mcp_server._register_collab_tools()

        tools = set(mcp_server.mcp._tool_manager._tools)
        self.assertGreaterEqual(len(tools), 76)
        for tool_name in {
            "query_memory",
            "screen_co_scientist_scope",
            "create_co_scientist_run",
            "start_hypothesis_verification",
            "get_co_scientist_report",
            "create_co_scientist_final_report",
        }:
            self.assertIn(tool_name, tools)

        help_result = mcp_server.help_library("create_co_scientist_run")
        description = help_result["description"]
        self.assertIn("Co-Scientist", description)
        self.assertIn("independent verification", description)
        self.assertIn("multi-agent research", description)


if __name__ == "__main__":
    unittest.main()
