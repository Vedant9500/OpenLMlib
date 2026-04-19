# Global MCP Configuration for CLI Coding Tools

## Overview

OpenLMlib now supports **global MCP server configuration** for popular CLI coding tools, just like it does for IDEs (VS Code, Cursor, etc.). This means:

✅ **One setup, works everywhere** - Configure once, use across all CLI tools  
✅ **Cross-tool continuity** - Start work in Claude Code, continue in Gemini CLI  
✅ **Shared library** - All tools access the same OpenLMlib knowledge base  
✅ **No per-project setup** - Global config applies to all projects automatically  

---

## Supported CLI Tools

| Tool | Global Config Location | Format | Status |
|------|----------------------|--------|--------|
| **Claude Code** | `~/.claude.json` | JSON | ✅ Native |
| **Gemini CLI** | `~/.gemini/settings.json` | JSON | ✅ Native |
| **Qwen Code** | `~/.qwen/settings.json` | JSON | ✅ Native |
| **OpenCode** | `~/.config/opencode/opencode.json` (Linux/macOS)<br>`%APPDATA%/opencode/opencode.json` (Windows) | JSON | ✅ Native |
| **Codex CLI** | `~/.codex/config.toml` | TOML | ✅ Supported |
| **Aider** | `~/.aider.conf.yml` | YAML | ⚠️ Requires bridge |

---

## Quick Setup

### Install to All CLI Tools

```bash
# Install OpenLMlib MCP server to all supported CLI tools
openlmlib mcp install --cli claude_code,gemini_cli,qwen_code,opencode,codex_cli

# Or install to specific tools only
openlmlib mcp install --cli claude_code,gemini_cli,qwen_code
```

### Verify Installation

```bash
# Check which CLI tools are configured
openlmlib mcp verify --cli all

# Check specific tools
openlmlib mcp verify --cli claude_code,gemini_cli
```

### Remove Configuration

```bash
# Remove from all CLI tools
openlmlib mcp remove --cli all

# Remove from specific tools
openlmlib mcp remove --cli codex_cli,aider
```

---

## Manual Configuration

If you prefer to configure manually, here are the exact configurations for each tool:

### 1. Claude Code

**File**: `~/.claude.json` (global, all projects)

```json
{
  "mcpServers": {
    "openlmlib": {
      "command": "python",
      "args": [
        "-m",
        "openlmlib.mcp_server",
        "--settings",
        "/path/to/openlmlib/settings.json"
      ]
    }
  }
}
```

**Verify**:
```bash
claude mcp list
# Should show: openlmlib (stdio)
```

**Test**:
```bash
claude --dangerously-skip-permissions
# Ask: "Search OpenLMlib for findings about memory management"
```

---

### 2. Gemini CLI

**File**: `~/.gemini/settings.json` (global, all projects)

```json
{
  "mcpServers": {
    "openlmlib": {
      "command": "python",
      "args": [
        "-m",
        "openlmlib.mcp_server",
        "--settings",
        "/path/to/openlmlib/settings.json"
      ]
    }
  }
}
```

**Verify**:
```bash
gemini
# Type: "Use OpenLMlib to search for recent findings"
```

**Notes**:
- Applies to all Gemini CLI sessions for current user
- Can also use project-level config: `.gemini/settings.json`

---

### 3. Qwen Code

**File**: `~/.qwen/settings.json` (global, all projects)

```json
{
  "mcpServers": {
    "openlmlib": {
      "command": "python",
      "args": [
        "-m",
        "openlmlib.mcp_server",
        "--settings",
        "/path/to/openlmlib/settings.json"
      ],
      "includeTools": [],
      "excludeTools": [],
      "trust": false,
      "timeout": 30000
    }
  }
}
```

**Advanced Features** (Qwen Code specific):
- `includeTools`: Allowlist specific tools
- `excludeTools`: Blocklist tools (takes precedence)
- `trust`: Auto-approve all tool calls (false = ask for permission)
- `timeout`: Request timeout in milliseconds

**Verify**:
```bash
qwen
# Ask: "查询 OpenLMlib 中关于记忆管理的发现"
```

---

### 4. OpenCode

**File**: `~/.config/opencode/opencode.json` (Linux/macOS)  
**File**: `%APPDATA%/opencode/opencode.json` (Windows)

```json
{
  "mcp": {
    "openlmlib": {
      "type": "local",
      "command": "python",
      "args": [
        "-m",
        "openlmlib.mcp_server",
        "--settings",
        "/path/to/openlmlib/settings.json"
      ]
    }
  }
}
```

**Alternative**: Use CLI command
```bash
opencode mcp add openlmlib --command python -m openlmlib.mcp_server --args "--settings /path/to/settings.json"
```

**Verify**:
```bash
opencode
# Ask: "Search OpenLMlib for memory retrieval implementations"
```

---

### 5. Codex CLI

**File**: `~/.codex/config.toml` (global)

```toml
[mcp_servers.openlmlib]
command = "python"
args = ["-m", "openlmlib.mcp_server", "--settings", "/path/to/settings.json"]
```

