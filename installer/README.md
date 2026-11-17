# OpenLMlib

**A local, cross-project knowledge and research library for LLM workflows.**

OpenLMlib stores research findings, decisions, and session notes in a local
database, then exposes them to AI assistants through semantic search and a
Model Context Protocol (MCP) server. Everything runs on your machine; no hosted
service or API key is required.

- **Local-first storage** — SQLite metadata, JSON findings, and a local vector index
- **Hybrid retrieval** — semantic + full-text search with deduplication and reranking
- **MCP server** — 76 tools for AI assistants and coding agents
- **CLI** — add, query, inspect, back up, and diagnose the library
- **Multi-agent sessions** — CollabSessions for structured agent-to-agent work
- **Co-Scientist workflow** — hypothesis generation with independent verification

Supported clients include Claude Code, Claude Desktop, Cursor, VS Code, Codex
CLI, Gemini CLI, Windsurf, Zed, Cline, and any other MCP-compatible client.

## Requirements

- **Node.js 18 or newer**
- **Python 3.10 or newer** — the installer can bootstrap Python via winget,
  Homebrew, apt, or dnf when it is missing, or you can install it manually from
  [python.org](https://www.python.org/downloads/)
- About 500 MB for the local embedding model, plus the Python dependency stack
  (PyTorch and related packages) in the managed virtual environment. The model
  is downloaded once during `openlmlib setup`; later runs work offline.
  On Linux and Windows the installer installs the CPU-only PyTorch build
  (a few hundred MB instead of the ~2-3 GB CUDA stack). Set
  `OPENLMLIB_TORCH_INDEX=pypi` to take the default PyPI build instead, or set it
  to another index URL to use a different wheel source.

## Installation

```bash
npm install -g openlmlib
openlmlib setup
```

The npm package is self-contained: it ships the installer and the matching
Python source, so installation does not depend on a separate PyPI release.

During installation OpenLMlib:

1. Creates a virtual environment at `~/.openlmlib/venv`.
2. Installs the bundled Python package into that environment.
3. Verifies that the full MCP tool surface is registered.
4. Configures the MCP clients you select.
5. Creates the default settings at `~/.openlmlib/config/settings.json`.

Restart your editor or AI client after `openlmlib setup` so it reloads the MCP
server definition.

### Other installation methods

```bash
# Python only (CLI and MCP server, no interactive installer)
pipx install openlmlib
openlmlib setup

# From source
git clone https://github.com/Vedant9500/OpenLMlib.git
cd OpenLMlib
pip install -e .
openlmlib setup
```

The npm installer is recommended because it manages the virtual environment and
MCP configuration for you.

## Quickstart

```bash
# Check the installation and storage
openlmlib doctor

# Add a finding
openlmlib add \
  --project retrieval \
  --claim "Contextual chunking improves retrieval quality by 15-30%" \
  --confidence 0.85 \
  --evidence "https://arxiv.org/abs/2401.00000" \
  --reasoning "Context-aware chunks preserve section boundaries and reduce split facts."

# Search with semantic + keyword retrieval
openlmlib query "retrieval chunking" --final-k 5

# List recent findings
openlmlib list --limit 20
```

## Connect your AI assistant

The interactive setup configures clients automatically. To configure specific
clients later:

```bash
openlmlib mcp-config --ide vscode --ide cursor
openlmlib mcp-config --ide claude_code --ide codex_cli
```

A manual MCP entry looks like this. Use `openlmlib mcp-config` when possible, so
the command paths match your platform.

```json
{
  "mcpServers": {
    "openlmlib": {
      "command": "/home/you/.openlmlib/venv/bin/python",
      "args": ["-m", "openlmlib.mcp_server"]
    }
  }
}
```

On Windows the interpreter is
`%USERPROFILE%\.openlmlib\venv\Scripts\python.exe`.

## MCP tools

The server exposes 76 tools across three groups:

| Group | Tools | Examples |
| --- | ---: | --- |
| Core library | 17 | `save_finding`, `search_findings`, `retrieve_findings`, `start_research` |
| Memory | 11 | `session_start`, `session_recap`, `query_memory`, `inject_context` |
| Collaboration | 48 | `create_session`, `send_message`, `create_co_scientist_run` |

The collaboration group includes templates, model discovery, session analytics,
and the 17 Co-Scientist tools. See the
[full MCP tool reference](https://github.com/Vedant9500/OpenLMlib/blob/master/docs/MCP_TOOLS.md)
for parameters and return values.

## CLI overview

| Command | Purpose |
| --- | --- |
| `openlmlib setup` | First-run bootstrap and client configuration |
| `openlmlib doctor` | Diagnose the environment, storage, and MCP registration |
| `openlmlib add` | Add a finding with evidence and reasoning |
| `openlmlib query` | Retrieve findings with semantic + keyword search |
| `openlmlib list` / `get` | Browse findings |
| `openlmlib mcp-config` | Write MCP client configuration |
| `openlmlib backup` / `restore` | Back up and restore the library |
| `openlmlib collab` | Manage multi-agent collaboration sessions |

Run `openlmlib --help` or `openlmlib <command> --help` for details.

## Troubleshooting

### The client shows fewer than 76 tools

1. Fully restart the client; most editors cache the MCP tool list at startup.
2. Run `openlmlib doctor`.
3. Verify the installed tool surface with the Python environment OpenLMlib uses:

   ```bash
   ~/.openlmlib/venv/bin/python -c "from openlmlib import mcp_server as m; m._register_memory_tools(); m._register_collab_tools(); print(len(m.mcp._tool_manager._tools))"
   ```

   On Windows, replace the interpreter with
   `%USERPROFILE%\.openlmlib\venv\Scripts\python.exe`.

4. Re-run `openlmlib mcp-config` and restart the client again.

### npm blocked the postinstall script

Newer npm releases can require explicit approval before running dependency
install scripts. If npm prints `install scripts blocked` and `openlmlib` then
reports "OpenLMlib is not installed", approve the script and reinstall:

```bash
npm install -g openlmlib --allow-scripts=openlmlib
```

You can also add `allow-scripts=openlmlib` to your `~/.npmrc`. Project-scoped
installs should put `openlmlib` in the project's `allowScripts` field instead.

### Python 3.10+ was not found

Run `openlmlib setup` again and accept the automatic installation prompt, or
install Python from [python.org](https://www.python.org/downloads/) and reinstall
the npm package.

### The embedding model download failed

The model is downloaded during `openlmlib setup`. Check network access to
Hugging Face, then run `openlmlib setup` again. If the machine must stay offline,
see the
[configuration documentation](https://github.com/Vedant9500/OpenLMlib/blob/master/CLI_MCP_GLOBAL_CONFIG.md)
for local model paths.

### Reinstall

```bash
npm uninstall -g openlmlib
npm install -g openlmlib
openlmlib setup
```

Library data lives in `~/.openlmlib/` and is preserved across reinstalls. Use
`openlmlib backup` before major upgrades.

## Documentation

- [Full documentation](https://github.com/Vedant9500/OpenLMlib/blob/master/docs/README.md)
- [MCP tools reference](https://github.com/Vedant9500/OpenLMlib/blob/master/docs/MCP_TOOLS.md)
- [CollabSessions](https://github.com/Vedant9500/OpenLMlib/blob/master/docs/COLLAB_SESSIONS.md)
- [Configuration](https://github.com/Vedant9500/OpenLMlib/blob/master/CLI_MCP_GLOBAL_CONFIG.md)
- [Changelog](https://github.com/Vedant9500/OpenLMlib/blob/master/CHANGELOG.md)
- [Issues](https://github.com/Vedant9500/OpenLMlib/issues)

## Development

The npm package lives in `installer/`. Packaging, verification, and release
steps are documented in
[DEVELOPING.md](https://github.com/Vedant9500/OpenLMlib/blob/master/installer/DEVELOPING.md).

## License

MIT. See [LICENSE](https://github.com/Vedant9500/OpenLMlib/blob/master/LICENSE).
