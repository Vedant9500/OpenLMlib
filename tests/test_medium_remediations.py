"""Regression tests for Medium remediations M-3..M-7, M-11..M-16, M-18."""

import json
import logging
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from openlmlib.embeddings import EmbeddingCache
from openlmlib.library import backup_library, restore_library
from openlmlib.memory.context_builder import ContextBuilder
from openlmlib.memory.memory_retriever import ProgressiveRetriever
from openlmlib.memory.storage import MemoryStorage, normalize_limit
from openlmlib.usage_analytics import log_tool_call
from openlmlib.vector_store import NumpyVectorStore, load_vector_store


class _SettingsFixture:
    """Minimal settings/tmp fixture shared by backup-restore tests."""

    def write_settings(self, root: Path) -> Path:
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

    def seed_data(self, root: Path) -> None:
        data = root / "data"
        findings = data / "findings"
        findings.mkdir(parents=True, exist_ok=True)
        (data / "findings.db").write_bytes(b"db-bytes")
        (data / "embeddings.faiss").write_bytes(b"index-bytes")
        (data / "embeddings_meta.json").write_text('{"backend":"numpy"}', encoding="utf-8")
        (data / "embeddings_cache.pkl").write_bytes(b"cache-bytes")
        (findings / "f-1.json").write_text('{"id":"f-1"}', encoding="utf-8")


