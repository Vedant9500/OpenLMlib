from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional
from typing import List as TypingList

from mcp.server.fastmcp import FastMCP

from .library import (
    add_finding,
    delete_finding,
    evaluate_dataset,
    get_finding,
    health,
    init_library,
    list_findings,
    retrieve_findings,
    retrieve_prompt_context,
    search_fts,
)
from .runtime import get_runtime


def _settings_path() -> Path:
    value = os.environ.get("OPENLMLIB_SETTINGS")
    if value:
        return Path(value)
    from .settings import resolve_global_settings_path
    return resolve_global_settings_path()


mcp = FastMCP("OpenLMlib")

# Lazy-load collab tools to avoid importing the entire collab module tree
# at startup. This cuts MCP server startup time from ~50s to ~2s.
_collab_registered = False

# Lazy-load memory tools to avoid importing memory module at startup.
_memory_registered = False


def _register_collab_tools() -> None:
    """Register collaboration tools with the MCP server on first access."""
    global _collab_registered
    if _collab_registered:
        return

    from .collab.collab_mcp import (
        save_artifact,
        create_session,
        create_from_template,
        export_to_library,
        sessions_summary,
        get_agent_sessions,
        get_artifact,
        get_model_details,
        recommended_models,
        session_context,
        session_relationships,
        get_session_state,
        session_statistics,
        get_template,
        grep_artifacts,
        grep_messages,
        help_collab as help_collab,
        join_session,
        leave_session,
        list_artifacts,
        list_models,
        list_sessions,
        list_templates,
        poll_messages,
        read_message_range,
        read_messages,
        search_sessions,
        send_message,
        tail_messages,
        terminate_session,
        update_session_state,
    )

    mcp.tool()(create_session)
    mcp.tool()(join_session)
    mcp.tool()(list_sessions)
    mcp.tool()(get_session_state)
    mcp.tool()(update_session_state)
    mcp.tool()(send_message)
    mcp.tool()(read_messages)
    mcp.tool()(poll_messages)
    mcp.tool()(tail_messages)
    mcp.tool()(read_message_range)
    mcp.tool()(grep_messages)
    mcp.tool()(session_context)
    mcp.tool()(save_artifact)
    mcp.tool()(list_artifacts)
    mcp.tool()(get_artifact)
    mcp.tool()(grep_artifacts)
    mcp.tool()(leave_session)
    mcp.tool()(terminate_session)
    mcp.tool()(export_to_library)
    mcp.tool()(list_templates)
    mcp.tool()(get_template)
    mcp.tool()(create_from_template)
    mcp.tool()(get_agent_sessions)
    mcp.tool()(sessions_summary)
    mcp.tool()(search_sessions)
    mcp.tool()(session_relationships)
    mcp.tool()(session_statistics)
    mcp.tool()(list_models)
    mcp.tool()(get_model_details)
    mcp.tool()(recommended_models)
    mcp.tool()(help_collab)

    _collab_registered = True


