# Multi-Agent Collaboration Feature: Research-Backed Implementation Plan (v2)

## Executive Summary

This plan outlines **CollabSessions** — a local-first, hybrid SQLite+file multi-agent collaboration system for OpenLMLib. After extensive research across academic papers (ICLR 2026, arXiv), production case studies (Oracle, Google ADK, Anthropic, Zylos), and coordination pattern analysis (Tacnode, Fazm, ElectricSQL), this revised plan adopts a **hybrid architecture**: SQLite for the session registry, message bus, and state tracking; files for artifacts and research outputs. This converges with what the industry's best systems are doing in 2026.

**Key research sources informing this plan:**
- Oracle: "Comparing File Systems and Databases for AI Agent Memory" (Feb 2026) — benchmarked FSAgent vs MemAgent
- Zylos Research: "AI Agent Memory Architectures for Multi-Agent Systems" (Mar 2026) — framework comparison
- Google ADK: "Architecting efficient context-aware multi-agent framework" (Dec 2025) — context engineering
- Anthropic: "How We Built Our Multi-Agent Research System" — artifact-based memory
- Tacnode: "8 Coordination Patterns That Actually Work" (Jan 2026) — production patterns
- arXiv 2601.13671: "The Orchestration of Multi-Agent Systems" (Jan 2026) — academic framework

---

## 1. Core Architecture — REVISED: Hybrid Approach

### 1.1 Design Philosophy (Updated)

**Research finding:** Oracle's benchmark showed MemAgent (SQLite) beat FSAgent (files) on both latency AND quality. Zylos Research: "Shared state demands a database." But files win as an *interface* — LLMs already know how to use them.

**Decision: Hybrid SQLite + Files**
- **SQLite** (`collab_sessions.db`): Session registry, message bus (append-only table), agent registry, state tracking. Gives us ACID transactions, FTS5 search, row-level locking, zero platform-specific code.
- **Files** (`sessions/{id}/artifacts/`): Research outputs, agent working notes, large artifacts. LLM-native interface, human-readable, versionable.
- **JSONL shadow log** (`sessions/{id}/messages.jsonl`): Human-readable copy of the messages table for debugging. Written alongside SQLite inserts.

### 1.2 Revised Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        CollabSessions Layer                      │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │          SQLite: collab_sessions.db                       │   │
│  │                                                          │   │
│  │  Tables:                                                 │   │
│  │  ├── sessions          (registry: id, status, metadata)  │   │
│  │  ├── messages          (append-only message bus)         │   │
│  │  ├── agents            (registered agents per session)   │   │
│  │  ├── tasks             (task assignments + tracking)     │   │
│  │  ├── artifacts         (artifact metadata index)         │   │
│  │  ├── session_state     (current state, versioned)        │   │
│  │  └── messages_fts      (FTS5 virtual table)              │   │
│  └──────────────────────┬───────────────────────────────────┘   │
│                         │                                       │
│  ┌──────────────────────┴───────────────────────────────────┐   │
│  │              File System: sessions/{session_id}/          │   │
│  │  ├── messages.jsonl        (human-readable shadow log)   │   │
│  │  ├── artifacts/            (research outputs)            │   │
│  │  │   ├── {agent_id}/       (per-agent workspace)         │   │
│  │  │   └── shared/           (shared outputs)              │   │
│  │  ├── summaries/            (auto-generated summaries)    │   │
│  │  └── offsets/              (agent read positions)        │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              MCP Tools (Expanded — 15 tools)              │   │
│  │  Session: create, join, list, leave, terminate           │   │
│  │  Messages: send, read, tail, grep, read_range            │   │
│  │  State: get_state, update_state (orchestrator only)      │   │
│  │  Artifacts: add, list, get, grep_artifacts               │   │
│  │  Context: get_session_context (compiled view)            │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 1.3 SQLite Schema

