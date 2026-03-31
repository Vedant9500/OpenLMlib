import json
import tempfile
import unittest
from pathlib import Path

from lmlib.library import backup_library, restore_library


class TestBackupRestore(unittest.TestCase):
    def _write_settings(self, root: Path) -> Path:
        config_dir = root / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        settings_path = config_dir / "settings.json"
        settings = {
            "data_root": "data",
            "db_path": "data/findings.db",
            "vector_index_path": "data/embeddings.faiss",
            "vector_meta_path": "data/embeddings_meta.json",
            "findings_dir": "data/findings",
            "embeddings_cache_path": "data/embeddings_cache.pkl",
            "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
            "embedding_dim": 384,
            "embedding_metric": "cosine",
        }
        settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        return settings_path

    def _seed_data(self, root: Path) -> None:
        data = root / "data"
        findings = data / "findings"
        findings.mkdir(parents=True, exist_ok=True)

        (data / "findings.db").write_bytes(b"db")
        (data / "embeddings.faiss").write_bytes(b"index")
        (data / "embeddings_meta.json").write_text('{"backend":"numpy"}', encoding="utf-8")
        (data / "embeddings_cache.pkl").write_bytes(b"cache")
        (findings / "f-1.json").write_text('{"id":"f-1"}', encoding="utf-8")

    def test_backup_creates_manifest_and_copies_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings_path = self._write_settings(root)
            self._seed_data(root)

            result = backup_library(settings_path)

            self.assertEqual(result["status"], "ok")
            backup_dir = Path(result["backup_dir"])
            self.assertTrue((backup_dir / "manifest.json").exists())
            self.assertTrue((backup_dir / "findings.db").exists())
            self.assertTrue((backup_dir / "findings" / "f-1.json").exists())

    def test_restore_requires_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings_path = self._write_settings(root)
            backup_dir = root / "missing"

            result = restore_library(settings_path, backup_dir=backup_dir, confirm=False)
            self.assertEqual(result["status"], "confirmation_required")

    def test_restore_recovers_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings_path = self._write_settings(root)
            self._seed_data(root)

            backup = backup_library(settings_path)
            self.assertEqual(backup["status"], "ok")

            data = root / "data"
            (data / "findings.db").write_bytes(b"modified")
            (data / "findings" / "f-1.json").write_text('{"id":"changed"}', encoding="utf-8")

            restored = restore_library(
                settings_path,
                backup_dir=Path(backup["backup_dir"]),
                confirm=True,
                create_pre_restore_backup=False,
            )
            self.assertEqual(restored["status"], "ok")
            self.assertEqual((data / "findings.db").read_bytes(), b"db")
            self.assertIn('"f-1"', (data / "findings" / "f-1.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
