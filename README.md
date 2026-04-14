# OpenLMlib

**Local knowledge and research library for LLM workflows**

Store, retrieve, and collaborate on findings with semantic search, full-text search, and multi-agent collaboration sessions.

[📚 Full Documentation](docs/README.md) · [Quickstart](#quickstart) · [MCP Tools](docs/MCP_TOOLS.md) · [CollabSessions](docs/COLLAB_SESSIONS.md)

---

## Features

- **Knowledge Base**: SQLite metadata + JSON findings + FAISS/Numpy vector index
- **Semantic Retrieval**: Multi-phase retrieval with semantic + lexical search, deduplication, and reranking
- **MCP Server**: 56 tools for AI assistants (15 core + 10 memory + 31 collaboration)
- **CollabSessions**: Multi-agent collaboration with message passing, artifacts, and templates
- **CLI**: Full command-line interface for management and diagnostics
- **Portable**: Findings exportable as JSON, easy backup and restore

---

## Quickstart

### Installation

```bash
npm install -g openlmlib
openlmlib setup  # Interactive wizard with React TUI
```

**Other options:**

**pipx (Python only)**
```bash
pipx install openlmlib
openlmlib setup
```

**From Source**
```bash
git clone https://github.com/Vedant9500/LMlib.git
cd LMlib
pip install -e .
openlmlib setup
```

> **Note**: The embedding model (~100-500MB) downloads during `setup`, not installation.

### First Steps

```bash
# Check health
openlmlib doctor

# Add a finding
openlmlib add \
  --project myproj \
  --claim "Contextual chunking improves retrieval by 15-30%" \
  --confidence 0.85 \
  --evidence "https://arxiv.org/example" \
  --reasoning "Benchmarks show context-aware chunking outperforms fixed-size"

# Search
openlmlib query "retrieval techniques" --final-k 5

# List findings
openlmlib list --limit 20
```

### Configure AI Assistants

```bash
# Interactive setup (recommended)
openlmlib setup

# Or configure specific IDEs
openlmlib mcp-config --ide vscode --ide cursor
```

**Supported clients**: VS Code, Cursor, Claude Desktop, Kiro, Windsurf, Zed, Cline, and more.

---

## What Can You Do?

### 📚 Build a Knowledge Base

Store findings from research, experiments, or analysis with structured metadata:

```bash
openlmlib add \
  --project retrieval \
  --claim "Dynamic chunk sizing reduces hallucination by 20%" \
  --confidence 0.78 \
  --evidence "https://example.com/study" \
  --reasoning "Adaptive chunk size based on query complexity..." \
  --caveats "Requires query complexity estimation" \
  --tags retrieval,chunking,evaluation
```

### 🔍 Retrieve with Context

Multi-phase retrieval combines semantic similarity, lexical matching, and recency:

```bash
# Semantic search with reasoning traces
openlmlib query "contextual retrieval" \
  --final-k 5 \
  --reasoning-trace

# With filters
openlmlib query "retrieval" \
  --project myproj \
  --tags retrieval \
  --confidence-min 0.8
```

### 🤖 Use with AI Assistants

56 MCP tools let AI assistants securely access and modify your knowledge base:

**Core Tools (15)**:
- `init_library`, `health` - Setup and diagnostics
- `save_finding`, `delete_finding` - Write operations (require confirmation)
- `retrieve_findings`, `search_findings` - Retrieval and search
- `list_findings`, `get_finding` - Browse findings
- `retrieve_context` - Format findings for LLM prompts
- `start_research`, `end_session` - Composite workflow tools
- `check_context`, `save_finding_auto` - Convenience tools
- `evaluate_retrieval`, `help_library` - Utilities

📖 **[See all 56 tools →](docs/MCP_TOOLS.md)**

### 👥 Multi-Agent Collaboration

CollabSessions enable structured collaboration between multiple LLM agents:

```bash
# Create session from template
openlmlib-mcp --call create_from_template '{
  "template_id": "deep_research",
  "title": "Research on Retrieval",
  "created_by": "gpt-4"
}'

# Join session
openlmlib-mcp --call join_session '{
  "session_id": "sess_20260409_abc12345",
  "model": "claude-3",
  "role": "worker"
}'

# Send and receive messages
openlmlib-mcp --call send_message '{...}'
openlmlib-mcp --call poll_messages '{...}'

# Add artifacts (reports, analysis)
openlmlib-mcp --call save_artifact '{...}'
```

**Available Templates**:
- `deep_research` - Comprehensive research (5 steps, 5 agents)
- `code_review` - Multi-agent code review (5 steps, 4 agents)
- `market_analysis` - Market/competitor analysis (4 steps, 4 agents)
- `incident_investigation` - Root cause analysis (4 steps, 3 agents)
- `literature_review` - Academic literature review (6 steps, 5 agents)

📖 **[Full CollabSessions guide →](docs/COLLAB_SESSIONS.md)**

### 🧠 Memory System (Session Persistence & Retrieval)

OpenLMlib includes a powerful memory system that persists session knowledge across work sessions, enabling AI assistants to "remember" what happened in previous sessions and continue work seamlessly.

**Key Features**:
- **Session Lifecycle**: Start/end sessions with automatic context injection and summarization
- **Progressive Retrieval**: 3-layer disclosure (search index → timeline → full details) for token efficiency
- **Retroactive Ingestion**: Auto-ingest session activity from git history — no manual logging needed!
- **Caveman Compression**: Ultra-compressed context injection (46% token savings)

**Memory Tools** (10 tools):
```
session_start           - Start session with context from previous sessions
session_end             - End session and auto-generate summary
log_observation         - Log tool executions for memory building
search_memory           - Layer 1: Search index (~75 tokens/result)
memory_timeline         - Layer 2: Chronological context (~200 tokens/result)
get_observations        - Layer 3: Full details (~750 tokens/result)
inject_context          - Auto-inject relevant context at session start
session_recap           - Synthesized recap of recent sessions (~150-250 tokens)
topic_context           - Deep dive on specific topics (~500-800 tokens)
ingest_git_history      - Auto-ingest from git history (no manual logging!)
```

**Example Workflow**:
```python
# Start of session - automatically loads relevant context
session_start(
    session_id="sess_20260414_001",
    query="memory retrieval optimization"
)
# Returns: Context from previous sessions with relevant observations

# During work - observations are logged automatically
log_observation(
    session_id="sess_20260414_001",
    tool_name="Edit",
    tool_input="Modified memory_retriever.py",
    tool_output="Added auto_inject_context method"
)

# End of session - auto-generates summary
session_end(session_id="sess_20260414_001")
# Creates synthesized knowledge: files touched, decisions, next steps

# Next session - continue seamlessly
session_recap(limit=3)
# Returns: Structured knowledge from last 3 sessions
```

**Token Efficiency**:
- Layer 1 only: 75 tokens/result (search index for filtering)
- Layer 1+2: 275 tokens/result (timeline context)
- Layer 1+2+3: 1,025 tokens/result (full details only for relevant items)
- **vs. full dump**: 3-13x token savings!

📖 **[Memory System Guide →](docs/MEMORY_QUICKSTART.md)**

---

## Architecture

```
OpenLMlib
├── Knowledge Base
│   ├── SQLite (metadata, full-text search)
│   ├── FAISS/Numpy (vector index)
│   └── JSON findings (portable, human-readable)
│
├── MCP Server (56 tools)
│   ├── 15 core library tools
│   ├── 10 memory tools (session lifecycle, progressive retrieval, retroactive ingestion)
│   └── 31 collaboration tools
│
├── CLI
│   ├── Setup and configuration
│   ├── Finding management
│   └── Diagnostics (doctor command)
│
└── CollabSessions
    ├── Message bus (SQLite + JSONL)
    ├── Artifact store
    ├── Session templates
    └── Context compaction
```

---

## Documentation

📚 **Complete documentation is in the [docs/](docs/README.md) folder:**

- **[docs/README.md](docs/README.md)** - Documentation index and quick reference
- **[docs/MCP_TOOLS.md](docs/MCP_TOOLS.md)** - Complete reference for all 56 MCP tools
- **[docs/COLLAB_SESSIONS.md](docs/COLLAB_SESSIONS.md)** - Multi-agent collaboration guide
- **[docs/SYSTEM_PROMPT.md](docs/SYSTEM_PROMPT.md)** - Agent instruction templates

---

## CLI Reference

```bash
# Setup and diagnostics
openlmlib setup          # First-run bootstrap
openlmlib doctor         # Health check
openlmlib --version      # Show version

# Knowledge base
openlmlib init           # Initialize storage
openlmlib add            # Add finding
openlmlib list           # List findings
openlmlib get            # Get finding details
openlmlib query          # Semantic retrieval
openlmlib delete         # Delete finding

# Collaboration
openlmlib-mcp            # MCP server (auto-configured)

# Backup and restore
openlmlib backup         # Create backup
openlmlib restore        # Restore from backup
```

---

## Configuration

### Global Install
- Settings: `~/.openlmlib/config/settings.json`
- Data: `~/.openlmlib/data/`

### Local/Dev Install
- Pass `--settings /path/to/settings.json`

---

## Uninstallation

```bash
# Remove package
npm uninstall -g openlmlib    # if installed via npm
pipx uninstall openlmlib      # if installed via pipx
pip uninstall openlmlib       # if installed from source

# Remove data (optional)
rm -rf ~/.openlmlib           # global install data
rm -rf data/                  # local install data
```

---

## Development

```bash
git clone https://github.com/Vedant9500/LMlib.git
cd LMlib
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev,faiss]"

# Run tests
python -m pytest tests/ -v

# Run MCP server manually
python -m openlmlib.mcp_server --settings ./config/settings.json
```

---

## Notes

- **Vector Search**: Uses FAISS if installed, otherwise Numpy fallback
- **Embedding Model**: `sentence-transformers/all-MiniLM-L6-v2` (default)
- **Python**: Requires 3.10+
- **Global vs Local**: Global installs use `~/.openlmlib/`, local uses project `data/`

---

## Releases

- **Versioning**: Semantic versioning (MAJOR.MINOR.PATCH)
- **Changelog**: [CHANGELOG.md](CHANGELOG.md)
- **Release process**: [RELEASE.md](RELEASE.md)

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development workflow and guidelines.

---

## License

MIT License - see [LICENSE](LICENSE)