def _register_memory_tools() -> None:
    """Register memory lifecycle and retrieval tools with the MCP server.
    
    Lazy-loads memory module to avoid import penalty at startup.
    Provides 7 tools for session lifecycle management and progressive retrieval.
    """
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

    # Initialize memory system components
    runtime = get_runtime(_settings_path())
    storage = MemoryStorage(runtime.conn)
    session_mgr = SessionManager(storage)
    retriever = ProgressiveRetriever(storage)
    context_builder = ContextBuilder(retriever)

    @mcp.tool()
    def session_start(
        session_id: str,
        user_id: Optional[str] = None,
        query: Optional[str] = None,
        limit: int = 50
    ) -> dict:
        """Start a new session and automatically inject relevant context from past sessions.

        AUTOMATIC TRIGGERS - Call this when:
        - Beginning a new work session or conversation
        - User starts a new conversation about ongoing work
        - You need context from previous sessions before starting work

        ALWAYS CALL THIS at the start of any work session - it prevents starting work
        without historical context. This loads knowledge from all previous sessions.

        WORKFLOW POSITION: First tool to call when starting work.

        PARAMETERS:
        - session_id: Unique identifier for this session (generate a unique ID like UUID or timestamp-based)
        - query: What this session will focus on - used to find relevant past context (optional but recommended)
        - limit: Max past observations to inject (default: 50, reduce for focused sessions)
        - user_id: Optional user/agent identifier

        Returns context block with relevant past observations (compressed for efficiency).
        """
        context = session_mgr.on_session_start(session_id, user_id, query)
        
        # Build injection context (with caveman compression enabled)
        context_block = context_builder.build_session_start_context(
            session_id, query, limit
        )
        
        return {
            "session_id": session_id,
            "context_injected": bool(context_block),
            "observation_count": context.get("observation_count", 0),
            "context_block": context_block,
            "message": "Session started with memory context loaded"
        }

    @mcp.tool()
    def session_end(session_id: str) -> dict:
        """End the current session and trigger automatic summarization to persist knowledge.

        AUTOMATIC TRIGGERS - Call this when:
        - User indicates they're done with current work ("done", "finished", "ending session")
        - Session goal has been achieved
        - About to start unrelated work
        - You're wrapping up a task or research phase

        ALWAYS CALL THIS when ending work to ensure session knowledge is not lost.
        This automatically generates a compressed summary of all observations.

        WORKFLOW POSITION: Last tool to call when finishing work.

        PARAMETERS:
        - session_id: The session to end (track this from session_start)
        """
        result = session_mgr.on_session_end(session_id)
        
        return {
            "session_id": session_id,
            "status": "ended",
            "summary_generated": result.get("summary_generated", False),
            "observation_count": result.get("observation_count", 0),
            "message": "Session ended and summary saved"
        }

    @mcp.tool()
    def log_observation(
        session_id: str,
        tool_name: str,
        tool_input: str,
        tool_output: str
    ) -> dict:
        """Log an observation from tool execution to build session memory.

        AUTOMATIC TRIGGERS - Call this when:
        - A tool execution produces important or surprising results
        - You want to remember what happened during the session
        - Building up context for the end-of-session summary

        This captures tool outputs for future memory retrieval.
        Call this after significant tool executions to build session memory.

        WORKFLOW POSITION: Call after important tool executions throughout the session.
        The observation will be compressed and summarized for future retrieval.

        PARAMETERS:
        - session_id: Active session identifier (from session_start)
        - tool_name: Tool that was executed (e.g., "web_search", "read_file")
        - tool_input: What was passed to the tool
        - tool_output: What the tool returned

        NOTE: Don't log every single tool call - only significant ones with novel insights.
        """
        obs_id = session_mgr.on_tool_use(
            session_id, tool_name, tool_input, tool_output
        )
        
        return {
            "observation_id": obs_id,
            "status": "logged" if obs_id else "failed",
            "message": "Observation queued for compression" if obs_id else "Session not active"
        }

    @mcp.tool()
    def search_memory(
        query: str,
        limit: int = 50,
        filters: Optional[dict] = None
    ) -> dict:
        """Layer 1: Lightweight search of memory index (~75 tokens/result). Fast metadata search.

        AUTOMATIC TRIGGERS - Call this when:
        - You need to identify which memories might be relevant
        - Before fetching full observations (to filter first)
        - Searching for observations by tool name, type, or session

        Returns compact metadata for filtering. Use this FIRST to identify relevant memories,
        then use memory_timeline or get_observations for details.

        SEARCH STRATEGY: Use specific keywords. Filter by tool_name, obs_type, or session_id.

        PARAMETERS:
        - query: Search query
        - limit: Max results (default: 50)
        - filters: Optional filters like {"tool_name": "web_search", "session_id": "..."}
        """
        results = retriever.layer1_search_index(query, limit, filters)
        
        return {
            "query": query,
            "results": [r.__dict__ for r in results],
            "count": len(results),
            "estimated_tokens": len(results) * 75
        }

    @mcp.tool()
    def memory_timeline(
        ids: TypingList[str],
        window: str = "5m"
    ) -> dict:
        """Layer 2: Get chronological context for memory IDs (~200 tokens/result).

        AUTOMATIC TRIGGERS - Call this when:
        - You have observation IDs from search_memory
        - You need to understand the sequence of events
        - Understanding how observations relate to each other over time

        Returns narrative flow around observations. Use AFTER search_memory to understand sequence.
        Provides timeline context for how observations relate to each other.

        PARAMETERS:
        - ids: List of observation IDs from search_memory
        - window: Time window for context around each observation (default: "5m")
        """
        results = retriever.layer2_timeline(ids, window)
        
        return {
            "ids": ids,
            "timeline": [r.__dict__ for r in results],
            "count": len(results),
            "estimated_tokens": len(results) * 200
        }

    @mcp.tool()
    def get_observations(ids: TypingList[str]) -> dict:
        """Layer 3: Get full details for specific memory IDs (~750 tokens/result). Most expensive.

        AUTOMATIC TRIGGERS - Call this when:
        - You have specific observation IDs and need complete details
        - After filtering with search_memory and memory_timeline
        - You need the full raw data of specific observations

        Returns complete observation data. Use ONLY for explicitly selected relevant items.
        This is the most expensive layer - filter first with search_memory.

        PARAMETERS:
        - ids: List of observation IDs from search_memory or memory_timeline
        """
        results = retriever.layer3_full_details(ids)
        
        return {
            "ids": ids,
            "observations": [r.__dict__ for r in results],
            "count": len(results),
            "estimated_tokens": len(results) * 750
        }

    @mcp.tool()
    def inject_context(
        session_id: str,
        query: Optional[str] = None,
        limit: int = 50
    ) -> dict:
        """Auto-inject relevant context from past sessions at any point during work.

        AUTOMATIC TRIGGERS - Call this when:
        - You need a refresher on past work mid-session
        - Starting work on a new subtask and want relevant context
        - User asks "what have we learned about X previously?"

        Retrieves up to 50 relevant observations from previous sessions.
        Unlike session_start (which auto-injects), you can call this mid-session.

        WORKFLOW POSITION: Call anytime you need past context, not just at session start.

        PARAMETERS:
        - session_id: Current session ID
        - query: What you want context about (optional - uses session focus if not provided)
        - limit: Max observations to inject (default: 50)
        """
        context = context_builder.build_session_start_context(session_id, query, limit)

        return {
            "session_id": session_id,
            "context_block": context,
            "observation_count": limit,
            "estimated_tokens": limit * 75
        }

    @mcp.tool()
    def session_recap(
        session_id: Optional[str] = None,
        limit: int = 3
    ) -> dict:
        """Get a synthesized recap of recent session knowledge (~150-250 tokens). Structured, not raw.

        AUTOMATIC TRIGGERS - Call this FIRST when:
        - Starting work to understand what happened in past sessions
        - User asks "what have we been working on?"
        - You want to see files touched, decisions made, next steps

        Returns STRUCTURED knowledge: files touched, decisions made, next steps,
        conventions discovered — NOT raw tool outputs.

        If you need more details on a specific topic AFTER reading the recap,
        call topic_context with a topic from the recap.

        PARAMETERS:
        - session_id: Optional specific session to recap (default: recent sessions)
        - limit: Max recent sessions to recap (default: 3)
        """
        if session_id:
            knowledge_entries = storage.get_knowledge(session_id)
        else:
            knowledge_entries = storage.get_knowledge(limit=limit)

        if not knowledge_entries:
            return {
                "quick_recap": "No synthesized knowledge from previous sessions found.",
                "sessions_recapped": 0,
                "message": "Call log_observation during work to build knowledge.",
                "estimated_tokens": 15,
            }

        # Build recap from knowledge entries
        recap_lines = []
        recap_lines.append("# Previous Sessions Recap")
        recap_lines.append("")

        all_next_steps = []
        all_decisions = []
        all_files = []

        for entry in knowledge_entries:
            knowledge_data = entry.get("knowledge", {})
            from .memory.knowledge_extractor import SessionKnowledge
            sk = SessionKnowledge.from_dict(knowledge_data)

            recap_lines.append(f"## Session: {entry['session_id'][:16]}")
            recap_lines.append(f"**Summary**: {sk.summary}")
            recap_lines.append("")

            if sk.files_touched:
                files = ", ".join(
                    f"{f['path']} ({f['action']})"
                    for f in sk.files_touched[:5]
                )
                recap_lines.append(f"**Files**: {files}")
                all_files.extend(sk.files_touched)
                recap_lines.append("")

            if sk.decisions_made:
                recap_lines.append("**Key Decisions**:")
                for d in sk.decisions_made[:3]:
                    recap_lines.append(f"- {d}")
                    all_decisions.append(d)
                recap_lines.append("")

            if sk.next_steps:
                recap_lines.append("**Next Steps**:")
                for n in sk.next_steps[:3]:
                    recap_lines.append(f"- {n}")
                    all_next_steps.append(n)
                recap_lines.append("")

        # Consolidated next steps
        if all_next_steps:
            recap_lines.append("## Consolidated Next Steps")
            for n in all_next_steps[:5]:
                recap_lines.append(f"- {n}")
            recap_lines.append("")

        recap_text = "\n".join(recap_lines)
        token_estimate = int(len(recap_text.split()) * 1.3)

        return {
            "quick_recap": recap_text,
            "sessions_recapped": len(knowledge_entries),
            "next_steps": all_next_steps[:5],
            "decisions_made": all_decisions[:5],
            "files_touched": all_files[:10],
            "estimated_tokens": token_estimate,
            "message": (
                f"Recapped {len(knowledge_entries)} session(s). "
                "Call topic_context(topic='X') for deep dive on a topic, "
                "or get_observations(ids=[...]) for raw observation details."
            ),
        }

    @mcp.tool()
    def topic_context(
        topic: str,
        session_id: Optional[str] = None
    ) -> dict:
        """Get detailed context about a specific topic from past sessions (~500-800 tokens). Deep dive.

        AUTOMATIC TRIGGERS - Call this AFTER session_recap when:
        - You need deep understanding of a specific topic
        - User asks about a specific area like "what do we know about storage?"
        - Example topics: 'storage', 'privacy', 'MCP', 'compression', 'caveman',
          'session_manager', or any file name/feature from the recap

        Returns detailed files, decisions, architecture notes, and conventions
        related to the topic — not just compressed tool outputs.

        PARAMETERS:
        - topic: Topic to get detailed context about (e.g., 'storage', 'privacy')
        - session_id: Optional specific session to search (default: all sessions)
        """
        # Get knowledge from relevant sessions
        if session_id:
            knowledge_entries = storage.get_knowledge(session_id)
        else:
            knowledge_entries = storage.get_knowledge(limit=10)

        if not knowledge_entries:
            return {
                "detailed_context": f"No knowledge found for topic: {topic}",
                "topic": topic,
                "message": "Call log_observation during work to build knowledge.",
                "estimated_tokens": 15,
            }

        # Search both knowledge AND observations for topic relevance
        from .memory.knowledge_extractor import SessionKnowledge

        context_parts = []
        context_parts.append(f"# Detailed Context: {topic}")
        context_parts.append("")

        relevant_found = False
        for entry in knowledge_entries:
            knowledge_data = entry.get("knowledge", {})
            sk = SessionKnowledge.from_dict(knowledge_data)

            # Check if topic is relevant to this session's knowledge
            topic_lower = topic.lower()
            all_text = (
                f"{sk.summary} "
                + " ".join(f['path'] for f in sk.files_touched) + " "
                + " ".join(f.get('reason', '') for f in sk.files_touched) + " "
                + " ".join(sk.decisions_made) + " "
                + " ".join(sk.conventions_found) + " "
                + " ".join(sk.architecture_notes) + " "
                + " ".join(sk.next_steps)
            ).lower()

            if topic_lower in all_text:
                relevant_found = True
                context_parts.append(f"## Session: {entry['session_id'][:16]}")
                context_parts.append(f"**Summary**: {sk.summary}")
                context_parts.append("")

                # Topic-related files
                topic_files = [
                    f for f in sk.files_touched
                    if topic_lower in f["path"].lower() or topic_lower in f.get("reason", "").lower()
                ]
                if topic_files:
                    context_parts.append("### Related Files")
                    for f in topic_files:
                        context_parts.append(f"- `{f['path']}` — {f['action']}: {f['reason']}")
                    context_parts.append("")

                # Topic-related decisions
                topic_decisions = [
                    d for d in sk.decisions_made
                    if topic_lower in d.lower()
                ]
                if topic_decisions:
                    context_parts.append("### Related Decisions")
                    for d in topic_decisions:
                        context_parts.append(f"- {d}")
                    context_parts.append("")

                # Architecture notes
                topic_arch = [
                    a for a in sk.architecture_notes
                    if topic_lower in a.lower()
                ]
                if topic_arch:
                    context_parts.append("### Architecture Notes")
                    for a in topic_arch:
                        context_parts.append(f"- {a}")
                    context_parts.append("")

                # Conventions
                topic_conventions = [
                    c for c in sk.conventions_found
                    if topic_lower in c.lower()
                ]
                if topic_conventions:
                    context_parts.append("### Conventions")
                    for c in topic_conventions:
                        context_parts.append(f"- {c}")
                    context_parts.append("")

        # Also search raw observations for the topic
        observations = storage.search_observations(query=topic, limit=10)
        if observations:
            context_parts.append("## Related Observations")
            context_parts.append(f"Found {len(observations)} observations mentioning '{topic}':")
            context_parts.append("")
            for obs in observations[:5]:
                title = obs.get("tool_name", "unknown")
                summary = obs.get("compressed_summary", "")
                context_parts.append(
                    f"- **{title}** (ID: {obs['id']}): {summary[:150]}"
                )
            context_parts.append("")

        if not relevant_found and not observations:
            return {
                "detailed_context": (
                    f"No knowledge or observations found related to '{topic}'. "
                    "Try a different topic, or call search_memory for raw text search."
                ),
                "topic": topic,
                "estimated_tokens": 25,
            }

        context_text = "\n".join(context_parts)
        token_estimate = int(len(context_text.split()) * 1.3)

        return {
            "detailed_context": context_text,
            "topic": topic,
            "sessions_searched": len(knowledge_entries),
            "observations_found": len(observations) if observations else 0,
            "estimated_tokens": token_estimate,
            "message": (
                f"Detailed context for '{topic}'. "
                "Call get_observations(ids=[...]) for full raw observation details."
            ),
        }

    @mcp.tool()
    def ingest_git_history(
        session_id: str,
        time_window_hours: int = 24,
        include_uncommitted: bool = True
    ) -> dict:
        """Auto-ingest session activity from git history. NO manual logging needed!

        AUTOMATIC TRIGGERS - Call this when:
        - You forgot to log observations during work
        - You want to reconstruct what happened in a past work session
        - Starting a session and want to capture recent code changes

        Scans git history to reconstruct session activity:
        - Modified/created/deleted files (from git status)
        - Commits made during the session (from git log)
        - Lines added/removed per file (from git diff)

        Works with ANY tool/agent (Qwen Code, Claude Code, manual edits)
        because it reads the actual codebase state, not tool call logs.

        After ingestion, call session_recap to see the synthesized knowledge.

        PARAMETERS:
        - session_id: Session identifier to create for this ingested session
        - time_window_hours: Hours to look back for commits (default: 24)
        - include_uncommitted: Include uncommitted changes (default: True)
        """
        from .memory.retrogit_ingest import retroactive_ingest as retro_ingest_fn

        result = retro_ingest_fn(
            session_id=session_id,
            time_window_hours=time_window_hours,
            include_uncommitted=include_uncommitted
        )

        # Save the synthesized knowledge
        if "knowledge" in result:
            try:
                storage.save_knowledge(session_id, result["knowledge"])
                result["knowledge_saved"] = True
            except Exception as e:
                result["knowledge_saved"] = False
                result["knowledge_error"] = str(e)

        return {
            "session_id": session_id,
            "files_found": result.get("files_found", []),
            "commits_found": result.get("commits_found", []),
            "observations_created": result.get("observations_created", 0),
            "knowledge_summary": result.get("knowledge_summary", ""),
            "knowledge_saved": result.get("knowledge_saved", False),
            "message": result.get("message", "Ingestion complete"),
            "estimated_tokens": result.get("observations_created", 0) * 75,
        }

    _memory_registered = True


