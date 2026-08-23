import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from openlmlib.cli import build_parser
from openlmlib.library import evaluate_dataset


class TestCli(unittest.TestCase):
    def test_default_settings_path_is_global(self):
        fake_home = Path("C:/Users/tester")
        with patch("pathlib.Path.home", return_value=fake_home):
            parser = build_parser()

        args = parser.parse_args(["setup", "--skip-model-warmup", "--skip-mcp-config"])
        self.assertEqual(
            args.settings,
            str(fake_home / ".openlmlib" / "config" / "settings.json"),
        )

    def test_eval_command_parsing(self):
        parser = build_parser()
        args = parser.parse_args(["eval", "--dataset", "config/eval_queries.json", "--final-k", "10"])
        self.assertEqual(args.command, "eval")
        self.assertEqual(args.dataset, "config/eval_queries.json")
        self.assertEqual(args.final_k, 10)


class TestEvalDatasetPathContainment(unittest.TestCase):
    """Eval datasets must live inside the configured library tree (L-1)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.settings_path = self.root / "config" / "settings.json"
        self.data_root = self.root / "data"
        self.data_root.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, dataset_path: Path):
        runtime = MagicMock()
        runtime.settings.data_root = self.data_root
        with patch("openlmlib.library.get_runtime", return_value=runtime):
            return evaluate_dataset(
                settings_path=self.settings_path,
                dataset_path=dataset_path,
                final_k=10,
            )

    def test_rejects_dataset_outside_library_tree(self):
        outside = Path(tempfile.gettempdir()) / "definitely-not-openlmlib-eval.json"
        result = self._run(outside)
        self.assertEqual(result["status"], "error")
        self.assertIn("data root", result["message"])

    def test_traversal_escape_is_rejected(self):
        result = self._run(self.root / "data" / ".." / ".." / "etc" / "passwd")
        self.assertEqual(result["status"], "error")
        self.assertIn("data root", result["message"])

    def test_allows_dataset_under_data_root(self):
        # Nonexistent contained file -> proceeds past the gate to existence
        # check instead of a containment rejection.
        inside = self.data_root / "eval_queries.json"
        result = self._run(inside)
        self.assertEqual(result["status"], "error")
        self.assertIn("Dataset not found", result["message"])

    def test_allows_dataset_in_settings_directory(self):
        config_dir = self.settings_path.parent
        config_dir.mkdir(parents=True, exist_ok=True)
        inside = config_dir / "eval_queries.json"
        result = self._run(inside)
        self.assertEqual(result["status"], "error")
        self.assertIn("Dataset not found", result["message"])


class TestCollabExportSessionIdValidation(unittest.TestCase):
    """CLI collab export must validate session IDs before path work (M-17)."""

    def _args(self, session_id):
        import argparse

        return argparse.Namespace(
            session_id=session_id,
            settings="/tmp/unused-settings.json",
            output_dir="/tmp/unused-output",
        )

    def test_traversal_session_id_rejected_without_filesystem_calls(self):
        from openlmlib import cli

        for bad in ("../../victim", "sess_1/../..", "abs/path", "back\\slash"):
            with patch.object(cli, "_collab_connection") as conn_factory:
                rc = cli.cmd_collab_export(self._args(bad))
                self.assertEqual(rc, 1, bad)
                conn_factory.assert_not_called()

    def test_malformed_session_id_rejected_before_connection(self):
        from openlmlib import cli

        with patch.object(cli, "_collab_connection") as conn_factory:
            rc = cli.cmd_collab_export(self._args("not-a-valid-session-id"))
            self.assertEqual(rc, 1)
            conn_factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
