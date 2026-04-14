# CollabSessions: Multi-Agent Collaboration for OpenLMLib

CollabSessions enables multiple LLM agents to collaborate on research tasks through a shared session backed by SQLite (for state/messages) and files (for artifacts).

## Architecture

- **SQLite** (`collab_sessions.db`): Session registry, append-only message bus, agent registry, task tracking, artifact metadata, versioned state
- **Files** (`sessions/{id}/`): Research artifacts, summaries, agent read offsets
- **MCP Tools**: 25+ tools for session management, messaging, context retrieval, and artifact handling

## Quick Start

### Via CLI

```bash
# Create a session
openlmlib collab create --title "Research Topic" --task "Description"

# List active sessions
openlmlib collab list --status active

# Join a session
openlmlib collab join <session_id> --model "gpt-4"

# View messages
openlmlib collab messages <session_id> --limit 50

# View artifacts
openlmlib collab artifacts <session_id>

# Terminate and export
openlmlib collab terminate <session_id> --summary "Done" --export
```

### Via MCP Tools

When connected to the OpenLMLib MCP server, agents have access to these tools:

| Category | Tools |
|----------|-------|
| Session | `create_session`, `join_session`, `list_sessions`, `leave_session`, `terminate_session` |
| Messages | `send_message`, `read_messages`, `tail_messages`, `grep_messages`, `read_message_range` |
| Context | `session_context` (primary tool) |
| State | `get_session_state`, `update_session_state` |
| Artifacts | `save_artifact`, `list_artifacts`, `get_artifact`, `grep_artifacts` |
| Templates | `list_templates`, `get_template`, `create_from_template` |
| Export | `export_to_library` |

Read APIs are membership-gated. Agents must pass their own `agent_id` to session state, message, artifact, and multi-session read tools, and those tools only return data for sessions the agent has joined.

### Programmatic Usage

```python
from openlmlib.collab.db import connect_collab_db, init_collab_db
from openlmlib.collab.session import create_collab_session, join_collab_session
from openlmlib.collab.message_bus import MessageBus
from pathlib import Path

conn = connect_collab_db(Path("data/collab_sessions.db"))
init_collab_db(conn)
sessions_dir = Path("data/sessions")

# Create session
result = create_collab_session(
    conn=conn,
    sessions_dir=sessions_dir,
    title="My Research",
    created_by="my-model",
    description="Research quantum computing advances",
    plan=[
        {"step": 1, "task": "Literature review", "assigned_to": "any"},
        {"step": 2, "task": "Technical analysis", "assigned_to": "any"},
    ],
)

# Send message
bus = MessageBus(conn, sessions_dir)
bus.send(
    session_id=result["session_id"],
    from_agent=result["agent_id"],
    msg_type="task",
    content="Please review the literature",
    to_agent=None,
)
```

## System Prompts

The `openlmlib.collab.prompts` module provides system prompts for each agent role:

```python
from openlmlib.collab.prompts import get_system_prompt

orchestrator_prompt = get_system_prompt(
    "orchestrator",
    session_id="sess_abc123",
    title="Research Session",
)

worker_prompt = get_system_prompt(
    "worker",
    session_id="sess_abc123",
    title="Research Session",
    agent_id="agent_codex_001",
)
```

Available roles: `orchestrator`, `worker`, `observer`.

## Error Handling

All collab operations use custom exception types:

```python
from openlmlib.collab.errors import (
    SessionNotFoundError,
    SessionNotActiveError,
    SessionFullError,
    AgentNotFoundError,
    AgentNotAuthorizedError,
    StateConflictError,
    InvalidMessageTypeError,
    MessageTooLongError,
    error_from_exception,
)

try:
    verify_agent_in_session(conn, agent_id, session_id)
except AgentNotFoundError:
    # Agent doesn't exist
except AgentNotAuthorizedError:
    # Agent not in this session
```

MCP tools return structured error responses:
```python
{"success": False, "error": "message", "error_type": "category"}
```

## Security

- **Input validation**: All MCP tool inputs are validated (session IDs, agent IDs, message types, content length)
- **Sanitization**: Content is sanitized via `openlmlib.sanitization.sanitize_text()` to prevent prompt injection
- **Session access enforcement**: Agents can only access sessions they've joined
- **Path traversal prevention**: All file paths are validated to stay within session directories
- **Single-writer state**: Only the orchestrator can update session state

## Performance

Run benchmarks:
```bash
python tests/bench_collab.py
python tests/bench_collab.py --iterations 1000
python tests/bench_collab.py --benchmark message_append
```

Targets:
| Metric | Target |
|--------|--------|
| Message append | < 3ms |
| Message read (50) | < 5ms |
| Context compilation | < 50ms |
| Session creation | < 20ms |
| FTS5 search | < 10ms |

## Testing

```bash
# Unit tests
python -m unittest tests.test_collab

# Integration tests with simulated agents
python -m unittest tests.test_collab_integration

# Performance benchmarks
python tests/bench_collab.py
```

## Session Templates

Built-in templates for common patterns:
- `deep_research` - Multi-phase research with literature review, analysis, synthesis
- `code_review` - Systematic code review with security, performance, and style checks
- `market_analysis` - Market research with competitor analysis and trend identification
- `incident_investigation` - Root cause analysis with timeline reconstruction
- `literature_review` - Academic literature survey and synthesis

```bash
openlmlib collab create-from-template deep_research --title "My Research" --task "Description"
```