def _ensure_runtime() -> None:
    """Pre-initialize the runtime so the first tool call isn't slow.

    This loads the embedding model, connects to the database, and warms
    up the vector store before any MCP tool is invoked.
    """
    try:
        get_runtime(_settings_path())
    except Exception:
        # If initialization fails, let individual tools handle it.
        pass


def _ensure_runtime_background() -> None:
    """Pre-initialize the runtime in a background thread.

    This allows the MCP server to respond to the `initialize` request
    immediately while the embedding model loads concurrently.
    """
    import threading
    t = threading.Thread(target=_ensure_runtime, daemon=True, name="openlmlib-runtime-prewarm")
    t.start()
    return t


def _check_active_sessions() -> Optional[str]:
    """Check if there are any active memory sessions.

    Returns a warning message if no sessions are active, None otherwise.
    """
    try:
        from .memory import SessionManager, MemoryStorage
        runtime = get_runtime(_settings_path())
        storage = MemoryStorage(runtime.conn)
        session_mgr = SessionManager(storage)
        active = session_mgr.get_active_sessions()
        if not active:
            return (
                "No active memory session detected. "
                "Consider calling session_start or start_research first "
                "to enable automatic context injection and knowledge tracking."
            )
        return None
    except Exception:
        return None  # If check fails, don't block the save


