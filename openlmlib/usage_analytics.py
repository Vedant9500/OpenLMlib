"""Tool usage analytics for Phase 4 validation.

Tracks tool call patterns to measure:
- Automatic vs explicit tool call rates
- Tool selection accuracy
- Parameter validation/hallucination rates
- Workflow completeness

Provides reporting tools for A/B testing and optimization.

Tables are initialized in db.py init_db(). This module provides
the logging and reporting APIs.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def log_tool_call(
    conn: sqlite3.Connection,
    tool_name: str,
    call_mode: str = "explicit",
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    parameters: Optional[Dict[str, Any]] = None,
    success: bool = True,
    error_message: Optional[str] = None,
    execution_time_ms: Optional[float] = None,
    result_summary: Optional[str] = None,
    workflow_position: Optional[str] = None,
    triggered_by: Optional[str] = None,
) -> str:
    """Log a tool call for analytics.

    Args:
        conn: Database connection
        tool_name: Name of the tool called
        call_mode: 'automatic' (model decided) or 'explicit' (user instructed)
        session_id: Session identifier
        user_id: User/agent identifier
        parameters: Tool parameters (stored as JSON)
        success: Whether the call succeeded
        error_message: Error message if failed
        execution_time_ms: Execution time in milliseconds
        result_summary: Brief summary of result
        workflow_position: Position in workflow (e.g., 'first', 'after_search')
        triggered_by: What triggered the call (e.g., 'user_request', 'discovery', 'workflow')

    Returns:
        Tool call ID
    """
    call_id = f"tc-{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()

    conn.execute(
        """
        INSERT INTO tool_calls (
            id, tool_name, called_at, call_mode, session_id, user_id,
            parameters, success, error_message, execution_time_ms,
            result_summary, workflow_position, triggered_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            call_id,
            tool_name,
            now,
            call_mode,
            session_id,
            user_id,
            json.dumps(parameters) if parameters else None,
            1 if success else 0,
            error_message,
            execution_time_ms,
            result_summary,
            workflow_position,
            triggered_by,
        ),
    )
    conn.commit()
    return call_id


def log_parameter_validation(
    conn: sqlite3.Connection,
    tool_call_id: str,
    field: str,
    proposed_value: Any,
    validated_value: Any,
    validation_type: str = "default_applied",
    is_hallucination: bool = False,
) -> None:
    """Log a parameter validation event.

    Args:
        conn: Database connection
        tool_call_id: ID from log_tool_call
        field: Parameter name
        proposed_value: What was proposed (may be invalid)
        validated_value: What was actually used (after validation/default)
        validation_type: Type of validation ('default_applied', 'corrected', 'coerced', 'rejected')
        is_hallucination: Whether the proposed value was hallucinated (made up)
    """
    validation_id = f"pv-{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()

    conn.execute(
        """
        INSERT INTO parameter_validations (
            id, tool_call_id, field, proposed_value, validated_value,
            validation_type, is_hallucination, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            validation_id,
            tool_call_id,
            field,
            str(proposed_value) if proposed_value is not None else None,
            str(validated_value) if validated_value is not None else None,
            validation_type,
            1 if is_hallucination else 0,
            now,
        ),
    )
    conn.commit()


def log_tool_selection(
    conn: sqlite3.Connection,
    query: str,
    selected_tool: str,
    expected_tool: Optional[str] = None,
    is_correct: Optional[bool] = None,
    confidence_score: Optional[float] = None,
    session_id: Optional[str] = None,
) -> str:
    """Log a tool selection decision.

    Args:
        conn: Database connection
        query: What the user asked for
        selected_tool: Tool the model chose
        expected_tool: What the correct tool should have been (if known)
        is_correct: Whether the selection was correct
        confidence_score: Model's confidence in selection
        session_id: Session identifier

    Returns:
        Selection ID
    """
    selection_id = f"ts-{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()

    if is_correct is None and expected_tool is not None:
        is_correct = selected_tool == expected_tool

    conn.execute(
        """
        INSERT INTO tool_selections (
            id, query, selected_tool, expected_tool, is_correct,
            confidence_score, created_at, session_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            selection_id,
            query,
            selected_tool,
            expected_tool,
            1 if is_correct else 0,
            confidence_score,
            now,
            session_id,
        ),
    )
    conn.commit()
    return selection_id


