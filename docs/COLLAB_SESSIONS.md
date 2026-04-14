# CollabSessions: Multi-Agent Collaboration

OpenLMlib's CollabSessions feature enables multiple LLM agents to collaborate on complex tasks through structured sessions with message passing, artifact sharing, and task management.

## Overview

CollabSessions provides:
- **Session Management**: Create, join, leave, and terminate collaboration sessions
- **Message Bus**: Reliable message passing with sequence numbers and offset tracking
- **Artifact Store**: Share and manage artifacts (reports, summaries, analysis)
- **Templates**: Predefined session plans for common collaboration patterns
- **Context Compaction**: Summarize session state for agents joining mid-session

## Quick Start

### Create a Session

```bash
openlmlib-mcp --call create_session '{
  "title": "Research on Retrieval",
  "created_by": "gpt-4",
  "description": "Multi-agent research on contextual retrieval"
}'
```

Or use a template:

```bash
openlmlib-mcp --call create_from_template '{
  "template_id": "deep_research",
  "title": "Deep Research on Topic X",
  "created_by": "claude-3-opus"
}'
```

### Join a Session

```bash
openlmlib-mcp --call join_session '{
  "session_id": "sess_20260409_abc12345",
  "model": "claude-3-sonnet",
  "role": "worker"
}'
```

### Send and Receive Messages

```bash
# Send a task result
openlmlib-mcp --call send_message '{
  "session_id": "sess_20260409_abc12345",
  "from_agent": "agent_claude-3-sonnet_xyz",
  "msg_type": "result",
  "content": "Found 15 relevant papers on contextual retrieval"
}'

# Poll for new messages
openlmlib-mcp --call poll_messages '{
  "session_id": "sess_20260409_abc12345",
  "agent_id": "agent_claude-3-sonnet_xyz"
}'
```

### Add Artifacts

```bash
openlmlib-mcp --call save_artifact '{
  "session_id": "sess_20260409_abc12345",
  "agent_id": "agent_claude-3-sonnet_xyz",
  "title": "Literature Review Summary",
  "content": "...",
  "artifact_type": "summary",
  "tags": ["literature", "retrieval"]
}'
```

### Terminate Session

```bash
openlmlib-mcp --call terminate_session '{
  "session_id": "sess_20260409_abc12345",
  "summary": "Research complete with 15 papers analyzed"
}'
```

## Available Templates

OpenLMlib ships with predefined templates for common collaboration patterns:

### `deep_research`
Comprehensive research with literature review, analysis, and synthesis
- **Steps**: 5 (literature review → analysis → comparison → synthesis → validation)
- **Max Agents**: 5

### `code_review`
Multi-agent code review with security, performance, and architecture analysis
- **Steps**: 5 (architecture → security → performance → quality → report)
- **Max Agents**: 4

### `market_analysis`
Market/competitor analysis with opportunity identification
- **Steps**: 4 (overview → competitor analysis → technology landscape → opportunities)
- **Max Agents**: 4

### `incident_investigation`
Structured incident investigation and root cause analysis
- **Steps**: 4 (timeline → root cause → impact → remediation)
- **Max Agents**: 3

### `literature_review`
Systematic academic literature review
- **Steps**: 6 (search strategy → collection → quality assessment → thematic analysis → gap analysis → write review)
- **Max Agents**: 5

List all templates:
```bash
openlmlib-mcp --call list_templates
```

## Message Types

| Type | Purpose |
|------|---------|
| `system` | Session lifecycle, task creation, announcements |
| `task` | Task assignment and instructions |
| `result` | Task completion and findings |
| `artifact` | Artifact creation notifications |
| `discussion` | General agent-to-agent communication |
| `summary` | Session summaries and compaction |

## Agent Roles

### Orchestrator
- Created with the session
- Manages task delegation and session state
- Performs synthesis and consolidation
- Can terminate the session

### Worker
- Executes assigned tasks
- Sends results and artifacts
- Can send discussion messages

### Observer
- Monitors session progress
- Read-only access to messages
- Can add discussion messages

## Session Lifecycle

```
Created → Active → Completed
              ↓
         Terminated (on error/early stop)
```

### State Management

Sessions maintain state including:
- Message count and sequence
- Task status and assignments
- Agent participation
- Compaction points
- Last activity timestamp

## Context Compaction

For long-running sessions, agents can generate summaries to manage context window size:

```bash
# Generate session summary
openlmlib-mcp --call session_context '{
  "session_id": "sess_20260409_abc12345",
  "from_seq": 0
}'
```

This returns:
- Session metadata and rules
- Task status summary
- Artifact list
- Key messages
- Compacted overview

## Session Discovery

### Find Related Sessions

```bash
# Get sessions related to current one
openlmlib-mcp --call session_relationships '{
  "session_id": "sess_20260409_abc12345"
}'
```

Returns sessions with:
- Shared agents
- Same orchestrator
- Similar content

### Search Sessions

```bash
openlmlib-mcp --call search_sessions '{
  "query": "retrieval research",
  "limit": 10
}'
```

## Analytics

Get session statistics:

```bash
openlmlib-mcp --call session_statistics '{
  "session_id": "sess_20260409_abc12345"
}'
```

Returns:
- Total messages
- Message breakdown by type and agent
- Artifact count
- First/last message timestamps

## Cross-Session Agent Activity

Track an agent's activity across all sessions:

```bash
openlmlib-mcp --call get_agent_sessions '{
  "agent_id": "agent_claude-3-sonnet_xyz",
  "limit": 10
}'
```

## Best Practices

### For Orchestrators
1. Define clear task plans with specific assignments
2. Set session rules (max agents, message limits, compaction thresholds)
3. Monitor progress with `get_session_state`
4. Generate summaries periodically for long sessions
5. Terminate with comprehensive summary

### For Workers
1. Poll messages regularly with offset tracking
2. Send results as artifacts for important outputs
3. Use appropriate message types (task/result/discussion)
4. Leave sessions gracefully when done

### Session Rules Configuration
```json
{
  "max_agents": 5,
  "require_assignment": true,
  "max_message_length": 8000,
  "require_artifact_for_results": true,
  "auto_compact_after_messages": 30
}
```

## Security

All CollabSession tools include:
- Input validation (session IDs, agent IDs, paths)
- Path traversal prevention
- Content sanitization
- Authorization checks
- Structured error responses

## Architecture

```
Session
├── Agents (orchestrator + workers)
├── Message Bus (SQLite + JSONL shadow log)
│   ├── send()
│   ├── read_messages()
│   ├── poll_messages() (with offset tracking)
│   └── grep_messages()
├── Artifact Store
│   ├── add_artifact()
│   ├── list_artifacts()
│   ├── get_artifact()
│   └── grep_artifacts()
├── State Manager
│   ├── get_state()
│   └── update_state()
└── Context Compiler
    └── compile_context() (for compaction)
```

## Related Tools

- See [MCP_TOOLS.md](MCP_TOOLS.md) for complete tool reference
- See [SYSTEM_PROMPT.md](SYSTEM_PROMPT.md) for agent instruction templates
- See main [README.md](../README.md) for installation and setup
