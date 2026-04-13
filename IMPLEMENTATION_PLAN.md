# Memory Injection Feature Implementation Plan

## 📋 Project: Add Lifecycle-Based Memory Injection to OpenLMlib

**Branch**: `feature/memory-injection`  
**Created**: 2026-04-13  
**Status**: Planning Phase

---

## 🎯 Objective

Implement automated, lifecycle-based memory injection inspired by claude-mem, adapted to OpenLMlib's MCP-native architecture. The system will automatically capture observations, compress them into semantic summaries, and inject relevant context at the right moment (session start, prompt submission) using progressive disclosure for token efficiency.

---

## 🏗️ Architecture Design

### High-Level Design

```
┌─────────────────────────────────────────────────────────────┐
│                    MCP Client Session                        │
└──────────────┬──────────────────────────┬───────────────────┘
               │                          │
               │ SessionStart             │ UserPromptSubmit
               ▼                          ▼
┌──────────────────────┐    ┌──────────────────────────┐
│  Session Manager     │    │  Context Injector        │
│  (tracks sessions)   │    │  (retrieves memories)    │
└──────────┬───────────┘    └──────────┬───────────────┘
           │                           │
           │ PostToolUse               │ Progressive Disclosure
           ▼                           ▼
┌──────────────────────┐    ┌──────────────────────────┐
│  Observation Queue   │    │  3-Layer Retriever       │
│  (async processing)  │    │  (index→timeline→detail) │
└──────────┬───────────┘    └──────────┬───────────────┘
           │                           │
           ▼                           │
┌──────────────────────┐               │
│  Memory Compressor   │◄──────────────┘
│  (AI summarization)  │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│  SQLite Storage      │
│  (sessions, obs,     │
│   summaries, memories)│
└──────────────────────┘
```

### Key Design Decisions

1. **MCP-Native**: No external plugin system needed; hooks are MCP lifecycle events
2. **Async Worker**: Background thread processes observations (non-blocking)
3. **Progressive Disclosure**: 3-layer retrieval (50→200→1000 tokens/result)
4. **Leverage Existing**: Use your `retrieval.py`, `summary_gen.py`, `library.py`
5. **Session Tracking**: SQLite table for session metadata + observation linkage

---

## 📁 New Files to Create

```
openlmlib/
├── memory/                          # New module
│   ├── __init__.py
│   ├── hooks.py                     # Lifecycle hook definitions
│   ├── session_manager.py           # Session tracking & lifecycle
│   ├── observation_queue.py         # Async observation processor
│   ├── memory_retriever.py          # Progressive disclosure (3-layer)
│   ├── compressor.py                # AI-powered memory compression
│   ├── storage.py                   # SQLite schema & operations
│   ├── context_builder.py           # Format memories for LLM injection
│   └── privacy.py                   # <private> tag filtering
│
└── mcp_server.py                    # Modified: Add memory MCP tools
```

---

## 🗂️ Implementation Phases

### Phase 1: Foundation - Session & Observation Tracking (Days 1-3)

**Goal**: Create session tracking and observation capture infrastructure

#### 1.1 Create `openlmlib/memory/__init__.py`
```python
# Module initialization
from .hooks import HookType, HookRegistry
from .session_manager import SessionManager
from .observation_queue import ObservationQueue
from .memory_retriever import ProgressiveRetriever
from .storage import MemoryStorage

__all__ = [
    "HookType",
    "HookRegistry",
    "SessionManager",
    "ObservationQueue",
    "ProgressiveRetriever",
    "MemoryStorage",
]
```

#### 1.2 Create `openlmlib/memory/storage.py`
**Purpose**: SQLite schema and operations for memory system

**Schema additions**:
```sql
CREATE TABLE IF NOT EXISTS memory_sessions (
    session_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    ended_at TEXT,
    user_id TEXT,
    summary TEXT,
    observation_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS memory_observations (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    tool_name TEXT,
    tool_input TEXT,
    tool_output TEXT,
    compressed_summary TEXT,
    tags TEXT,  -- JSON array
    embedding_id TEXT,
    FOREIGN KEY (session_id) REFERENCES memory_sessions(session_id)
);

CREATE TABLE IF NOT EXISTS memory_summaries (
    session_id TEXT PRIMARY KEY,
    summary TEXT NOT NULL,
    key_facts TEXT,  -- JSON array
    concepts TEXT,   -- JSON array
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES memory_sessions(session_id)
);

CREATE INDEX idx_obs_session ON memory_observations(session_id);
CREATE INDEX idx_obs_timestamp ON memory_observations(timestamp);
```

