import unittest
from pathlib import Path
from unittest.mock import patch

from openlmlib.cli import build_parser


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


if __name__ == "__main__":
    unittest.main()
