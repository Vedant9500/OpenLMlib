# Claude-Mem Memory Injection Analysis & Implementation Plan

## 🔍 Deep Research: How Claude-Mem Injects Memory at the Right Moment

### Core Architecture Overview

Claude-mem implements a **lifecycle hook-based memory system** that automatically captures, compresses, and injects contextual knowledge into AI coding sessions. The key innovation is **timing** — memories are injected at precise moments to maximize relevance while minimizing token overhead.

---

## 🎯 The 5 Lifecycle Hooks (The Secret Sauce)

Claude-mem hooks into Claude Code's plugin system via **5 critical lifecycle events**:

### 1. **SessionStart** (Primary Injection Point)
**When**: Immediately when a new session initializes (before first user prompt)

**What it does**:
- Starts the background worker service (HTTP API on port 37777)
- Waits for worker health check (`curl localhost:37777/health`)
- Calls `hook claude-code context` to inject stored memories
- Loads compressed observations from SQLite database
- Injects **exactly 50 observations** by default (configurable via `CLAUDE_MEM_CONTEXT_OBSERVATIONS`)

**Why it works**: 
- Injects context **before** the user asks anything, so the AI has immediate project awareness
- Uses **pre-processed** data (not real-time computation), so it's fast
- Returns `{"continue":true,"suppressOutput":true}` to avoid cluttering the session

**Hook registration** (from `plugin/hooks/hooks.json`):
```json
{
  "SessionStart": [
    {
      "matcher": "startup|clear|compact",
      "hooks": [
        {
          "type": "command",
          "command": "node \"$_R/scripts/worker-service.cjs\" hook claude-code context",
          "timeout": 60
        }
      ]
    }
  ]
}
```

### 2. **UserPromptSubmit** (Session-Specific Context)
**When**: Right after user submits a prompt, before AI processes it

**What it does**:
- Calls `hook claude-code session-init`
- Captures the user's query for pattern recognition
- Can inject session-specific memory state before processing

**Why it works**: 
- Allows **reactive memory retrieval** based on what the user is actually asking
- Enables semantic search against memory database matched to the prompt

### 3. **PostToolUse** (Observation Capture)
**When**: After every tool execution (file reads, bash commands, edits, etc.)

**What it does**:
- Calls `hook claude-code observation`
- Captures tool input AND output
- Queues data to the background worker for processing
- Matcher `"*"` means it fires on **every tool use**

**Why it works**:
- **Non-blocking**: Hooks queue tasks and return immediately
- **Continuous capture**: Logs everything without slowing the session
- **Privacy filtering**: Content wrapped in `<private>` tags is excluded at the edge

### 4. **Stop** (Session Summarization)
**When**: When Claude finishes responding (session pause point)

**What it does**:
- Calls `hook claude-code summarize`
- Triggers AI-powered compression of raw observations
- Generates structured session summaries (~500 tokens from 1000-10,000 tokens)

**Why it works**:
- Summarization happens **after** the session, not during (avoids latency)
- Uses AI to extract: Title, Subtitle, Narrative, Facts, Concepts, Type, Files

### 5. **SessionEnd** (Finalization)
**When**: When the session is terminated

**What it does**:
- Calls `hook claude-code session-complete`
- Finalizes persistence to SQLite + Chroma vector DB
- Commits all queued data, runs cleanup

---

## 🧠 Progressive Disclosure (Token-Efficient Retrieval)

This is the **key innovation** that makes memory injection practical:

### 3-Layer Retrieval Workflow:

**Layer 1: Search Index** (~50-100 tokens/result)
```javascript
search(query="authentication bug", type="bugfix", limit=10)
// Returns: compact index with IDs, titles, types, timestamps
```

**Layer 2: Timeline** (chronological context)
```javascript
timeline(ids=[123, 456])
// Returns: narrative flow around specific observations
```

**Layer 3: Full Details** (~500-1,000 tokens/result)
```javascript
get_observations(ids=[123, 456])
// Returns: complete observation data (only for explicitly selected IDs)
```

**Why this is brilliant**:
- Claude **filters first** using lightweight index
- Only fetches granular details for **relevant** memories
- Saves ~10x token usage vs. dumping full history
- Prevents context window overflow

