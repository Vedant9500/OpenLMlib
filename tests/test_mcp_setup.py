import json
import sys
import tempfile
import unittest
from pathlib import Path
try:
    import tomllib
except ImportError:  # pragma: no cover
    import tomli as tomllib

from openlmlib.mcp_setup import (
    install_client_config,
    install_or_refresh_default_client_configs,
    normalize_client_ids,
)


class TestMcpSetup(unittest.TestCase):
    def test_normalize_client_ids_deduplicates_aliases(self):
        client_ids = normalize_client_ids(["VS Code, cursor", "code", "kiro", "antigravity"])
        self.assertEqual(client_ids, ["vscode", "cursor", "kiro", "antigravity"])

    def test_install_aider_writes_yaml_not_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            settings_path = home / ".openlmlib" / "config" / "settings.json"
            result = install_client_config(
                "aider",
                settings_path=settings_path,
                platform="linux",
                home=home,
            )
            self.assertEqual(result["status"], "ok")
            config_path = home / ".aider.conf.yml"
            raw = config_path.read_text(encoding="utf-8")
            self.assertFalse(raw.lstrip().startswith("{"))
            self.assertIn("mcp_servers:", raw)
            self.assertIn("openlmlib:", raw)
            self.assertIn("command:", raw)
            self.assertIn("-m", raw)

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
            self.assertEqual(payload["servers"]["openlmlib"]["command"], sys.executable)
            self.assertEqual(
                payload["servers"]["openlmlib"]["args"],
                ["-m", "openlmlib.mcp_server", "--settings", str(settings_path.resolve())],
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

    def test_install_opencode_uses_current_mcp_entry_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            settings_path = home / ".openlmlib" / "config" / "settings.json"

            result = install_client_config(
                "opencode",
                settings_path=settings_path,
                platform="linux",
                home=home,
            )

            self.assertEqual(result["status"], "ok")
            config_path = home / ".config" / "opencode" / "opencode.json"
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            entry = payload["mcp"]["openlmlib"]
            self.assertEqual(entry["type"], "local")
            self.assertTrue(entry["enabled"])
            self.assertEqual(
                entry["command"],
                [
                    sys.executable,
                    "-m",
                    "openlmlib.mcp_server",
                    "--settings",
                    str(settings_path.resolve()),
                ],
            )
            self.assertNotIn("args", entry)

    def test_refresh_defaults_prefers_existing_client_configs(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            settings_path = home / ".openlmlib" / "config" / "settings.json"

            # Seed only Cursor config to emulate an existing install.
            cursor_path = home / ".cursor" / "mcp.json"
            cursor_path.parent.mkdir(parents=True, exist_ok=True)
            cursor_path.write_text("{}", encoding="utf-8")

            result = install_or_refresh_default_client_configs(
                settings_path=settings_path,
                platform="linux",
                home=home,
            )

            self.assertEqual(result["status"], "ok")
            configured = {item["client"] for item in result["results"]}
            self.assertEqual(configured, {"cursor"})

    def test_refresh_defaults_falls_back_to_vscode_and_cli_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            settings_path = home / ".openlmlib" / "config" / "settings.json"

            result = install_or_refresh_default_client_configs(
                settings_path=settings_path,
                platform="linux",
                home=home,
            )

            self.assertEqual(result["status"], "ok")
            configured = {item["client"] for item in result["results"]}
            # Default includes VS Code + popular CLI tools with native MCP support
            self.assertEqual(configured, {"vscode", "claude_code", "gemini_cli", "qwen_code", "opencode", "codex_cli"})

    def test_install_codex_cli_preserves_existing_toml_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            settings_path = home / ".openlmlib" / "config" / "settings.json"
            config_path = home / ".codex" / "config.toml"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                'model = "gpt-5"\n\n[profiles.default]\nreasoning_effort = "medium"\n',
                encoding="utf-8",
            )

            result = install_client_config(
                "codex_cli",
                settings_path=settings_path,
                platform="linux",
                home=home,
            )

            self.assertEqual(result["status"], "ok")
            payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["model"], "gpt-5")
            self.assertEqual(payload["profiles"]["default"]["reasoning_effort"], "medium")
            self.assertIn("openlmlib", payload["mcp_servers"])


if __name__ == "__main__":
    unittest.main()