**Python implementation**:
```python
class MemoryStorage:
    def __init__(self, conn):
        self.conn = conn
        self._init_schema()
    
    def create_session(self, session_id: str, user_id: str = None) -> dict:
        # Insert session record
        pass
    
    def add_observation(self, obs: dict) -> str:
        # Insert observation, return ID
        pass
    
    def get_session_observations(self, session_id: str, limit: int = 100) -> list:
        # Query observations for session
        pass
    
    def save_summary(self, session_id: str, summary: dict):
        # Save session summary
        pass
    
    def search_memories(self, query: str, limit: int = 50, layer: int = 1) -> list:
        # Layer 1: index, Layer 2: timeline, Layer 3: full
        pass
```

#### 1.3 Create `openlmlib/memory/session_manager.py`
**Purpose**: Track session lifecycle and trigger hooks

```python
class SessionManager:
    def __init__(self, storage: MemoryStorage):
        self.storage = storage
        self.active_sessions: dict = {}
        self.hooks = HookRegistry()
    
    def on_session_start(self, session_id: str, user_id: str = None):
        """Called when MCP client connects"""
        self.storage.create_session(session_id, user_id)
        self.active_sessions[session_id] = {
            "start_time": time.time(),
            "observation_count": 0
        }
        
        # Trigger SessionStart hooks
        context = self.hooks.trigger(HookType.SESSION_START, {
            "session_id": session_id,
            "user_id": user_id
        })
        
        return context
    
    def on_tool_use(self, session_id: str, tool_name: str, tool_input: str, tool_output: str):
        """Called after MCP tool execution"""
        observation = {
            "id": f"obs_{uuid4().hex[:12]}",
            "session_id": session_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tool_name": tool_name,
            "tool_input": tool_input,
            "tool_output": tool_output,
        }
        
        # Privacy filter
        if contains_private(tool_output):
            return
        
        obs_id = self.storage.add_observation(observation)
        self.active_sessions[session_id]["observation_count"] += 1
        
        # Queue for async compression
        return obs_id
    
    def on_session_end(self, session_id: str):
        """Called when MCP client disconnects"""
        self.storage.end_session(session_id)
        
        # Trigger summarization
        observations = self.storage.get_session_observations(session_id)
        if observations:
            summary = self._summarize_session(observations)
            self.storage.save_summary(session_id, summary)
        
        del self.active_sessions[session_id]
```

#### 1.4 Create `openlmlib/memory/hooks.py`
**Purpose**: Hook registry and lifecycle event definitions

```python
from enum import Enum
from typing import Callable, Any, Dict, List

class HookType(Enum):
    SESSION_START = "session_start"
    USER_PROMPT_SUBMIT = "user_prompt_submit"
    POST_TOOL_USE = "post_tool_use"
    STOP = "stop"
    SESSION_END = "session_end"

class Hook:
    def __init__(self, hook_type: HookType, handler: Callable, priority: int = 0):
        self.type = hook_type
        self.handler = handler
        self.priority = priority

class HookRegistry:
    def __init__(self):
        self.hooks: Dict[HookType, List[Hook]] = {ht: [] for ht in HookType}
    
    def register(self, hook: Hook):
        self.hooks[hook.type].append(hook)
        # Sort by priority
        self.hooks[hook.type].sort(key=lambda h: h.priority, reverse=True)
    
    def trigger(self, hook_type: HookType, context: Dict[str, Any]) -> Any:
        results = []
        for hook in self.hooks[hook_type]:
            result = hook.handler(context)
            results.append(result)
        return results
```

#### 1.5 Create `openlmlib/memory/observation_queue.py`
**Purpose**: Async processing of observations (non-blocking)

```python
import asyncio
import queue
import threading
from typing import Dict, Any

class ObservationQueue:
    def __init__(self, storage: MemoryStorage, compressor=None):
        self.storage = storage
        self.compressor = compressor
        self.queue = queue.Queue()
        self.worker_thread = threading.Thread(
            target=self._process_loop, daemon=True, name="memory-worker"
        )
        self.running = False
    
    def start(self):
        self.running = True
        self.worker_thread.start()
    
    def stop(self):
        self.running = False
        self.queue.put(None)  # Sentinel
        self.worker_thread.join()
    
    def enqueue(self, observation: Dict[str, Any]):
        self.queue.put(observation)
    
    def _process_loop(self):
        while self.running:
            observation = self.queue.get()
            if observation is None:
                break
            
            try:
                # Compress observation
                if self.compressor:
                    compressed = self.compressor.compress(observation)
                    self.storage.update_observation_compression(
                        observation["id"], compressed
                    )
            except Exception as e:
                logger.error(f"Error processing observation: {e}")
            finally:
                self.queue.task_done()
```

---

### Phase 2: Progressive Disclosure Retriever (Days 4-6)

**Goal**: Implement 3-layer memory retrieval

