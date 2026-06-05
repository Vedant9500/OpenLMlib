#!/usr/bin/env python3
"""Check OpenLMlib MCP entries in supported client config files."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

try:
    import tomllib
except ImportError:  # pragma: no cover
    import tomli as tomllib

from openlmlib.mcp_setup import (
    CLIENTS_BY_ID,
    SERVER_NAME,
    available_clients,
    client_config_path,
    normalize_client_ids,
)


def _load_config(path: Path, client_id: str) -> dict:
    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        return {}

    if client_id == "codex_cli" or path.suffix == ".toml":
        payload = tomllib.loads(raw)
    else:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            # JSON is valid YAML, and OpenLMlib writes JSON-shaped config even
            # for a few clients whose config file extension is .yml.
            try:
                import yaml  # type: ignore

                payload = yaml.safe_load(raw)
            except Exception as exc:
                raise ValueError(f"could not parse JSON/YAML config: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError("config root is not an object")
    return payload


def _settings_from_args(args: list[object]) -> str | None:
    values = [str(value) for value in args]
    for index, value in enumerate(values):
        if value == "--settings" and index + 1 < len(values):
            return values[index + 1]
        if value.startswith("--settings="):
            return value.split("=", 1)[1]
    return None


def _same_path(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    return str(Path(left).expanduser().resolve(strict=False)) == str(
        Path(right).expanduser().resolve(strict=False)
    )


def check_client(client_id: str, expected_settings: str | None) -> dict:
    client = CLIENTS_BY_ID[client_id]
    path = client_config_path(client_id)
    if path is None:
        return {
            "client": client_id,
            "label": client.label,
            "status": "unsupported_platform",
        }
    if not path.exists():
        return {
            "client": client_id,
            "label": client.label,
            "status": "missing_config",
            "path": str(path),
        }

    try:
        payload = _load_config(path, client_id)
    except Exception as exc:
        return {
            "client": client_id,
            "label": client.label,
            "status": "error",
            "path": str(path),
            "message": str(exc),
        }

    root = payload.get(client.root_key)
    if not isinstance(root, dict):
        return {
            "client": client_id,
            "label": client.label,
            "status": "missing_root",
            "path": str(path),
            "root_key": client.root_key,
        }

    entry = root.get(SERVER_NAME)
    if not isinstance(entry, dict):
        return {
            "client": client_id,
            "label": client.label,
            "status": "missing_server",
            "path": str(path),
            "root_key": client.root_key,
        }

    command = str(entry.get("command", ""))
    args = entry.get("args", [])
    if not isinstance(args, list):
        args = []
    settings_arg = _settings_from_args(args)

    warnings: list[str] = []
    if not command:
        warnings.append("server command is empty")
    elif not Path(command).expanduser().exists() and os.path.sep in command:
        warnings.append("server command path does not exist")
    if "-m" not in [str(value) for value in args] or "openlmlib.mcp_server" not in [str(value) for value in args]:
        warnings.append("args do not launch openlmlib.mcp_server")
    if expected_settings and not _same_path(settings_arg, expected_settings):
        warnings.append(f"settings path differs from expected {expected_settings}")

    return {
        "client": client_id,
        "label": client.label,
        "status": "warning" if warnings else "ok",
        "path": str(path),
        "root_key": client.root_key,
        "command": command,
        "args": args,
        "settings": settings_arg,
        "warnings": warnings,
    }


def _print_result(result: dict) -> None:
    label = result.get("label", result.get("client"))
    status = result.get("status")
    print(f"[{status}] {label} ({result.get('client')})")
    if result.get("path"):
        print(f"  config: {result['path']}")
    if result.get("root_key"):
        print(f"  root: {result['root_key']}")
    if result.get("command"):
        print(f"  command: {result['command']}")
    if result.get("args"):
        print(f"  args: {result['args']}")
    if result.get("settings"):
        print(f"  settings: {result['settings']}")
    if result.get("message"):
        print(f"  error: {result['message']}")
    for warning in result.get("warnings", []):
        print(f"  warning: {warning}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ide",
        action="append",
        help="Client ID or alias to check. Repeat or comma-separate. Defaults to all supported clients.",
    )
    parser.add_argument(
        "--settings",
        help="Expected settings.json path. When provided, the script verifies --settings args match it.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit nonzero for missing configs or warnings. Useful for per-client smoke tests.",
    )
    args = parser.parse_args()

    try:
        client_ids = normalize_client_ids(args.ide) if args.ide else [client.id for client in available_clients()]
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 1

    results = [check_client(client_id, args.settings) for client_id in client_ids]
    for index, result in enumerate(results):
        if index:
            print()
        _print_result(result)

    bad_statuses = {"error"}
    if args.ide:
        bad_statuses.add("missing_root")
        bad_statuses.add("missing_server")
        bad_statuses.add("missing_config")
        bad_statuses.add("unsupported_platform")
    if args.strict:
        bad_statuses.add("warning")
        bad_statuses.add("missing_config")
        bad_statuses.add("unsupported_platform")

    return 1 if any(result.get("status") in bad_statuses for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