---

## ⚙️ The Worker Service Architecture

**What it is**: Background HTTP API (port 37777) managed by Bun

**Responsibilities**:
- Receives queued observations from hooks
- Runs AI compression (semantic summarization)
- Manages SQLite database (sessions, observations, summaries)
- Chroma vector DB for hybrid semantic + keyword search
- Serves 10 search endpoints + web viewer
- Handles MCP tool requests

**Key design principle**: 
Hooks **queue and return immediately** → Worker does heavy lifting asynchronously → Session never blocks

---

## 📦 Storage Architecture

### Hybrid Storage (Best of Both Worlds):

1. **SQLite with FTS5**
   - Structured metadata (sessions, observations, summaries)
   - Full-text keyword search
   - Fast, reliable, ACID-compliant

2. **Chroma Vector Database**
   - Semantic similarity search
   - Embedding-based retrieval
   - Requires Python (`uv` package manager)

3. **JSON Files**
   - Portable findings (your LMlib already does this!)
   - Human-readable backups

---

## 🔐 Privacy Controls

**Edge Exclusion Pattern**:
```xml
<private>
API_KEY=sk-live-abc123xyz789
DATABASE_PASSWORD=supersecret456
</private>
```

- Filtered **before** database write (never stored)
- Not indexed by vector search
- Implemented in PostToolUse hook observer

---

## 🆚 Comparison: Claude-Mem vs. OpenLMlib

| Feature | Claude-Mem | OpenLMlib (Current) |
|---------|-----------|---------------------|
| **Memory Capture** | Automatic (hooks) | Manual (CLI/MCP tools) |
| **Injection Timing** | SessionStart, UserPromptSubmit | Manual retrieval via `query` |
| **Compression** | AI-powered (500-token summaries) | None (full findings stored) |
| **Progressive Disclosure** | 3-layer (index → timeline → details) | Single-layer (retrieve all) |
| **Lifecycle Hooks** | 5 hooks (automated) | None (manual triggers) |
| **Privacy Filtering** | `<private>` tag exclusion | None |
| **Vector Search** | Chroma (semantic + keyword) | FAISS/Numpy (semantic only) |
| **Token Efficiency** | ~10x optimization | Full context loaded |
| **Session Continuity** | Automatic across sessions | Manual session management |

---

## 🚀 Implementation Plan: Add Claude-Mem-Style Memory to OpenLMlib

### Phase 1: Lifecycle Hook System

**Goal**: Implement hook-based observation capture

#### Step 1.1: Define Hook Interface
```python
# openlmlib/hooks.py
from enum import Enum
from typing import Callable, Any, Dict

class HookType(Enum):
    SESSION_START = "session_start"
    USER_PROMPT_SUBMIT = "user_prompt_submit"
    POST_TOOL_USE = "post_tool_use"
    STOP = "stop"
    SESSION_END = "session_end"

class Hook:
    def __init__(self, hook_type: HookType, handler: Callable, matcher: str = "*"):
        self.type = hook_type
        self.handler = handler
        self.matcher = matcher  # regex or "*"
        
class HookRegistry:
    def __init__(self):
        self.hooks: Dict[HookType, list[Hook]] = {ht: [] for ht in HookType}
    
    def register(self, hook: Hook):
        self.hooks[hook.type].append(hook)
    
    def trigger(self, hook_type: HookType, context: Dict[str, Any]):
        for hook in self.hooks[hook_type]:
            if hook.matcher == "*" or matches(hook.matcher, context):
                hook.handler(context)
```

