from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from typing import Dict, Iterable, List, Optional


SERVER_NAME = "openlmlib"


@dataclass(frozen=True)
class McpClientSpec:
    id: str
    label: str
    root_key: str


CLIENT_SPECS = (
    # IDEs (existing)
    McpClientSpec(id="vscode", label="VS Code", root_key="servers"),
    McpClientSpec(id="cursor", label="Cursor", root_key="mcpServers"),
    McpClientSpec(id="kiro", label="Kiro", root_key="mcpServers"),
    McpClientSpec(id="claude_desktop", label="Claude Desktop", root_key="mcpServers"),
    McpClientSpec(id="antigravity", label="Antigravity", root_key="mcpServers"),
    McpClientSpec(id="windsurf", label="Windsurf", root_key="mcpServers"),
    McpClientSpec(id="zed", label="Zed", root_key="context_servers"),
    McpClientSpec(id="cline", label="Cline", root_key="mcpServers"),
    McpClientSpec(id="openclaw", label="OpenClaw", root_key="mcpServers"),
    
    # CLI Coding Tools (NEW - Global configs)
    McpClientSpec(id="claude_code", label="Claude Code", root_key="mcpServers"),
    McpClientSpec(id="gemini_cli", label="Gemini CLI", root_key="mcpServers"),
    McpClientSpec(id="qwen_code", label="Qwen Code", root_key="mcpServers"),
    McpClientSpec(id="opencode", label="OpenCode", root_key="mcp"),
    McpClientSpec(id="codex_cli", label="Codex CLI", root_key="mcp_servers"),
    McpClientSpec(id="aider", label="Aider", root_key="mcp_servers"),
)

CLIENTS_BY_ID = {client.id: client for client in CLIENT_SPECS}

CLIENT_ALIASES = {
    # IDEs (existing)
    "code": "vscode",
    "vscode": "vscode",
    "vs-code": "vscode",
    "cursor": "cursor",
    "kiro": "kiro",
    "claude": "claude_desktop",
    "claude-desktop": "claude_desktop",
    "claude_desktop": "claude_desktop",
    "antigravity": "antigravity",
    "windsurf": "windsurf",
    "zed": "zed",
    "zed-editor": "zed",
    "cline": "cline",
    "openclaw": "openclaw",
    "open-claw": "openclaw",
    
    # CLI Coding Tools (NEW)
    "claude-code": "claude_code",
    "claude_code": "claude_code",
    "gemini": "gemini_cli",
    "gemini-cli": "gemini_cli",
    "gemini_cli": "gemini_cli",
    "qwen": "qwen_code",
    "qwen-code": "qwen_code",
    "qwen_code": "qwen_code",
    "opencode": "opencode",
    "open-code": "opencode",
    "open_code": "opencode",
    "codex": "codex_cli",
    "codex-cli": "codex_cli",
    "codex_cli": "codex_cli",
    "aider": "aider",
}


def _format_toml_value(value: object) -> str:
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_format_toml_value(item) for item in value) + "]"
    if value is None:
        return '""'
    return json.dumps(str(value))


_BARE_TOML_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _format_toml_key(key: str) -> str:
    """Format a TOML key segment, quoting paths/plugin ids when needed."""
    if _BARE_TOML_KEY_RE.match(key):
        return key
    return json.dumps(key)


def _dump_simple_toml(data: Dict[str, object]) -> str:
    """Serialize the simple TOML structures used by MCP client configs."""
    lines: List[str] = []

    def emit_table(table: Dict[str, object], path: List[str]) -> None:
        scalars = [(key, value) for key, value in table.items() if not isinstance(value, dict)]
        nested = [(key, value) for key, value in table.items() if isinstance(value, dict)]

        if path:
            if lines and lines[-1] != "":
                lines.append("")
            lines.append("[" + ".".join(_format_toml_key(segment) for segment in path) + "]")

        for key, value in scalars:
            lines.append(f"{_format_toml_key(key)} = {_format_toml_value(value)}")

        for key, value in nested:
            emit_table(value, path + [key])

    emit_table(data, [])
    return "\n".join(lines).rstrip() + "\n"


