import unittest
import os
from pathlib import Path
from unittest.mock import patch

from openlmlib import mcp_server


class TestMcpServerTools(unittest.TestCase):
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

    def test_preimport_embedding_dependencies_can_be_disabled(self):
        with patch.dict(os.environ, {"OPENLMLIB_MCP_PREIMPORT_EMBEDDINGS": "0"}), \
             patch.object(mcp_server.importlib, "import_module") as import_module:
            result = mcp_server._preimport_embedding_dependencies()

        self.assertFalse(result)
        import_module.assert_not_called()

    def test_preimport_embedding_dependencies_imports_sentence_transformers(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(mcp_server.importlib, "import_module", return_value=object()) as import_module:
            result = mcp_server._preimport_embedding_dependencies()

        self.assertTrue(result)
        import_module.assert_called_once_with("sentence_transformers")


if __name__ == "__main__":
    unittest.main()