@mcp.tool()
def init_library() -> dict:
    """Initialize the OpenLMlib knowledge base. Call this ONCE before using any other tools.

    AUTOMATIC TRIGGERS - Call this when:
    - First time using OpenLMlib on a new machine or project
    - You get database errors suggesting the database doesn't exist
    - User asks to set up or initialize OpenLMlib

    DO NOT CALL for:
    - Normal tool usage (database already exists)
    - Each session start (initialization is permanent)

    This creates the SQLite database, vector index, and required directories.
    Safe to call multiple times - will skip if already initialized.
    """
    return init_library(_settings_path())


@mcp.tool()
def save_finding(
    project: str,
    claim: str,
    confidence: float = 0.8,
    evidence: Optional[List[str]] = None,
    reasoning: str = "",
    caveats: Optional[List[str]] = None,
    tags: Optional[List[str]] = None,
    full_text: str = "",
    proposed_by: str = "",
    finding_id: Optional[str] = None,
    confirm: bool = False,
) -> dict:
    """Save critical research findings, discoveries, and insights to persistent library.

    AUTOMATIC TRIGGERS - Call this when:
    - You discover important factual information during research
    - You complete an analysis with actionable insights
    - You find evidence supporting or refuting a hypothesis
    - You learn something new about the codebase or project
    - User shares important information that should be remembered

    DO NOT CALL for:
    - Temporary working notes
    - Process updates or progress reports
    - Conversation summaries
    - Tool execution results (unless they contain novel insights)

    WORKFLOW POSITION: Call after discovering insights, before ending session.
    Save findings as you go - don't wait until the end.

    READ-BEFORE-WRITE: This tool automatically checks for similar findings before saving.
    If a very similar finding exists (similarity > 0.90), it will be returned as a suggestion
    instead of saving a duplicate. Consider updating the existing finding instead.

    SESSION AWARENESS: For best results, use start_research or session_start before saving
    findings. This enables automatic context injection and session-based knowledge tracking.
    If no active session is detected, a warning will be returned.

    CONFIRMATION TIER: WRITE OPERATION - Requires confirm=True.
    This creates persistent data. Set confirm=true for final saves, confirm=false for drafts.

    PARAMETERS:
    - project: Project name for categorization (required)
    - claim: The finding/insight text (required) - be specific and actionable
    - confidence: Confidence level 0.0-1.0 (default: 0.8). Use 0.9 for definitive findings, 0.7 for tentative, 0.5 for hypotheses
    - evidence: Supporting evidence strings (optional) - quotes, data points, references
    - reasoning: Your reasoning behind the finding (optional but recommended)
    - caveats: Limitations or cave (optional)
    - tags: Tags for categorization (optional) - use consistent tags
    - confirm: Must be True to save (safety gate). Use False for drafts.

    TIP: If a similar finding already exists, consider updating it instead of creating a duplicate.
    Use search_findings first to check for duplicates.
    """
    import time
    from .usage_analytics import log_tool_call
    _t0 = time.monotonic()

    # Read-before-write: auto-check for similar findings before saving
    # This acts as a safety net - even if the model didn't search first,
    # it will see similar findings in the response and can decide to update instead
    _duplicate_check = search_fts(_settings_path(), claim, limit=3)
    _similar_findings = _duplicate_check.get("items", []) if _duplicate_check.get("status") == "ok" else []

    # Session enforcement: warn if no active memory session
    _session_warning = _check_active_sessions()

    try:
        result = add_finding(
            settings_path=_settings_path(),
            project=project,
            claim=claim,
            confidence=confidence,
            evidence=evidence,
            reasoning=reasoning,
            caveats=caveats,
            tags=tags,
            full_text=full_text,
            proposed_by=proposed_by,
            finding_id=finding_id,
            confirm=confirm,
            similar_findings=_similar_findings,
            session_warning=_session_warning,
        )
        _elapsed_ms = (time.monotonic() - _t0) * 1000
        # Log tool call for analytics
        try:
            _runtime = get_runtime(_settings_path())
            log_tool_call(
                conn=_runtime.conn,
                tool_name="save_finding",
                call_mode="automatic",  # Model decides based on discovery
                parameters={"project": project, "confidence": confidence},
                success=result.get("status") == "ok",
                error_message=result.get("message") if result.get("status") != "ok" else None,
                execution_time_ms=_elapsed_ms,
                result_summary=f"Saved finding: {claim[:80]}",
                triggered_by="discovery",
            )
        except Exception:
            pass  # Analytics logging should never break tool
        return result
    except Exception as exc:
        _elapsed_ms = (time.monotonic() - _t0) * 1000
        try:
            _runtime = get_runtime(_settings_path())
            log_tool_call(
                conn=_runtime.conn,
                tool_name="save_finding",
                call_mode="automatic",
                parameters={"project": project, "confidence": confidence},
                success=False,
                error_message=str(exc),
                execution_time_ms=_elapsed_ms,
                triggered_by="discovery",
            )
        except Exception:
            pass
        raise


@mcp.tool()
def list_findings(limit: int = 50, offset: int = 0) -> dict:
    """List recent findings in the library. Use for browsing, not targeted search.

    AUTOMATIC TRIGGERS - Call this when:
    - User asks to see all findings or browse the library
    - You want to get a sense of what's stored in the library
    - Checking library contents after initialization

    FOR TARGETED SEARCH, use search_findings or retrieve_findings instead.

    PARAMETERS:
    - limit: Max findings to return (default: 50, max: 200)
    - offset: Offset for pagination (default: 0)
    """
    return list_findings(_settings_path(), limit=limit, offset=offset)


@mcp.tool()
def get_finding(finding_id: str) -> dict:
    """Get a specific finding by its ID.

    AUTOMATIC TRIGGERS - Call this when:
    - You have a finding_id from search results or list
    - You need the full details of a specific finding
    - User references a specific finding ID

    Use search_findings first to find the ID if you don't have it.
    """
    return get_finding(_settings_path(), finding_id)


