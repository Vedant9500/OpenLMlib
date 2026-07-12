import unittest
from pathlib import Path
from unittest.mock import patch

from openlmlib import tui_setup


class TestTuiSetup(unittest.TestCase):
    def test_passes_settings_path_via_env(self):
        settings = Path("D:/custom/config/settings.json")
        with patch.object(tui_setup.shutil, "which", return_value="node"), \
             patch.object(tui_setup.subprocess, "run") as run:
            run.return_value.returncode = 0
            # Point wizard path at a temp-looking existing path by stubbing Path.exists
            fake_run_setup = Path("installer/src/run-setup.mjs")
            with patch.object(Path, "exists", return_value=True):
                result = tui_setup.run_interactive_setup(settings)

        self.assertEqual(result["status"], "ok")
        env = run.call_args.kwargs["env"]
        self.assertIn("OPENLMLIB_SETTINGS", env)
        self.assertTrue(env["OPENLMLIB_SETTINGS"].replace("\\", "/").endswith("custom/config/settings.json") or "settings.json" in env["OPENLMLIB_SETTINGS"])


if __name__ == "__main__":
    unittest.main()