**Environment Variable** (optional):
```bash
# Override default config location
export CODEX_HOME=/custom/path/.codex
```

**Verify**:
```bash
codex
# Ask: "Search OpenLMlib for recent memory system findings"
```

**Notes**:
- Uses TOML format instead of JSON
- `CODEX_HOME` env var overrides default location
- Community MCP wrappers also available for bidirectional support

---

### 6. Aider

**File**: `~/.aider.conf.yml` (global)

```yaml
mcp_servers:
  openlmlib:
    command: python
    args:
      - "-m"
      - "openlmlib.mcp_server"
      - "--settings"
      - "/path/to/settings.json"
```

**Alternative**: Use MCP bridge
```bash
# Install Aider MCP server
pip install aider-mcp-server

# Or use mcpm-aider to manage multiple servers
pip install mcpm-aider
mcpm add openlmlib --command python -m openlmlib.mcp_server
```

**Verify**:
```bash
aider
# Ask: "Use OpenLMlib to search for memory implementation"
```

**Notes**:
- Requires community bridge for full MCP support
- Multiple MCP server management available via `mcpm-aider`

---

## Cross-Tool Workflow

### Example: Seamless Work Continuation

**Scenario**: You're working on optimizing memory retrieval and want to continue your work across different tools.

#### Step 1: Start in Claude Code

```bash
# Claude Code session
claude

> "Use OpenLMlib to search for memory retrieval optimizations"
> OpenLMlib finds: "ProgressiveRetriever with 3-layer disclosure, 92% token savings"
> "Implement caching layer for frequently accessed memories"
> *Writes code, logs tool executions to OpenLMlib*
```

#### Step 2: Continue in Gemini CLI

```bash
# Gemini CLI session (same project, different tool)
gemini

> "What did I work on recently in OpenLMlib?"
> OpenLMlib injects context from Claude Code session:
>   - Searched memory retrieval optimizations
>   - Implemented caching layer
>   - Modified memory_retriever.py
> "Continue optimizing the cache invalidation logic"
> *Continues work seamlessly*
```

#### Step 3: Review in Qwen Code

```bash
# Qwen Code session (for code review)
qwen

> "Show me recent changes to memory system from OpenLMlib"
> OpenLMlib provides full timeline:
>   1. Claude Code: Initial implementation
>   2. Gemini CLI: Cache invalidation optimization
> "Review the changes for potential issues"
> *Completes review, adds findings to library*
```

**Result**: All three tools worked on the **same project**, accessing the **same knowledge base**, with **full continuity** of work.

---

## Configuration Examples

### Full Claude Code Config with Advanced Features

```json
{
  "mcpServers": {
    "openlmlib": {
      "command": "python",
      "args": [
        "-m",
        "openlmlib.mcp_server",
        "--settings",
        "/home/user/.openlmlib/config/settings.json"
      ],
      "env": {
        "OPENLMLIB_SETTINGS": "/home/user/.openlmlib/config/settings.json"
      },
      "cwd": "/home/user/projects/my-project"
    }
  }
}
```

### Full Qwen Code Config with Enterprise Features

```json
{
  "mcpServers": {
    "openlmlib": {
      "command": "python",
      "args": [
        "-m",
        "openlmlib.mcp_server",
        "--settings",
        "/home/user/.openlmlib/config/settings.json"
      ],
      "cwd": "/home/user/projects/my-project",
      "env": {
        "OPENLMLIB_SETTINGS": "/home/user/.openlmlib/config/settings.json"
      },
      "includeTools": [
        "search_findings",
        "add_finding",
        "list_findings",
        "retrieve_findings"
      ],
      "excludeTools": [
        "delete_finding"
      ],
      "trust": false,
      "timeout": 30000,
      "description": "OpenLMlib knowledge base for memory management and retrieval"
    }
  },
  "permissions": {
    "mcp__openlmlib": {
      "search_findings": "allow",
      "add_finding": "allow",
      "delete_finding": "deny"
    }
  }
}
```

### Full Codex CLI Config (TOML)

```toml
# OpenLMlib MCP Server Configuration for Codex CLI
# File: ~/.codex/config.toml

[mcp_servers.openlmlib]
command = "python"
args = ["-m", "openlmlib.mcp_server", "--settings", "/home/user/.openlmlib/config/settings.json"]

# Optional: Environment variables
[mcp_servers.openlmlib.env]
OPENLMLIB_SETTINGS = "/home/user/.openlmlib/config/settings.json"

# Optional: Working directory
[mcp_servers.openlmlib.options]
cwd = "/home/user/projects/my-project"
```

---

## Troubleshooting

### Issue: "MCP server not found"

**Solution**:
```bash
# Verify config file exists
ls -la ~/.claude.json        # Claude Code
ls -la ~/.gemini/settings.json  # Gemini CLI
ls -la ~/.qwen/settings.json    # Qwen Code

# Reinstall config
openlmlib mcp install --cli claude_code
```