#### Step 1.2: Implement MCP Hook Handlers
```python
# openlmlib/memory_hooks.py
import json
import time
from pathlib import Path
from .db import get_db_connection
from .settings import get_settings

class MemoryHookHandler:
    def __init__(self):
        self.settings = get_settings()
        self.data_dir = Path(self.settings.get("data_dir", "~/.openlmlib/data"))
        self.observation_log = self.data_dir / "observations.jsonl"
        
    def on_post_tool_use(self, context: dict):
        """Capture tool execution results"""
        observation = {
            "timestamp": time.time(),
            "tool": context.get("tool_name"),
            "input": context.get("input"),
            "output": context.get("output"),
            "session_id": context.get("session_id"),
        }
        
        # Privacy filtering
        if self._contains_private(observation["output"]):
            return  # Skip storage
        
        self._append_observation(observation)
    
    def on_session_start(self, context: dict):
        """Inject relevant memories into session"""
        query = context.get("initial_query", "")
        
        # Progressive disclosure: Layer 1 - Index
        index_results = self._search_index(query, limit=50)
        
        # Format for injection
        context_block = self._format_context(index_results)
        
        return {
            "system_prompt_addition": context_block,
            "observation_count": len(index_results)
        }
    
    def on_stop(self, context: dict):
        """Summarize session activity"""
        observations = self._get_session_observations(context.get("session_id"))
        
        # AI-powered compression (use your existing summary_gen.py!)
        summary = self._generate_summary(observations)
        
        self._save_summary(summary)
    
    def _contains_private(self, text: str) -> bool:
        """Check for <private> tags"""
        return "<private>" in text and "</private>" in text
    
    def _search_index(self, query: str, limit: int = 50):
        """Layer 1: Lightweight index search"""
        # Use your existing retrieval.py with token limit
        from .retrieval import retrieve
        return retrieve(query, k=limit, return_metadata_only=True)
```

---

### Phase 2: Background Worker Service

**Goal**: Async processing of observations

#### Step 2.1: Worker Service Skeleton
```python
# openlmlib/worker_service.py
import asyncio
import aiohttp
from aiohttp import web
import json
from .library import KnowledgeLibrary
from .summary_gen import generate_session_summary

class MemoryWorker:
    def __init__(self, port: int = 37778):
        self.port = port
        self.library = KnowledgeLibrary()
        self.observation_queue = asyncio.Queue()
        self.app = web.Application()
        self._setup_routes()
    
    def _setup_routes(self):
        self.app.router.add_post('/observe', self.handle_observation)
        self.app.router.add_get('/health', self.health_check)
        self.app.router.add_post('/context', self.get_context)
        self.app.router.add_post('/summarize', self.handle_summarize)
    
    async def handle_observation(self, request):
        data = await request.json()
        await self.observation_queue.put(data)
        return web.json_response({"status": "queued"})
    
    async def get_context(self, request):
        """Progressive disclosure: Layer 1 - Index"""
        data = await request.json()
        query = data.get("query", "")
        limit = data.get("limit", 50)
        
        # Fast index search
        results = await self._search_index(query, limit)
        
        return web.json_response({
            "observations": results,
            "count": len(results)
        })
    
    async def health_check(self, request):
        return web.json_response({"status": "healthy"})
    
    async def process_queue(self):
        """Background worker loop"""
        while True:
            observation = await self.observation_queue.get()
            try:
                # Compress and store
                await self._compress_and_store(observation)
            except Exception as e:
                print(f"Error processing observation: {e}")
            finally:
                self.observation_queue.task_done()
    
    def start(self):
        """Start the worker service"""
        loop = asyncio.new_event_loop()
        asyncio.create_task(self.process_queue())
        web.run_app(self.app, port=self.port)
```

---

### Phase 3: Progressive Disclosure Integration

**Goal**: Token-efficient memory retrieval

#### Step 3.1: 3-Layer Retrieval
```python
# openlmlib/progressive_retrieval.py
from .retrieval import retrieve
from .library import KnowledgeLibrary

class ProgressiveRetriever:
    def __init__(self):
        self.library = KnowledgeLibrary()
    
    def layer1_search_index(self, query: str, limit: int = 50):
        """
        Returns compact index (~50-100 tokens/result)
        Use for initial filtering
        """
        findings = retrieve(query, k=limit)
        
        return [
            {
                "id": f.id,
                "title": f.claim[:100],
                "type": f.tags[0] if f.tags else "general",
                "timestamp": f.created_at,
                "confidence": f.confidence,
            }
            for f in findings
        ]
    
    def layer2_timeline(self, ids: list[str], window: str = "5m"):
        """
        Returns chronological context (~200 tokens/result)
        Use for understanding sequence of events
        """
        findings = [self.library.get_finding(id) for id in ids]
        
        timeline = []
        for f in findings:
            timeline.append({
                "id": f.id,
                "timestamp": f.created_at,
                "narrative": f.reasoning[:200],
                "related": f.tags,
            })
        
        return sorted(timeline, key=lambda x: x["timestamp"])
    
    def layer3_full_details(self, ids: list[str]):
        """
        Returns complete observations (~500-1000 tokens/result)
        Use only for explicitly selected relevant items
        """
        findings = [self.library.get_finding(id) for id in ids]
        
        return [
            {
                "id": f.id,
                "claim": f.claim,
                "confidence": f.confidence,
                "evidence": f.evidence,
                "reasoning": f.reasoning,
                "caveats": f.caveats,
                "tags": f.tags,
            }
            for f in findings
        ]
```

