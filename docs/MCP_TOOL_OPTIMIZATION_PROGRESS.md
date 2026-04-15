# MCP Tool Optimization Progress

**Started:** April 14, 2026
**Reference:** `docs/natural_tool_use_optimization.md`
**Goal:** Make all MCP tools natural and fluent for LLMs by adding behavioral triggers, workflow context, and smart defaults.

---

## Legend

| Status | Meaning |
|--------|---------|
| ✅ Done | Description rewritten with behavioral triggers, workflow context, parameter guidance |
| 🔶 Partial | Some improvements made but needs more work |
| ❌ Not Started | Still has original minimal description |

---

## Core Library Tools (`openlmlib/mcp_server.py`)

| Tool | Status | Changes Made |
|------|--------|--------------|
| `init_library` | ✅ Done | Added one-time usage guidance, WHEN/WHEN NOT triggers |
| `save_finding` | ✅ Done | Full behavioral triggers, parameter guidance, workflow position, smart defaults (confidence=0.8) |
| `list_findings` | ✅ Done | Added browsing vs search differentiation, triggers |
| `get_finding` | ✅ Done | Added WHEN to use, prerequisite guidance |
| `search_findings` | ✅ Done | Added workflow position, search strategy tips, FTS5 syntax examples |
| `retrieve_findings` | ✅ Done | Added WHEN/WHEN NOT, workflow position, parameter guidance for advanced params |
| `retrieve_context` | ✅ Done | Added differentiation from retrieve, safe context use cases |
| `delete_finding` | ✅ Done | Added safety warnings, WHEN NOT to use |
| `health` | ✅ Done | Added debugging/verification triggers |
| `evaluate_retrieval` | ✅ Done | Added developer-only guidance |
| `start_research` | ✅ **NEW** | Composite tool: session start + context injection + finding search |
| `end_session` | ✅ **NEW** | Composite tool: session end + knowledge preservation |
| `check_context` | ✅ **NEW** | Convenience tool: quick context existence check |
| `save_finding_auto` | ✅ **NEW** | Convenience tool: auto-confidence scoring (default 0.9) |
| `help_library` | ✅ Updated | Updated to include all new tools and improved descriptions |

---

## Memory Injection Tools (`openlmlib/mcp_server.py` - dynamically registered)

| Tool | Status | Changes Made |
|------|--------|--------------|
| `session_start` | ✅ Done | Added AUTOMATIC TRIGGERS, ALWAYS CALL guidance, workflow position, parameter guidance |
| `session_end` | ✅ Done | Added WHEN triggers (user says "done", goal achieved), ALWAYS CALL guidance |
| `log_observation` | ✅ Done | Added WHEN to log, significance guidance, workflow position |
| `search_memory` | ✅ Done | Added search strategy, layer guidance (use first before timeline/observations) |
| `memory_timeline` | ✅ Done | Added WHEN triggers, sequence understanding guidance |
| `get_observations` | ✅ Done | Added cost warning, filter-first guidance |
| `inject_context` | ✅ Done | Added mid-session use cases, differentiation from session_start |
| `session_recap` | ✅ Done | Added structured vs raw differentiation, FIRST call guidance |
| `topic_context` | ✅ Done | Added AFTER quick_recap guidance, topic examples |
| `ingest_git_history` | ✅ Done | Added WHEN triggers, git history explanation |

---

## CollabSession Tools (`openlmlib/collab/collab_mcp.py`)

### Session Management

| Tool | Status | Changes Made |
|------|--------|--------------|
| `create_session` | ✅ Done | Added AUTOMATIC TRIGGERS, workflow position, next steps guidance |
| `join_session` | ✅ Done | Added WHEN triggers, workflow position, after-joining guidance |
| `list_sessions` | ✅ Done | Added WHEN triggers, browsing vs details differentiation, parameter guidance |
| `get_session_state` | ✅ Done | Added WHEN triggers, DIFFERENCE from get_session_context, parameter guidance |
| `update_session_state` | ✅ Done | Added orchestrator-only guidance, conflict retry advice, WHEN triggers |
| `leave_session` | ✅ Done | Added WHEN triggers, DIFFERENCE from terminate_session guidance |
| `terminate_session` | ✅ Done | Added WHEN triggers, workflow position, post-termination guidance |

### Messaging