class TestLegacyCacheMigration(unittest.TestCase):
    """Legacy pickle caches are detected and preserved, not destroyed (M-12)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "cache" / "embeddings_cache.pkl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_pickle_signature_is_detected(self):
        from openlmlib.embeddings import _looks_like_legacy_pickle

        self.assertTrue(_looks_like_legacy_pickle(b"\x80\x04\x95abc"))
        self.assertFalse(_looks_like_legacy_pickle(b'{"key": [1.0]}'))

    def test_legacy_cache_loads_empty_and_warns(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(b"\x80\x04\x95hostile-pickle-payload")
        cache = EmbeddingCache(self.path)

        with self.assertLogs("openlmlib.embeddings", level="WARNING"):
            value = cache.get("anything")

        self.assertIsNone(value)  # nothing deserialized, no code execution

    def test_save_preserves_legacy_file_before_rewrite(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        legacy_bytes = b"\x80\x04\x95old-vectors"
        self.path.write_bytes(legacy_bytes)
        cache = EmbeddingCache(self.path)
        cache.set("k", [1.0, 2.0])

        with self.assertLogs("openlmlib.embeddings", level="WARNING"):
            cache.save()

        legacy_copy = self.path.with_suffix(self.path.suffix + ".legacy")
        self.assertTrue(legacy_copy.exists())
        self.assertEqual(legacy_copy.read_bytes(), legacy_bytes)
        # New file is valid JSON.
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertIn("k", payload)


class TestBackupManifestAndRestoreStaging(_SettingsFixture, unittest.TestCase):
    """Manifest integrity + staged restore (M-13, M-6)."""

    def test_manifest_records_version_and_checksums(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings_path = self.write_settings(root)
            self.seed_data(root)

            result = backup_library(settings_path)
            manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))

            self.assertGreaterEqual(manifest["format_version"], 2)
            files = {entry["path"]: entry for entry in manifest["files"]}
            self.assertIn("findings.db", files)
            self.assertIn("findings/f-1.json", files)
            self.assertEqual(len(files["findings.db"]["sha256"]), 64)

    def test_restore_aborts_on_tampered_backup_without_touching_live_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings_path = self.write_settings(root)
            self.seed_data(root)
            result = backup_library(settings_path)
            backup_dir = Path(result["backup_dir"])

            original_db = (root / "data" / "findings.db").read_bytes()

            # Tamper with a backed-up file after the checksum was recorded.
            tampered = backup_dir / "findings.db"
            tampered.write_bytes(b"tampered")

            restore = restore_library(settings_path, backup_dir, confirm=True)
            self.assertEqual(restore["status"], "error")
            self.assertIn("integrity", restore["message"])
            self.assertTrue(restore["problems"])
            self.assertEqual((root / "data" / "findings.db").read_bytes(), original_db)

    def test_unreadable_source_aborts_before_live_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings_path = self.write_settings(root)
            self.seed_data(root)
            result = backup_library(settings_path)
            backup_dir = Path(result["backup_dir"])

            live_db = root / "data" / "findings.db"
            original_db = live_db.read_bytes()

            with patch("openlmlib.library.shutil.copy2", side_effect=OSError("disk error")):
                with self.assertRaises(OSError):
                    restore_library(settings_path, backup_dir, confirm=True)

            # Live data survived the failed commit.
            self.assertEqual(live_db.read_bytes(), original_db)


class TestVectorPersistenceHardening(unittest.TestCase):
    """Vector load/merge failures fail closed instead of silently (M-7)."""

    def _write_index(self, path: Path, dim: int, ids, vectors):
        import numpy as np

        with path.open("wb") as handle:
            np.savez(
                handle,
                dim=np.asarray([dim], dtype=np.int64),
                ids=np.asarray(ids, dtype=np.int64),
                vectors=np.asarray(vectors, dtype=np.float32),
            )

    def test_corrupt_numpy_load_raises_not_replaced_with_empty_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path = root / "idx.npy"
            meta_path = root / "meta.json"
            self._write_index(index_path, dim=384, ids=[1], vectors=[[1.0] * 10])
            meta_path.write_text(json.dumps({
                "backend": "numpy", "dim": 384, "metric": "cosine",
                "index_path": str(index_path),
            }), encoding="utf-8")

            with self.assertRaises(RuntimeError):
                load_vector_store(index_path, meta_path)

    def test_meta_dim_mismatch_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path = root / "idx.npy"
            meta_path = root / "meta.json"
            self._write_index(index_path, dim=999, ids=[], vectors=[])
            meta_path.write_text(json.dumps({
                "backend": "numpy", "dim": 384, "metric": "cosine",
                "index_path": str(index_path),
            }), encoding="utf-8")

            with self.assertRaises(RuntimeError):
                load_vector_store(index_path, meta_path)

    def test_id_count_mismatch_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad = root / "bad.npy"
            self._write_index(bad, dim=3, ids=[1, 2, 3], vectors=[[1.0, 1.0, 1.0]])
            with self.assertRaises(ValueError):
                NumpyVectorStore.load(bad, "cosine")

    def test_shutdown_flush_failure_is_logged_loudly(self):
        from openlmlib.runtime import shutdown_runtime

        state = MagicMock()
        with patch("openlmlib.runtime._RUNTIMES", {"k": state}), \
             patch("openlmlib.runtime._runtime_key", return_value="k"), \
             patch("openlmlib.runtime.maybe_flush", side_effect=OSError("disk full")), \
             self.assertLogs("openlmlib.runtime", level="ERROR") as captured:
            shutdown_runtime(Path("/tmp/settings.json"))

        self.assertTrue(any("flush failed" in line.lower() for line in captured.output))


class TestAnalyticsRedaction(unittest.TestCase):
    """Analytics storage redacts and caps persisted content (M-15)."""

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("""
            CREATE TABLE tool_calls (
                id TEXT PRIMARY KEY, tool_name TEXT, called_at TEXT,
                call_mode TEXT, session_id TEXT, user_id TEXT, parameters TEXT,
                success INTEGER, error_message TEXT, execution_time_ms REAL,
                result_summary TEXT, workflow_position TEXT, triggered_by TEXT
            )
        """)

    def _last_row(self):
        return self.conn.execute(
            "SELECT * FROM tool_calls ORDER BY called_at DESC LIMIT 1"
        ).fetchone()

    def test_secrets_in_parameters_and_summary_are_redacted(self):
        log_tool_call(
            self.conn,
            tool_name="save_finding",
            parameters={"claim": "API_KEY=sk-live-supersecret123 and normal words"},
            result_summary="Saved finding: API_KEY=sk-live-supersecret123",
            error_message=None,
        )
        row = self._last_row()
        params = row["parameters"] or ""
        summary = row["result_summary"] or ""
        self.assertNotIn("sk-live-supersecret123", params)
        self.assertNotIn("sk-live-supersecret123", summary)
        self.assertIn("[REDACTED]", params + summary)

    def test_oversized_parameters_are_dropped_not_stored(self):
        log_tool_call(
            self.conn,
            tool_name="save_finding",
            parameters={"blob": "x" * 50_000},
            result_summary="ok",
        )
        row = self._last_row()
        params = json.loads(row["parameters"])
        self.assertTrue(params.get("_redacted"))

    def test_summary_is_length_capped(self):
        log_tool_call(
            self.conn,
            tool_name="t",
            result_summary="y" * 5_000,
        )
        row = self._last_row()
        self.assertLessEqual(len(row["result_summary"]), 200)


class TestWorkerSpecRestrictions(unittest.TestCase):
    """Worker specs cannot launch arbitrary executables or override env (M-11)."""

    def _spec(self, command, env=None, cwd=None):
        from openlmlib.co_scientist.worker_runner import WorkerLaunchSpec

        return WorkerLaunchSpec(
            session_id="sess_20260101_abcdef01",
            agent_role="worker",
            task_prompt="do analysis",
            command=command,
            env=env or {},
            cwd=cwd,
        )

    def test_foreign_executable_rejected_by_default(self):
        from openlmlib.co_scientist.worker_runner import WorkerRunnerError

        with self.assertRaises(WorkerRunnerError) as ctx:
            self._spec(["/usr/bin/touch", "/tmp/should-not-run"]).validate()
        self.assertIn("allow-list", str(ctx.exception))

    def test_current_python_allowed_by_default(self):
        self._spec([sys.executable, "-c", "print('hi')"]).validate()

    def test_protected_env_keys_rejected(self):
        from openlmlib.co_scientist.worker_runner import WorkerRunnerError

        with self.assertRaises(WorkerRunnerError) as ctx:
            self._spec(
                [sys.executable, "-c", "x"],
                env={"PATH": "/attacker/bin"},
            ).validate()
        self.assertIn("PATH", str(ctx.exception))

    def test_cwd_outside_workspace_rejected(self):
        from openlmlib.co_scientist.worker_runner import (
            ExternalWorkerRunner,
            WorkerRunnerError,
        )

        with tempfile.TemporaryDirectory() as tmp:
            workers_dir = Path(tmp) / "data" / "workers"
            runner = ExternalWorkerRunner(
                conn=MagicMock(),
                sessions_dir=Path(tmp) / "data" / "sessions",
                workers_dir=workers_dir,
            )
            with self.assertRaises(WorkerRunnerError):
                runner.validate_workspace_cwd(self._spec([sys.executable], cwd=Path("/tmp")))
            runner.validate_workspace_cwd(self._spec([sys.executable]))  # None ok
            inside = workers_dir / "run-1"
            inside.mkdir(parents=True, exist_ok=True)
            runner.validate_workspace_cwd(self._spec([sys.executable], cwd=inside))


class TestInstallerInterpolationGuard(unittest.TestCase):
    """Installer builds Python via JSON round-trip, not interpolation (M-18)."""

    REPO_ROOT = Path(__file__).resolve().parent.parent

    def test_no_direct_model_interpolation_into_python_source(self):
        wizard = (self.REPO_ROOT / "installer/src/ui/setup-wizard.js").read_text(encoding="utf-8")
        install_js = (self.REPO_ROOT / "installer/src/install.js").read_text(encoding="utf-8")
        for source in (wizard, install_js):
            self.assertNotIn('SentenceTransformer("${', source)
            self.assertNotIn("payload['embedding_model'] = '${", source)
        self.assertIn("json.loads", install_js)
        self.assertIn("json.loads", wizard)

    def test_generated_python_parses_for_hostile_values(self):
        # Mirror of the installer's JSON round-trip: hostile values must yield
        # parseable Python that treats them as data.
        import ast

        hostile = 'x"; import os; os.system("pwned"); "'
        payload_json = json.dumps({"embedding_model": hostile})
        script = f"import json\nconfig = json.loads({json.dumps(payload_json)!r})\nvalue = config['embedding_model']"
        tree = ast.parse(script)  # parses cleanly; hostile text is inert data


class TestMemoryPromptLogging(unittest.TestCase):
    """DEBUG logs never contain prompt text (M-16)."""

    def test_no_context_log_withholds_prompt_text(self):
        conn = sqlite3.connect(":memory:")
        storage = MemoryStorage(conn)
        retriever = ProgressiveRetriever(storage)
        builder = ContextBuilder(retriever)

        secret_prompt = "my-secret-project-codeword-alpha"
        logger = logging.getLogger("openlmlib.memory.context_builder")

        with self.assertLogs(logger, level="DEBUG") as captured:
            builder.build_prompt_context("current-session", secret_prompt, limit=5)

        joined = "\n".join(captured.output)
        self.assertNotIn(secret_prompt, joined)
        conn.close()


class TestNormalizeLimitHelper(unittest.TestCase):
    def test_defaults_and_caps(self):
        from openlmlib.memory.storage import MEMORY_LIMIT_MAX

        self.assertEqual(normalize_limit(-3, default=20), 20)
        self.assertEqual(normalize_limit(None, default=20), 20)
        self.assertEqual(normalize_limit(999_999_999, default=20), MEMORY_LIMIT_MAX)
        self.assertEqual(normalize_limit(12, default=20), 12)


if __name__ == "__main__":
    unittest.main()