---

### Phase 4: MCP Tool Integration

**Goal**: Expose memory tools to AI assistants

#### Step 4.1: Add Progressive Disclosure MCP Tools
```python
# Add to openlmlib/mcp_server.py

@mcp.tool()
async def memory_search(query: str, type: str = None, limit: int = 50):
    """Layer 1: Search memory index (lightweight)"""
    retriever = ProgressiveRetriever()
    return retriever.layer1_search_index(query, limit)

@mcp.tool()
async def memory_timeline(ids: list[str], window: str = "5m"):
    """Layer 2: Get chronological context for memory IDs"""
    retriever = ProgressiveRetriever()
    return retriever.layer2_timeline(ids, window)

@mcp.tool()
async def memory_get_observations(ids: list[str]):
    """Layer 3: Get full details for specific memory IDs"""
    retriever = ProgressiveRetriever()
    return retriever.layer3_full_details(ids)

@mcp.tool()
async def memory_inject_context(session_id: str, query: str = None):
    """Auto-inject relevant context at session start"""
    handler = MemoryHookHandler()
    return handler.on_session_start({
        "session_id": session_id,
        "initial_query": query or ""
    })
```

---

### Phase 5: Configuration

**Goal**: Settings for memory injection behavior

```json
// config/settings.json addition
{
  "memory_injection": {
    "enabled": true,
    "observations_at_session_start": 50,
    "progressive_disclosure": {
      "layer1_limit": 50,
      "layer2_window": "5m",
      "layer3_enabled": true
    },
    "privacy": {
      "filter_private_tags": true
    },
    "compression": {
      "enabled": true,
      "max_summary_tokens": 500
    },
    "worker": {
      "port": 37778,
      "auto_start": true
    }
  }
}
```

---

### Phase 6: CLAUDE.md Context Files (Optional)

**Goal**: Auto-generate folder-level context files

```python
# openlmlib/context_files.py
from pathlib import Path

class ContextFileManager:
    def __init__(self, project_dir: Path):
        self.project_dir = project_dir
        self.context_file = project_dir / "CLAUDE.md"
    
    def update_context(self, session_summary: dict):
        """Update Recent Activity section in CLAUDE.md"""
        existing = self._read_existing()
        
        # Preserve user content outside tags
        user_content = self._extract_user_content(existing)
        
        # Update memory section
        memory_section = f"""
<claude-mem-context>
## Recent Activity
{self._format_timeline(session_summary)}
</claude-mem-context>
"""
        
        self._write_combined(user_content, memory_section)
    
    def _contains_private(self, text: str) -> bool:
        """Filter private content"""
        return "<private>" not in text
```

---

## 📋 Implementation Priority & Milestones

### Milestone 1: Core Infrastructure (Week 1)
- [ ] Create `openlmlib/hooks.py` - Hook registry
- [ ] Create `openlmlib/memory_hooks.py` - Hook handlers
- [ ] Create `openlmlib/worker_service.py` - Background worker
- [ ] Add memory injection settings to `config/settings.json`

### Milestone 2: Progressive Retrieval (Week 2)
- [ ] Create `openlmlib/progressive_retrieval.py` - 3-layer retrieval
- [ ] Integrate with existing `retrieval.py`
- [ ] Add MCP tools for memory_search, memory_timeline, memory_get_observations
- [ ] Test token efficiency

### Milestone 3: Session Lifecycle (Week 3)
- [ ] Implement SessionStart hook integration
- [ ] Implement PostToolUse observation capture
- [ ] Implement Stop/SessionEnd summarization
- [ ] Add privacy filtering (`<private>` tag support)