```sql
-- Session registry
CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'paused', 'completed', 'terminated')),
    orchestrator TEXT NOT NULL,
    rules_json TEXT,
    updated_at TEXT NOT NULL
);

-- Append-only message bus (the core coordination primitive)
CREATE TABLE messages (
    msg_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    seq INTEGER NOT NULL,  -- Monotonic sequence number per session
    from_agent TEXT NOT NULL,
    from_model TEXT,
    msg_type TEXT NOT NULL CHECK (msg_type IN (
        'task', 'result', 'question', 'answer', 'ack',
        'update', 'artifact', 'system', 'complete', 'summary'
    )),
    to_agent TEXT,  -- NULL = broadcast
    content TEXT NOT NULL,
    metadata_json TEXT,
    created_at TEXT NOT NULL
);

-- FTS5 for keyword search across messages
CREATE VIRTUAL TABLE messages_fts USING fts5(
    content, metadata_json,
    content='messages', content_rowid='rowid'
);

-- Agent registry
CREATE TABLE agents (
    agent_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    model TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('orchestrator', 'worker', 'observer')),
    capabilities_json TEXT,
    joined_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'inactive', 'left')),
    last_seen TEXT
);

-- Task tracking
CREATE TABLE tasks (
    task_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    step_num INTEGER NOT NULL,
    description TEXT NOT NULL,
    assigned_to TEXT,  -- agent_id or 'any'
    status TEXT NOT NULL CHECK (status IN ('pending', 'in_progress', 'completed', 'cancelled')),
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT
);

-- Artifact metadata index
CREATE TABLE artifacts (
    artifact_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    created_by TEXT NOT NULL,
    title TEXT NOT NULL,
    artifact_type TEXT,
    file_path TEXT NOT NULL,
    tags_json TEXT,
    word_count INTEGER,
    created_at TEXT NOT NULL,
    referenced_in_messages_json TEXT
);

-- Session state (versioned, single-writer)
CREATE TABLE session_state (
    session_id TEXT PRIMARY KEY REFERENCES sessions(session_id),
    state_json TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL,
    updated_by TEXT
);
```

---

## 2. Session Lifecycle

### 2.1 Session Creation

```
User → Orchestrator LLM (e.g., Opus 4.6)
  → LLM calls create_session via MCP
    → INSERT into sessions table (SQLite transaction)
    → INSERT initial system message into messages table
    → INSERT session_state row
    → Write JSONL shadow log
    → Create artifact directories
    → Return session_id to LLM
    → LLM writes initial plan via update_session_state
```

### 2.2 Agent Joining

```
User → Helper LLM (e.g., Codex/Gemini) in different IDE
  → LLM calls list_sessions
  → User selects session
  → LLM calls join_session
    → INSERT into agents table
    → System message logged: "agent_X joined"
    → LLM calls session_context
      → Returns: session summary + last 20 messages + current state + artifact list
    → LLM can now participate
```

### 2.3 Message Exchange

All inter-agent communication goes through the **append-only messages table** in SQLite.

**Message types:**
- `task` — Orchestrator assigns work
- `result` — Agent returns findings
- `question` / `answer` — Clarification exchanges
- `ack` — Acknowledgment
- `update` — Progress update
- `artifact` — Reference to a saved artifact
- `system` — Join, leave, state change notifications
- `complete` — Task completion
- `summary` — Auto-generated session summary (compaction)

### 2.4 Session Termination

```
Orchestrator evaluates results
  → Calls terminate_session
    → System message: "Session completed"
    → Final summary generated and stored
    → Session status → "completed"
    → Optional: export artifacts to OpenLMLib main library
```

---

## 3. Context Window Management — NEW CRITICAL SECTION

**Research finding:** Anthropic found token usage explains 80% of performance variance. Google ADK: "Context is a compiled view over a richer stateful system." This is the single most important design area.

### 3.1 The Problem

If agents read the full message log every turn, they blow their context window. A 50-message session with artifacts can easily exceed 100K tokens.

### 3.2 Solution: Progressive Disclosure + Compiled Context

**Three-tier context architecture** (inspired by Google ADK):

```
┌─────────────────────────────────────────────────┐
│  Working Context (per LLM call)                 │
│  - System instructions + agent identity          │
│  - Session summary (if exists)                   │
│  - Last N messages (filtered by relevance)       │
│  - Artifact references (not content)             │
│  - Current task assignment                       │
└─────────────────────────────────────────────────┘
         ▲ compiled from
┌─────────────────────────────────────────────────┐
│  Session Storage (durable state)                 │
│  - Full message history (SQLite)                 │
│  - All artifacts (files)                         │
│  - Session state (versioned)                     │
│  - Summaries (auto-generated)                    │
└─────────────────────────────────────────────────┘
```

