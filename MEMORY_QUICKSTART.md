# Memory Injection Quickstart Guide

## 🚀 Quick Start

### Basic Usage

```python
from openlmlib.memory import SessionManager, MemoryStorage
from openlmlib.runtime import get_runtime
from pathlib import Path

# Initialize
settings_path = Path("config/settings.json")
runtime = get_runtime(settings_path)
storage = MemoryStorage(runtime.conn)
session_mgr = SessionManager(storage)

# Start a session (automatically loads previous context)
session_id = "sess_20260413_001"
result = session_mgr.on_session_start(
    session_id, 
    user_id="agent_gpt4",
    query="How do I optimize retrieval?"
)

print(f"Session started: {result['status']}")
print(f"Context injected: {result.get('context_injected', False)}")

# Log tool executions automatically
session_mgr.on_tool_use(
    session_id,
    tool_name="Read",
    tool_input="file: retrieval.py",
    tool_output="class RetrievalEngine: ..."
)

# End session (auto-generates summary)
result = session_mgr.on_session_end(session_id)
print(f"Session ended: {result['status']}")
print(f"Observations logged: {result['observation_count']}")
```

---

## 📚 Progressive Retrieval

### 3-Layer Disclosure

```python
from openlmlib.memory import ProgressiveRetriever

retriever = ProgressiveRetriever(storage)

# Layer 1: Lightweight search index (~75 tokens/result)
index = retriever.layer1_search_index(
    query="retrieval optimization",
    limit=20
)

print(f"Found {len(index)} relevant memories")
for item in index:
    print(f"  - {item.title} (ID: {item.id})")

# Layer 2: Timeline context (~200 tokens/result)
if index:
    relevant_ids = [item.id for item in index[:5]]
    timeline = retriever.layer2_timeline(relevant_ids)
    
    for entry in timeline:
        print(f"\n{entry.timestamp}:")
        print(f"  {entry.narrative}")

# Layer 3: Full details (~750 tokens/result)
details = retriever.layer3_full_details(relevant_ids[:2])

for detail in details:
    print(f"\n{detail.tool_name}:")
    print(f"  {detail.compressed_summary}")
    print(f"  Facts: {detail.facts}")
```

**Token Efficiency**:
- Layer 1 only: 1,500 tokens (20 results × 75)
- Layer 1 + 2: 5,500 tokens (20×75 + 5×200)
- Layer 1 + 2 + 3: 7,000 tokens (20×75 + 5×200 + 2×750)
- **vs. Full dump**: 20,000 tokens (20 × 1,000)
- **Savings**: 3-13x reduction!

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

## 🎯 Context Building

### Session Start Context

```python
from openlmlib.memory import ContextBuilder, ProgressiveRetriever

retriever = ProgressiveRetriever(storage)
context_builder = ContextBuilder(retriever)

# Build session start context
context = context_builder.build_session_start_context(
    session_id="new_session",
    query="retrieval optimization",  # Optional: filter by relevance
    limit=50  # Max observations to inject
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

### Prompt-Specific Context

```python
# More targeted than session start
context = context_builder.build_prompt_context(
    session_id="current_session",
    user_prompt="How does semantic search work?",
    limit=20
)

print(context)
# Output:
# # Relevant Previous Context
# Found 5 relevant memories for your query:
# 
# - [discovery] FAISS index configuration (ID: obs_abc123)
# - [experiment] Embedding model comparison (ID: obs_def456)
# ...
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

## 🔧 Advanced Usage

### Custom Hook Registration

```python
from openlmlib.memory import SessionManager
from openlmlib.memory.hooks import HookType, Hook

def my_custom_handler(context):
    print(f"Session {context['session_id']} started!")
    return {"custom_data": "value"}

# Register custom hook
session_mgr = SessionManager(storage)
session_mgr.register_hook(
    HookType.SESSION_START,
    handler=my_custom_handler,
    priority=10,  # Higher = runs first
    name="my_custom_hook"
)
```

### Async Observation Queue

```python
from openlmlib.memory.observation_queue import ObservationQueue

def process_observation(obs):
    # Heavy processing (compression, embedding, etc.)
    print(f"Processing: {obs['id']}")

queue = ObservationQueue(processor=process_observation)
queue.start()

# Enqueue observations
queue.enqueue({
    "session_id": "sess_001",
    "tool_name": "Read",
    "tool_output": "..."
})

# Cleanup
queue.stop()
```

### Session Statistics

```python
# Get active sessions
active = session_mgr.get_active_sessions()
for session in active:
    print(f"Session: {session['session_id']}")
    print(f"  Observations: {session['observation_count']}")
    print(f"  Duration: {session['duration']:.1f}s")

# Get session info
info = session_mgr.get_session_info("sess_001")
if info:
    print(f"Session is active: {info['is_active']}")

# Get storage stats
stats = storage.get_session_stats("sess_001")
print(f"Type breakdown: {stats['type_breakdown']}")
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
   index = retriever.layer1_search_index(query, limit=50)  # ~3,750 tokens
   ```

2. **Filter Before Fetching**: Identify relevant IDs
   ```python
   relevant = [item.id for item in index if "relevant" in item.title]
   ```

3. **Fetch Details Selectively**: Only for truly relevant items
   ```python
   details = retriever.layer3_full_details(relevant[:5])  # ~3,750 tokens
   ```

4. **Set Reasonable Limits**: Don't inject everything
   ```python
   context = retriever.auto_inject_context(session_id, limit=50)
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

## 📖 Next Steps

1. **Phase 4**: MCP tool integration (coming next)
   - `memory_session_start` tool
   - `memory_search` tool
   - `memory_get_observations` tool

2. **Phase 5**: Advanced features
   - LLM-powered summarization
   - Semantic search integration
   - Context file auto-generation

3. **Phase 6**: Production polish
   - CLI commands
   - Monitoring
   - Performance optimization

---

## 📚 Additional Resources

- [Memory Injection Analysis](MEMORY_INJECTION_ANALYSIS.md) - Deep research on claude-mem
- [Implementation Plan](IMPLEMENTATION_PLAN.md) - 6-phase roadmap
- [Implementation Summary](MEMORY_IMPLEMENTATION_SUMMARY.md) - What was built
- [Test Suite](tests/test_memory_injection.py) - 35 comprehensive tests

---

## 💡 Tips

1. **Start Small**: Begin with 20-30 observations per session
2. **Monitor Tokens**: Use `token_estimate` fields to track usage
3. **Layer Gradually**: Use Layer 1 → 2 → 3 progression
4. **Test Privacy**: Verify filtering doesn't remove needed content
5. **Compress Wisely**: Adjust compressor params for your use case

---

**Happy memory injecting! 🧠✨**