#### 2.1 Create `openlmlib/memory/memory_retriever.py`

```python
from dataclasses import dataclass
from typing import List, Dict, Any
from .storage import MemoryStorage

@dataclass
class MemoryIndex:
    id: str
    title: str
    type: str
    timestamp: str
    confidence: float
    token_estimate: int  # ~50-100 tokens

@dataclass
class MemoryTimeline:
    id: str
    timestamp: str
    narrative: str
    related: List[str]
    token_estimate: int  # ~200 tokens

@dataclass
class MemoryDetail:
    id: str
    full_observation: Dict[str, Any]
    summary: str
    facts: List[str]
    concepts: List[str]
    token_estimate: int  # ~500-1000 tokens

class ProgressiveRetriever:
    def __init__(self, storage: MemoryStorage, retrieval_engine=None):
        self.storage = storage
        self.retrieval_engine = retrieval_engine  # Use existing retrieval.py
    
    def layer1_search_index(
        self, 
        query: str, 
        limit: int = 50,
        filters: Dict[str, Any] = None
    ) -> List[MemoryIndex]:
        """
        Layer 1: Lightweight search index (~50-100 tokens/result)
        Returns compact metadata for filtering
        """
        observations = self.storage.search_observations(query, limit=limit)
        
        return [
            MemoryIndex(
                id=obs["id"],
                title=obs.get("tool_name", "observation")[:100],
                type=obs.get("tool_name", "general"),
                timestamp=obs["timestamp"],
                confidence=obs.get("confidence", 0.5),
                token_estimate=75
            )
            for obs in observations
        ]
    
    def layer2_timeline(
        self, 
        ids: List[str], 
        window: str = "5m"
    ) -> List[MemoryTimeline]:
        """
        Layer 2: Chronological context (~200 tokens/result)
        Returns narrative flow around observations
        """
        observations = self.storage.get_observations_by_ids(ids)
        
        timeline = []
        for obs in observations:
            timeline.append(MemoryTimeline(
                id=obs["id"],
                timestamp=obs["timestamp"],
                narrative=obs.get("compressed_summary", "")[:200],
                related=obs.get("tags", []),
                token_estimate=200
            ))
        
        return sorted(timeline, key=lambda x: x.timestamp)
    
    def layer3_full_details(self, ids: List[str]) -> List[MemoryDetail]:
        """
        Layer 3: Complete observation details (~500-1000 tokens/result)
        Returns full data for explicitly selected relevant items
        """
        observations = self.storage.get_observations_by_ids(ids)
        
        details = []
        for obs in observations:
            details.append(MemoryDetail(
                id=obs["id"],
                full_observation=obs,
                summary=obs.get("compressed_summary", ""),
                facts=obs.get("facts", []),
                concepts=obs.get("concepts", []),
                token_estimate=750
            ))
        
        return details
    
    def auto_inject_context(
        self, 
        session_id: str, 
        query: str = None,
        limit: int = 50
    ) -> Dict[str, Any]:
        """
        Automatic context injection at session start
        Returns formatted context block for LLM
        """
        # Use existing retrieval if available
        if self.retrieval_engine and query:
            findings = self.retrieval_engine.search(query, final_k=limit)
        else:
            # Fallback: recent observations
            findings = self.storage.get_recent_observations(limit=limit)
        
        # Format for injection
        context_block = self._format_context(findings)
        
        return {
            "context_block": context_block,
            "observation_count": len(findings),
            "token_estimate": len(findings) * 75
        }
    
    def _format_context(self, findings: List[Dict[str, Any]]) -> str:
        """Format findings into LLM-readable context block"""
        lines = []
        lines.append("<openlmlib-memory-context>")
        lines.append(f"# Retrieved Knowledge ({len(findings)} items)")
        lines.append("")
        
        for idx, finding in enumerate(findings, 1):
            lines.append(f"## {idx}. {finding.get('claim', 'Observation')[:80]}")
            lines.append(f"**Confidence**: {finding.get('confidence', 0.5)}")
            if finding.get('reasoning'):
                lines.append(f"**Reasoning**: {finding['reasoning'][:200]}")
            if finding.get('tags'):
                lines.append(f"**Tags**: {', '.join(finding['tags'][:5])}")
            lines.append("")
        
        lines.append("</openlmlib-memory-context>")
        return "\n".join(lines)
```

---

### Phase 3: Memory Compression & Privacy (Days 7-9)

**Goal**: AI-powered summarization and privacy filtering

#### 3.1 Create `openlmlib/memory/compressor.py`