@mcp.tool()
def search_findings(query: str, limit: int = 10) -> dict:
    """Search findings using keyword (FTS5) search. Fast, exact keyword matching.

    AUTOMATIC TRIGGERS - Call this when:
    - Looking for findings containing specific keywords
    - You know the exact terms used in a finding
    - Quick lookup of stored knowledge

    WORKFLOW POSITION: Use FIRST for targeted keyword search. If results are insufficient,
    try retrieve_findings for semantic search that finds related concepts.

    CONFIRMATION TIER: READ OPERATION - No confirmation needed. Safe to call freely.

    SEARCH TIPS: Use specific keywords. FTS5 supports boolean operators:
    - "python web framework" finds all three words
    - "python AND web" finds both
    - "python OR javascript" finds either

    PARAMETERS:
    - query: Search query (keyword(s))
    - limit: Max results (default: 10)
    """
    return search_fts(_settings_path(), query, limit=limit)


@mcp.tool()
def retrieve_findings(
    query: str,
    project: Optional[str] = None,
    tags: Optional[List[str]] = None,
    created_after: Optional[str] = None,
    created_before: Optional[str] = None,
    confidence_min: Optional[float] = None,
    semantic_k: Optional[int] = None,
    lexical_k: Optional[int] = None,
    final_k: Optional[int] = None,
) -> dict:
    """Run intelligent retrieval combining semantic similarity and keyword matching.

    AUTOMATIC TRIGGERS - Call this when:
    - Keyword search (search_fts) didn't find relevant results
    - Looking for findings related to a concept or topic
    - You need the most relevant findings for a research question
    - Broad exploration of what knowledge exists

    WORKFLOW POSITION: Use AFTER search_fts returns insufficient results.
    This tool automatically combines semantic (meaning-based) and lexical (keyword) search.

    CONFIRMATION TIER: READ OPERATION - No confirmation needed. Safe to call freely.

    PARAMETERS:
    - query: Search query (required) - describe what you're looking for
    - project: Filter by project name (optional)
    - tags: Filter by tags (optional)
    - confidence_min: Minimum confidence 0.0-1.0 (optional) - filter low-confidence findings
    - final_k: Number of results to return (optional, default: 10)

    ADVANCED: semantic_k and lexical_k control how many candidates are fetched
    before reranking. Usually not needed - use final_k instead.
    """
    return retrieve_findings(
        settings_path=_settings_path(),
        query=query,
        project=project,
        tags=tags,
        created_after=created_after,
        created_before=created_before,
        confidence_min=confidence_min,
        semantic_k=semantic_k,
        lexical_k=lexical_k,
        final_k=final_k,
    )


@mcp.tool()
def retrieve_context(
    query: str,
    project: Optional[str] = None,
    tags: Optional[List[str]] = None,
    confidence_min: Optional[float] = None,
    final_k: Optional[int] = None,
) -> dict:
    """Retrieve findings and return them in a sanitized format safe for LLM context.

    AUTOMATIC TRIGGERS - Call this when:
    - You need to inject findings into your context for reasoning
    - Building a knowledge base context for analysis
    - You want findings formatted safely without injection risks

    DIFFERENCE from retrieve_findings: This returns a sanitized context block
    optimized for safe inclusion in LLM prompts. Use retrieve for raw data.

    ERROR RECOVERY: If this returns no results, try search_findings for keyword-based
    search instead - the semantic query may not match any findings.

    PARAMETERS:
    - query: Search query (required)
    - project: Filter by project (optional)
    - tags: Filter by tags (optional)
    - confidence_min: Minimum confidence (optional)
    - final_k: Number of results (optional, default: 10)
    """
    return retrieve_prompt_context(
        settings_path=_settings_path(),
        query=query,
        project=project,
        tags=tags,
        confidence_min=confidence_min,
        final_k=final_k,
    )


@mcp.tool()
def search_knowledge(query: str, limit: int = 10) -> dict:
    """Search findings using both semantic similarity and keyword matching. Automatically combines both approaches for best results.

    AUTOMATIC TRIGGERS - Call this when:
    - You need to search for existing knowledge
    - Starting research or looking for past findings
    - Not sure whether to use keyword or semantic search

    This tool handles routing internally - no need to choose between
    search_findings and retrieve_findings.

    For broad exploration, use general query terms. For specific facts,
    use exact phrases or keywords.

    CONFIRMATION TIER: READ OPERATION - No confirmation needed. Safe to call freely.

    PARAMETERS:
    - query: Search query (required) - keywords or natural language
    - limit: Max results (default: 10)

    Returns combined results from both FTS keyword search and semantic retrieval.
    """
    # Run both keyword and semantic search
    keyword_results = search_fts(_settings_path(), query, limit=limit)
    semantic_results = None
    try:
        semantic_results = retrieve_findings(
            _settings_path(),
            query=query,
            final_k=limit,
        )
    except Exception:
        pass  # If semantic search fails, fall back to keyword only

    # Merge and deduplicate results
    all_items = []
    seen_ids = set()

    # Add keyword results first (higher precision for exact matches)
    for item in keyword_results.get("items", []):
        item_id = item.get("id")
        if item_id and item_id not in seen_ids:
            item["source"] = "keyword"
            all_items.append(item)
            seen_ids.add(item_id)

    # Add semantic results (better for concept matching)
    for item in (semantic_results.get("items", []) if semantic_results else []):
        item_id = item.get("id")
        if item_id and item_id not in seen_ids:
            item["source"] = "semantic"
            all_items.append(item)
            seen_ids.add(item_id)

    return {
        "status": "ok",
        "query": query,
        "items": all_items[:limit],
        "total_found": len(all_items),
        "keyword_count": keyword_results.get("count", 0),
        "semantic_count": semantic_results.get("meta", {}).get("total", 0) if semantic_results else 0,
        "message": f"Found {len(all_items)} unique findings from combined keyword and semantic search"
    }


@mcp.tool()
def delete_finding(finding_id: str, confirm: bool = False) -> dict:
    """Delete a finding by ID. DESTRUCTIVE - use with caution.

    AUTOMATIC TRIGGERS - Call this when:
    - User explicitly asks to delete a specific finding
    - A finding is clearly incorrect or outdated

    DO NOT CALL for:
    - Cleaning up duplicates (update instead)
    - Without explicit user confirmation

    CONFIRMATION TIER: DESTRUCTIVE - Requires explicit confirm=True with user approval.
    This operation is PERMANENT and cannot be undone. Always warn the user before calling.

    SAFETY: Requires confirm=True to prevent accidental deletion.
    The finding is permanently removed.

    PARAMETERS:
    - finding_id: ID of the finding to delete (required)
    - confirm: Must be True to delete (safety gate)
    """
    return delete_finding(_settings_path(), finding_id, confirm=confirm)


@mcp.tool()
def health() -> dict:
    """Check OpenLMlib database and vector index health.

    AUTOMATIC TRIGGERS - Call this when:
    - Debugging tool errors or unexpected behavior
    - User asks about the system status
    - Verifying initialization succeeded

    Returns database size, finding count, vector index status.
    """
    return health(_settings_path())


