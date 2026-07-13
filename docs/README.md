# OpenLMlib Documentation

Complete documentation for OpenLMlib - Local knowledge and research library for LLM workflows.

## 📚 Documentation Index

### Getting Started
- **[Main README](../README.md)** - Installation, quickstart, and overview
- **[Installation Guide](#installation)** - Detailed installation options

### Core Features
- **[MCP Tools Reference](MCP_TOOLS.md)** - Complete reference for MCP tools
- **[Knowledge Base Guide](#knowledge-base)** - Managing findings and retrieval
- **[Memory System Quickstart](MEMORY_QUICKSTART.md)** - Session persistence and progressive retrieval
- **[Co-Scientist Scope Policy](CO_SCIENTIST_SCOPE_POLICY.md)** - Phase 0 safety and approval gates

### Collaboration
- **[CollabSessions Guide](COLLAB_SESSIONS.md)** - Multi-agent collaboration
- **[Session Templates](COLLAB_SESSIONS.md#available-templates)** - Predefined session plans

### Memory System
- **[Memory Quickstart](MEMORY_QUICKSTART.md)** - Session persistence, progressive retrieval, retroactive ingestion
- **[Caveman Compression](CAVEMAN_COMPRESSION.md)** - Token-efficient linguistic compression

### Agent Integration
- **[System Prompt Templates](SYSTEM_PROMPT.md)** - Agent instruction templates
- **[MCP Configuration](#mcp-client-configuration)** - IDE/client setup
- **[CLI MCP Integration](../CLI_MCP_GLOBAL_CONFIG.md)** - Global MCP config for CLI tools
- **[Co-Scientist Client Integration](MCP_CLI_INTEGRATION_RESEARCH.md#phase-10-co-scientist-client-integration)** - Codex, Claude, Antigravity, and smoke tests

### Development
- **[CHANGELOG](../CHANGELOG.md)** - Release history
- **[Contributing Guide](../CONTRIBUTING.md)** - How to contribute
- **[MCP CLI Research](MCP_CLI_INTEGRATION_RESEARCH.md)** - Market research on CLI tool MCP integration

---

## Installation

### Option 1: npm (Recommended)
```bash
npm install -g openlmlib
openlmlib setup  # Initialize and configure
```

### Option 2: pipx
```bash
pipx install openlmlib
openlmlib setup
```

### Option 3: From Source
```bash
git clone https://github.com/Vedant9500/LMlib.git
cd LMlib
pip install -e .
openlmlib setup
```

**Note:** The embedding model downloads on first `setup` run, not during installation.

---

## Quick Reference

### Knowledge Base Operations

```bash
# Initialize
openlmlib init

# Add finding (with confirmation)
openlmlib add --project myproj --claim "..." --confidence 0.8

# Search
openlmlib query "contextual retrieval" --final-k 5

# List findings
openlmlib list --limit 20

# Get specific finding
openlmlib get --id <finding-id>

# Health check
openlmlib doctor
```

### Collaboration Sessions

```bash
# Create session
openlmlib-mcp --call create_session '{...}'

# Join session
openlmlib-mcp --call join_session '{...}'

# Send message
openlmlib-mcp --call send_message '{...}'

# Poll messages
openlmlib-mcp --call poll_messages '{...}'

# Add artifact
openlmlib-mcp --call save_artifact '{...}'
```

---

## MCP Tools Overview

OpenLMlib provides **76 MCP tools** across three categories:

### Core Library Tools (17)
- Knowledge base management (`init`, `add`, `delete`, `health`)
- Retrieval and search (`retrieve`, `search_fts`, `search_knowledge`, `retrieve_context`)
- Finding browsing (`list_findings`, `get_finding`)
- Composite workflows (`start_research`, `end_session`, `check_context`, `save_finding_auto`)
- Utilities (`evaluate_dataset`, `get_usage_analytics`, `help`)

### Memory System Tools (11)
- Session lifecycle (`session_start`, `session_end`, `log_observation`)
- Adaptive and progressive retrieval (`query_memory`, `search_memory`, `memory_timeline`, `get_observations`)
- Context injection and recap (`inject_context`, `session_recap`, `topic_context`)
- Retroactive ingestion (`ingest_git_history`)

### Collaboration Tools (48)
- **Session Management** (7): Create, join, terminate sessions
- **Message Operations** (7): Send, read, poll, search messages
- **Artifact Management** (4): Add, list, get, search artifacts
- **Session Discovery** (6): Find and analyze sessions
- **Templates** (3): Predefined session plans
- **Model Discovery** (3): OpenRouter model information
- **Co-Scientist** (17): Scope screening, hypothesis packet validation, citation grounding, linked runs, verification handoff, reports, export, and evaluation
- **Utilities** (1): Help and documentation

📖 **See [MCP_TOOLS.md](MCP_TOOLS.md) for complete tool reference with all parameters and examples.**

---

## Key Concepts

### Findings
A finding is a single piece of knowledge with:
- **Claim**: One clear, specific statement
- **Confidence**: Score from 0.0 to 1.0
- **Evidence**: Citations, URLs, sources
- **Reasoning**: Why the claim is believed
- **Caveats**: Limitations or conditions
- **Tags**: Categories for organization

### Retrieval
Multi-phase retrieval combining:
1. **Semantic search** (vector similarity)
2. **Lexical search** (full-text matching)
3. **Recency scoring** (time decay)
4. **Deduplication** (merge similar findings)
5. **Optional reranking** (LLM-based)

### CollabSessions
Multi-agent collaboration with:
- Structured sessions with roles (orchestrator/worker/observer)
- Message bus with sequence tracking
- Artifact sharing
- Predefined templates for common patterns
- Context compaction for long sessions

---

## MCP Client Configuration

Configure AI assistants to use OpenLMlib:

```bash
# Interactive setup (recommended)
openlmlib setup

# Configure specific IDEs
openlmlib mcp-config --ide vscode --ide cursor

# Configure Codex CLI and Claude Code
openlmlib mcp-config --ide codex_cli --ide claude_code

# Configure the common Co-Scientist clients
openlmlib mcp-config --ide codex_cli --ide claude_code --ide claude_desktop --ide antigravity

# List supported IDEs
openlmlib mcp-config --list-ides
```

MCP clients do not discover arbitrary local servers from another app's prompt.
Each client must have an `openlmlib` server entry in its own MCP config, then
the client must be restarted or its MCP servers refreshed. System prompts help
models decide when to use already-loaded tools, but they cannot load a missing
MCP server.

Co-Scientist discovery works best when the client has both the MCP config entry
and a short instruction snippet. Use wording such as "research this and verify
the hypotheses" or "start a Co-Scientist run" for clients that rely heavily on
natural-language tool descriptions.

By default the MCP server registers its tools first, then starts a delayed
runtime/model prewarm in the background. This keeps the MCP initialize handshake
fast while making the first semantic retrieval more likely to be warm by the
time you need it. Tune or disable the behavior in the client's OpenLMlib server
entry:

```toml
[mcp_servers.openlmlib.env]
OPENLMLIB_MCP_PREWARM = "1"              # default: 1
OPENLMLIB_MCP_PREWARM_DELAY_SEC = "5"    # default: 5
OPENLMLIB_EMBED_PREWARM = "1"            # default: 1
```

Set `OPENLMLIB_MCP_PREWARM = "0"` to disable background model work. Avoid
`OPENLMLIB_MCP_PREIMPORT_EMBEDDINGS = "1"` unless you specifically want the
embedding stack imported on the main startup path.

**Supported clients:**
- VS Code, Cursor, Claude Desktop
- Claude Code, Gemini CLI, Qwen Code
- Aider, Windsurf, Zed, Cline
- And more...

📖 **See [SYSTEM_PROMPT.md](SYSTEM_PROMPT.md) for agent instruction templates.**

---

## Architecture

```
OpenLMlib
├── Knowledge Base
│   ├── SQLite (metadata)
│   ├── FAISS/Numpy (vector index)
│   └── JSON findings (portable)
│
├── MCP Server
│   ├── 17 core library tools
│   ├── 11 memory tools
│   └── 48 collaboration tools
│
├── CLI
│   ├── Setup and configuration
│   ├── Finding management
│   └── Diagnostics
│
└── CollabSessions
    ├── Message bus
    ├── Artifact store
    ├── Session templates
    └── Context compaction
```

---

## Common Workflows

### 1. Build Knowledge Base
```
1. openlmlib init
2. Add findings manually or via agents
3. Search with openlmlib query "..."
4. Retrieve context for LLMs
```

### 2. Multi-Agent Research
```
1. create_from_template("deep_research")
2. Agents join and execute tasks
3. Share artifacts (reports, analysis)
4. Terminate with summary
5. Export findings to knowledge base
```

### 3. Code Review
```
1. create_from_template("code_review")
2. Agents review architecture, security, performance
3. Consolidated report created
4. Findings added to knowledge base
```

---

## Troubleshooting

### Only seeing 10 MCP tools in IDE?
1. Restart your IDE (caching old tool list)
2. Run `openlmlib doctor` to verify installation
3. Check tool count in [MCP_TOOLS.md](MCP_TOOLS.md)

### MCP server startup slow or timing out?
- Keep `OPENLMLIB_MCP_PREIMPORT_EMBEDDINGS` unset or set to `0` in the client's
  server entry.
- If startup is still contended on a slow machine, increase
  `OPENLMLIB_MCP_PREWARM_DELAY_SEC` or set `OPENLMLIB_MCP_PREWARM = "0"`.
- `sentence_transformers` imports can take 10+ seconds on Windows even when the
  model is already downloaded; this is separate from model download time.
- Delayed prewarm should not block the handshake, but it can use CPU and memory
  shortly after the server starts.

### Model download slow?
- First run downloads embedding model (~100-500MB)
- Subsequent runs use cached model
- Model downloads during `openlmlib setup`, not install

### Session issues?
- Check agent is joined to session
- Verify session is active
- Use `help_collab` for tool documentation

---

## Related Documentation

- **[RELEASE.md](../RELEASE.md)** - Versioning and publish flow
- **[CHANGELOG.md](../CHANGELOG.md)** - Change history
- **[CONTRIBUTING.md](../CONTRIBUTING.md)** - Contribution guidelines
- **[SECURITY.md](../SECURITY.md)** - Security policy

---

## Getting Help

- **Documentation**: You're reading it!
- **Issues**: [GitHub Issues](https://github.com/Vedant9500/LMlib/issues)
- **CLI Help**: `openlmlib --help` or `openlmlib help`
- **MCP Help**: `openlmlib-mcp --call help_library` or `help_collab`
