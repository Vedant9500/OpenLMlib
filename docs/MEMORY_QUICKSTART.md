# Memory System Quickstart Guide

**Session persistence, progressive retrieval, and retroactive ingestion for AI assistants.**

This guide shows you how to use OpenLMlib's memory system to maintain context across work sessions — enabling AI assistants to "remember" what happened and continue work seamlessly.

---

## 🚀 Quick Start (MCP Tools)

### Basic Workflow

```python
# MCP tool calls from any AI assistant (Claude Code, Gemini CLI, Qwen Code, etc.)

# 1. Start session — automatically loads relevant context from previous sessions
session_start(
    session_id="sess_20260414_001",
    user_id="agent_gpt4",
    query="How do I optimize retrieval?"
)
# Returns: Context block with up to 50 relevant observations (compressed with caveman ultra)

# 2. During work — observations are logged automatically (or via retroactive ingestion)
log_observation(
    session_id="sess_20260414_001",
    tool_name="Read",
    tool_input="file: retrieval.py",
    tool_output="class RetrievalEngine: ..."
)

# 3. End session — auto-generates summary and synthesizes knowledge
session_end(session_id="sess_20260414_001")
# Creates: Files touched, decisions made, next steps, conventions discovered
```

### Or Use Retroactive Ingestion (No Manual Logging!)

```python
# Forgot to log observations? No problem!
ingest_git_history(
    session_id="sess_20260414_001",
    time_window_hours=24,
    include_uncommitted=True
)
# Scans git history: modified/created/deleted files, commits, lines added/removed
# Works with ANY tool/agent — reads actual codebase state, not tool call logs

# Then check what was synthesized
session_recap(session_id="sess_20260414_001")
```

---

## 🧠 Memory MCP Tools (10 Tools)

### Session Lifecycle

| Tool | Description | Token Cost |
|------|-------------|------------|
| `session_start` | Start session with context injection | ~3,750 tokens (50 obs × 75) |
| `session_end` | End session and trigger summarization | 0 (background processing) |
| `log_observation` | Log tool execution for memory building | 0 (queued for compression) |

### Progressive Retrieval (3-Layer Disclosure)

| Layer | Tool | Description | Tokens/Result |
|-------|------|-------------|---------------|
| **1** | `search_memory` | Lightweight search index (compact metadata) | ~75 tokens |
| **2** | `memory_timeline` | Chronological context (narrative flow) | ~200 tokens |
| **3** | `get_observations` | Full details (complete observation data) | ~750 tokens |

**Token Efficiency**:
```
Layer 1 only:  50 results × 75   = 3,750 tokens
Layer 1 + 2:   50×75 + 10×200   = 5,750 tokens
Layer 1+2+3:   50×75 + 10×200 + 3×750 = 8,000 tokens
vs. Full dump: 50 × 1,000       = 50,000 tokens
Savings: 6.25x reduction!
```

### Context Injection & Synthesis

| Tool | Description | Token Cost |
|------|-------------|------------|
| `inject_context` | Auto-inject relevant context at session start | ~3,750 tokens |
| `session_recap` | Synthesized recap of recent sessions | ~150-250 tokens |
| `topic_context` | Deep dive on specific topics | ~500-800 tokens |

---

## 📚 Progressive Retrieval (Detailed)

### Step 1: Layer 1 — Search Index

```python
# Lightweight search — returns compact metadata for filtering
results = search_memory(
    query="retrieval optimization",
    limit=20,
    filters={"tool_name": "Edit"}  # Optional filters
)

print(f"Found {results['count']} relevant memories")
print(f"Estimated tokens: {results['estimated_tokens']}")

for item in results['results']:
    print(f"  - {item['title']} (ID: {item['id']})")
    print(f"    Type: {item['type']} | Confidence: {item['confidence']:.2f}")
```

### Step 2: Layer 2 — Timeline Context

```python
# Get chronological flow for top results
if results['count'] > 0:
    relevant_ids = [item['id'] for item in results['results'][:5]]
    
    timeline = memory_timeline(ids=relevant_ids, window="10m")
    
    for entry in timeline['timeline']:
        print(f"\n{entry['timestamp']}:")
        print(f"  {entry['narrative']}")
        print(f"  Related: {entry['related']}")
```

### Step 3: Layer 3 — Full Details

```python
# Only for explicitly selected relevant items
if timeline['count'] > 0:
    top_ids = [entry['id'] for entry in timeline['timeline'][:2]]
    
    details = get_observations(ids=top_ids)
    
    for obs in details['observations']:
        print(f"\n{obs['tool_name']}:")
        print(f"  Summary: {obs['compressed_summary']}")
        print(f"  Facts: {obs['facts']}")
        print(f"  Concepts: {obs['concepts']}")
```

---

## 🎯 Context Injection Patterns

### Pattern 1: Session Start (Automatic)