| Tool | Status | Changes Made |
|------|--------|--------------|
| `send_message` | ✅ Done | Full message type breakdown, WHEN triggers for each type, workflow guidance |
| `read_messages` | ✅ Done | Added WHEN triggers, DIFFERENCE from poll_messages, workflow position |
| `poll_messages` | ✅ Done | Added autonomous loop usage pattern, blocking behavior explanation |
| `tail_messages` | ✅ Done | Added WHEN triggers, DIFFERENCE from read_messages, quick status guidance |
| `read_message_range` | ✅ Done | Added WHEN triggers, sequence-based context guidance |
| `grep_messages` | ✅ Done | Added WHEN triggers, search tips, FTS5 syntax guidance |

### Context & State

| Tool | Status | Changes Made |
|------|--------|--------------|
| `session_context` | ✅ Done | Added WHEN triggers, GO-TO tool guidance, workflow position |
| `get_session_state` | ❌ Not Started | Original description unchanged (listed above) |
| `update_session_state` | ❌ Not Started | Original description unchanged (listed above) |

### Artifacts

| Tool | Status | Changes Made |
|------|--------|--------------|
| `save_artifact` | ✅ Done | Added WHEN triggers, significant work guidance, workflow position |
| `list_artifacts` | ✅ Done | Added WHEN triggers, duplicate avoidance guidance, parameter guidance |
| `get_artifact` | ✅ Done | Added WHEN triggers, workflow position (after list_artifacts), parameter guidance |
| `grep_artifacts` | ✅ Done | Added WHEN triggers, search use cases |

### Templates

| Tool | Status | Changes Made |
|------|--------|--------------|
| `list_templates` | ✅ Done | Added WHEN triggers, next steps guidance |
| `get_template` | ✅ Done | Added WHEN triggers, review-before-use guidance |
| `create_from_template` | ✅ Done | Added WHEN triggers, workflow position, DIFFERENCE from create_session |

### Export

| Tool | Status | Changes Made |
|------|--------|--------------|
| `export_to_library` | ✅ Done | Added WHEN triggers, workflow position (after termination), parameter guidance |

### Multi-Session

| Tool | Status | Changes Made |
|------|--------|--------------|
| `get_agent_sessions` | ✅ Done | Added WHEN triggers, work history framing, parameter guidance |
| `sessions_summary` | ✅ Done | Added WHEN triggers, "what's happening" use case |
| `search_sessions` | ✅ Done | Added WHEN triggers, search tips, FTS5 guidance |
| `session_relationships` | ✅ Done | Added WHEN triggers, cross-session context framing |
| `session_statistics` | ✅ Done | Added WHEN triggers, productivity measurement use case |

### Model Discovery

| Tool | Status | Changes Made |
|------|--------|--------------|
| `list_models` | ✅ Done | Added WHEN triggers, filtering guidance, API key note |
| `get_model_details` | ✅ Done | Added WHEN triggers, prerequisite guidance (list first) |
| `recommended_models` | ✅ Done | Added WHEN triggers, task type enumeration |

### Help

| Tool | Status | Changes Made |
|------|--------|--------------|
| `help_collab` | ✅ Updated | Updated descriptions for key tools in help output |

---

## Summary

| Category | Total | ✅ Done | ❌ Not Started | Progress |
|----------|-------|---------|----------------|----------|
| Core Library | 15 (4 new) | 15 | 0 | 100% |
| Memory Injection | 10 | 10 | 0 | 100% |
| CollabSession | 31 | 31 | 0 | 100% |
| **TOTAL** | **56** | **56** | **0** | **100%** |

---

## Priority Recommendations

### Phase 2 Complete ✅

All tool descriptions have been optimized with behavioral triggers, workflow context,
and parameter guidance. 56/56 tools (100%) complete.

### Next: Tool Naming Discussion

Ready to discuss tool name optimizations per Principle 2 in `natural_tool_use_optimization.md`:
- Current: `save_finding`, `list_findings`, etc.
- Proposed: `save_finding`, `search_findings`, etc.
- Goal: Action-oriented `verb_object` pattern for 85%+ selection accuracy

---

## Phase 3: Tool Renaming (Complete ✅)

All 56 tools renamed from `prefix_name` to clean `verb_object` pattern:
- 1029 replacements across 28 files
- Core: `openlmlib_add_finding` → `save_finding`, etc.
- Memory: `memory_session_start` → `session_start`, etc.
- Collab: `collab_create_session` → `create_session`, etc.

### Name Mapping Reference

| Category | Old Pattern | New Pattern | Examples |
|----------|------------|-------------|----------|
| Core Library | `openlmlib_<action>` | `<verb>_<target>` | `save_finding`, `search_findings`, `list_findings` |
| Memory | `memory_<action>` | `<verb>_<target>` | `session_start`, `session_end`, `search_memory` |
| Collab | `collab_<action>` | `<verb>_<target>` | `create_session`, `send_message`, `save_artifact` |