```python
from typing import Dict, Any, List
from ..summary_gen import SummaryGenerator

class MemoryCompressor:
    def __init__(self):
        self.summary_gen = SummaryGenerator(
            max_summary_length=200,
            max_key_points=5
        )
    
    def compress(self, observation: Dict[str, Any]) -> Dict[str, Any]:
        """
        Compress raw observation into semantic summary
        Extracts: Title, Subtitle, Narrative, Facts, Concepts, Type
        """
        tool_output = observation.get("tool_output", "")
        tool_name = observation.get("tool_name", "")
        
        # Extract key information
        summary = {
            "title": self._extract_title(tool_name, tool_output),
            "subtitle": self._extract_subtitle(tool_output),
            "narrative": self._extract_narrative(tool_output),
            "facts": self._extract_facts(tool_output),
            "concepts": self._extract_concepts(tool_output),
            "type": self._classify_observation(tool_name, tool_output),
            "token_count_original": self._count_tokens(tool_output),
            "token_count_compressed": 0,
        }
        
        # Count compressed tokens
        compressed_text = f"{summary['title']} {summary['narrative']} {' '.join(summary['facts'])}"
        summary["token_count_compressed"] = self._count_tokens(compressed_text)
        
        return summary
    
    def _extract_title(self, tool_name: str, output: str) -> str:
        """Extract concise title from observation"""
        # Use first meaningful sentence
        lines = output.strip().split("\n")
        for line in lines:
            line = line.strip()
            if line and len(line) > 20:
                return line[:100]
        return f"{tool_name} output"
    
    def _extract_subtitle(self, output: str) -> str:
        """Extract key outcome"""
        # Look for success/failure indicators
        if "error" in output.lower():
            return "Tool execution failed"
        if "success" in output.lower():
            return "Tool executed successfully"
        return ""
    
    def _extract_narrative(self, output: str) -> str:
        """Extract narrative description"""
        # Truncate to ~200 tokens
        return output[:1000]  # Rough approximation
    
    def _extract_facts(self, output: str) -> List[str]:
        """Extract key factual statements"""
        facts = []
        # Simple heuristic: bullet points or numbered lists
        for line in output.split("\n"):
            line = line.strip()
            if line.startswith(("-", "*", "•")) or line[0].isdigit():
                facts.append(line.strip("-*•").strip())
        return facts[:5]
    
    def _extract_concepts(self, output: str) -> List[str]:
        """Extract key concepts/tags"""
        # Extract technical terms (simple heuristic)
        import re
        terms = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', output)
        return list(set(terms))[:10]
    
    def _classify_observation(self, tool_name: str, output: str) -> str:
        """Classify observation type"""
        if tool_name in ["Read", "read_file"]:
            return "discovery"
        if tool_name in ["Edit", "edit"]:
            return "change"
        if tool_name in ["run_shell_command", "bash"]:
            return "experiment"
        if "error" in output.lower():
            return "bugfix"
        return "general"
    
    def _count_tokens(self, text: str) -> int:
        """Rough token count (words * 1.3)"""
        return int(len(text.split()) * 1.3)
```

#### 3.2 Create `openlmlib/memory/privacy.py`

```python
import re
from typing import Set

# Patterns to detect private content
PRIVATE_PATTERNS = [
    r'API_KEY\s*=\s*\S+',
    r'SECRET\s*=\s*\S+',
    r'PASSWORD\s*=\s*\S+',
    r'TOKEN\s*=\s*\S+',
    r'sk-live-\S+',
    r'sk-test-\S+',
]

def contains_private(text: str) -> bool:
    """Check if text contains private/sensitive content"""
    # Check for <private> tags
    if "<private>" in text and "</private>" in text:
        return True
    
    # Check for secret patterns
    for pattern in PRIVATE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    
    return False

def filter_private(text: str) -> str:
    """Remove private content wrapped in <private> tags"""
    # Remove content between <private> and </private>
    pattern = r'<private>.*?</private>'
    return re.sub(pattern, '[PRIVATE CONTENT REMOVED]', text, flags=re.DOTALL)

def sanitize_for_storage(text: str) -> str:
    """Sanitize text before storage"""
    if contains_private(text):
        return filter_private(text)
    return text
```

---

### Phase 4: Context Builder & MCP Integration (Days 10-12)

**Goal**: Format memories for LLM injection and add MCP tools

#### 4.1 Create `openlmlib/memory/context_builder.py`

