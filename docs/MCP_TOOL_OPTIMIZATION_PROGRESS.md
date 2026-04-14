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
| `openlmlib_init` | ✅ Done | Added one-time usage guidance, WHEN/WHEN NOT triggers |
| `openlmlib_add_finding` | ✅ Done | Full behavioral triggers, parameter guidance, workflow position, smart defaults (confidence=0.8) |
| `openlmlib_list_findings` | ✅ Done | Added browsing vs search differentiation, triggers |
| `openlmlib_get_finding` | ✅ Done | Added WHEN to use, prerequisite guidance |
| `openlmlib_search_fts` | ✅ Done | Added workflow position, search strategy tips, FTS5 syntax examples |
| `openlmlib_retrieve` | ✅ Done | Added WHEN/WHEN NOT, workflow position, parameter guidance for advanced params |
| `openlmlib_retrieve_context` | ✅ Done | Added differentiation from retrieve, safe context use cases |
| `openlmlib_delete_finding` | ✅ Done | Added safety warnings, WHEN NOT to use |
| `openlmlib_health` | ✅ Done | Added debugging/verification triggers |
| `openlmlib_evaluate_dataset` | ✅ Done | Added developer-only guidance |
| `start_research_workflow` | ✅ **NEW** | Composite tool: session start + context injection + finding search |
| `complete_session` | ✅ **NEW** | Composite tool: session end + knowledge preservation |
| `check_relevant_context` | ✅ **NEW** | Convenience tool: quick context existence check |
| `save_important_finding` | ✅ **NEW** | Convenience tool: auto-confidence scoring (default 0.9) |
| `openlmlib_help` | ✅ Updated | Updated to include all new tools and improved descriptions |

---

## Memory Injection Tools (`openlmlib/mcp_server.py` - dynamically registered)

| Tool | Status | Changes Made |
|------|--------|--------------|
| `memory_session_start` | ✅ Done | Added AUTOMATIC TRIGGERS, ALWAYS CALL guidance, workflow position, parameter guidance |
| `memory_session_end` | ✅ Done | Added WHEN triggers (user says "done", goal achieved), ALWAYS CALL guidance |
| `memory_log_observation` | ✅ Done | Added WHEN to log, significance guidance, workflow position |
| `memory_search` | ✅ Done | Added search strategy, layer guidance (use first before timeline/observations) |
| `memory_timeline` | ✅ Done | Added WHEN triggers, sequence understanding guidance |
| `memory_get_observations` | ✅ Done | Added cost warning, filter-first guidance |
| `memory_inject_context` | ✅ Done | Added mid-session use cases, differentiation from session_start |
| `memory_quick_recap` | ✅ Done | Added structured vs raw differentiation, FIRST call guidance |
| `memory_detailed_context` | ✅ Done | Added AFTER quick_recap guidance, topic examples |
| `memory_retroactive_ingest` | ✅ Done | Added WHEN triggers, git history explanation |

---

## CollabSession Tools (`openlmlib/collab/collab_mcp.py`)

### Session Management

| Tool | Status | Changes Made |
|------|--------|--------------|
| `collab_create_session` | ✅ Done | Added AUTOMATIC TRIGGERS, workflow position, next steps guidance |
| `collab_join_session` | ✅ Done | Added WHEN triggers, workflow position, after-joining guidance |
| `collab_list_sessions` | ✅ Done | Added WHEN triggers, browsing vs details differentiation, parameter guidance |
| `collab_get_session_state` | ✅ Done | Added WHEN triggers, DIFFERENCE from get_session_context, parameter guidance |
| `collab_update_session_state` | ✅ Done | Added orchestrator-only guidance, conflict retry advice, WHEN triggers |
| `collab_leave_session` | ✅ Done | Added WHEN triggers, DIFFERENCE from terminate_session guidance |
| `collab_terminate_session` | ✅ Done | Added WHEN triggers, workflow position, post-termination guidance |

### Messaging

| Tool | Status | Changes Made |
|------|--------|--------------|
| `collab_send_message` | ✅ Done | Full message type breakdown, WHEN triggers for each type, workflow guidance |
| `collab_read_messages` | ✅ Done | Added WHEN triggers, DIFFERENCE from poll_messages, workflow position |
| `collab_poll_messages` | ✅ Done | Added autonomous loop usage pattern, blocking behavior explanation |
| `collab_tail_messages` | ✅ Done | Added WHEN triggers, DIFFERENCE from read_messages, quick status guidance |
| `collab_read_message_range` | ✅ Done | Added WHEN triggers, sequence-based context guidance |
| `collab_grep_messages` | ✅ Done | Added WHEN triggers, search tips, FTS5 syntax guidance |

