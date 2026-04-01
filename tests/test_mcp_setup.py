import json
import tempfile
import unittest
from pathlib import Path

from openlmlib.mcp_setup import install_client_config, normalize_client_ids


class TestMcpSetup(unittest.TestCase):
    def test_normalize_client_ids_deduplicates_aliases(self):
        client_ids = normalize_client_ids(["VS Code, cursor", "code", "kiro", "antigravity"])
        self.assertEqual(client_ids, ["vscode", "cursor", "kiro", "antigravity"])

    def test_install_vscode_global_config_uses_servers_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            settings_path = home / ".openlmlib" / "config" / "settings.json"

            result = install_client_config(
                "vscode",
                settings_path=settings_path,
                platform="linux",
                home=home,
            )

            self.assertEqual(result["status"], "ok")
            config_path = home / ".config" / "Code" / "User" / "mcp.json"
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertIn("servers", payload)
            self.assertNotIn("mcpServers", payload)
            self.assertEqual(payload["servers"]["openlmlib"]["command"], "openlmlib-mcp")
            self.assertEqual(
                payload["servers"]["openlmlib"]["args"],
                ["--settings", str(settings_path.resolve())],
            )

    def test_install_vscode_global_config_migrates_old_root_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            config_path = home / ".config" / "Code" / "User" / "mcp.json"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                json.dumps(
                    {
                        "mcpServers": {
                            "legacy": {
                                "command": "legacy-server",
                                "args": [],
                            }
                        }
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            result = install_client_config(
                "vscode",
                settings_path=home / ".openlmlib" / "config" / "settings.json",
                platform="linux",
                home=home,
            )

            self.assertEqual(result["status"], "ok")
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertIn("servers", payload)
            self.assertNotIn("mcpServers", payload)
            self.assertIn("legacy", payload["servers"])
            self.assertIn("openlmlib", payload["servers"])

    def test_install_vscode_global_config_accepts_empty_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            config_path = home / ".config" / "Code" / "User" / "mcp.json"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text("", encoding="utf-8")

            result = install_client_config(
                "vscode",
                settings_path=home / ".openlmlib" / "config" / "settings.json",
                platform="linux",
                home=home,
            )

            self.assertEqual(result["status"], "ok")
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertIn("servers", payload)
            self.assertIn("openlmlib", payload["servers"])

    def test_claude_desktop_reports_unsupported_platform_on_linux(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            result = install_client_config(
                "claude_desktop",
                settings_path=home / ".openlmlib" / "config" / "settings.json",
                platform="linux",
                home=home,
            )

            self.assertEqual(result["status"], "unsupported_platform")

    def test_install_antigravity_global_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            settings_path = home / ".openlmlib" / "config" / "settings.json"

            result = install_client_config(
                "antigravity",
                settings_path=settings_path,
                platform="linux",
                home=home,
            )

            self.assertEqual(result["status"], "ok")
            config_path = home / ".gemini" / "antigravity" / "mcp_config.json"
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertIn("mcpServers", payload)
            self.assertIn("openlmlib", payload["mcpServers"])


if __name__ == "__main__":
    unittest.main()