### 3.3 Progressive Disclosure Tools

Agents get these tools to explore session context efficiently:

| Tool | Purpose | When to Use |
|------|---------|-------------|
| `session_context` | Get compiled view: summary + recent messages + state + artifact list | First thing after joining, or every turn |
| `read_messages` | Read new messages since last check (offset-based) | Every turn to catch up |
| `tail_messages` | Read last N messages | Quick status check |
| `grep_messages` | Search messages by keyword | Find specific discussions |
| `read_message_range` | Read messages in a sequence range | Zoom into a specific conversation |
| `get_artifact` | Get full artifact content | When you need to read a specific artifact |
| `grep_artifacts` | Search across all artifact content | Find relevant research outputs |

**Agent reading policy** (encoded in system prompt):
1. Start with `session_context` — get the compiled view
2. Use `tail_messages` for a quick status check
3. Use `grep_messages` to find specific topics
4. Use `read_message_range` to zoom into relevant sections
5. Use `get_artifact` only when you need full content
6. NEVER read the entire message history in one call

### 3.4 Automatic Session Summarization (Compaction)

**Inspired by Google ADK's context compaction:**

- After every N messages (configurable, default 30), the system generates a summary
- Summary is stored as a `summary` type message in the messages table
- Summary is also saved as a file in `summaries/` directory
- New agents joining get the latest summary + recent messages instead of full history
- Summaries include: key decisions, completed tasks, artifact references, open questions

```python
def auto_compact_session(session_id, messages_since_last_summary=30):
    """Generate a summary of recent session activity"""
    recent_msgs = get_messages_since_last_summary(session_id, messages_since_last_summary)
    summary = llm_generate_summary(recent_msgs)  # Use any available LLM
    store_summary(session_id, summary)
    insert_message(session_id, {
        "msg_type": "summary",
        "content": summary,
        "from_agent": "system"
    })
```

### 3.5 Artifact Handle Pattern

**Inspired by Google ADK's ArtifactService:**

- Artifacts are stored as files, NOT in the message content
- Messages contain only lightweight references: `{"artifact_id": "art_001", "title": "...", "summary": "..."}`
- Agents load full artifact content on-demand via `get_artifact`
- This keeps message content small and context windows lean

---

## 4. Hierarchical Memory Architecture — NEW

**Research finding:** Zylos Research shows industry converging on 3-layer model: global, group/role, private. CrewAI, MemOS, and others independently arrived at this pattern.

### 4.1 Three-Layer Memory

```
┌──────────────────────────────────────────────┐
│  GLOBAL (session-wide)                       │
│  - Session plan and rules                    │
│  - All messages (broadcast type)             │
│  - Shared artifacts                          │
│  - Session state                             │
└──────────────────┬───────────────────────────┘
                   │
┌──────────────────┴───────────────────────────┐
│  TASK-SCOPED (per task/step)                 │
│  - Messages related to specific tasks        │
│  - Task-specific artifacts                   │
│  - Task progress and notes                   │
└──────────────────┬───────────────────────────┘
                   │
┌──────────────────┴───────────────────────────┐
│  PRIVATE (per-agent workspace)               │
│  - Agent's working notes                     │
│  - Draft artifacts (not yet shared)          │
│  - Agent's read offset tracking              │
└──────────────────────────────────────────────┘
```

### 4.2 Implementation

- **Global**: SQLite messages table (all agents can read)
- **Task-scoped**: Messages with `metadata.task_id` field; filtered queries
- **Private**: File-based workspace at `sessions/{id}/artifacts/{agent_id}/`

Each agent's `session_context` call returns:
1. Global context (summary + recent broadcast messages + state)
2. Task-scoped context (messages for their assigned tasks)
3. Private context pointer (path to their workspace)

---

## 5. Conflict Resolution — REVISED

**Research finding:** Tacnode's #4 pattern: "Single-writer principle for critical state." LangGraph uses reducer functions. Last-write-wins silently discards information.

### 5.1 Single-Writer for Session State

Only the **orchestrator** can update `session_state`. Workers can only:
- Append messages (append-only, no conflicts)
- Write to their private workspace (isolated)
- Create artifacts (unique IDs, no conflicts)

