# MCP Tools Reference

Complete reference for all 52 MCP tools available in OpenLMlib.

## Table of Contents

- [Core Library Tools (11)](#core-library-tools)
- [Memory System Tools (10)](#memory-system-tools)
  - [Session Lifecycle (3)](#session-lifecycle)
  - [Progressive Retrieval (4)](#progressive-retrieval)
  - [Context Injection (3)](#context-injection)
- [Collaboration Session Tools (31)](#collaboration-session-tools)
  - [Session Management (7)](#session-management)
  - [Message Operations (7)](#message-operations)
  - [Artifact Management (4)](#artifact-management)
  - [Session Discovery & Analytics (6)](#session-discovery--analytics)
  - [Templates (3)](#templates)
  - [Model Discovery (3)](#model-discovery)
  - [Utilities (1)](#utilities)

---

## Core Library Tools

Knowledge base management and retrieval tools.

### `openlmlib_init`
Initialize the library storage and database.

**Parameters:** None

**Returns:** Initialization status and paths

---

### `openlmlib_add_finding`
Add a new finding to the knowledge base.

**Parameters:**
- `project` (string): Project name
- `claim` (string): The core claim/finding
- `confidence` (float): Confidence score 0.0-1.0
- `evidence` (array of strings, optional): Supporting evidence
- `reasoning` (string, optional): Reasoning behind the finding
- `caveats` (array of strings, optional): Limitations or caveats
- `tags` (array of strings, optional): Classification tags
- `confirm` (boolean, **required**): Must be `true` to execute

**Safety:** Requires explicit `confirm=true` parameter

---

### `openlmlib_list_findings`
List findings with optional pagination.

**Parameters:**
- `limit` (int, default 50): Max results to return
- `offset` (int, default 0): Offset for pagination

**Returns:** List of findings with id, project, claim, confidence, status

---

### `openlmlib_get_finding`
Get full details of a specific finding.

**Parameters:**
- `finding_id` (string): The finding ID to retrieve

**Returns:** Complete finding with text, evidence, reasoning, tags, audit info

---

### `openlmlib_search_fts`
Full-text search across findings.

**Parameters:**
- `query` (string): Search query
- `limit` (int, default 10): Max results

**Returns:** Matching findings ranked by relevance

---

### `openlmlib_retrieve`
Advanced semantic retrieval with multi-phase ranking.

**Parameters:**
- `query` (string): Search query
- `project` (string, optional): Filter by project
- `tags` (array of strings, optional): Filter by tags
- `confidence_min` (float, optional): Minimum confidence filter
- `semantic_k` (int, optional): Semantic search results count
- `lexical_k` (int, optional): Lexical search results count
- `final_k` (int, optional): Final results after reranking
- `deduplicate` (boolean, default true): Remove duplicates
- `reasoning_trace` (boolean, default true): Include why each finding matched

**Returns:** Ranked findings with scores and optional reasoning traces

---

### `openlmlib_retrieve_context`
Retrieve findings formatted as prompt context.

**Parameters:**
- `query` (string): Search query
- `project` (string, optional): Filter by project
- `max_tokens` (int, optional): Context window limit
- `safe_context` (boolean, default true): Sanitize retrieved content

**Returns:** Formatted context string for LLM prompts

---

### `openlmlib_delete_finding`
Delete a finding from the knowledge base.

**Parameters:**
- `finding_id` (string): Finding to delete
- `confirm` (boolean, **required**): Must be `true` to execute

**Safety:** Requires explicit `confirm=true` parameter

---

### `openlmlib_health`
Check library health and status.

**Parameters:** None

**Returns:** Database status, vector index status, finding counts, backend info

---

### `openlmlib_evaluate_dataset`
Evaluate retrieval performance on a dataset.

**Parameters:**
- `dataset_path` (string, default "config/eval_queries.json"): Path to evaluation dataset
- `final_k` (int, default 10): Results count for evaluation

**Returns:** Evaluation metrics (hit rate, MRR, etc.)

---

### `openlmlib_help`
Get help documentation for tools.

**Parameters:**
- `tool_name` (string, optional): Specific tool to get help for (or all tools if omitted)

**Returns:** Tool descriptions and usage examples

---

## Memory System Tools

Session persistence, progressive retrieval, and retroactive ingestion tools. These tools enable AI assistants to maintain context across work sessions without manual logging.

### Session Lifecycle

#### `memory_session_start`
Start a new session and inject relevant context from previous sessions.

**Parameters:**
- `session_id` (string): Unique session identifier
- `user_id` (string, optional): User/agent identifier
- `query` (string, optional): Initial query to filter relevant memories
- `limit` (int, default 50): Max observations to inject

**Returns:** Session ID, context block, observation count, injection status

**Example:**
```python
memory_session_start(
    session_id="sess_20260414_001",
    query="memory retrieval optimization",
    limit=30
)
```

---

#### `memory_session_end`
End a session and trigger automatic summarization.

**Parameters:**
- `session_id` (string): Session identifier to end

**Returns:** Session ID, status, summary generation status, observation count

**Example:**
```python
memory_session_end(session_id="sess_20260414_001")
```

---

#### `memory_log_observation`
Log an observation from tool execution for memory building.

**Parameters:**
- `session_id` (string): Active session identifier
- `tool_name` (string): Tool that was executed (e.g., "Read", "Edit")
- `tool_input` (string): Tool input
- `tool_output` (string): Tool output

**Returns:** Observation ID, logging status

**Example:**
```python
memory_log_observation(
    session_id="sess_20260414_001",
    tool_name="Edit",
    tool_input="Modified memory_retriever.py",
    tool_output="Added auto_inject_context method"
)
```

---

### Progressive Retrieval

Three-layer disclosure system for token-efficient memory retrieval.

#### `memory_search` (Layer 1)
Search memory index with compact metadata (~75 tokens/result).

**Parameters:**
- `query` (string): Search query
- `limit` (int, default 50): Max results to return
- `filters` (dict, optional): Filters (tool_name, obs_type, session_id)

**Returns:** Search results with id, title, type, timestamp, confidence, estimated tokens

**Token Efficiency:** ~75 tokens per result (vs ~750 for full details)

**Example:**
```python
memory_search(query="retrieval optimization", limit=20)
```

---

#### `memory_timeline` (Layer 2)
Get chronological context for memory IDs (~200 tokens/result).

**Parameters:**
- `ids` (array of strings): Observation IDs from memory_search
- `window` (string, default "5m"): Time window for context

**Returns:** Timeline entries with narrative flow and related concepts

**Token Efficiency:** ~200 tokens per entry

**Example:**
```python
# After memory_search, get timeline for top 5 results
memory_timeline(ids=[...], window="10m")
```

---

#### `memory_get_observations` (Layer 3)
Get full details for specific memory IDs (~750 tokens/result).

**Parameters:**
- `ids` (array of strings): Observation IDs from memory_search or memory_timeline

**Returns:** Full observation data with tool inputs, outputs, facts, concepts

**Token Efficiency:** ~750 tokens per observation (use only for explicitly selected items)

**Example:**
```python
# After filtering with layers 1-2, get full details for top 2
memory_get_observations(ids=[...])
```

---

### Context Injection & Synthesis

#### `memory_inject_context`
Auto-inject relevant context at session start with progressive compression.

**Parameters:**
- `session_id` (string): Current session ID
- `query` (string, optional): Query to filter relevant memories
- `limit` (int, default 50): Max observations to inject

**Returns:** Context block, observation count, estimated tokens

**Example:**
```python
memory_inject_context(
    session_id="sess_20260414_001",
    query="caveman compression",
    limit=20
)
```

---

#### `memory_quick_recap`
Get synthesized recap of recent sessions (~150-250 tokens). **Call FIRST** when starting work.

Returns structured knowledge: files touched, decisions made, next steps, conventions discovered — not raw tool outputs.

**Parameters:**
- `session_id` (string, optional): Specific session to recap (default: recent sessions)
- `limit` (int, default 3): Max recent sessions to recap

**Returns:** Quick recap text, session summaries, next steps, decisions, files touched

**Example:**
```python
# Start of session - get overview of what happened recently
memory_quick_recap(limit=3)
```

---

#### `memory_detailed_context`
Get detailed context about a specific topic from past sessions (~500-800 tokens). **Call AFTER** memory_quick_recap.

Returns detailed files, decisions, architecture notes, and conventions related to the topic.

**Parameters:**
- `topic` (string): Topic to get detailed context about (e.g., 'storage', 'privacy', 'MCP')
- `session_id` (string, optional): Specific session to search (default: all sessions)

**Returns:** Detailed context text, related knowledge, sessions searched, observations found

**Example:**
```python
# Deep dive on a topic from the recap
memory_detailed_context(topic="memory retrieval", session_id="sess_20260414_001")
```

---

#### `memory_retroactive_ingest`
Auto-ingest session activity from git history. **No manual logging needed!**

Scans git working tree to reconstruct what happened: modified/created/deleted files, commits, lines added/removed. Works with ANY tool/agent because it reads actual codebase state.

**Parameters:**
- `session_id` (string): Session identifier for ingested session
- `time_window_hours` (int, default 24): Hours to look back for commits
- `include_uncommitted` (boolean, default true): Include uncommitted changes

**Returns:** Files found, commits found, observations created, knowledge saved

**Example:**
```python
# Forgot to log observations? Ingest from git history!
memory_retroactive_ingest(
    session_id="sess_retroactive_001",
    time_window_hours=12,
    include_uncommitted=True
)

# Then check what was found
memory_quick_recap(session_id="sess_retroactive_001")
```

---

## Collaboration Session Tools

Multi-agent collaboration session management and communication tools.

### Session Management

#### `collab_create_session`
Create a new collaboration session.

**Parameters:**
- `title` (string): Session title
- `created_by` (string): Creator identifier (model name)
- `description` (string, optional): Session description
- `plan` (array of objects, optional): Task plan with steps
- `rules` (object, optional): Session rules configuration

**Returns:** Session ID, agent ID, orchestrator info

---

#### `collab_join_session`
Join an existing collaboration session.

**Parameters:**
- `session_id` (string): Session to join
- `model` (string): Model identifier
- `role` (string, default "worker"): Agent role (worker/observer)
- `capabilities` (array of strings, optional): Agent capabilities

**Returns:** Agent ID, session info, joining instructions

---

#### `collab_list_sessions`
List collaboration sessions.

**Parameters:**
- `status` (string, optional): Filter by status (active/completed)
- `limit` (int, default 20): Max results

**Returns:** Session list with metadata

---

#### `collab_get_session_state`
Get current state of a session.

**Parameters:**
- `session_id` (string): Session identifier

**Returns:** Session state including tasks, agents, progress

---

#### `collab_update_session_state`
Update session state.

**Parameters:**
- `session_id` (string): Session identifier
- `state` (object): New state data

**Returns:** Update confirmation

---

#### `collab_leave_session`
Leave a collaboration session gracefully.

**Parameters:**
- `agent_id` (string): Agent leaving
- `reason` (string, optional): Reason for leaving

**Returns:** Success confirmation

---

#### `collab_terminate_session`
Terminate a collaboration session.

**Parameters:**
- `session_id` (string): Session to terminate
- `summary` (string, optional): Final summary text

**Returns:** Termination confirmation

---

### Message Operations

#### `collab_send_message`
Send a message to a session.

**Parameters:**
- `session_id` (string): Target session
- `from_agent` (string): Sender agent ID
- `msg_type` (string): Message type (system/task/result/artifact/discussion)
- `content` (string): Message content
- `to_agent` (string, optional): Recipient agent
- `metadata` (object, optional): Additional metadata

**Returns:** Message ID and sequence number

---

#### `collab_read_messages`
Read messages from a session.

**Parameters:**
- `session_id` (string): Session to read from
- `last_seq` (int): Last seen sequence number
- `limit` (int, default 50): Max messages
- `msg_types` (array of strings, optional): Filter by type
- `from_agent` (string, optional): Filter by sender

**Returns:** List of new messages

---

#### `collab_poll_messages`
Poll for new messages with offset tracking.

**Parameters:**
- `session_id` (string): Session to poll
- `agent_id` (string): Polling agent ID
- `limit` (int, default 50): Max messages

**Returns:** New messages since last poll

---

#### `collab_tail_messages`
Get the most recent messages from a session.

**Parameters:**
- `session_id` (string): Session identifier
- `n` (int, default 20): Number of messages

**Returns:** Last N messages

---

#### `collab_read_message_range`
Read messages in a sequence range.

**Parameters:**
- `session_id` (string): Session identifier
- `start_seq` (int): Start sequence
- `end_seq` (int): End sequence

**Returns:** Messages in range

---

#### `collab_grep_messages`
Search session messages by pattern.

**Parameters:**
- `session_id` (string): Session to search
- `pattern` (string): Search pattern
- `limit` (int, default 50): Max results
- `msg_types` (array of strings, optional): Filter by type

**Returns:** Matching messages

---

### Artifact Management

#### `collab_add_artifact`
Add an artifact to a session.

**Parameters:**
- `session_id` (string): Target session
- `agent_id` (string): Creating agent
- `title` (string): Artifact title
- `content` (string): Artifact content
- `artifact_type` (string): Type (report/summary/analysis/notes)
- `tags` (array of strings, optional): Classification tags

**Returns:** Artifact ID and metadata

---

#### `collab_list_artifacts`
List artifacts for a session.

**Parameters:**
- `session_id` (string): Session identifier
- `artifact_type` (string, optional): Filter by type
- `limit` (int, default 50): Max results

**Returns:** Artifact list with metadata

---

#### `collab_get_artifact`
Get artifact content and metadata.

**Parameters:**
- `session_id` (string): Session identifier
- `artifact_id` (string): Artifact identifier

**Returns:** Artifact with content

---

#### `collab_grep_artifacts`
Search artifacts by keyword pattern.

**Parameters:**
- `session_id` (string): Session identifier
- `pattern` (string): Search pattern
- `limit` (int, default 20): Max results

**Returns:** Matching artifacts

---

### Session Discovery & Analytics

#### `collab_get_session_context`
Get compacted session context for agents.

**Parameters:**
- `session_id` (string): Session identifier
- `from_seq` (int, default 0): Start sequence

**Returns:** Compacted session summary and current state

---

#### `collab_get_agent_sessions`
Get sessions for a specific agent.

**Parameters:**
- `agent_id` (string): Agent identifier
- `limit` (int, default 10): Max results

**Returns:** List of agent's sessions

---

#### `collab_get_active_sessions_summary`
Get summary of all active sessions.

**Parameters:**
- `agent_id` (string, optional): Filter sessions by agent participation

**Returns:** Active sessions overview

---

#### `collab_search_sessions`
Search sessions by content or metadata.

**Parameters:**
- `query` (string): Search query
- `agent_id` (string, optional): Filter by agent
- `limit` (int, default 10): Max results

**Returns:** Matching sessions

---

#### `collab_get_session_relationships`
Find sessions related to a given session.

**Parameters:**
- `session_id` (string): Base session
- `agent_id` (string, optional): Authorization filter

**Returns:** Related sessions grouped by relationship type

---

#### `collab_get_session_statistics`
Get detailed statistics for a session.

**Parameters:**
- `session_id` (string): Session identifier

**Returns:** Message counts, activity by agent/type, time range

---

### Templates

#### `collab_list_templates`
List available session templates.

**Parameters:** None

**Returns:** Template list with descriptions and step counts

---

#### `collab_get_template`
Get a specific template by ID.

**Parameters:**
- `template_id` (string): Template identifier

**Returns:** Template with plan, rules, and metadata

---

#### `collab_create_session_from_template`
Create a session using a template.

**Parameters:**
- `template_id` (string): Template to use
- `title` (string): Session title
- `created_by` (string): Creator identifier
- `description` (string, optional): Override template description

**Returns:** Session info with agent ID

---

### Model Discovery

#### `collab_list_openrouter_models`
List available models from OpenRouter.

**Parameters:** None

**Returns:** List of models with capabilities and pricing

---

#### `collab_get_openrouter_model_details`
Get details for a specific model.

**Parameters:**
- `model_id` (string): Model identifier

**Returns:** Model capabilities, context window, pricing

---

#### `collab_get_recommended_models`
Get model recommendations for specific tasks.

**Parameters:**
- `task_type` (string, optional): Task category

**Returns:** Recommended models with rationale

---

### Utilities

#### `collab_help`
Get help for collaboration tools.

**Parameters:**
- `tool_name` (string, optional): Specific tool (or all if omitted)

**Returns:** Tool documentation and examples

---

## Usage Examples

### Basic Session Flow

```
1. collab_create_session(title="Research Project", created_by="gpt-4")
2. collab_join_session(session_id="...", model="claude-3")
3. collab_send_message(session_id="...", from_agent="...", msg_type="task", content="...")
4. collab_poll_messages(session_id="...", agent_id="...")
5. collab_add_artifact(session_id="...", agent_id="...", title="Report", content="...")
6. collab_terminate_session(session_id="...", summary="Complete")
```

### Template-Based Session

```
1. collab_list_templates()
2. collab_create_session_from_template(template_id="deep_research", title="...", created_by="...")
3. Follow the template's predefined plan steps
```

### Knowledge Retrieval

```
1. openlmlib_health()
2. openlmlib_retrieve(query="contextual retrieval", final_k=5, reasoning_trace=true)
3. openlmlib_add_finding(project="...", claim="...", confidence=0.85, confirm=true)
```

---

## Tool Categories Summary

| Category | Tools | Purpose |
|----------|-------|---------|
| Core Library | 11 | Knowledge base management & retrieval |
| Session Management | 7 | Create, join, terminate sessions |
| Message Operations | 7 | Send, read, poll, search messages |
| Artifact Management | 4 | Add, list, get, search artifacts |
| Session Discovery | 6 | Find and analyze sessions |
| Templates | 3 | Predefined session plans |
| Model Discovery | 3 | OpenRouter model information |
| Utilities | 1 | Help and documentation |
| **Total** | **42** | |