@mcp.tool()
def evaluate_retrieval(dataset_path: str = "config/eval_queries.json", final_k: int = 10) -> dict:
    """Run retrieval evaluation metrics on a test dataset. For developers testing improvements.

    AUTOMATIC TRIGGERS - Call this when:
    - Evaluating retrieval quality after configuration changes
    - Running the evaluation pipeline
    - Measuring recall/precision of the search system

    This is a development/evaluation tool, not needed for normal usage.

    PARAMETERS:
    - dataset_path: Path to JSON file with test queries (default: config/eval_queries.json)
    - final_k: Number of results per query to evaluate (default: 10)
    """
    return evaluate_dataset(
        settings_path=_settings_path(),
        dataset_path=Path(dataset_path),
        final_k=final_k,
    )


@mcp.tool()
def start_research(
    session_id: str,
    topic: str,
    user_id: Optional[str] = None,
    limit: int = 50
) -> dict:
    """Begin a complete research session with automatic context loading. COMPOSITE TOOL.

    AUTOMATIC TRIGGERS - Call this when:
    - Starting any research task or investigation
    - User asks to "research" or "look into" something
    - Beginning work on a new topic area

    This replaces calling session_start + search_findings separately.
    It handles session creation, context injection, and initial finding search in one step.

    WORKFLOW: After this returns, proceed with research and call save_finding
    for important discoveries. When done, call session_end.

    PARAMETERS:
    - session_id: Unique session identifier for this research session
    - topic: What you'll be researching (used to find relevant past context and search findings)
    - user_id: Optional user/agent identifier
    - limit: Max past observations to inject (default: 50)

    Returns session info, injected context, and any existing findings on the topic.
    """
    # Step 1: Start session and inject past context
    session_result = None
    try:
        session_mgr_for_workflow = __import__('openlmlib.memory', fromlist=['SessionManager']).SessionManager(
            __import__('openlmlib.memory', fromlist=['MemoryStorage']).MemoryStorage(
                get_runtime(_settings_path()).conn
            )
        )
        session_result = session_mgr_for_workflow.on_session_start(session_id, user_id, topic)
    except Exception:
        pass  # Session may already exist - continue anyway

    # Step 2: Search existing findings on the topic
    existing_findings = search_fts(_settings_path(), topic, limit=10)

    return {
        "session_id": session_id,
        "session_started": session_result is not None,
        "topic": topic,
        "existing_findings": existing_findings,
        "finding_count": existing_findings.get("count", 0),
        "next_steps": [
            "Proceed with research (web search, code analysis, etc.)",
            "Call save_finding for important discoveries",
            "Call session_end when research is complete"
        ]
    }


@mcp.tool()
def end_session(
    session_id: str,
    export_to_library: bool = True,
    project: Optional[str] = None,
) -> dict:
    """Gracefully end the current session with automatic knowledge preservation. COMPOSITE TOOL.

    AUTOMATIC TRIGGERS - Call this when:
    - User indicates work is done ("done", "finished", "ending session")
    - Research or analysis is complete
    - About to start unrelated work

    This combines: session_end (saves summary) + optional artifact export.
    ALWAYS call this when user indicates work is done to prevent knowledge loss.

    WORKFLOW POSITION: Last tool in any research/analysis workflow.

    PARAMETERS:
    - session_id: The session to end (track from start_research or session_start)
    - export_to_library: If True, also search for recent findings to persist (default: True)
    - project: Project name for any exported findings (optional)

    Returns session end status and export results.
    """
    # Step 1: End session and generate summary
    end_result = None
    try:
        from .memory import SessionManager, MemoryStorage
        runtime = get_runtime(_settings_path())
        storage = MemoryStorage(runtime.conn)
        session_mgr_end = SessionManager(storage)
        end_result = session_mgr_end.on_session_end(session_id)
    except Exception as e:
        return {
            "session_id": session_id,
            "status": "error",
            "error": str(e),
            "message": "Failed to end session"
        }

    # Step 2: List recent findings for potential export
    recent_findings = None
    if export_to_library:
        recent_findings = list_findings(_settings_path(), limit=20)

    # Build response with warning if no observations
    obs_count = end_result.get("observation_count", 0)
    message = "Session ended and knowledge preserved"
    if obs_count == 0:
        message = (
            "Session ended but no observations were logged. "
            "Consider calling log_observation during work to build session memory."
        )

    return {
        "session_id": session_id,
        "status": "completed",
        "summary_generated": end_result.get("summary_generated", False),
        "observation_count": obs_count,
        "recent_findings_count": recent_findings.get("count", 0) if recent_findings else 0,
        "message": message,
    }


@mcp.tool()
def check_context(query: str, project: Optional[str] = None) -> dict:
    """Quick check if relevant context exists before starting work. CONVENIENCE TOOL.

    AUTOMATIC TRIGGERS - Call this at the start of ANY new task to determine
    whether you have existing knowledge to build upon.

    This is a convenience wrapper around search_fts that returns a simple
    yes/no with relevant finding count and top topics.

    WORKFLOW POSITION: First tool to call when starting any task.

    CONFIRMATION TIER: READ OPERATION - No confirmation needed. Safe to call freely.

    PARAMETERS:
    - query: What you're about to work on
    - project: Filter by project (optional)

    Returns: {has_context: bool, finding_count: int, top_findings: []}
    """
    results = search_fts(_settings_path(), query, limit=5)
    findings = results.get("findings", [])

    # Extract top topics/tags
    top_topics = []
    for f in findings[:3]:
        claim = f.get("claim", "")[:100]
        top_topics.append(claim)

    return {
        "has_context": len(findings) > 0,
        "finding_count": results.get("count", 0),
        "top_findings": top_topics,
        "recommendation": "Existing knowledge found - review before doing fresh research" if findings else "No existing knowledge - proceed with fresh research"
    }


@mcp.tool()
def save_finding_auto(
    project: str,
    claim: str,
    confidence: Optional[float] = None,
    evidence: Optional[List[str]] = None,
    reasoning: str = "",
    caveats: Optional[List[str]] = None,
    tags: Optional[List[str]] = None,
    confirm: bool = False,
) -> dict:
    """Convenience wrapper for saving findings with automatic confidence scoring.

    AUTOMATIC TRIGGERS - Call this whenever you discover something important.
    Use when you think 'this is important' or 'this should be remembered'.

    Automatically sets confidence based on claim language:
    - 0.9 for definitive findings (factual, certain claims)
    - 0.7 for tentative findings (contains words like 'might', 'possibly', 'appears', 'suggests')
    - Uses provided confidence if explicitly set

    READ-BEFORE-WRITE: This tool automatically checks for similar findings before saving.
    If a very similar finding exists, it will be returned as a suggestion.

    CONFIRMATION TIER: WRITE OPERATION - Requires confirm=True.
    This creates persistent data. Set confirm=true for final saves.

    PARAMETERS:
    - project: Project name (required)
    - claim: The finding text (required)
    - confidence: Optional override (default: auto-scored 0.9 for definitive, 0.7 for tentative)
    - evidence: Supporting evidence (optional)
    - reasoning: Your reasoning (optional but recommended)
    - caveats: Limitations or cave (optional)
    - tags: Tags for categorization (optional)
    - confirm: Must be True to save (safety gate)
    """
    # Auto-score confidence if not provided
    if confidence is None:
        # Heuristic: tentative findings contain uncertainty markers
        _tentative_markers = ["might", "could", "possibly", "likely", "appears",
                             "seems", "tentative", "preliminary", "hypothesis",
                             "suggests", "potential", "uncertain"]
        _claim_lower = claim.lower()
        if any(marker in _claim_lower for marker in _tentative_markers):
            confidence = 0.7  # Tentative finding
        else:
            confidence = 0.9  # Definitive finding

    # Read-before-write: auto-check for similar findings (safety net)
    _duplicate_check = search_fts(_settings_path(), claim, limit=3)
    _similar_findings = _duplicate_check.get("items", []) if _duplicate_check.get("status") == "ok" else []

    return add_finding(
        settings_path=_settings_path(),
        project=project,
        claim=claim,
        confidence=confidence,
        evidence=evidence,
        reasoning=reasoning,
        caveats=caveats,
        tags=tags,
        confirm=confirm,
        similar_findings=_similar_findings,
    )


