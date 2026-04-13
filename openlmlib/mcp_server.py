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
        collab_add_artifact,
        collab_create_session,
        collab_create_session_from_template,
        collab_export_to_library,
        collab_get_active_sessions_summary,
        collab_get_agent_sessions,
        collab_get_artifact,
        collab_get_openrouter_model_details,
        collab_get_recommended_models,
        collab_get_session_context,
        collab_get_session_relationships,
        collab_get_session_state,
        collab_get_session_statistics,
        collab_get_template,
        collab_grep_artifacts,
        collab_grep_messages,
        collab_help as collab_help,
        collab_join_session,
        collab_leave_session,
        collab_list_artifacts,
        collab_list_openrouter_models,
        collab_list_sessions,
        collab_list_templates,
        collab_poll_messages,
        collab_read_message_range,
        collab_read_messages,
        collab_search_sessions,
        collab_send_message,
        collab_tail_messages,
        collab_terminate_session,
        collab_update_session_state,
    )

    mcp.tool()(collab_create_session)
    mcp.tool()(collab_join_session)
    mcp.tool()(collab_list_sessions)
    mcp.tool()(collab_get_session_state)
    mcp.tool()(collab_update_session_state)
    mcp.tool()(collab_send_message)
    mcp.tool()(collab_read_messages)
    mcp.tool()(collab_poll_messages)
    mcp.tool()(collab_tail_messages)
    mcp.tool()(collab_read_message_range)
    mcp.tool()(collab_grep_messages)
    mcp.tool()(collab_get_session_context)
    mcp.tool()(collab_add_artifact)
    mcp.tool()(collab_list_artifacts)
    mcp.tool()(collab_get_artifact)
    mcp.tool()(collab_grep_artifacts)
    mcp.tool()(collab_leave_session)
    mcp.tool()(collab_terminate_session)
    mcp.tool()(collab_export_to_library)
    mcp.tool()(collab_list_templates)
    mcp.tool()(collab_get_template)
    mcp.tool()(collab_create_session_from_template)
    mcp.tool()(collab_get_agent_sessions)
    mcp.tool()(collab_get_active_sessions_summary)
    mcp.tool()(collab_search_sessions)
    mcp.tool()(collab_get_session_relationships)
    mcp.tool()(collab_get_session_statistics)
    mcp.tool()(collab_list_openrouter_models)
    mcp.tool()(collab_get_openrouter_model_details)
    mcp.tool()(collab_get_recommended_models)
    mcp.tool()(collab_help)

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
    def memory_session_start(
        session_id: str,
        user_id: Optional[str] = None,
        query: Optional[str] = None,
        limit: int = 50
    ) -> dict:
        """Start a new session and inject relevant context from previous sessions.
        
        Call this when beginning work to load knowledge from past sessions.
        Returns context block with up to 50 relevant observations (compressed with caveman ultra).
        
        Args:
            session_id: Unique session identifier
            user_id: Optional user/agent identifier
            query: Optional initial query to filter relevant memories
            limit: Max observations to inject (default: 50)
        
        Returns:
            Dict with session_id, context_block, and observation_count
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
    def memory_session_end(session_id: str) -> dict:
        """End a session and trigger summarization.
        
        Call this when finishing work to summarize and persist session knowledge.
        Automatically generates a compressed summary of all observations.
        
        Args:
            session_id: Session identifier to end
        
        Returns:
            Dict with session_id, status, and summary info
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
    def memory_log_observation(
        session_id: str,
        tool_name: str,
        tool_input: str,
        tool_output: str
    ) -> dict:
        """Log an observation from tool execution.
        
        Captures tool outputs for future memory retrieval.
        Call this after important tool executions to build session memory.
        
        Args:
            session_id: Active session identifier
            tool_name: Tool that was executed (e.g., "Read", "Edit")
            tool_input: Tool input
            tool_output: Tool output
        
        Returns:
            Dict with observation_id and status
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
    def memory_search(
        query: str,
        limit: int = 50,
        filters: Optional[dict] = None
    ) -> dict:
        """Layer 1: Search memory index (lightweight, ~75 tokens/result).
        
        Returns compact metadata for filtering. Use this first to identify relevant memories.
        Token-efficient: ~75 tokens per result vs ~750 for full details.
        
        Args:
            query: Search query
            limit: Max results to return (default: 50)
            filters: Optional filters (tool_name, obs_type, session_id)
        
        Returns:
            Dict with results (list of MemoryIndex), count, and estimated_tokens
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
        
        Returns narrative flow around observations. Use after memory_search to understand sequence.
        Provides timeline context for how observations relate to each other.
        
        Args:
            ids: List of observation IDs from memory_search
            window: Time window for context (not yet implemented)
        
        Returns:
            Dict with timeline entries and estimated_tokens
        """
        results = retriever.layer2_timeline(ids, window)
        
        return {
            "ids": ids,
            "timeline": [r.__dict__ for r in results],
            "count": len(results),
            "estimated_tokens": len(results) * 200
        }

    @mcp.tool()
    def memory_get_observations(ids: TypingList[str]) -> dict:
        """Layer 3: Get full details for specific memory IDs (~750 tokens/result).
        
        Returns complete observation data. Use only for explicitly selected relevant items.
        Most expensive layer - use after filtering with memory_search and memory_timeline.
        
        Args:
            ids: List of observation IDs from memory_search or memory_timeline
        
        Returns:
            Dict with full observation details and estimated_tokens
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
        query: Optional[str] = None,
        limit: int = 50
    ) -> dict:
        """Auto-inject relevant context at session start.

        Retrieves up to 50 relevant observations from previous sessions.
        Primary entry point for memory injection with caveman ultra compression.

        Args:
            session_id: Current session ID
            query: Optional query to filter relevant memories
            limit: Max observations to inject (default: 50)

        Returns:
            Dict with context_block, observation_count, and estimated_tokens
        """
        context = context_builder.build_session_start_context(session_id, query, limit)

        return {
            "session_id": session_id,
            "context_block": context,
            "observation_count": limit,
            "estimated_tokens": limit * 75
        }

    @mcp.tool()
    def memory_quick_recap(
        session_id: Optional[str] = None,
        limit: int = 3
    ) -> dict:
        """Get a synthesized recap of recent session knowledge (~150-250 tokens).

        Call this FIRST when starting work to understand what happened in past sessions.
        Returns structured knowledge: files touched, decisions made, next steps,
        conventions discovered — not raw tool outputs.

        If you need more details on a specific topic after reading the recap,
        call memory_detailed_context with a topic from the recap.

        Args:
            session_id: Optional specific session to recap (default: recent sessions)
            limit: Max recent sessions to recap (default: 3)

        Returns:
            Dict with quick_recap text, session summaries, and next steps
        """
        if session_id:
            knowledge_entries = storage.get_knowledge(session_id)
        else:
            knowledge_entries = storage.get_knowledge(limit=limit)

        if not knowledge_entries:
            return {
                "quick_recap": "No synthesized knowledge from previous sessions found.",
                "sessions_recapped": 0,
                "message": "Call memory_log_observation during work to build knowledge.",
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
                "Call memory_detailed_context(topic='X') for deep dive on a topic, "
                "or memory_get_observations(ids=[...]) for raw observation details."
            ),
        }

    @mcp.tool()
    def memory_detailed_context(
        topic: str,
        session_id: Optional[str] = None
    ) -> dict:
        """Get detailed context about a specific topic from past sessions (~500-800 tokens).

        Call this AFTER memory_quick_recap when you need deep understanding of a topic.
        Example topics: 'storage', 'privacy', 'MCP', 'compression', 'caveman',
        'session_manager', or any file name/feature from the recap.

        Returns detailed files, decisions, architecture notes, and conventions
        related to the topic — not just compressed tool outputs.

        Args:
            topic: Topic to get detailed context about (e.g., 'storage', 'privacy')
            session_id: Optional specific session to search (default: all sessions)

        Returns:
            Dict with detailed context text and related knowledge
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
                "message": "Call memory_log_observation during work to build knowledge.",
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
                    "Try a different topic, or call memory_search for raw text search."
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
                "Call memory_get_observations(ids=[...]) for full raw observation details."
            ),
        }

    @mcp.tool()
    def memory_retroactive_ingest(
        session_id: str,
        time_window_hours: int = 24,
        include_uncommitted: bool = True
    ) -> dict:
        """Auto-ingest session activity from git history. NO manual logging needed!

        Call this when you forgot to log observations during work. It scans
        the git working tree to reconstruct what happened:
        - Modified/created/deleted files (from git status)
        - Commits made during the session (from git log)
        - Lines added/removed per file (from git diff)

        Works with ANY tool/agent (Qwen Code, Claude Code, manual edits)
        because it reads the actual codebase state, not tool call logs.

        After ingestion, call memory_quick_recap to see the synthesized knowledge.

        Args:
            session_id: Session identifier to create for this ingested session
            time_window_hours: Hours to look back for commits (default: 24)
            include_uncommitted: Include uncommitted changes (default: True)

        Returns:
            Dict with files found, commits found, observations created, and knowledge
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


