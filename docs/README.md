# OpenLMlib Documentation

Complete documentation for OpenLMlib - Local knowledge and research library for LLM workflows.

## 📚 Documentation Index

### Getting Started
- **[Main README](../README.md)** - Installation, quickstart, and overview
- **[Installation Guide](#installation)** - Detailed installation options

### Core Features
- **[MCP Tools Reference](MCP_TOOLS.md)** - Complete reference for all 42 MCP tools
- **[Knowledge Base Guide](#knowledge-base)** - Managing findings and retrieval

### Collaboration
- **[CollabSessions Guide](COLLAB_SESSIONS.md)** - Multi-agent collaboration
- **[Session Templates](COLLAB_SESSIONS.md#available-templates)** - Predefined session plans

### Agent Integration
- **[System Prompt Templates](SYSTEM_PROMPT.md)** - Agent instruction templates
- **[MCP Configuration](#mcp-client-configuration)** - IDE/client setup

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
openlmlib-mcp --call collab_create_session '{...}'

# Join session
openlmlib-mcp --call collab_join_session '{...}'

# Send message
openlmlib-mcp --call collab_send_message '{...}'

# Poll messages
openlmlib-mcp --call collab_poll_messages '{...}'

# Add artifact
openlmlib-mcp --call collab_add_artifact '{...}'
```

---

## MCP Tools Overview

OpenLMlib provides **42 MCP tools** across two categories:

### Core Library Tools (11)
- Knowledge base management (`init`, `add`, `delete`, `health`)
- Retrieval and search (`retrieve`, `search_fts`, `retrieve_context`)
- Finding browsing (`list_findings`, `get_finding`)
- Utilities (`evaluate_dataset`, `help`)

### Collaboration Tools (31)
- **Session Management** (7): Create, join, terminate sessions
- **Message Operations** (7): Send, read, poll, search messages
- **Artifact Management** (4): Add, list, get, search artifacts
- **Session Discovery** (6): Find and analyze sessions
- **Templates** (3): Predefined session plans
- **Model Discovery** (3): OpenRouter model information
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

# List supported IDEs
openlmlib mcp-config --list-ides
```

**Supported clients:**
- VS Code
- Cursor
- Claude Desktop
- Kiro
- Windsurf
- Zed
- Cline
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
│   ├── 11 core library tools
│   └── 31 collaboration tools
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
1. collab_create_session_from_template("deep_research")
2. Agents join and execute tasks
3. Share artifacts (reports, analysis)
4. Terminate with summary
5. Export findings to knowledge base
```

### 3. Code Review
```
1. collab_create_session_from_template("code_review")
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

### Model download slow?
- First run downloads embedding model (~100-500MB)
- Subsequent runs use cached model
- Model downloads during `openlmlib setup`, not install

### Session issues?
- Check agent is joined to session
- Verify session is active
- Use `collab_help` for tool documentation

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
- **MCP Help**: `openlmlib-mcp --call openlmlib_help` or `collab_help`