### Issue: "Command not found: python"

**Solution**: Use full path to python executable
```bash
# Find python path
which python
# or on Windows:
where python

# Update config with full path
{
  "command": "/usr/bin/python3",  # or C:\\Python39\\python.exe
  "args": ["-m", "openlmlib.mcp_server", "--settings", "..."]
}
```

### Issue: "Permission denied on tool calls"

**Solution**:
- Claude Code: Use `--dangerously-skip-permissions` flag (testing only)
- Qwen Code: Set `"trust": true` in config (use with caution)
- Other tools: Check permission settings for `mcp__openlmlib`

### Issue: "Config file format error"

**Solution**:
```bash
# Validate JSON
python -m json.tool ~/.claude.json

# Validate TOML (Codex CLI)
pip install tomli
python -c "import tomli; tomli.load(open('~/.codex/config.toml', 'rb'))"

# Backup and regenerate
cp ~/.claude.json ~/.claude.json.backup
openlmlib mcp install --cli claude_code
```

---

## Architecture

### How Global Config Works

```
┌─────────────────────────────────────────┐
│         OpenLMlib Settings              │
│   ~/.openlmlib/config/settings.json     │
│      (Shared knowledge base)            │
└──────────────────┬──────────────────────┘
                   │
                   │ MCP Protocol (stdio)
                   │
        ┌──────────┴──────────┐
        │                     │
┌───────▼────────┐   ┌────────▼────────┐
│  Claude Code   │   │  Gemini CLI     │
│  ~/.claude.json│   │  ~/.gemini/     │
│                │   │  settings.json  │
└────────────────┘   └─────────────────┘
        │                     │
        │                     │
┌───────▼────────┐   ┌────────▼────────┐
│  Qwen Code     │   │  OpenCode       │
│  ~/.qwen/      │   │  ~/.config/     │
│  settings.json │   │  opencode.json  │
└────────────────┘   └─────────────────┘
```

**Key Points**:
1. **Single settings.json** - All tools share the same OpenLMlib knowledge base
2. **Global config per tool** - Each CLI tool has its own config file in home directory
3. **MCP protocol** - Standard stdio transport for local execution
4. **No project-level config needed** - Works across all projects automatically

---

## API Reference

### Python API

```python
from openlmlib.mcp_setup import (
    install_client_config,
    install_client_configs,
    client_config_path,
    available_clients,
    normalize_client_ids,
)

# Install to single CLI tool
result = install_client_config(
    "claude_code",
    settings_path=Path("~/.openlmlib/config/settings.json").expanduser()
)

# Install to multiple CLI tools
results = install_client_configs(
    ["claude_code", "gemini_cli", "qwen_code"],
    settings_path=Path("~/.openlmlib/config/settings.json").expanduser()
)

# Get config path for a tool
path = client_config_path("claude_code")
# Returns: Path("~/.claude.json")

# List all available clients
clients = available_clients()
# Returns: [McpClientSpec(...), ...]

# Normalize client ID
normalized = normalize_client_ids(["claude-code", "gemini_cli"])
# Returns: ["claude_code", "gemini_cli"]
```

---

## Benefits

### For Developers

✅ **Setup once, use everywhere** - No need to configure per tool  
✅ **Seamless continuity** - Switch between tools without losing context  
✅ **Shared knowledge** - All tools access same findings and memories  
✅ **Cross-pollination** - Start in one tool, finish in another  

### For Teams

✅ **Standardized workflow** - Same MCP server across all developer tools  
✅ **Enterprise security** - Tool filtering, permissions, trust mode (Qwen Code)  
✅ **Audit trail** - All tool executions logged to shared knowledge base  
✅ **Collaboration** - Multiple developers using different tools can collaborate  

### For OpenLMlib

✅ **Wider adoption** - Support for 6 major CLI tools (~1.38M+ developers)  
✅ **Ecosystem growth** - Join MCP server marketplace  
✅ **Future-proof** - MCP becoming industry standard  
✅ **Composable architecture** - Add new tools without modifying each CLI  

---

## Next Steps

1. **Test with actual CLI tools** - Verify integration works end-to-end
2. **Add more CLI tools** - Support emerging tools with MCP capability
3. **HTTP transport** - Enable remote MCP server connections
4. **Advanced filtering** - Per-tool access control and rate limiting
5. **Analytics** - Track which tools are using OpenLMlib (opt-in)

---

## References

- [Claude Code MCP Docs](https://docs.anthropic.com/en/docs/claude-code/mcp)
- [Gemini CLI Configuration](https://google-gemini.github.io/gemini-cli/docs/get-started/configuration.html)
- [Qwen Code MCP Settings](https://qwenlm.github.io/qwen-code-docs/en/users/configuration/settings/)
- [OpenCode MCP Config](https://opencode.ai/docs/mcp-servers/)
- [Codex CLI Config](https://platform.openai.com/docs/guides/tools-mcp)
- [Aider MCP Server](https://github.com/danielscholl/aider-mcp-server)