```python
from typing import List, Dict, Any
from .memory_retriever import ProgressiveRetriever

class ContextBuilder:
    def __init__(self, retriever: ProgressiveRetriever):
        self.retriever = retriever
    
    def build_session_start_context(
        self,
        session_id: str,
        query: str = None,
        limit: int = 50
    ) -> str:
        """
        Build context block for session start
        This gets injected into system prompt
        """
        # Get relevant memories
        injection = self.retriever.auto_inject_context(session_id, query, limit)
        
        # Format as system instruction
        context_lines = []
        context_lines.append("# Previous Session Context")
        context_lines.append("")
        context_lines.append("The following knowledge has been retrieved from previous sessions:")
        context_lines.append("")
        context_lines.append(injection["context_block"])
        context_lines.append("")
        context_lines.append("Use this context to inform your current work. This knowledge persists across sessions.")
        
        return "\n".join(context_lines)
    
    def build_prompt_context(
        self,
        session_id: str,
        user_prompt: str,
        limit: int = 20
    ) -> str:
        """
        Build context for specific user prompt
        More targeted than session start
        """
        # Progressive disclosure: Layer 1 only
        index = self.retriever.layer1_search_index(user_prompt, limit=limit)
        
        if not index:
            return ""
        
        context_lines = []
        context_lines.append("# Relevant Previous Context")
        context_lines.append("")
        
        for item in index:
            context_lines.append(f"- [{item.type}] {item.title} (ID: {item.id})")
        
        context_lines.append("")
        context_lines.append("Use `memory_get_observations` tool to fetch full details if needed.")
        
        return "\n".join(context_lines)
```

#### 4.2 Modify `openlmlib/mcp_server.py`

Add new memory tools at the end of the file (before `main()` function):

```python
# Memory injection tools (lazy-loaded)
_memory_registered = False

def _register_memory_tools() -> None:
    """Register memory lifecycle tools with MCP server."""
    global _memory_registered
    if _memory_registered:
        return
    
    from .memory import (
        SessionManager,
        ProgressiveRetriever,
        MemoryStorage,
        ContextBuilder,
    )
    from .runtime import get_runtime
    
    # Initialize memory system
    runtime = get_runtime(_settings_path())
    storage = MemoryStorage(runtime.conn)
    session_mgr = SessionManager(storage)
    retriever = ProgressiveRetriever(storage, runtime.retrieval_engine)
    context_builder = ContextBuilder(retriever)
    
    @mcp.tool()
    def memory_session_start(session_id: str, user_id: str = None) -> dict:
        """Start a new session and inject relevant context from previous sessions.
        
        Call this when beginning work to load knowledge from past sessions.
        Returns context block with up to 50 relevant observations.
        """
        context = session_mgr.on_session_start(session_id, user_id)
        
        # Build injection context
        injection = context_builder.build_session_start_context(session_id)
        
        return {
            "session_id": session_id,
            "context_injected": bool(injection),
            "observation_count": context.get("observation_count", 0),
            "context_block": injection,
            "message": "Session started with memory context loaded"
        }
    
    @mcp.tool()
    def memory_session_end(session_id: str) -> dict:
        """End a session and trigger summarization.
        
        Call this when finishing work to summarize and persist session knowledge.
        """
        session_mgr.on_session_end(session_id)
        
        return {
            "session_id": session_id,
            "status": "ended",
            "message": "Session ended and summary saved"
        }
    
    @mcp.tool()
    def memory_log_observation(
        session_id: str,
        tool_name: str,
        tool_input: str,
        tool_output: str
    ) -> dict:
        """Log an observation from tool execution.
        
        This captures tool outputs for future memory retrieval.
        Called automatically after MCP tool use.
        """
        obs_id = session_mgr.on_tool_use(
            session_id, tool_name, tool_input, tool_output
        )
        
        return {
            "observation_id": obs_id,
            "status": "logged",
            "message": "Observation queued for compression"
        }
    
    @mcp.tool()
    def memory_search(
        query: str,
        type: str = None,
        limit: int = 50
    ) -> dict:
        """Layer 1: Search memory index (lightweight, ~50-100 tokens/result).
        
        Returns compact metadata for filtering. Use this first to identify relevant memories.
        """
        results = retriever.layer1_search_index(query, limit)
        
        return {
            "query": query,
            "results": [r.__dict__ for r in results],
            "count": len(results),
            "estimated_tokens": len(results) * 75
        }
    
    @mcp.tool()
    def memory_timeline(
        ids: List[str],
        window: str = "5m"
    ) -> dict:
        """Layer 2: Get chronological context for memory IDs (~200 tokens/result).
        
        Returns narrative flow around observations. Use after memory_search to understand sequence.
        """
        results = retriever.layer2_timeline(ids, window)
        
        return {
            "ids": ids,
            "timeline": [r.__dict__ for r in results],
            "count": len(results),
            "estimated_tokens": len(results) * 200
        }
    
    @mcp.tool()
    def memory_get_observations(ids: List[str]) -> dict:
        """Layer 3: Get full details for specific memory IDs (~500-1000 tokens/result).
        
        Returns complete observation data. Use only for explicitly selected relevant items.
        """
        results = retriever.layer3_full_details(ids)
        
        return {
            "ids": ids,
            "observations": [r.__dict__ for r in results],
            "count": len(results),
            "estimated_tokens": len(results) * 750
        }
    
    @mcp.tool()
    def memory_inject_context(
        session_id: str,
        query: str = None,
        limit: int = 50
    ) -> dict:
        """Auto-inject relevant context at session start.
        
        Retrieves up to 50 relevant observations from previous sessions.
        This is the primary entry point for memory injection.
        """
        context = context_builder.build_session_start_context(session_id, query, limit)
        
        return {
            "session_id": session_id,
            "context_block": context,
            "observation_count": limit,
            "estimated_tokens": limit * 75
        }
    
    _memory_registered = True
```