```python
def update_session_state(session_id, new_state, requesting_agent):
    session = get_session(session_id)
    if requesting_agent != session.orchestrator:
        raise PermissionError("Only orchestrator can update session state")
    
    # Atomic update with version check
    conn.execute("""
        UPDATE session_state
        SET state_json = ?, version = version + 1, updated_at = ?, updated_by = ?
        WHERE session_id = ? AND version = ?
    """, (json.dumps(new_state), now(), requesting_agent, session_id, current_version))
    
    if conn.changes == 0:
        raise ConflictError("State was modified by another process")
```

### 5.2 Natural Reducers for Append-Only Data

- **Messages**: Append-only — no conflicts possible
- **Agents**: INSERT-only for joining; status updates only by the agent itself
- **Tasks**: Status transitions are atomic (pending → in_progress → completed)
- **Artifacts**: Unique ID generation prevents conflicts

### 5.3 Event Sourcing via Message Log

The messages table IS the event log. Current state can be derived by replaying:
- Session created → agents joined → tasks assigned → messages exchanged → tasks completed

This gives us:
- Complete audit trail
- Ability to reconstruct any point in time
- Debuggability (read the log to understand what happened)

---

## 6. Notification Mechanism — REVISED

**Research finding:** Fazm: "Agents do not need real-time messaging. They need a shared understanding of state." LLM agents are request-response, not event-driven.

**Decision: Pure polling with offset tracking.** No `watchdog` dependency.

```python
class MessageReader:
    def __init__(self, session_id, agent_id):
        self.session_id = session_id
        self.agent_id = agent_id
        self.last_seq = self._load_offset()  # Last seen sequence number

    def read_new_messages(self, limit=50, msg_types=None, from_agent=None):
        """Read messages since last check, with optional filters"""
        query = """
            SELECT * FROM messages
            WHERE session_id = ? AND seq > ?
        """
        params = [self.session_id, self.last_seq]

        if msg_types:
            placeholders = ','.join('?' for _ in msg_types)
            query += f" AND msg_type IN ({placeholders})"
            params.extend(msg_types)

        if from_agent:
            query += " AND from_agent = ?"
            params.append(from_agent)

        query += " ORDER BY seq ASC LIMIT ?"
        params.append(limit)

        messages = execute_query(query, params)
        if messages:
            self.last_seq = messages[-1]['seq']
            self._save_offset()
        return messages
```

---

## 7. Agent Context Translation — NEW

**Research finding:** Google ADK: When transferring control between agents, messages must be "reframed" so the new agent doesn't confuse prior agents' outputs with its own.

### 7.1 Context Compilation for Each Agent

When an agent reads messages, they are formatted with clear attribution:

```
[Session: Research on Quantum Computing]
[Your role: worker | Agent ID: agent_codex_001]

=== SESSION SUMMARY (generated at 10:15) ===
Research is in phase 2. Literature review complete (12 papers found).
Current task: Technical analysis of Google's Willow chip.

=== RECENT MESSAGES (last 10) ===

[10:01] [opus-4.6 → all] [task] Please research recent advances in error correction.
[10:03] [codex → opus-4.6] [result] Found 12 relevant papers. Key findings: ...
  ↳ Artifact: art_001 (Quantum Error Correction Review)
[10:03] [opus-4.6 → codex] [ack] Good work. Now analyze the technical approach in art_001.
[10:05] [system] [update] Task 2 assigned to agent_codex_001

=== YOUR CURRENT TASK ===
Step 2: Technical analysis of Google's Willow chip
Status: in_progress
Assigned to: you (agent_codex_001)

=== AVAILABLE ARTIFACTS ===
- art_001: Quantum Error Correction Review (by codex)
- art_002: Google Willow Chip Analysis (by codex)
```

Note how messages are attributed (`[opus-4.6 → all]`), not presented as the current agent's own history.

---

## 8. MCP Tools — Expanded

### 8.1 Complete Tool List

| Category | Tool | Description |
|----------|------|-------------|
| **Session** | `create_session` | Create session with title, description, plan |
| | `join_session` | Register as participant |
| | `list_sessions` | List sessions (filter by status) |
| | `leave_session` | Leave gracefully |
| | `terminate_session` | End and archive |
| **Messages** | `send_message` | Append message to session |
| | `read_messages` | Read new messages (offset-based, filterable) |
| | `tail_messages` | Read last N messages |
| | `grep_messages` | Search messages by keyword |
| | `read_message_range` | Read messages by sequence range |
| **State** | `get_session_state` | Get current state |
| | `update_session_state` | Update state (orchestrator only) |
| **Artifacts** | `save_artifact` | Save artifact (content → file, metadata → DB) |
| | `list_artifacts` | List artifacts (filter by agent, type, tags) |
| | `get_artifact` | Get full artifact content |
| | `grep_artifacts` | Search across artifact content |
| **Context** | `session_context` | **Primary tool**: compiled view for the agent |