### Milestone 4: Polish & Optimization (Week 4)
- [ ] Add Context file manager (CLAUDE.md auto-generation)
- [ ] Optimize worker service async processing
- [ ] Add configuration UI/CLI
- [ ] Write tests and documentation

---

## 🔑 Key Takeaways from Claude-Mem

1. **Timing is Everything**: Inject at SessionStart, not during prompt
2. **Async Processing**: Hooks queue and return, worker does heavy lifting
3. **Progressive Disclosure**: 3 layers prevent context overflow
4. **Privacy by Design**: Edge filtering with `<private>` tags
5. **Token Efficiency**: ~10x optimization vs. full history dump
6. **Session Continuity**: Memories persist across sessions automatically
7. **AI Compression**: Use LLM to summarize, not just store raw data

---

## 🎯 Recommended Approach for OpenLMlib

**What to adopt**:
1. ✅ Lifecycle hook system (adapted for MCP workflow)
2. ✅ Progressive disclosure (your retrieval.py is already close!)
3. ✅ Session summarization (leverage your existing `summary_gen.py`)
4. ✅ Background worker service (async processing)
5. ✅ Privacy filtering (`<private>` tag support)

**What to skip**:
- ❌ Chroma vector DB (your FAISS is sufficient)
- ❌ Complex plugin system (you have MCP, use it)
- ❌ Bun runtime (stick with Python/asyncio)
- ❌ SQLite FTS5 (your existing search works)

**What you already have**:
- ✅ Knowledge library with findings
- ✅ FAISS semantic search
- ✅ MCP server with 42 tools
- ✅ Summary generation (`summary_gen.py`)
- ✅ CollabSessions (session management!)
- ✅ JSON portable findings

**What to add**:
- 🆕 Hook system for lifecycle events
- 🆕 Progressive disclosure (3-layer retrieval)
- 🆕 Background worker for async observation processing
- 🆕 SessionStart auto-injection
- 🆕 Privacy filtering
- 🆕 Token-efficient context formatting

---

## 💡 Implementation Strategy

### Option A: MCP-Native Approach (Recommended)
Since OpenLMlib already has MCP, implement hooks as **MCP lifecycle events**:

```python
# When MCP client connects → SessionStart
# When tool is called → PostToolUse  
# When MCP client disconnects → SessionEnd
```

**Pros**: 
- No external plugin system needed
- Works with any MCP-compatible client
- Leverages existing MCP infrastructure

**Cons**:
- Requires MCP client to support lifecycle events
- Less automatic than Claude Code plugin hooks

### Option B: CLI Wrapper Approach
Create wrapper scripts that run before/after sessions:

```bash
# Pre-session
openlmlib memory inject --session-id xyz

# Post-session  
openlmlib memory summarize --session-id xyz
```

**Pros**:
- Simple to implement
- Works with any client
- Explicit control

**Cons**:
- Manual triggering (not automatic)
- Less seamless UX

### Option C: Hybrid Approach (Best of Both)
- Use MCP tools for progressive disclosure (automatic)
- Add CLI commands for manual injection (fallback)
- Implement hook system in Python (internal API)
- Support both MCP lifecycle events AND manual triggers

**Recommendation**: Go with **Option C** for maximum flexibility.

---

## 📚 Next Steps

1. **Review this analysis** and decide on implementation approach (A, B, or C)
2. **Start with Phase 1** (hook system + memory capture)
3. **Leverage existing code** (summary_gen.py, retrieval.py, library.py)
4. **Add progressive disclosure** as new MCP tools
5. **Test with real sessions** to validate token efficiency
6. **Document and iterate** based on usage patterns

---

## 📖 References

- Claude-Mem GitHub: https://github.com/thedotmack/claude-mem
- Hooks Architecture: https://www.mintlify.com/thedotmack/claude-mem/hooks-architecture
- Usage Guide: https://apidog.com/blog/how-to-use-claude-mem/
- Complete Guide: https://www.datacamp.com/tutorial/claude-mem-guide
- Architecture Blog: https://www.penligent.ai/hackinglabs/tr/inside-claude-code-the-architecture-behind-tools-memory-hooks-and-mcp/