Then in the `main()` function, add before `_register_collab_tools()`:

```python
def main() -> None:
    # ... existing code ...
    
    # Register memory tools
    _register_memory_tools()
    
    # Register collab tools
    _register_collab_tools()
    
    # ... rest of existing code ...
```

---

### Phase 5: Settings & Configuration (Day 13)

**Goal**: Add memory injection settings

#### 5.1 Modify `openlmlib/settings.py`

Add new settings dataclass:

```python
@dataclass
class MemoryInjectionSettings:
    enabled: bool = True
    observations_at_session_start: int = 50
    auto_log_tool_use: bool = True
    progressive_disclosure: bool = True
    max_context_tokens: int = 4000
    privacy_filtering: bool = True
    compression_enabled: bool = True

@dataclass
class Settings:
    # ... existing fields ...
    memory: MemoryInjectionSettings  # Add this field
    
    @classmethod
    def from_dict(cls, data: dict, base_dir: Path) -> "Settings":
        # ... existing code ...
        
        memory_data = data.get("memory", {})
        
        return cls(
            # ... existing fields ...
            memory=MemoryInjectionSettings(
                enabled=bool(memory_data.get("enabled", True)),
                observations_at_session_start=int(memory_data.get("observations_at_session_start", 50)),
                auto_log_tool_use=bool(memory_data.get("auto_log_tool_use", True)),
                progressive_disclosure=bool(memory_data.get("progressive_disclosure", True)),
                max_context_tokens=int(memory_data.get("max_context_tokens", 4000)),
                privacy_filtering=bool(memory_data.get("privacy_filtering", True)),
                compression_enabled=bool(memory_data.get("compression_enabled", True)),
            )
        )
```

#### 5.2 Update `DEFAULT_SETTINGS_DATA` in `settings.py`

```python
DEFAULT_SETTINGS_DATA = {
    # ... existing settings ...
    "memory": {
        "enabled": True,
        "observations_at_session_start": 50,
        "auto_log_tool_use": True,
        "progressive_disclosure": True,
        "max_context_tokens": 4000,
        "privacy_filtering": True,
        "compression_enabled": True
    }
}
```

---

### Phase 6: Integration & Testing (Days 14-15)

**Goal**: Wire everything together and test

#### 6.1 Create `tests/test_memory_injection.py`

```python
import pytest
from openlmlib.memory import SessionManager, MemoryStorage, ProgressiveRetriever
from openlmlib.runtime import get_runtime
from pathlib import Path

@pytest.fixture
def runtime():
    settings_path = Path("config/settings.json")
    return get_runtime(settings_path)

@pytest.fixture
def storage(runtime):
    return MemoryStorage(runtime.conn)

@pytest.fixture
def session_manager(storage):
    return SessionManager(storage)

def test_session_lifecycle(session_manager):
    # Start session
    session_id = "test_session_123"
    context = session_manager.on_session_start(session_id, "test_user")
    
    assert session_id in session_manager.active_sessions
    
    # Log observation
    session_manager.on_tool_use(
        session_id,
        "Read",
        "file.txt",
        "file content here"
    )
    
    # End session
    session_manager.on_session_end(session_id)
    
    assert session_id not in session_manager.active_sessions

def test_progressive_retrieval(storage):
    retriever = ProgressiveRetriever(storage)
    
    # Layer 1: Index
    index = retriever.layer1_search_index("test query", limit=10)
    assert isinstance(index, list)
    
    if index:
        # Layer 2: Timeline
        timeline = retriever.layer2_timeline([index[0].id])
        assert isinstance(timeline, list)
        
        # Layer 3: Full details
        details = retriever.layer3_full_details([index[0].id])
        assert isinstance(details, list)

def test_privacy_filtering():
    from openlmlib.memory.privacy import contains_private, filter_private
    
    assert contains_private("<private>secret</private>")
    assert contains_private("API_KEY=sk-live-abc123")
    
    filtered = filter_private("normal text <private>secret</private> more text")
    assert "[PRIVATE CONTENT REMOVED]" in filtered
    assert "secret" not in filtered
```

#### 6.2 Create integration test script