def log_workflow_event(
    conn: sqlite3.Connection,
    workflow_type: str,
    step_number: int,
    tool_name: str,
    session_id: Optional[str] = None,
    skipped: bool = False,
    skipped_reason: Optional[str] = None,
) -> str:
    """Log a workflow event for completeness tracking.

    Args:
        conn: Database connection
        workflow_type: Type of workflow (e.g., 'research', 'analysis')
        step_number: Step number in workflow
        tool_name: Tool that was called (or should have been called)
        session_id: Session identifier
        skipped: Whether the step was skipped
        skipped_reason: Why it was skipped

    Returns:
        Event ID
    """
    event_id = f"we-{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()

    conn.execute(
        """
        INSERT INTO workflow_events (
            id, workflow_type, step_number, tool_name, session_id,
            completed_at, skipped, skipped_reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            workflow_type,
            step_number,
            tool_name,
            session_id,
            now,
            1 if skipped else 0,
            skipped_reason,
        ),
    )
    conn.commit()
    return event_id


def _cutoff(days: int) -> str:
    """Get ISO cutoff datetime."""
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def get_automatic_call_rate(
    conn: sqlite3.Connection,
    tool_name: Optional[str] = None,
    days: int = 7,
) -> Dict[str, Any]:
    """Get automatic vs explicit call rates.

    Args:
        conn: Database connection
        tool_name: Filter by specific tool (None for all)
        days: Look back N days

    Returns:
        Dict with automatic_rate, explicit_rate, total_calls, breakdown
    """
    cutoff = _cutoff(days)

    where = "WHERE called_at >= ?"
    params: List[Any] = [cutoff]

    if tool_name:
        where += " AND tool_name = ?"
        params.append(tool_name)

    row = conn.execute(
        f"""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN call_mode = 'automatic' THEN 1 ELSE 0 END) as automatic,
            SUM(CASE WHEN call_mode = 'explicit' THEN 1 ELSE 0 END) as explicit
        FROM tool_calls
        {where}
        """,
        params,
    ).fetchone()

    total = row["total"] or 0
    automatic = row["automatic"] or 0
    explicit = row["explicit"] or 0

    return {
        "total_calls": total,
        "automatic_calls": automatic,
        "explicit_calls": explicit,
        "automatic_rate": automatic / total if total > 0 else 0.0,
        "explicit_rate": explicit / total if total > 0 else 0.0,
        "period_days": days,
    }


def get_tool_selection_accuracy(
    conn: sqlite3.Connection,
    days: int = 7,
) -> Dict[str, Any]:
    """Get tool selection accuracy metrics."""
    cutoff = _cutoff(days)

    row = conn.execute(
        """
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) as correct,
            AVG(CASE WHEN is_correct IS NOT NULL THEN CAST(is_correct AS REAL) END) as accuracy
        FROM tool_selections
        WHERE created_at >= ?
        """,
        (cutoff,),
    ).fetchone()

    total = row["total"] or 0
    correct = row["correct"] or 0

    return {
        "total_selections": total,
        "correct_selections": correct,
        "accuracy_rate": correct / total if total > 0 else 0.0,
        "period_days": days,
    }


def get_parameter_hallucination_rate(
    conn: sqlite3.Connection,
    days: int = 7,
) -> Dict[str, Any]:
    """Get parameter hallucination rate."""
    cutoff = _cutoff(days)

    row = conn.execute(
        """
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN is_hallucination = 1 THEN 1 ELSE 0 END) as hallucinations
        FROM parameter_validations
        WHERE created_at >= ?
        """,
        (cutoff,),
    ).fetchone()

    total = row["total"] or 0
    hallucinations = row["hallucinations"] or 0

    # Breakdown by field
    field_rows = conn.execute(
        """
        SELECT
            field,
            COUNT(*) as count,
            SUM(CASE WHEN is_hallucination = 1 THEN 1 ELSE 0 END) as hallucinations
        FROM parameter_validations
        WHERE created_at >= ?
        GROUP BY field
        ORDER BY hallucinations DESC
        """,
        (cutoff,),
    ).fetchall()

    return {
        "total_validations": total,
        "hallucinations": hallucinations,
        "hallucination_rate": hallucinations / total if total > 0 else 0.0,
        "by_field": [
            {
                "field": r["field"],
                "count": r["count"],
                "hallucinations": r["hallucinations"],
                "rate": r["hallucinations"] / r["count"] if r["count"] > 0 else 0.0,
            }
            for r in field_rows
        ],
        "period_days": days,
    }


def get_workflow_completeness(
    conn: sqlite3.Connection,
    workflow_type: Optional[str] = None,
    days: int = 7,
) -> Dict[str, Any]:
    """Get workflow completion rates."""
    cutoff = _cutoff(days)

    where = "WHERE completed_at >= ?"
    params: List[Any] = [cutoff]

    if workflow_type:
        where += " AND workflow_type = ?"
        params.append(workflow_type)

    row = conn.execute(
        f"""
        SELECT
            COUNT(*) as total_steps,
            SUM(CASE WHEN skipped = 0 THEN 1 ELSE 0 END) as completed,
            SUM(CASE WHEN skipped = 1 THEN 1 ELSE 0 END) as skipped
        FROM workflow_events
        {where}
        """,
        params,
    ).fetchone()

    total = row["total_steps"] or 0
    completed = row["completed"] or 0
    skipped = row["skipped"] or 0

    # Completion by workflow type
    type_rows = conn.execute(
        f"""
        SELECT
            workflow_type,
            COUNT(*) as steps,
            SUM(CASE WHEN skipped = 0 THEN 1 ELSE 0 END) as completed
        FROM workflow_events
        {where}
        GROUP BY workflow_type
        """,
        params,
    ).fetchall()

    return {
        "total_steps": total,
        "completed_steps": completed,
        "skipped_steps": skipped,
        "completion_rate": completed / total if total > 0 else 0.0,
        "by_workflow": [
            {
                "type": r["workflow_type"],
                "steps": r["steps"],
                "completed": r["completed"],
                "rate": r["completed"] / r["steps"] if r["steps"] > 0 else 0.0,
            }
            for r in type_rows
        ],
        "period_days": days,
    }


def get_full_analytics_report(
    conn: sqlite3.Connection,
    days: int = 7,
) -> Dict[str, Any]:
    """Generate comprehensive analytics report.

    Args:
        conn: Database connection
        days: Look back N days

    Returns:
        Full analytics report dict
    """
    return {
        "automatic_call_rate": get_automatic_call_rate(conn, days=days),
        "tool_selection_accuracy": get_tool_selection_accuracy(conn, days=days),
        "parameter_hallucination_rate": get_parameter_hallucination_rate(conn, days=days),
        "workflow_completeness": get_workflow_completeness(conn, days=days),
        "report_period_days": days,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def get_tool_usage_summary(
    conn: sqlite3.Connection,
    tool_name: Optional[str] = None,
    days: int = 7,
) -> List[Dict[str, Any]]:
    """Get usage summary by tool."""
    cutoff = _cutoff(days)

    where = "WHERE called_at >= ?"
    params: List[Any] = [cutoff]

    if tool_name:
        where += " AND tool_name = ?"
        params.append(tool_name)

    rows = conn.execute(
        f"""
        SELECT
            tool_name,
            COUNT(*) as total_calls,
            SUM(CASE WHEN call_mode = 'automatic' THEN 1 ELSE 0 END) as automatic_calls,
            SUM(CASE WHEN call_mode = 'explicit' THEN 1 ELSE 0 END) as explicit_calls,
            SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful,
            SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as failed,
            AVG(execution_time_ms) as avg_execution_ms
        FROM tool_calls
        {where}
        GROUP BY tool_name
        ORDER BY total_calls DESC
        """,
        params,
    ).fetchall()

    return [
        {
            "tool_name": r["tool_name"],
            "total_calls": r["total_calls"],
            "automatic_calls": r["automatic_calls"],
            "explicit_calls": r["explicit_calls"],
            "automatic_rate": r["automatic_calls"] / r["total_calls"] if r["total_calls"] > 0 else 0.0,
            "successful": r["successful"],
            "failed": r["failed"],
            "success_rate": r["successful"] / r["total_calls"] if r["total_calls"] > 0 else 0.0,
            "avg_execution_ms": r["avg_execution_ms"],
        }
        for r in rows
    ]