@mcp.tool()
def openlmlib_init() -> dict:
    """Initialize database, data directories, and vector index."""
    return init_library(_settings_path())


@mcp.tool()
def openlmlib_add_finding(
    project: str,
    claim: str,
    confidence: float,
    evidence: Optional[List[str]] = None,
    reasoning: str = "",
    caveats: Optional[List[str]] = None,
    tags: Optional[List[str]] = None,
    full_text: str = "",
    proposed_by: str = "",
    finding_id: Optional[str] = None,
    confirm: bool = False,
) -> dict:
    """Add a finding to OpenLMlib. Requires confirm=true for writes."""
    return add_finding(
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
    )


@mcp.tool()
def openlmlib_list_findings(limit: int = 50, offset: int = 0) -> dict:
    """List findings in OpenLMlib."""
    return list_findings(_settings_path(), limit=limit, offset=offset)


@mcp.tool()
def openlmlib_get_finding(finding_id: str) -> dict:
    """Get a finding by id."""
    return get_finding(_settings_path(), finding_id)


@mcp.tool()
def openlmlib_search_fts(query: str, limit: int = 10) -> dict:
    """Search findings using SQLite FTS5."""
    return search_fts(_settings_path(), query, limit=limit)


@mcp.tool()
def openlmlib_retrieve(
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
    """Run dual-index retrieval (semantic + lexical) with optional filters."""
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
def openlmlib_retrieve_context(
    query: str,
    project: Optional[str] = None,
    tags: Optional[List[str]] = None,
    confidence_min: Optional[float] = None,
    final_k: Optional[int] = None,
) -> dict:
    """Retrieve findings and return sanitized untrusted context block for LLM prompts."""
    return retrieve_prompt_context(
        settings_path=_settings_path(),
        query=query,
        project=project,
        tags=tags,
        confidence_min=confidence_min,
        final_k=final_k,
    )


@mcp.tool()
def openlmlib_delete_finding(finding_id: str, confirm: bool = False) -> dict:
    """Delete a finding by id. Requires confirm=true for writes."""
    return delete_finding(_settings_path(), finding_id, confirm=confirm)


@mcp.tool()
def openlmlib_health() -> dict:
    """Return database and vector index health info."""
    return health(_settings_path())


@mcp.tool()
def openlmlib_evaluate_dataset(dataset_path: str = "config/eval_queries.json", final_k: int = 10) -> dict:
    """Run retrieval evaluation metrics on a local dataset file."""
    return evaluate_dataset(
        settings_path=_settings_path(),
        dataset_path=Path(dataset_path),
        final_k=final_k,
    )


@mcp.tool()
def openlmlib_help(tool_name: Optional[str] = None) -> dict:
    """Get help about all OpenLMlib MCP tools or a specific tool.

    Call this with no arguments to see all available tools organized by category.
    Call with a specific tool_name to get detailed usage instructions.

    Args:
        tool_name: Optional specific tool name to get help for
                   (e.g., 'openlmlib_add_finding', 'collab_create_session')

    Returns:
        Dict with tool descriptions and usage information
    """
    core_tools = {
        "openlmlib_init": {
            "description": "Initialize database, data directories, and vector index.",
            "args": {},
            "returns": "Dict with initialization status",
        },
        "openlmlib_add_finding": {
            "description": "Add a finding to OpenLMLib.",
            "args": {
                "project": "Project name",
                "claim": "The claim/finding text",
                "confidence": "Confidence score (0.0-1.0)",
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
        "openlmlib_list_findings": {
            "description": "List findings in OpenLMLib.",
            "args": {
                "limit": "Max findings to return (default: 50)",
                "offset": "Offset for pagination (default: 0)",
            },
            "returns": "Dict with list of findings",
        },
        "openlmlib_get_finding": {
            "description": "Get a finding by id.",
            "args": {
                "finding_id": "ID of the finding to retrieve",
            },
            "returns": "Dict with finding details",
        },
        "openlmlib_search_fts": {
            "description": "Search findings using SQLite FTS5 full-text search.",
            "args": {
                "query": "Search query",
                "limit": "Max results (default: 10)",
            },
            "returns": "Dict with matching findings",
        },
        "openlmlib_retrieve": {
            "description": "Run dual-index retrieval (semantic + lexical) with optional filters.",
            "args": {
                "query": "Search query",
                "project": "Filter by project (optional)",
                "tags": "Filter by tags (optional)",
                "created_after": "Filter by creation date (optional)",
                "created_before": "Filter by creation date (optional)",
                "confidence_min": "Minimum confidence score (optional)",
                "semantic_k": "Number of semantic results (optional)",
                "lexical_k": "Number of lexical results (optional)",
                "final_k": "Final number of results (optional)",
            },
            "returns": "Dict with retrieved findings",
        },
        "openlmlib_retrieve_context": {
            "description": "Retrieve findings and return sanitized untrusted context block for LLM prompts.",
            "args": {
                "query": "Search query",
                "project": "Filter by project (optional)",
                "tags": "Filter by tags (optional)",
                "confidence_min": "Minimum confidence score (optional)",
                "final_k": "Final number of results (optional)",
            },
            "returns": "Dict with sanitized context",
        },
        "openlmlib_delete_finding": {
            "description": "Delete a finding by id.",
            "args": {
                "finding_id": "ID of the finding to delete",
                "confirm": "Must be True for writes (safety)",
            },
            "returns": "Dict with deletion status",
        },
        "openlmlib_health": {
            "description": "Return database and vector index health info.",
            "args": {},
            "returns": "Dict with health status",
        },
        "openlmlib_evaluate_dataset": {
            "description": "Run retrieval evaluation metrics on a local dataset file.",
            "args": {
                "dataset_path": "Path to dataset file (default: 'config/eval_queries.json')",
                "final_k": "Final number of results (default: 10)",
            },
            "returns": "Dict with evaluation metrics",
        },
    }

    collab_tools_summary = {
        "collab_create_session": "Create a new collaboration session for multi-agent research.",
        "collab_join_session": "Join an existing collaboration session.",
        "collab_list_sessions": "List collaboration sessions.",
        "collab_get_session_state": "Get the current state of a collaboration session for a joined agent.",
        "collab_update_session_state": "Update the session state (orchestrator only).",
        "collab_send_message": "Send a message to a collaboration session.",
        "collab_read_messages": "Read new messages from a joined session (offset-based).",
        "collab_poll_messages": "Wait for new messages with timeout (AUTONOMOUS LOOP - use for continuous agent communication).",
        "collab_tail_messages": "Read the last N messages from a joined session (quick status check).",
        "collab_read_message_range": "Read messages in a specific sequence range from a joined session.",
        "collab_grep_messages": "Search messages in a joined session by keyword.",
        "collab_get_session_context": "Get a compiled context view of the session (PRIMARY tool for understanding session state).",
        "collab_add_artifact": "Save a research artifact (finding, analysis, summary) to the session.",
        "collab_list_artifacts": "List artifacts in a joined session.",
        "collab_get_artifact": "Get the full content of a specific artifact from a joined session.",
        "collab_grep_artifacts": "Search artifact content in a joined session by keyword.",
        "collab_leave_session": "Leave a collaboration session gracefully.",
        "collab_terminate_session": "Terminate and complete a collaboration session (orchestrator only).",
        "collab_export_to_library": "Export session artifacts as findings in the main OpenLMLib library.",
        "collab_list_templates": "List available session templates for quick session creation.",
        "collab_get_template": "Get details of a specific session template.",
        "collab_create_session_from_template": "Create a session from a predefined template.",
        "collab_get_agent_sessions": "Get all sessions the requesting agent has participated in.",
        "collab_get_active_sessions_summary": "Get a summary of active sessions joined by the requesting agent.",
        "collab_search_sessions": "Search joined sessions by message content using FTS5.",
        "collab_get_session_relationships": "Find sessions related to a joined session.",
        "collab_get_session_statistics": "Get detailed statistics for a joined session.",
        "collab_list_openrouter_models": "List available models from OpenRouter API.",
        "collab_get_openrouter_model_details": "Get detailed information about a specific OpenRouter model.",
        "collab_get_recommended_models": "Get recommended OpenRouter models for a specific task type.",
        "collab_help": "Get help about collab MCP tools.",
    }

    memory_tools = {
        "memory_session_start": "Start a new session and inject relevant context from previous sessions.",
        "memory_session_end": "End a session and trigger summarization.",
        "memory_log_observation": "Log an observation from tool execution.",
        "memory_search": "Layer 1: Search memory index (lightweight, ~75 tokens/result).",
        "memory_timeline": "Layer 2: Get chronological context for memory IDs (~200 tokens/result).",
        "memory_get_observations": "Layer 3: Get full details for specific memory IDs (~750 tokens/result).",
        "memory_inject_context": "Auto-inject relevant context at session start.",
        "memory_quick_recap": "Get a synthesized recap of recent sessions (~150-250 tokens). Call FIRST for structured knowledge.",
        "memory_detailed_context": "Get detailed context about a specific topic (~500-800 tokens). Call AFTER quick recap.",
        "memory_retroactive_ingest": "Auto-ingest session activity from git history. No manual logging needed!",
    }

    if tool_name:
        if tool_name in core_tools:
            return {"tool": tool_name, **core_tools[tool_name]}
        elif tool_name in collab_tools_summary:
            return {
                "tool": tool_name,
                "description": collab_tools_summary[tool_name],
                "note": f"Use collab_help(tool_name='{tool_name}') for detailed usage information",
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
                "description": "Manage findings in the OpenLMLib knowledge base",
                "tools": {name: info["description"] for name, info in core_tools.items()},
            },
            "Memory Injection Tools": {
                "description": "Lifecycle-based memory management with progressive disclosure and retroactive git ingestion (10 tools)",
                "tools": memory_tools,
                "note": "Use openlmlib_help(tool_name='memory_<tool>') for detailed usage",
            },
            "CollabSession Tools": {
                "description": "Multi-agent collaboration session management (30 tools)",
                "summary": collab_tools_summary,
                "note": "Use collab_help() for detailed collab tool documentation",
            },
        },
        "usage": [
            "Call openlmlib_help(tool_name='<tool>') for detailed usage of a core tool",
            "Call openlmlib_help(tool_name='memory_<tool>') for memory tool usage",
            "Call collab_help(tool_name='<tool>') for detailed usage of a collab tool",
        ],
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