@mcp.tool()
def help_library(tool_name: Optional[str] = None) -> dict:
    """Get help about all OpenLMlib MCP tools or a specific tool.

    Call this with no arguments to see all available tools organized by category.
    Call with a specific tool_name to get detailed usage instructions.

    Args:
        tool_name: Optional specific tool name to get help for
                   (e.g., 'save_finding', 'create_session')

    Returns:
        Dict with tool descriptions and usage information
    """
    core_tools = {
        "init_library": {
            "description": "Initialize the OpenLMlib knowledge base. Call ONCE before first use.",
            "args": {},
            "returns": "Dict with initialization status",
        },
        "save_finding": {
            "description": "Save critical research findings, discoveries, and insights. Auto-trigger when discovering important information.",
            "args": {
                "project": "Project name (required)",
                "claim": "The finding/insight text (required)",
                "confidence": "Confidence 0.0-1.0 (default: 0.8). 0.9=definitive, 0.7=tentative",
                "evidence": "Optional list of evidence strings",
                "reasoning": "Reasoning behind the finding",
                "caveats": "Optional list of caveats",
                "tags": "Optional tags for categorization",
                "full_text": "Full text of the finding",
                "proposed_by": "Who proposed this finding",
                "finding_id": "Optional specific finding ID",
                "confirm": "Must be True for writes (safety)",
            },
            "returns": "Dict with finding info",
        },
        "list_findings": {
            "description": "List recent findings. Use for browsing, not targeted search.",
            "args": {
                "limit": "Max findings to return (default: 50)",
                "offset": "Offset for pagination (default: 0)",
            },
            "returns": "Dict with list of findings",
        },
        "get_finding": {
            "description": "Get a specific finding by its ID.",
            "args": {
                "finding_id": "ID of the finding to retrieve",
            },
            "returns": "Dict with finding details",
        },
        "search_findings": {
            "description": "Search findings using keyword (FTS5) search. Fast, exact keyword matching.",
            "args": {
                "query": "Search query (keyword(s))",
                "limit": "Max results (default: 10)",
            },
            "returns": "Dict with matching findings",
        },
        "retrieve_findings": {
            "description": "Intelligent retrieval combining semantic similarity and keyword matching.",
            "args": {
                "query": "Search query (required)",
                "project": "Filter by project (optional)",
                "tags": "Filter by tags (optional)",
                "confidence_min": "Minimum confidence score (optional)",
                "final_k": "Final number of results (optional)",
            },
            "returns": "Dict with retrieved findings",
        },
        "retrieve_context": {
            "description": "Retrieve findings in sanitized format safe for LLM context.",
            "args": {
                "query": "Search query (required)",
                "project": "Filter by project (optional)",
                "tags": "Filter by tags (optional)",
                "confidence_min": "Minimum confidence (optional)",
                "final_k": "Number of results (optional)",
            },
            "returns": "Dict with sanitized context",
        },
        "delete_finding": {
            "description": "Delete a finding by ID. DESTRUCTIVE - use with caution.",
            "args": {
                "finding_id": "ID of the finding to delete",
                "confirm": "Must be True to delete (safety)",
            },
            "returns": "Dict with deletion status",
        },
        "health": {
            "description": "Check database and vector index health.",
            "args": {},
            "returns": "Dict with health status",
        },
        "evaluate_retrieval": {
            "description": "Run retrieval evaluation metrics. For developers.",
            "args": {
                "dataset_path": "Path to dataset file (default: 'config/eval_queries.json')",
                "final_k": "Number of results (default: 10)",
            },
            "returns": "Dict with evaluation metrics",
        },
        "start_research": {
            "description": "COMPOSITE: Begin a complete research session with context loading. Replaces session_start + search.",
            "args": {
                "session_id": "Unique session identifier",
                "topic": "What you'll be researching",
                "user_id": "Optional user/agent identifier",
                "limit": "Max observations to inject (default: 50)",
            },
            "returns": "Dict with session info, context, and existing findings",
        },
        "end_session": {
            "description": "COMPOSITE: Gracefully end session with knowledge preservation. Replaces session_end + export.",
            "args": {
                "session_id": "The session to end",
                "export_to_library": "Also export findings (default: True)",
                "project": "Project name for exported findings (optional)",
            },
            "returns": "Dict with session end status and export results",
        },
        "check_context": {
            "description": "CONVENIENCE: Quick check if relevant context exists before starting work.",
            "args": {
                "query": "What you're about to work on",
                "project": "Filter by project (optional)",
            },
            "returns": "Dict with has_context, finding_count, and top findings",
        },
        "save_finding_auto": {
            "description": "CONVENIENCE: Save finding with automatic confidence scoring. Use when discovering something important.",
            "args": {
                "project": "Project name (required)",
                "claim": "The finding text (required)",
                "confidence": "Optional override (default: 0.9)",
                "evidence": "Supporting evidence (optional)",
                "reasoning": "Your reasoning (optional)",
                "caveats": "Limitations (optional)",
                "tags": "Tags for categorization (optional)",
                "confirm": "Must be True to save (safety)",
            },
            "returns": "Dict with finding info",
        },
    }

    collab_tools_summary = {
        "create_session": "Create a new collaboration session for multi-agent research.",
        "join_session": "Join an existing collaboration session.",
        "list_sessions": "List collaboration sessions.",
        "get_session_state": "Get the current state of a collaboration session for a joined agent.",
        "update_session_state": "Update the session state (orchestrator only).",
        "send_message": "Send a message to a collaboration session.",
        "read_messages": "Read new messages from a joined session (offset-based).",
        "poll_messages": "Wait for new messages with timeout (AUTONOMOUS LOOP - use for continuous agent communication).",
        "tail_messages": "Read the last N messages from a joined session (quick status check).",
        "read_message_range": "Read messages in a specific sequence range from a joined session.",
        "grep_messages": "Search messages in a joined session by keyword.",
        "session_context": "Get a compiled context view of the session (PRIMARY tool for understanding session state).",
        "save_artifact": "Save a research artifact (finding, analysis, summary) to the session.",
        "list_artifacts": "List artifacts in a joined session.",
        "get_artifact": "Get the full content of a specific artifact from a joined session.",
        "grep_artifacts": "Search artifact content in a joined session by keyword.",
        "leave_session": "Leave a collaboration session gracefully.",
        "terminate_session": "Terminate and complete a collaboration session (orchestrator only).",
        "export_to_library": "Export session artifacts as findings in the main OpenLMLib library.",
        "list_templates": "List available session templates for quick session creation.",
        "get_template": "Get details of a specific session template.",
        "create_from_template": "Create a session from a predefined template.",
        "get_agent_sessions": "Get all sessions the requesting agent has participated in.",
        "sessions_summary": "Get a summary of active sessions joined by the requesting agent.",
        "search_sessions": "Search joined sessions by message content using FTS5.",
        "session_relationships": "Find sessions related to a joined session.",
        "session_statistics": "Get detailed statistics for a joined session.",
        "list_models": "List available models from OpenRouter API.",
        "get_model_details": "Get detailed information about a specific OpenRouter model.",
        "recommended_models": "Get recommended OpenRouter models for a specific task type.",
        "help_collab": "Get help about collab MCP tools.",
    }

    memory_tools = {
        "session_start": "Start a new session and auto-inject relevant context from past sessions.",
        "session_end": "End a session and trigger automatic summarization.",
        "log_observation": "Log an observation from tool execution to build session memory.",
        "search_memory": "Layer 1: Lightweight search of memory index (~75 tokens/result).",
        "memory_timeline": "Layer 2: Get chronological context for memory IDs (~200 tokens/result).",
        "get_observations": "Layer 3: Get full details for specific memory IDs (~750 tokens/result).",
        "inject_context": "Auto-inject relevant context at any point during work.",
        "session_recap": "Get synthesized recap of recent sessions. Call FIRST for structured knowledge.",
        "topic_context": "Get detailed context about a specific topic. Call AFTER quick recap.",
        "ingest_git_history": "Auto-ingest session activity from git history. No manual logging needed!",
    }

    if tool_name:
        if tool_name in core_tools:
            return {"tool": tool_name, **core_tools[tool_name]}
        elif tool_name in collab_tools_summary:
            return {
                "tool": tool_name,
                "description": collab_tools_summary[tool_name],
                "note": f"Use help_collab(tool_name='{tool_name}') for detailed usage information",
            }
        elif tool_name in memory_tools:
            return {
                "tool": tool_name,
                "description": memory_tools[tool_name],
                "category": "Memory Injection",
            }
        else:
            return {
                "error": f"Tool '{tool_name}' not found",
                "available_core_tools": sorted(core_tools.keys()),
                "available_collab_tools": sorted(collab_tools_summary.keys()),
                "available_memory_tools": sorted(memory_tools.keys()),
            }

    return {
        "description": "OpenLMlib MCP Server - Knowledge management and multi-agent collaboration tools",
        "categories": {
            "Core Library Tools": {
                "description": "Manage findings in the OpenLMlib knowledge base (14 tools including composite and convenience tools)",
                "tools": {name: info["description"] for name, info in core_tools.items()},
            },
            "Memory Injection Tools": {
                "description": "Lifecycle-based memory management with progressive disclosure and retroactive git ingestion (10 tools)",
                "tools": memory_tools,
                "note": "Use help_library(tool_name='memory_<tool>') for detailed usage",
            },
            "CollabSession Tools": {
                "description": "Multi-agent collaboration session management (30 tools)",
                "summary": collab_tools_summary,
                "note": "Use help_collab() for detailed collab tool documentation",
            },
        },
        "usage": [
            "Call help_library(tool_name='<tool>') for detailed usage of a core tool",
            "Call help_library(tool_name='memory_<tool>') for memory tool usage",
            "Call help_collab(tool_name='<tool>') for detailed usage of a collab tool",
            "WORKFLOW TIP: Use start_research and end_session for common research patterns",
        ],
    }


