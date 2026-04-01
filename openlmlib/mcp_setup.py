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
    McpClientSpec(id="vscode", label="VS Code", root_key="servers"),
    McpClientSpec(id="cursor", label="Cursor", root_key="mcpServers"),
    McpClientSpec(id="kiro", label="Kiro", root_key="mcpServers"),
    McpClientSpec(id="claude_desktop", label="Claude Desktop", root_key="mcpServers"),
)

CLIENTS_BY_ID = {client.id: client for client in CLIENT_SPECS}

CLIENT_ALIASES = {
    "code": "vscode",
    "vscode": "vscode",
    "vs-code": "vscode",
    "cursor": "cursor",
    "kiro": "kiro",
    "claude": "claude_desktop",
    "claude-desktop": "claude_desktop",
    "claude_desktop": "claude_desktop",
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


def build_server_entry(settings_path: Path) -> Dict[str, object]:
    resolved_settings = str(Path(settings_path).expanduser().resolve(strict=False))
    return {
        "command": "openlmlib-mcp",
        "args": ["--settings", resolved_settings],
    }


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

    raise ValueError(f"Unknown client id: {client_id}")


def _load_existing_config(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {}

    payload = json.loads(path.read_text(encoding="utf-8"))
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
    client = CLIENTS_BY_ID[client_id]
    target_path = client_config_path(client_id, platform=platform, env=env, home=home)

    if target_path is None:
        return {
            "client": client.id,
            "label": client.label,
            "status": "unsupported_platform",
        }

    try:
        payload = _load_existing_config(target_path)
        payload = _prepare_config_root(client, payload)
        root = payload[client.root_key]
        assert isinstance(root, dict)
        new_entry = build_server_entry(settings_path)
        changed = root.get(SERVER_NAME) != new_entry
        root[SERVER_NAME] = new_entry

        if changed or not target_path.exists():
            target_path.parent.mkdir(parents=True, exist_ok=True)
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
    elif all(result.get("status") == "ok" for result in results):
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