### 8.2 Tool Usage Pattern

**Orchestrator workflow:**
```
1. create_session → get session_id
2. update_session_state → set plan and tasks
3. send_message(type="task", to="agent_X") → assign work
4. read_messages → check agent responses
5. Repeat 3-4 until plan complete
6. terminate_session → wrap up
```

**Worker workflow:**
```
1. list_sessions → find session to join
2. join_session → register
3. session_context → understand current state
4. read_messages → catch up on activity
5. Do work → save_artifact → save output
6. send_message(type="result") → report back
7. Repeat 3-6 until task complete
8. send_message(type="complete") → mark done
```

---

## 9. Integration with Existing OpenLMLib

### 9.1 Storage Layout

```
data/
├── findings.db              # Existing: main library
├── embeddings.faiss         # Existing: vector index
├── findings/                # Existing: finding JSON files
├── collab_sessions.db       # NEW: session data (SQLite)
└── sessions/                # NEW: file artifacts
    ├── sess_abc123/
    │   ├── artifacts/
    │   │   ├── agent_codex_001/
    │   │   └── shared/
    │   └── summaries/
    └── sess_def456/
```

### 9.2 Bridge: Export to Library

When a session completes, orchestrator can export artifacts as findings:

```python
def export_session_to_library(session_id, settings_path):
    """Export session artifacts as OpenLMLib findings"""
    artifacts = get_session_artifacts(session_id)
    messages = get_all_messages(session_id)
    summary = get_latest_summary(session_id)

    for artifact in artifacts:
        add_finding(
            settings_path=settings_path,
            project=artifact.tags[0] if artifact.tags else "collab_research",
            claim=artifact.title,
            confidence=0.8,
            evidence=artifact.content,
            reasoning=f"Generated in session {session_id}. Summary: {summary}",
            source=f"session:{session_id}",
            tags=artifact.tags + ["collab_session"],
            proposed_by=artifact.created_by
        )
```

---

## 10. Implementation Phases — REVISED

### Phase 1: Core Infrastructure (Week 1-2)

**New files:**
```
openlmlib/
├── collab/
│   ├── __init__.py
│   ├── db.py               # SQLite schema, connection, CRUD
│   ├── message_bus.py      # Append-only message operations + JSONL shadow
│   ├── session.py          # Session lifecycle (create, join, leave, terminate)
│   ├── context_compiler.py # Context compilation (progressive disclosure)
│   ├── artifact_store.py   # File-based artifact management
│   ├── state_manager.py    # Versioned state (orchestrator-only writes)
│   └── collab_mcp.py       # MCP tools (all 15)
```

**Deliverables:**
- SQLite schema and connection management (reuse patterns from existing `db.py`)
- Session CRUD with SQLite transactions
- Append-only message bus with FTS5
- JSONL shadow log for debugging
- Basic MCP tools: create, join, list, send, read
- Context compiler: `session_context`
- Unit tests

### Phase 2: Coordination Features (Week 3-4)

**Deliverables:**
- Progressive disclosure tools: tail, grep, read_range
- Task assignment and tracking
- Artifact storage with handle pattern
- Session rules engine
- Hierarchical memory (global/task/private scopes)
- Agent context translation (attribution formatting)
- Offset-based message reading
- Idle detection

### Phase 3: Advanced Features (Week 5-6)

**Deliverables:**
- Automatic session summarization (compaction)
- Export to OpenLMLib main library
- Session templates (predefined plans)
- Multi-session support
- Session search and discovery
- CLI commands

### Phase 4: Production Polish (Week 7-8)

**Deliverables:**
- System prompts for orchestrator and worker agents
- Comprehensive error handling and recovery
- Performance benchmarks
- Integration tests with simulated agents
- Documentation and examples
- Security hardening

---

## 11. CLI Commands