@mcp.tool()
def get_usage_analytics(days: int = 7, tool_name: Optional[str] = None) -> dict:
    """Get tool usage analytics and optimization metrics. For developers and optimization tracking.

    AUTOMATIC TRIGGERS - Call this when:
    - Measuring optimization effectiveness after tool description changes
    - Tracking automatic vs explicit tool call rates
    - Monitoring parameter hallucination rates
    - Evaluating tool selection accuracy
    - Running A/B tests on tool descriptions

    Returns metrics for:
    - Automatic call rate (% of calls the model made without explicit instruction)
    - Tool selection accuracy (% of correct tool choices)
    - Parameter hallucination rate (% of parameters that needed correction)
    - Workflow completeness (% of workflow steps completed)
    - Per-tool usage breakdown

    PARAMETERS:
    - days: Look back N days (default: 7)
    - tool_name: Filter by specific tool (optional)

    This is a development/evaluation tool, not needed for normal usage.
    """
    from .usage_analytics import (
        get_automatic_call_rate,
        get_tool_selection_accuracy,
        get_parameter_hallucination_rate,
        get_workflow_completeness,
        get_tool_usage_summary,
        get_full_analytics_report,
    )

    try:
        runtime = get_runtime(_settings_path())
        conn = runtime.conn

        if tool_name:
            # Per-tool report
            tool_summary = get_tool_usage_summary(conn, tool_name=tool_name, days=days)
            auto_rate = get_automatic_call_rate(conn, tool_name=tool_name, days=days)
            return {
                "status": "ok",
                "tool_name": tool_name,
                "period_days": days,
                "usage_summary": tool_summary,
                "automatic_call_rate": auto_rate,
            }
        else:
            # Full report
            report = get_full_analytics_report(conn, days=days)
            tool_summary = get_tool_usage_summary(conn, days=days)
            return {
                "status": "ok",
                "period_days": days,
                "report": report,
                "tool_summary": tool_summary,
            }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
            "note": "Analytics may not be available if database is not initialized",
        }


def main() -> None:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="OpenLMlib MCP Server", add_help=False)
    parser.add_argument("--dir", type=str, help="Base directory of the OpenLMlib project")
    parser.add_argument("--settings", type=str, help="Absolute path to settings.json")

    args, unknown = parser.parse_known_args()

    if args.settings:
        os.environ["OPENLMLIB_SETTINGS"] = args.settings
    elif args.dir:
        os.environ["OPENLMLIB_SETTINGS"] = str(Path(args.dir) / "config" / "settings.json")

    sys.argv = [sys.argv[0]] + unknown

    # Register memory tools (lazy-loaded to avoid import penalty)
    _register_memory_tools()

    # Register collab tools just before the server starts (not at import time).
    # This avoids the heavy collab module import penalty during Python startup.
    _register_collab_tools()

    # Start runtime pre-warming in background so the server can respond to
    # `initialize` immediately. The embedding model loads concurrently.
    _ensure_runtime_background()

    mcp.run()


if __name__ == "__main__":
    main()