```python
# Most common — call this at the start of every session
result = session_start(
    session_id="sess_20260414_001",
    query="memory retrieval",  # Optional: filter by topic
    limit=50  # Max observations to inject
)

print(f"Session started: {result['session_id']}")
print(f"Context injected: {result['context_injected']}")
print(f"Observations loaded: {result['observation_count']}")
print(f"Context preview: {result['context_block'][:200]}...")
```

### Pattern 2: Quick Recap (Start of Work)

```python
# Call FIRST when starting work — returns structured knowledge
recap = session_recap(limit=3)

print(f"Sessions recapped: {recap['sessions_recapped']}")
print(f"Next steps: {recap['next_steps']}")
print(f"Decisions: {recap['decisions_made']}")
print(f"Files touched: {recap['files_touched']}")
```

### Pattern 3: Deep Dive (After Recap)

```python
# Call AFTER session_recap — get detailed context on a topic
context = topic_context(
    topic="storage",  # Topic from recap
    session_id="sess_20260414_001"  # Optional: specific session
)

print(f"Sessions searched: {context['sessions_searched']}")
print(f"Observations found: {context['observations_found']}")
print(f"Detailed context: {context['detailed_context'][:500]}...")
```

---

## 🔧 Python API (Direct Usage)

For programmatic access (outside MCP tools):

```python
from openlmlib.memory import SessionManager, MemoryStorage, ProgressiveRetriever, ContextBuilder
from openlmlib.runtime import get_runtime
from pathlib import Path

# Initialize
settings_path = Path("config/settings.json")
runtime = get_runtime(settings_path)
storage = MemoryStorage(runtime.conn)
session_mgr = SessionManager(storage)
retriever = ProgressiveRetriever(storage)
context_builder = ContextBuilder(retriever)

# Build session start context
context = context_builder.build_session_start_context(
    session_id="new_session",
    query="retrieval optimization",
    limit=50
)

print(context)
# Output:
# # Previous Session Context
#
# The following knowledge has been retrieved from previous sessions (15 items):
#
# <openlmlib-memory-context>
# # Retrieved Knowledge (15 items)
# ...
# </openlmlib-memory-context>
```

---

## 🔒 Privacy Filtering

### Automatic Protection

```python
from openlmlib.memory.privacy import (
    contains_private,
    filter_private,
    sanitize_for_storage
)

# Detection
text = "API_KEY=sk-live-secret123"
if contains_private(text):
    print("⚠️ Private content detected!")

# Filtering
text = "Config: <private>password123</private>"
safe_text = filter_private(text)
print(safe_text)  # "Config: [PRIVATE CONTENT REMOVED]"

# Full sanitization
text = "PASSWORD=secret123 normal text"
sanitized = sanitize_for_storage(text)
print(sanitized)  # "[REDACTED] normal text"
```

### Protected Patterns
- ✅ `<private>...</private>` tags
- ✅ API keys (`sk-live-*`, `sk-test-*`)
- ✅ Passwords (`PASSWORD=*`, `DB_PASSWORD=*`)
- ✅ Connection strings (`mongodb://user:pass@`)
- ✅ Private keys (`-----BEGIN PRIVATE KEY-----`)

---

## 🗜️ Memory Compression

### Automatic Summarization

```python
from openlmlib.memory.compressor import MemoryCompressor

compressor = MemoryCompressor()

observation = {
    "tool_name": "Read",
    "tool_output": """
    File: retrieval.py

    - Semantic search uses FAISS index
    - Lexical search uses SQLite FTS5
    - Dual-index merging with recency scoring
    - Final ranking: semantic×0.55 + lexical×0.25 + recency×0.20
    """
}

summary = compressor.compress(observation)

print(f"Title: {summary['title']}")
print(f"Type: {summary['type']}")
print(f"Facts: {summary['facts']}")
print(f"Concepts: {summary['concepts']}")
print(f"Compression: {summary['token_count_original']} → {summary['token_count_compressed']} tokens")
```

**Output**:
```
Title: File: retrieval.py
Type: discovery
Facts: ['Semantic search uses FAISS index', 'Lexical search uses SQLite FTS5', ...]
Concepts: ['Semantic Search', 'Faiss Index', 'Lexical Search', 'Sqlite Fts5', ...]
Compression: 52 → 38 tokens (1.4x reduction)
```

---

## ⚙️ Configuration

### Settings (config/settings.json)

```json
{
  "memory": {
    "enabled": true,
    "observations_at_session_start": 50,
    "auto_log_tool_use": true,
    "progressive_disclosure": true,
    "max_context_tokens": 4000,
    "privacy_filtering": true,
    "compression_enabled": true,
    "max_observations_per_session": 500,
    "session_cleanup_days": 30
  }
}
```

### Environment Variables