```bash
# Session management
openlmlib collab create --title "Research Topic" --task "Description" [--plan plan.json]
openlmlib collab list [--status active|completed|terminated]
openlmlib collab join <session_id> --model "gpt-4" --capabilities "research,analysis"
openlmlib collab state <session_id>
openlmlib collab terminate <session_id> --summary "..." [--export]
openlmlib collab leave <session_id> [--reason "done"]

# Message inspection
openlmlib collab messages <session_id> [--limit 50] [--type task] [--from agent_id]
openlmlib collab tail <session_id> [--lines 20]
openlmlib collab grep <session_id> "search term" [--type result]
openlmlib collab timeline <session_id>    # Chronological view

# Artifact management
openlmlib collab artifacts <session_id> [--agent agent_id] [--type research_summary]
openlmlib collab export <session_id> --output-dir ./research/

# Session administration
openlmlib collab inspect <session_id>     # Full overview
openlmlib collab compact <session_id>     # Force summarization
openlmlib collab cleanup [--older-than 30d]  # Archive old sessions
```

---

## 12. System Prompts

### 12.1 Orchestrator Agent

```
You are the ORCHESTRATOR of a collaboration session.

SESSION: {session_id}
TITLE: {title}
YOUR ROLE: orchestrator (you control session state and task assignments)

YOUR RESPONSIBILITIES:
1. Define a clear plan with specific, numbered tasks
2. Assign tasks to agents based on their capabilities
3. Monitor progress by reading session messages
4. Synthesize results from multiple agents
5. Terminate the session when research is complete

CONTEXT MANAGEMENT:
- Use session_context to get a compiled view each turn
- Use tail_messages for quick status checks
- Use grep_messages to find specific discussions
- NEVER read the entire message history in one call

BEST PRACTICES:
- Break complex tasks into specific, assignable subtasks
- Address messages to specific agents (not "any") when possible
- Request artifacts for significant findings (not inline in messages)
- Provide clear acceptance criteria for each task
- Summarize progress periodically
- Export important findings to the main library when done

AVAILABLE TOOLS:
- session_context: Get compiled view of session
- send_message: Communicate with agents
- read_messages: See what agents have done
- update_session_state: Update task assignments and plan
- save_artifact: Save important findings
- tail_messages: Quick status check (last N messages)
- grep_messages: Search for specific topics
- terminate_session: End the session
```

### 12.2 Worker Agent

```
You are a WORKER agent in a collaboration session.

SESSION: {session_id}
TITLE: {title}
YOUR ROLE: worker (you complete assigned tasks)
YOUR AGENT ID: {agent_id}

YOUR RESPONSIBILITIES:
1. Read session context before responding
2. Complete assigned tasks thoroughly
3. Save significant work as artifacts
4. Report progress and results clearly

CONTEXT MANAGEMENT:
- ALWAYS start with session_context
- Use tail_messages for a quick status check
- Use grep_messages to find specific discussions
- Use get_artifact to read specific artifacts
- NEVER read the entire message history in one call

BEST PRACTICES:
- Check if your assigned task is still valid before starting
- Save detailed work as artifacts (not inline in messages)
- Reference artifacts by ID in your messages
- Ask for clarification if a task is unclear
- Send a "complete" message when your task is done
- Use your private workspace for drafts before sharing

AVAILABLE TOOLS:
- session_context: Get compiled view of session
- read_messages: Catch up on session activity
- send_message: Report results or ask questions
- save_artifact: Save your research outputs
- get_artifact: Read a specific artifact's full content
- tail_messages: Quick status check (last N messages)
- grep_messages: Search for specific topics
- get_session_state: Check current session status
- leave_session: Leave when your work is done
```

---

## 13. Testing Strategy

### 13.1 Unit Tests
- SQLite schema and CRUD operations
- Append-only message bus (concurrent writes via SQLite transactions)
- Context compiler (progressive disclosure logic)
- Artifact store (file creation, metadata, retrieval)
- State manager (versioned updates, single-writer enforcement)
- Offset-based message reading
- Session summarization

### 13.2 Integration Tests
- Simulate orchestrator + 2 worker agents
- Test concurrent message writes from multiple processes
- Test full session lifecycle (create → join → work → compact → terminate)
- Test export to main library
- Test idle detection and agent timeout
- Test context compilation with attribution

