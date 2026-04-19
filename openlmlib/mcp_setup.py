from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
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
        # Linux support for Claude Desktop
        return home / ".config" / "Claude" / "claude_desktop_config.json"

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
        payload = _load_existing_config(target_path, client_id)
        payload = _prepare_config_root(client, payload)
        root = payload[client.root_key]
        assert isinstance(root, dict)
        new_entry = build_server_entry(settings_path, client_id=client_id)
        changed = root.get(SERVER_NAME) != new_entry
        root[SERVER_NAME] = new_entry

        if changed or not target_path.exists():
            target_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Handle TOML serialization for Codex CLI
            if client_id == "codex_cli" or target_path.suffix == ".toml":
                try:
                    import tomli_w
                except ImportError:
                    # Fallback: try tomllib (write not supported), use simple serializer
                    try:
                        import tomllib
                    except ImportError:
                        import tomli as tomllib
                    
                    # Simple TOML serializer for basic dict structures
                    def _serialize_toml(data: dict, indent: int = 0) -> str:
                        lines = []
                        prefix = "  " * indent
                        for key, value in data.items():
                            if isinstance(value, dict):
                                lines.append(f"{prefix}[{key}]")
                                lines.append(_serialize_toml(value, indent + 1))
                            elif isinstance(value, str):
                                lines.append(f'{prefix}{key} = "{value}"')
                            elif isinstance(value, list):
                                lines.append(f"{prefix}{key} = {value}")
                            elif isinstance(value, bool):
                                lines.append(f"{prefix}{key} = {'true' if value else 'false'}")
                            elif isinstance(value, (int, float)):
                                lines.append(f"{prefix}{key} = {value}")
                        return "\n".join(lines)
                    
                    tomli_w = None
                
                if tomli_w:
                    target_path.write_text(tomli_w.dumps(payload), encoding="utf-8")
                else:
                    # Simple TOML writer for MCP config
                    lines = []
                    lines.append("# OpenLMlib MCP Server Configuration")
                    lines.append("")
                    lines.append("[mcp_servers.openlmlib]")
                    lines.append(f'command = "{new_entry["command"]}"')
                    args_list = ', '.join(f'"{arg}"' for arg in new_entry["args"])
                    lines.append(f"args = [{args_list}]")
                    target_path.write_text("\n".join(lines), encoding="utf-8")
            else:
                # Default JSON serialization
                target_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        return {
            "client": client.id,
            "label": client.label,
            "status": "ok",
            "path": str(target_path),
            "updated": changed or not target_path.exists(),
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