```bash
# Override settings
export OPENLMLIB_MEMORY_ENABLED=true
export OPENLMLIB_MEMORY_OBSERVATIONS_AT_START=50
export OPENLMLIB_MEMORY_MAX_CONTEXT_TOKENS=4000
```

---

## 🧪 Testing

### Run Tests

```bash
# All memory tests
python -m pytest tests/test_memory_injection.py -v

# Specific test class
python -m pytest tests/test_memory_injection.py::TestSessionManager -v

# With coverage
python -m pytest tests/test_memory_injection.py --cov=openlmlib.memory
```

### Manual Testing

```python
# Quick smoke test
from openlmlib.memory import SessionManager, MemoryStorage
import sqlite3

# In-memory database
conn = sqlite3.connect(":memory:")
storage = MemoryStorage(conn)
session_mgr = SessionManager(storage)

# Test lifecycle
sid = "test_001"
session_mgr.on_session_start(sid, "user")
session_mgr.on_tool_use(sid, "Read", "file.txt", "content")
result = session_mgr.on_session_end(sid)

assert result["status"] == "ended"
print("✅ All good!")
```

---

## 📊 Token Efficiency Guide

### Best Practices

1. **Use Layer 1 First**: Always start with index search
   ```python
   index = search_memory(query="...", limit=50)  # ~3,750 tokens
   ```

2. **Filter Before Fetching**: Identify relevant IDs
   ```python
   relevant = [item['id'] for item in index['results'] if "relevant" in item['title']]
   ```

3. **Fetch Details Selectively**: Only for truly relevant items
   ```python
   details = get_observations(ids=relevant[:5])  # ~3,750 tokens
   ```

4. **Set Reasonable Limits**: Don't inject everything
   ```python
   context = session_start(session_id="...", limit=50)
   ```

### Token Budget Example

```
Session Start Context:
  Layer 1: 50 results × 75 tokens = 3,750 tokens
  Layer 2: 10 results × 200 tokens = 2,000 tokens
  Layer 3:  3 results × 750 tokens = 2,250 tokens
  ───────────────────────────────────────────
  Total: 8,000 tokens (vs. 50,000 for full dump)
  Savings: 6.25x reduction!
```

---

## 🐛 Troubleshooting

### Common Issues

**Problem**: No context injected at session start
```python
# Check if memory system is enabled
settings = load_settings(path)
print(settings.memory.enabled)  # Should be True

# Check if observations exist
recent = storage.get_recent_observations(limit=10)
print(f"Found {len(recent)} recent observations")
```

**Problem**: Privacy filtering too aggressive
```python
# Check what's being filtered
from openlmlib.memory.privacy import PrivacyFilter

pf = PrivacyFilter()
text, filtered = pf.filter_text("your text here")
print(pf.stats())  # Shows what was filtered
```

**Problem**: Compression losing important info
```python
# Increase max narrative length
compressor = MemoryCompressor(
    max_narrative_length=500,  # Default: 300
    max_facts=10,              # Default: 5
)
```

---

## 📖 MCP Integration

All 10 memory tools are available via MCP for AI assistants:

```bash
# Install OpenLMlib MCP server to your AI assistant
openlmlib mcp-config --ide claude_code,gemini_cli,qwen_code

# Then use memory tools from any AI assistant
# Example: Claude Code
claude
> "Start a new session with memory context"
> session_start(session_id="sess_001")

# Example: Gemini CLI
gemini
> "What did I work on recently?"
> session_recap(limit=3)
```

**Supported CLI Tools**: Claude Code, Gemini CLI, Qwen Code, OpenCode, Codex CLI, Aider

📖 **[Full CLI MCP Guide →](CLI_MCP_GLOBAL_CONFIG.md)**

---

## 📚 Additional Resources

- [Memory System Quickstart](MEMORY_QUICKSTART.md) - This guide
- [MCP Tools Reference](MCP_TOOLS.md) - Complete MCP tool reference (52 tools)
- [CLI MCP Integration](../CLI_MCP_GLOBAL_CONFIG.md) - Global MCP config for CLI tools
- [Caveman Compression](CAVEMAN_COMPRESSION.md) - Token-efficient linguistic compression
- [CHANGELOG](../CHANGELOG.md) - Release history and feature additions
- [Test Suite](../tests/test_memory_injection.py) - Comprehensive memory system tests

---

## 💡 Tips

1. **Start Small**: Begin with 20-30 observations per session
2. **Monitor Tokens**: Use `estimated_tokens` fields to track usage
3. **Layer Gradually**: Use Layer 1 → 2 → 3 progression
4. **Use Retroactive Ingestion**: Forget logging? `ingest_git_history` scans git history
5. **Quick Recap First**: Call `session_recap` before deep diving into topics
6. **Compress Wisely**: Adjust compressor params for your use case

---

**Happy memory injecting! 🧠✨**
