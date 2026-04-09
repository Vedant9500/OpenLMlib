import json
import tempfile
import unittest
from pathlib import Path

from openlmlib.library import health, init_library


class TestHealth(unittest.TestCase):
    def _write_settings(self, root: Path) -> Path:
        config_dir = root / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        settings_path = config_dir / "settings.json"
        settings_path.write_text(
            json.dumps(
                {
                    "data_root": "data",
                    "db_path": "data/findings.db",
                    "vector_index_path": "data/embeddings.faiss",
                    "vector_meta_path": "data/embeddings_meta.json",
                    "findings_dir": "data/findings",
                    "embeddings_cache_path": "data/embeddings_cache.pkl",
                    "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
                    "embedding_dim": 384,
                    "embedding_metric": "cosine",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return settings_path

    def test_health_reports_vector_store_status(self):
        """Test health() reports vector store status from in-memory runtime.

        Note: health() now uses the in-memory runtime store instead of reloading
        from disk for performance. This means it reports the store's current state,
        not whether the file exists on disk (which only matters on restart).
        """
        from openlmlib.runtime import shutdown_runtime

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings_path = self._write_settings(root)
            init_result = init_library(settings_path)
            self.assertEqual(init_result["status"], "ok")

            # Health should report OK since runtime loaded the store successfully
            result = health(settings_path)
            self.assertEqual(result["status"], "ok")
            self.assertIn("vector_backend", result["health"])
            self.assertIn("vector_count", result["health"])

            # Clean up runtime so temp directory can be removed
            shutdown_runtime(settings_path)


if __name__ == "__main__":
    unittest.main()
