#!/usr/bin/env python3
"""Check for stale MCP configurations in IDE settings files."""
import json
import os
import sys
from pathlib import Path

def check_config(label, config_path):
    """Check an IDE's MCP config file for openlmlib entries."""
    if not config_path.exists():
        print(f"[SKIP] {label}: {config_path} not found")
        return
    
    try:
        with open(config_path) as f:
            cfg = json.load(f)
    except Exception as e:
        print(f"[ERROR] {label}: {e}")
        return
    
    # Check different root keys
    for root_key in ['mcpServers', 'servers', 'context_servers']:
        root = cfg.get(root_key, {})
        if 'openlmlib' in root:
            entry = root['openlmlib']
            print(f"\n[{label}] Found openlmlib in {root_key}:")
            print(f"  Command: {entry.get('command', 'N/A')}")
            print(f"  Args: {entry.get('args', [])}")
        elif any('openlmlib' in k.lower() for k in root.keys()):
            print(f"\n[{label}] Found openlmlib-like entries in {root_key}:")
            for k, v in root.items():
                if 'openlmlib' in k.lower():
                    print(f"  {k}: {v}")
    
    print(f"[OK] {label}: {config_path}")

# Common IDE config locations
home = Path.home()

configs = [
    ("VS Code", home / ".vscode" / "mcp.json"),
    ("VS Code (workspace)", Path.cwd() / ".vscode" / "mcp.json"),
    ("Cursor", home / ".cursor" / "mcp.json"),
    ("Claude Desktop", home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"),
    ("Claude Desktop (Win)", home / "AppData" / "Roaming" / "Claude" / "claude_desktop_config.json"),
    ("Cline (VS Code)", home / "AppData" / "Roaming" / "Code" / "User" / "globalStorage" / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json"),
]

print("Checking IDE MCP configurations for openlmlib...")
print("=" * 60)

for label, path in configs:
    check_config(label, path)

print("\n" + "=" * 60)
print("To refresh your MCP config, run: openlmlib setup")
print("Or: openlmlib mcp-config --client <your-ide>")
