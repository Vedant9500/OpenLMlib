#!/usr/bin/env python
"""Manually log this session to memory for continuation."""
from pathlib import Path
from datetime import datetime, timezone
from openlmlib.memory import SessionManager, MemoryStorage
from openlmlib.runtime import get_runtime

session_id = "session_20260413_memory_dev_v3"

runtime = get_runtime(Path("config/settings.json"))
print(f"Using DB: {runtime.settings.db_path}")

storage = MemoryStorage(runtime.conn)
session_mgr = SessionManager(storage)

session_mgr.on_session_start(session_id, "developer", 
    "Deep code audit, knowledge extraction, and retroactive git ingestion")

observations = [
    ("code_review", "Deep audit of openlmlib/memory/", 
     "Conducted deep code audit of all 11 memory modules and 2 test scripts. "
     "Found 14 issues: 3 Critical (duplicate observation count, in-place mutation, "
     "broken join()), 5 High (tool_input not filtered, sanitize_for_storage unused, "
     "missing secret patterns, LIKE wildcard injection, no atexit handler), "
     "6 Medium. All fixed and committed as 3826cdc."),
    
    ("architecture_decision", "Knowledge extraction layer",
     "Added knowledge extraction layer on top of compressed observations. "
     "SessionKnowledge dataclass captures: files_touched, decisions_made, "
     "phases_completed/remaining, conventions_found, architecture_notes, "
     "open_questions, next_steps. Auto-extracted at session end. "
     "New MCP tools: memory_quick_recap (~200 tokens) and "
     "memory_detailed_context(topic) (~500-800 tokens)."),
    
    ("architecture_decision", "Retroactive git ingestion",
     "claude-mem uses Claude Code lifecycle hooks for real-time capture. "
     "FastMCP has no middleware, so we use retroactive git ingestion: "
     "scans git status + log + diff to reconstruct session activity. "
     "Works with ANY tool/agent. New MCP tool: memory_retroactive_ingest. "
     ".qwen/debug/ logs only have app-level events, not structured tool calls."),
    
    ("implementation", "knowledge_extractor.py (395 lines)",
     "Synthesizes observations into structured knowledge. Extracts: file paths "
     "via regex, decisions via keyword matching, conventions via pattern matching, "
     "phases via regex, errors from traceback detection. "
     "Auto-generates next_steps from remaining phases and errors."),
    
    ("implementation", "retrogit_ingest.py (395 lines)",
     "Git-based session reconstruction. Functions: get_modified_files, "
     "get_file_diff, get_recent_commits, get_commit_diff, count_lines_changed, "
     "infer_file_reason. Main entry: retroactive_ingest() creates session, "
     "builds observations from file changes and commits, synthesizes knowledge."),
    
    ("schema_change", "memory_knowledge table",
     "New table: memory_knowledge (session_id PK, knowledge_json, summary, "
     "files_touched, decisions, next_steps, created_at). ON DELETE CASCADE. "
     "save_knowledge() and get_knowledge() methods added."),
    
    ("mcp_tools", "10 memory tools total (was 7)",
     "New tools: memory_quick_recap, memory_detailed_context, "
     "memory_retroactive_ingest. Progressive flow: recap -> detailed -> raw. "
     "All registered in MCP server, documented in openlmlib_help()."),
    
    ("fixes_applied", "Deep analysis fixes (fc5194d)",
     "Fixed: TypingList scope (FastMCP crash), unused imports, get_file_diff "
     "logging, unused parameters, session_id safety, test script unique IDs."),
    
    ("next_steps", "Remaining work",
     "1. Auto-capture at MCP dispatch level (wrap FastMCP tool execution). "
     "2. Cross-session knowledge search by topic. "
     "3. Semantic search on knowledge entries (embeddings). "
     "4. Test retroactive ingest in production workflow."),
]

for i, (tool, inp, out) in enumerate(observations, 1):
    obs_id = session_mgr.on_tool_use(session_id, tool, inp, out)
    print(f"  Observation {i}: {tool} -> {obs_id}")

result = session_mgr.on_session_end(session_id)
print(f"\nSession ended: {result['observation_count']} observations")
print(f"Summary generated: {result['summary_generated']}")
print(f"Session ID: {session_id}")

# Verify
import sqlite3
conn = sqlite3.connect(str(runtime.settings.db_path))
c = conn.cursor()
c.execute("SELECT COUNT(*) FROM memory_sessions")
print(f"\nTotal sessions in DB: {c.fetchone()[0]}")
c.execute("SELECT session_id, observation_count FROM memory_sessions "
          "ORDER BY created_at DESC LIMIT 5")
for r in c.fetchall():
    print(f"  {r[0]}: {r[1]} obs")
c.execute("SELECT COUNT(*) FROM memory_knowledge")
print(f"Total knowledge entries: {c.fetchone()[0]}")
c.execute("SELECT session_id, summary FROM memory_knowledge "
          "ORDER BY created_at DESC LIMIT 3")
for r in c.fetchall():
    print(f"  {r[0]}: {r[1][:80]}")
conn.close()

print("\n✓ Memory logged successfully!")