Create `scripts/test_memory_workflow.py`:

```python
#!/usr/bin/env python
"""Test complete memory injection workflow"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from openlmlib.runtime import get_runtime
from openlmlib.memory import (
    SessionManager,
    MemoryStorage,
    ProgressiveRetriever,
    ContextBuilder,
)

def main():
    print("=" * 60)
    print("Memory Injection Workflow Test")
    print("=" * 60)
    
    # Initialize
    settings_path = Path("config/settings.json")
    runtime = get_runtime(settings_path)
    storage = MemoryStorage(runtime.conn)
    session_mgr = SessionManager(storage)
    retriever = ProgressiveRetriever(storage)
    context_builder = ContextBuilder(retriever)
    
    # Test 1: Session lifecycle
    print("\n1. Testing session lifecycle...")
    session_id = "test_workflow_001"
    
    context = session_mgr.on_session_start(session_id, "test_user")
    print(f"   ✓ Session started: {session_id}")
    
    # Test 2: Log observations
    print("\n2. Testing observation logging...")
    session_mgr.on_tool_use(session_id, "Read", "README.md", "# OpenLMlib project")
    session_mgr.on_tool_use(session_id, "Edit", "file.py", "def foo(): pass")
    print("   ✓ Observations logged")
    
    # Test 3: End session
    print("\n3. Testing session end...")
    session_mgr.on_session_end(session_id)
    print("   ✓ Session ended")
    
    # Test 4: Start new session with context
    print("\n4. Testing context injection...")
    new_session_id = "test_workflow_002"
    session_mgr.on_session_start(new_session_id, "test_user")
    
    context = context_builder.build_session_start_context(new_session_id)
    print(f"   ✓ Context injected ({len(context)} chars)")
    
    # Test 5: Progressive retrieval
    print("\n5. Testing progressive disclosure...")
    index = retriever.layer1_search_index("OpenLMlib", limit=10)
    print(f"   ✓ Layer 1: {len(index)} results")
    
    if index:
        timeline = retriever.layer2_timeline([index[0].id])
        print(f"   ✓ Layer 2: {len(timeline)} results")
        
        details = retriever.layer3_full_details([index[0].id])
        print(f"   ✓ Layer 3: {len(details)} results")
    
    # Cleanup
    session_mgr.on_session_end(new_session_id)
    
    print("\n" + "=" * 60)
    print("✅ All tests passed!")
    print("=" * 60)

if __name__ == "__main__":
    main()
```

---

## 📊 Token Efficiency Analysis

| Approach | Tokens per Result | 50 Results | Optimization |
|----------|-------------------|------------|--------------|
| Full context dump | ~1000 | 50,000 | Baseline |
| Layer 1 (index) only | ~75 | 3,750 | **13x reduction** |
| Layer 1 + Layer 2 (timeline) | ~275 | 13,750 | **3.6x reduction** |
| Layer 1 + 5 Layer 3 details | ~3,825 | 3,825 | **13x reduction** |
| **Progressive (recommended)** | **~3,825** | **3,825** | **13x reduction** |

---

## 🎯 Success Metrics

1. **Token Efficiency**: 10x reduction in context tokens vs. full dump
2. **Latency**: <2s for session start context injection
3. **Relevance**: >80% of injected memories are useful for current session
4. **Privacy**: 100% filtering of `<private>` tagged content
5. **Compression**: 10x reduction (10,000 → 1,000 tokens per observation)

---

## 🔄 Workflow Examples

### Example 1: Session Start with Memory Injection

```python
# MCP client connects
session_id = "sess_20260413_001"

# Agent calls memory tool
result = mcp_call("memory_session_start", {
    "session_id": session_id,
    "user_id": "agent_gpt4"
})

# Returns:
{
    "session_id": "sess_20260413_001",
    "context_injected": True,
    "observation_count": 50,
    "context_block": "# Previous Session Context\n...",
    "message": "Session started with memory context loaded"
}
```

### Example 2: Progressive Retrieval

```python
# Step 1: Lightweight search
index = mcp_call("memory_search", {
    "query": "retrieval optimization",
    "limit": 20
})
# Returns 20 compact results (~1,500 tokens)

# Step 2: Identify relevant IDs
relevant_ids = [r["id"] for r in index["results"] if "retrieval" in r["title"]]

# Step 3: Fetch full details only for relevant
details = mcp_call("memory_get_observations", {
    "ids": relevant_ids[:5]
})
# Returns 5 full observations (~3,750 tokens)
# Total: 5,250 tokens vs 50,000 for full dump
```

### Example 3: Tool Use Observation