### 13.3 Real-World Tests
- Run with actual MCP-compatible LLMs in different IDEs
- Test with 3+ agents simultaneously
- Measure message throughput and context compilation latency
- Test session summarization with 100+ message sessions

---

## 14. Security Considerations

1. **Session isolation** — Agents can only access sessions they've joined (enforced at DB query level)
2. **Local-only** — All data stays on the machine
3. **Single-writer state** — Only orchestrator can update session state
4. **Agent identity** — Agent IDs are generated, not user-provided
5. **No code execution** — System only manages communication
6. **Prompt injection mitigation** — Reuse existing `sanitization.py`
7. **Provenance tracking** — Every message and artifact is attributed to its creator
8. **Namespace isolation** — Each agent has a private workspace

---

## 15. Performance Targets

| Metric | Target | Notes |
|--------|--------|-------|
| Message append | < 3ms | SQLite INSERT (no file locking needed) |
| Message read (50) | < 5ms | SQLite query with offset |
| Context compilation | < 50ms | Summary + recent messages + state |
| Session creation | < 20ms | SQLite transaction + directory creation |
| Concurrent writers | Up to 10 | SQLite handles serialization |
| Max messages/session | 100,000+ | With auto-compaction |
| Max artifacts/session | 1,000+ | Filesystem limited |
| FTS5 search | < 10ms | Keyword search across all messages |

---

## 16. Why This Approach Wins

1. **SQLite gives us ACID for free** — No platform-specific file locking, no silent corruption
2. **Files stay as the LLM interface** — Artifacts are human-readable, versionable, inspectable
3. **Context engineering is first-class** — Progressive disclosure prevents context window blowup
4. **Hierarchical memory** — Global/task/private scopes prevent noise and contamination
5. **Event-sourced by design** — The message log is the complete audit trail
6. **Leverages existing patterns** — Reuses OpenLMLib's SQLite + FTS5 expertise
7. **Zero new dependencies** — Only uses stdlib + sqlite3 (already in OpenLMLib)
8. **Local-first** — All data stays on the machine

---

## 17. Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| SQLite database corruption | High | Regular backups (reuse existing backup pattern); WAL mode for crash safety |
| Context window overflow | High | Progressive disclosure tools + auto-compaction + artifact handle pattern |
| Agent reads full history | Medium | System prompt enforcement + tool design (no "read all" tool) |
| Orphaned sessions | Low | Idle detection + auto-archive after timeout |
| Orchestrator crashes | Medium | Session state is persistent; new orchestrator can resume from state |
| Message log grows too large | Low | Auto-compaction + FTS5 for efficient search without reading all messages |

---

## 18. Research-Backed Design Decisions Summary

| Decision | Original Plan | Revised Plan | Research Source |
|----------|--------------|--------------|-----------------|
| Storage | Pure files | Hybrid SQLite + files | Oracle benchmark, Zylos Research |
| Concurrency | File locking | SQLite transactions | Zylos: "Shared state demands a database" |
| Context | Full message dump | Progressive disclosure + compiled view | Google ADK, Anthropic |
| Memory | Flat shared | Hierarchical (global/task/private) | CrewAI, MemOS, Zylos |
| Conflict resolution | Optimistic retries | Single-writer + append-only | Tacnode #4, LangGraph reducers |
| Notification | File watching | Pure polling | Fazm: agents don't need real-time |
| Agent handoff | Raw messages | Context translation with attribution | Google ADK |
| Large outputs | Inline in messages | Artifact handle pattern | Google ADK ArtifactService |
| State management | Multi-writer JSON | Single-writer versioned SQLite | Tacnode single-writer principle |
| Audit trail | JSONL only | SQLite messages table + JSONL shadow | Event sourcing pattern |

---

## 19. Future Extensions (Post-MVP)

1. **Cross-machine sessions** — Sync session directories via git or cloud storage
2. **WebSocket bridge** — Optional real-time layer for co-located agents
3. **Session templates** — Predefined plans for common research patterns
4. **Agent capability matching** — Auto-suggest which agents should join a session
5. **Session analytics** — Metrics on agent productivity, session duration, output quality
6. **Multi-orchestrator** — Hierarchical sessions with sub-session orchestration
7. **Vector search on messages** — Embed messages for semantic search beyond FTS5
8. **MCP as memory interop** — Expose session state as an MCP resource for any agent