def available_clients() -> List[McpClientSpec]:
    return list(CLIENT_SPECS)


def normalize_client_ids(values: Optional[Iterable[str]]) -> List[str]:
    normalized: List[str] = []
    seen = set()

    for raw_value in values or []:
        for token in str(raw_value).replace(";", ",").split(","):
            value = token.strip().lower().replace(" ", "-")
            if not value:
                continue
            client_id = CLIENT_ALIASES.get(value)
            if client_id is None:
                raise ValueError(f"Unsupported IDE/client: {token.strip()}")
            if client_id in seen:
                continue
            seen.add(client_id)
            normalized.append(client_id)

    return normalized


def global_settings_path() -> Path:
    return Path.home() / ".openlmlib" / "config" / "settings.json"


def build_server_entry(settings_path: Path, client_id: str = "") -> Dict[str, object]:
    import sys

    resolved_settings = str(Path(settings_path).expanduser().resolve(strict=False))
    entry: Dict[str, object] = {
        "command": sys.executable,
        "args": ["-m", "openlmlib.mcp_server", "--settings", resolved_settings],
    }
    # OpenCode requires a "type" field to distinguish local vs remote servers
    if client_id == "opencode":
        entry["type"] = "local"
    return entry


def client_config_path(
    client_id: str,
    *,
    platform: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    home: Optional[Path] = None,
) -> Optional[Path]:
    platform = platform or os.sys.platform
    env = env or dict(os.environ)
    home = Path(home) if home is not None else Path.home()

    if client_id == "vscode":
        if platform == "win32":
            appdata = env.get("APPDATA")
            base = Path(appdata) if appdata else home / "AppData" / "Roaming"
            return base / "Code" / "User" / "mcp.json"
        if platform == "darwin":
            return home / "Library" / "Application Support" / "Code" / "User" / "mcp.json"
        return home / ".config" / "Code" / "User" / "mcp.json"

    if client_id == "cursor":
        return home / ".cursor" / "mcp.json"

    if client_id == "kiro":
        return home / ".kiro" / "settings" / "mcp.json"

    if client_id == "claude_desktop":
        if platform == "win32":
            appdata = env.get("APPDATA")
            base = Path(appdata) if appdata else home / "AppData" / "Roaming"
            return base / "Claude" / "claude_desktop_config.json"
        if platform == "darwin":
            return home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
        return None

    if client_id == "claude_code":
        # Global config: ~/.claude.json (primary) or ~/.claude/settings.json (fallback)
        # See: https://github.com/anthropics/claude-code/issues/15797
        return home / ".claude.json"

    if client_id == "gemini_cli":
        # Global config: ~/.gemini/settings.json
        # Applies to all Gemini CLI sessions for current user
        return home / ".gemini" / "settings.json"

    if client_id == "qwen_code":
        # Global config: ~/.qwen/settings.json
        # Applies to all Qwen Code sessions for current user
        return home / ".qwen" / "settings.json"

    if client_id == "opencode":
        # Global config: ~/.config/opencode/opencode.json (Linux/macOS)
        # On Windows: %APPDATA%/opencode/opencode.json
        if platform == "win32":
            appdata = env.get("APPDATA")
            base = Path(appdata) if appdata else home / "AppData" / "Roaming"
            return base / "opencode" / "opencode.json"
        return home / ".config" / "opencode" / "opencode.json"

    if client_id == "codex_cli":
        # Global config: ~/.codex/config.toml
        # CODEX_HOME env var overrides, defaults to ~/.codex
        codex_home = env.get("CODEX_HOME")
        if codex_home:
            return Path(codex_home) / "config.toml"
        return home / ".codex" / "config.toml"

    if client_id == "aider":
        # Global config: ~/.aider.conf.yml
        # Can also use ~/.aider.conf.json or ~/.aider.conf.toml
        return home / ".aider.conf.yml"

    if client_id == "antigravity":
        return home / ".gemini" / "antigravity" / "mcp_config.json"

    if client_id == "windsurf":
        return home / ".codeium" / "windsurf" / "mcp_config.json"

    if client_id == "zed":
        if platform == "win32":
            appdata = env.get("LOCALAPPDATA")
            base = Path(appdata) if appdata else home / "AppData" / "Local"
            return base / "Zed" / "settings.json"
        if platform == "darwin":
            return home / "Library" / "Application Support" / "Zed" / "settings.json"
        return home / ".config" / "zed" / "settings.json"

    if client_id == "cline":
        if platform == "win32":
            appdata = env.get("APPDATA")
            base = Path(appdata) if appdata else home / "AppData" / "Roaming"
            return base / "Code" / "User" / "globalStorage" / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json"
        if platform == "darwin":
            return home / "Library" / "Application Support" / "Code" / "User" / "globalStorage" / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json"
        return home / ".config" / "Code" / "User" / "globalStorage" / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json"

    if client_id == "openclaw":
        return home / ".openclaw" / "openclaw.json"

    raise ValueError(f"Unknown client id: {client_id}")