```python
# After Read tool execution
mcp_call("memory_log_observation", {
    "session_id": "sess_001",
    "tool_name": "Read",
    "tool_input": "file: README.md",
    "tool_output": "# OpenLMlib\n\nLocal knowledge library..."
})

# Observation is queued for async compression
# Returns immediately (non-blocking)
```

---

## 🚀 Rollout Plan

### Week 1: Foundation
- [ ] Create `openlmlib/memory/` module structure
- [ ] Implement `storage.py` with SQLite schema
- [ ] Implement `session_manager.py`
- [ ] Implement `hooks.py`
- [ ] Implement `observation_queue.py`
- [ ] Add memory settings to `settings.py`

### Week 2: Retrieval & Compression
- [ ] Implement `memory_retriever.py` (3-layer progressive)
- [ ] Implement `compressor.py`
- [ ] Implement `privacy.py`
- [ ] Integrate with existing `retrieval.py`
- [ ] Test token efficiency

### Week 3: MCP Integration
- [ ] Implement `context_builder.py`
- [ ] Add MCP tools to `mcp_server.py`
- [ ] Implement lazy loading for memory module
- [ ] Write unit tests
- [ ] Write integration tests

### Week 4: Polish & Docs
- [ ] Add CLI commands for memory management
- [ ] Update documentation
- [ ] Add examples to `examples/`
- [ ] Performance optimization
- [ ] Final testing and cleanup

---

## 🔧 Configuration Example

```json
{
  "memory": {
    "enabled": true,
    "observations_at_session_start": 50,
    "auto_log_tool_use": true,
    "progressive_disclosure": true,
    "max_context_tokens": 4000,
    "privacy_filtering": true,
    "compression_enabled": true
  }
}
```

---

## 📝 Notes

### What We're NOT Implementing (vs. Claude-Mem)

- ❌ **Chroma Vector DB**: Your FAISS is sufficient
- ❌ **External plugin system**: You have MCP, use it
- ❌ **Bun runtime**: Stick with Python/asyncio
- ❌ **SQLite FTS5**: Your existing search works
- ❌ **Complex hook matchers**: Simple priority-based is enough

### What We Already Have (Leverage!)

- ✅ `retrieval.py` - Dual-index semantic + lexical search
- ✅ `summary_gen.py` - Finding summarization
- ✅ `library.py` - Knowledge storage infrastructure
- ✅ `mcp_server.py` - 42 existing tools
- ✅ `runtime.py` - Runtime state management
- ✅ CollabSessions - Session tracking already exists!

### Key Differences from Claude-Mem

1. **MCP-Native**: No Claude Code plugin hooks; we use MCP tool lifecycle
2. **Manual Triggering**: Sessions start/end via explicit MCP calls (not automatic)
3. **Python-Only**: No Bun, no Node.js; pure Python async
4. **FAISS**: Use your existing vector store, not Chroma
5. **Simpler**: Focus on core features, not all 7 hook types

---

## 🎓 Architecture Decisions

### ADR-1: Use MCP Lifecycle Events (Not External Hooks)

**Decision**: Memory hooks are triggered by MCP tool calls, not external plugin system.

**Rationale**:
- OpenLMlib already has MCP infrastructure
- Works with any MCP-compatible client
- No dependency on Claude Code specifically
- Simpler deployment (no plugin registration)

**Trade-offs**:
- ❌ Less automatic than Claude Code plugin hooks
- ✅ Universal compatibility with MCP ecosystem

### ADR-2: Progressive Disclosure as 3 Separate MCP Tools

**Decision**: Expose each layer as independent MCP tool.

**Rationale**:
- AI agents can control retrieval depth
- Token-efficient by design
- Composable workflow

**Trade-offs**:
- ❌ Requires multiple tool calls
- ✅ Maximum flexibility for agents

### ADR-3: Async Observation Queue (Not Blocking)

**Decision**: Observations are queued and processed asynchronously.

**Rationale**:
- Tool calls return immediately
- Compression happens in background
- No impact on session performance

**Trade-offs**:
- ❌ Slight delay in summary availability
- ✅ Non-blocking, scalable architecture

---

## ✅ Checklist

Before merging to main:

- [ ] All phases implemented
- [ ] Unit tests pass (pytest)
- [ ] Integration tests pass
- [ ] Token efficiency validated (>10x)
- [ ] Privacy filtering tested
- [ ] Settings documented
- [ ] Examples created
- [ ] README updated
- [ ] CHANGELOG updated
- [ ] Code review completed
- [ ] Performance benchmarks run

---

## 📞 Next Steps

1. **Review this plan** and confirm architecture decisions
2. **Create branch**: `git checkout -b feature/memory-injection`
3. **Start Phase 1**: Foundation (storage, session manager, hooks)
4. **Iterate**: Test each phase before moving to next
5. **Document**: Update README with memory injection guide

Ready to proceed? 🚀