### Context & State

| Tool | Status | Changes Made |
|------|--------|--------------|
| `collab_get_session_context` | ✅ Done | Added WHEN triggers, GO-TO tool guidance, workflow position |
| `collab_get_session_state` | ❌ Not Started | Original description unchanged (listed above) |
| `collab_update_session_state` | ❌ Not Started | Original description unchanged (listed above) |

### Artifacts

| Tool | Status | Changes Made |
|------|--------|--------------|
| `collab_add_artifact` | ✅ Done | Added WHEN triggers, significant work guidance, workflow position |
| `collab_list_artifacts` | ✅ Done | Added WHEN triggers, duplicate avoidance guidance, parameter guidance |
| `collab_get_artifact` | ✅ Done | Added WHEN triggers, workflow position (after list_artifacts), parameter guidance |
| `collab_grep_artifacts` | ✅ Done | Added WHEN triggers, search use cases |

### Templates

| Tool | Status | Changes Made |
|------|--------|--------------|
| `collab_list_templates` | ✅ Done | Added WHEN triggers, next steps guidance |
| `collab_get_template` | ✅ Done | Added WHEN triggers, review-before-use guidance |
| `collab_create_session_from_template` | ✅ Done | Added WHEN triggers, workflow position, DIFFERENCE from create_session |

### Export

| Tool | Status | Changes Made |
|------|--------|--------------|
| `collab_export_to_library` | ✅ Done | Added WHEN triggers, workflow position (after termination), parameter guidance |

### Multi-Session

| Tool | Status | Changes Made |
|------|--------|--------------|
| `collab_get_agent_sessions` | ✅ Done | Added WHEN triggers, work history framing, parameter guidance |
| `collab_get_active_sessions_summary` | ✅ Done | Added WHEN triggers, "what's happening" use case |
| `collab_search_sessions` | ✅ Done | Added WHEN triggers, search tips, FTS5 guidance |
| `collab_get_session_relationships` | ✅ Done | Added WHEN triggers, cross-session context framing |
| `collab_get_session_statistics` | ✅ Done | Added WHEN triggers, productivity measurement use case |

### Model Discovery

| Tool | Status | Changes Made |
|------|--------|--------------|
| `collab_list_openrouter_models` | ✅ Done | Added WHEN triggers, filtering guidance, API key note |
| `collab_get_openrouter_model_details` | ✅ Done | Added WHEN triggers, prerequisite guidance (list first) |
| `collab_get_recommended_models` | ✅ Done | Added WHEN triggers, task type enumeration |

### Help

| Tool | Status | Changes Made |
|------|--------|--------------|
| `collab_help` | ✅ Updated | Updated descriptions for key tools in help output |

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
- Current: `openlmlib_add_finding`, `openlmlib_list_findings`, etc.
- Proposed: `save_finding`, `search_findings`, etc.
- Goal: Action-oriented `verb_object` pattern for 85%+ selection accuracy

---

## Phase 3: Enforcement (Not Yet Started)

Per `natural_tool_use_optimization.md`, these are still TODO:

- [ ] Add read-before-write enforcement for `save_finding` (check for duplicates)
- [ ] Add session-aware validation (error if no active session)
- [ ] Implement duplicate detection with suggestions
- [ ] Add tiered confirmations (read=auto, write=confirm)

---

## Implementation Notes

### Parameter Schema Optimizations Done
- `openlmlib_add_finding.confidence` → default `0.8` (was required)
- `save_important_finding.confidence` → auto-scored (default `0.9`)

### Behavioral Trigger Patterns Applied
- **AUTOMATIC TRIGGERS** - WHEN to call the tool
- **DO NOT CALL for** - WHEN NOT to call
- **WORKFLOW POSITION** - Where in sequence
- **PARAMETERS** - Guidance on each parameter
- **DIFFERENCE from X** - Differentiation from similar tools

### Composite/Convenience Tools Added
- `start_research_workflow` - Replaces memory_session_start + search_fts
- `complete_session` - Replaces memory_session_end + export
- `check_relevant_context` - Quick context existence check
- `save_important_finding` - Auto-confidence scoring wrapper