def _yaml_scalar(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if text == "" or any(ch in text for ch in ":#{}[]&*!|>'\"%@`") or text.strip() != text:
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return text


def _dump_simple_yaml(data: object, indent: int = 0) -> str:
    """Minimal YAML serializer for nested dict/list MCP configs (no PyYAML required)."""
    pad = "  " * indent
    if isinstance(data, dict):
        if not data:
            return "{}\n" if indent == 0 else "{}"
        lines: List[str] = []
        for key, value in data.items():
            key_text = str(key)
            if isinstance(value, dict):
                if not value:
                    lines.append(f"{pad}{key_text}: {{}}")
                else:
                    lines.append(f"{pad}{key_text}:")
                    lines.append(_dump_simple_yaml(value, indent + 1).rstrip("\n"))
            elif isinstance(value, list):
                if not value:
                    lines.append(f"{pad}{key_text}: []")
                else:
                    lines.append(f"{pad}{key_text}:")
                    lines.append(_dump_simple_yaml(value, indent + 1).rstrip("\n"))
            else:
                lines.append(f"{pad}{key_text}: {_yaml_scalar(value)}")
        return "\n".join(lines) + ("\n" if indent == 0 else "")
    if isinstance(data, list):
        if not data:
            return "[]\n" if indent == 0 else "[]"
        lines = []
        for item in data:
            if isinstance(item, (dict, list)):
                nested = _dump_simple_yaml(item, indent + 1).rstrip("\n")
                lines.append(f"{pad}-")
                lines.append(nested)
            else:
                lines.append(f"{pad}- {_yaml_scalar(item)}")
        return "\n".join(lines) + ("\n" if indent == 0 else "")
    return f"{pad}{_yaml_scalar(data)}\n"


def _load_existing_config(path: Path, client_id: str = "") -> Dict[str, object]:
    if not path.exists():
        return {}

    raw_text = path.read_text(encoding="utf-8")
    if not raw_text.strip():
        return {}

    # Handle TOML format for Codex CLI
    if client_id == "codex_cli" or path.suffix == ".toml":
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # Python < 3.11 fallback
        
        payload = tomllib.loads(raw_text)
        if not isinstance(payload, dict):
            raise ValueError(f"Expected a TOML object in {path}")
        return payload

    # YAML for Aider and other .yml/.yaml configs
    if client_id == "aider" or path.suffix.lower() in {".yml", ".yaml"}:
        try:
            import yaml  # type: ignore
            payload = yaml.safe_load(raw_text)
            if payload is None:
                return {}
            if not isinstance(payload, dict):
                raise ValueError(f"Expected a YAML object in {path}")
            return payload
        except ImportError:
            # Prefer JSON when PyYAML is unavailable (handles prior JSON-into-yml installs).
            try:
                payload = json.loads(raw_text)
                if isinstance(payload, dict):
                    return payload
            except Exception:
                return {}
            return {}

    # Default JSON handling
    payload = json.loads(raw_text)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return payload


def _prepare_config_root(client: McpClientSpec, payload: Dict[str, object]) -> Dict[str, object]:
    if client.id == "vscode" and "servers" not in payload and isinstance(payload.get("mcpServers"), dict):
        payload["servers"] = payload.pop("mcpServers")

    root = payload.get(client.root_key)
    if root is None:
        payload[client.root_key] = {}
        return payload

    if not isinstance(root, dict):
        raise ValueError(f"Expected '{client.root_key}' to be a JSON object")

    return payload


def install_client_config(
    client_id: str,
    *,
    settings_path: Path,
    platform: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    home: Optional[Path] = None,
) -> Dict[str, object]:
    client = CLIENTS_BY_ID.get(client_id)
    if client is None:
        return {
            "client": client_id,
            "label": client_id,
            "status": "skipped",
            "message": "Unsupported client in this OpenLMlib version",
        }

    target_path = client_config_path(client_id, platform=platform, env=env, home=home)

    if target_path is None:
        return {
            "client": client.id,
            "label": client.label,
            "status": "unsupported_platform",
        }

    try:
        target_existed = target_path.exists()
        payload = _load_existing_config(target_path, client_id)
        payload = _prepare_config_root(client, payload)
        root = payload[client.root_key]
        assert isinstance(root, dict)
        new_entry = build_server_entry(settings_path, client_id=client_id)
        changed = root.get(SERVER_NAME) != new_entry
        root[SERVER_NAME] = new_entry

        if changed or not target_existed:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Handle TOML serialization for Codex CLI
            if client_id == "codex_cli" or target_path.suffix == ".toml":
                try:
                    import tomli_w
                except ImportError:
                    tomli_w = None
                
                if tomli_w:
                    target_path.write_text(tomli_w.dumps(payload), encoding="utf-8")
                else:
                    target_path.write_text(_dump_simple_toml(payload), encoding="utf-8")
            elif client_id == "aider" or target_path.suffix.lower() in {".yml", ".yaml"}:
                try:
                    import yaml  # type: ignore
                    target_path.write_text(
                        yaml.safe_dump(payload, sort_keys=False, default_flow_style=False),
                        encoding="utf-8",
                    )
                except ImportError:
                    target_path.write_text(_dump_simple_yaml(payload), encoding="utf-8")
            else:
                # Default JSON serialization
                target_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        return {
            "client": client.id,
            "label": client.label,
            "status": "ok",
            "path": str(target_path),
            "updated": changed or not target_existed,
        }
    except Exception as exc:
        return {
            "client": client.id,
            "label": client.label,
            "status": "error",
            "path": str(target_path),
            "message": str(exc),
        }


def install_client_configs(
    client_ids: Iterable[str],
    *,
    settings_path: Path,
    platform: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    home: Optional[Path] = None,
) -> Dict[str, object]:
    results = [
        install_client_config(
            client_id,
            settings_path=settings_path,
            platform=platform,
            env=env,
            home=home,
        )
        for client_id in client_ids
    ]

    if not results:
        status = "skipped"
    elif all(result.get("status") in {"ok", "skipped"} for result in results):
        status = "ok"
    elif any(result.get("status") == "ok" for result in results):
        status = "partial"
    else:
        status = "error"

    return {
        "status": status,
        "settings_path": str(Path(settings_path).expanduser().resolve(strict=False)),
        "results": results,
    }


def discover_existing_client_ids(
    *,
    platform: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    home: Optional[Path] = None,
) -> List[str]:
    discovered: List[str] = []
    for client in CLIENT_SPECS:
        path = client_config_path(client.id, platform=platform, env=env, home=home)
        if path is None:
            continue
        if path.exists():
            discovered.append(client.id)
    return discovered


def install_or_refresh_default_client_configs(
    *,
    settings_path: Path,
    platform: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    home: Optional[Path] = None,
) -> Dict[str, object]:
    # Upgrade MCP entries for clients the user already configured.
    # If no client config exists yet, seed VS Code + popular CLI tools by default.
    client_ids = discover_existing_client_ids(platform=platform, env=env, home=home)
    if not client_ids:
        # Default to VS Code + top CLI tools with native MCP support
        client_ids = ["vscode", "claude_code", "gemini_cli", "qwen_code", "opencode", "codex_cli"]

    return install_client_configs(
        client_ids,
        settings_path=settings_path,
        platform=platform,
        env=env,
        home=home,
    )