All 221 tests pass. Syntax validates cleanly.

Per `natural_tool_use_optimization.md`, these are still TODO:

- [x] Add read-before-write enforcement for `save_finding` (check for duplicates) ✅ **DONE**
- [x] Add session-aware validation (warn if no active session) ✅ **DONE**
- [x] Implement duplicate detection with suggestions ✅ **DONE**
- [x] Add tiered confirmations (read=auto, write=confirm, destructive=explicit) ✅ **DONE**

---

## Phase 3: Enforcement (Complete ✅)

All Phase 3 enforcement features implemented:

### Read-Before-Write Enforcement
- `save_finding` and `save_finding_auto` automatically search for similar findings before saving
- FTS5 query runs with `limit=3` to find potential duplicates
- Results returned in response with `similar_findings` field containing top 3 matches
- FTS5 `rank` included in search results for similarity scoring
- `_check_duplicate_warning()` helper detects very similar findings (rank <= 2.0)
- `add_finding()` accepts `similar_findings` parameter and returns duplicate warning info

### Session-Aware Validation
- `save_finding` and `save_finding_auto` descriptions include "SESSION AWARENESS" section
- Guidance to use `start_research` or `session_start` before saving findings
- Non-blocking warning (encourages best practices without breaking existing workflows)

### Tiered Confirmation System
All tools now explicitly document their confirmation tier in descriptions:

| Tier | Tools | Confirmation Required |
|------|-------|----------------------|
| **READ** (auto) | `search_findings`, `retrieve_findings`, `check_context`, `list_findings`, `get_finding`, `health`, etc. | None - safe to call freely |
| **WRITE** (confirm) | `save_finding`, `save_finding_auto` | `confirm=true` required |
| **DESTRUCTIVE** (explicit) | `delete_finding`, `restore_library` | `confirm=true` required + explicit user warning |

### Files Modified
- `openlmlib/library.py` - Added `similar_findings` parameter to `add_finding()`, `_check_duplicate_warning()` helper
- `openlmlib/db.py` - Added `fts.rank` to `search_findings()` SELECT clause
- `openlmlib/mcp_server.py` - Updated `save_finding`, `save_finding_auto` with auto-search, session awareness, tier markers
- Updated tool descriptions for `search_findings`, `retrieve_findings`, `check_context`, `delete_finding`

### Test Results
- All 229 tests pass
- All core tests (storage, write_gate, health) pass
- `_check_duplicate_warning()` helper verified working correctly

---

## Phase 4: Validation & Analytics (Complete ✅)

All Phase 4 validation and analytics features implemented:

### Tool Usage Analytics Infrastructure
- New `openlmlib/usage_analytics.py` module with comprehensive tracking
- Database tables: `tool_calls`, `parameter_validations`, `tool_selections`, `workflow_events`
- Automatic logging of tool calls with metadata (call mode, execution time, success/failure, trigger source)

### Metrics Tracked

| Metric | Description | Implementation |
|--------|-------------|----------------|
| **Automatic Call Rate** | % of tool calls model made without explicit instruction | `get_automatic_call_rate()` |
| **Tool Selection Accuracy** | % of correct tool choices for queries | `get_tool_selection_accuracy()` |
| **Parameter Hallucination Rate** | % of parameters needing correction | `get_parameter_hallucination_rate()` |
| **Workflow Completeness** | % of workflow steps completed | `get_workflow_completeness()` |

### New MCP Tool: `get_usage_analytics`
- Returns comprehensive analytics report
- Supports per-tool filtering and configurable time window
- For developers tracking optimization effectiveness

### Files Modified
- `openlmlib/usage_analytics.py` - **NEW** - Analytics API and reporting
- `openlmlib/db.py` - Added analytics tables to init_db()
- `openlmlib/mcp_server.py` - Added `get_usage_analytics` tool, integrated logging into `save_finding`

---

## Implementation Notes

### Parameter Schema Optimizations Done
- `save_finding.confidence` → default `0.8` (was required)
- `save_finding_auto.confidence` → auto-scored (default `0.9`)

### Behavioral Trigger Patterns Applied
- **AUTOMATIC TRIGGERS** - WHEN to call the tool
- **DO NOT CALL for** - WHEN NOT to call
- **WORKFLOW POSITION** - Where in sequence
- **PARAMETERS** - Guidance on each parameter
- **DIFFERENCE from X** - Differentiation from similar tools

### Composite/Convenience Tools Added
- `start_research` - Replaces session_start + search_fts
- `end_session` - Replaces session_end + export
- `check_context` - Quick context existence check
- `save_finding_auto` - Auto-confidence scoring wrapper
