"""Deterministic evaluation helpers for Co-Scientist workflows."""

from __future__ import annotations

import datetime as _dt
import sqlite3
from copy import deepcopy
from typing import Any, Dict, Iterable, List, Optional

from openlmlib.collab import db as collab_db

from .orchestrator import _load_run_state


WORKFLOW_TYPES = frozenset({
    "single_agent",
    "one_session_multi_agent",
    "two_session_co_scientist",
})

DEFAULT_BENCHMARK_TASKS: List[Dict[str, Any]] = [
    {
        "task_id": "cosci_bench_001",
        "title": "MCP tool discoverability regression",
        "prompt": "Research why an installed MCP server is not being considered by coding agents and propose testable fixes.",
        "success_criteria": [
            "Identifies client configuration and prompt-discoverability causes separately.",
            "Provides citations or local artifacts for each claim.",
            "Includes a verification plan for the proposed fixes.",
        ],
        "risk_level": "medium",
    },
    {
        "task_id": "cosci_bench_002",
        "title": "Retrieval pipeline optimization",
        "prompt": "Compare two approaches to improving hybrid retrieval precision without increasing latency.",
        "success_criteria": [
            "States expected I/O and token tradeoffs.",
            "Finds at least one disconfirming argument.",
            "Produces an implementation-neutral recommendation.",
        ],
        "risk_level": "medium",
    },
    {
        "task_id": "cosci_bench_003",
        "title": "Multi-agent handoff quality",
        "prompt": "Evaluate whether two-session hypothesis verification improves traceability over a single research session.",
        "success_criteria": [
            "Compares single-agent and two-session outputs.",
            "Tracks citation coverage and contradiction discovery.",
            "Identifies when the simpler workflow should remain default.",
        ],
        "risk_level": "high",
    },
]


def get_benchmark_tasks() -> Dict[str, Any]:
    """Return the built-in Phase 9 benchmark task set."""
    return {
        "tasks": deepcopy(DEFAULT_BENCHMARK_TASKS),
        "count": len(DEFAULT_BENCHMARK_TASKS),
        "workflow_types": sorted(WORKFLOW_TYPES),
    }


def evaluate_run(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    token_count: Optional[int] = None,
    cost_usd: Optional[float] = None,
    human_edits_needed: Optional[int] = None,
    expert_accepted: Optional[bool] = None,
) -> Dict[str, Any]:
    """Evaluate a two-session Co-Scientist run from persisted run state."""
    run_state, _ = _load_run_state(conn, run_id)
    hypotheses = list(run_state.get("hypotheses", {}).values())
    reports = list(run_state.get("verification_reports", {}).values())
    selected_ids = list(run_state.get("selected_hypothesis_ids", []))
    supported_reports = [
        report for report in reports
        if report.get("verdict") in {"supported", "partially_supported"}
    ]
    rejected_reports = [
        report for report in reports
        if report.get("verdict") in {"contradicted", "unsafe_or_out_of_scope"}
    ]

    generation_messages = collab_db.get_messages(conn, run_state["generation_session_id"], limit=10_000)
    verification_messages = collab_db.get_messages(conn, run_state["verification_session_id"], limit=10_000)
    total_turns = len(generation_messages) + len(verification_messages)
    duration_seconds = _duration_seconds(run_state)

    citation_hypotheses = sum(1 for item in hypotheses if int(item.get("citation_count", 0)) > 0)
    citation_reports = sum(1 for report in reports if int(report.get("citation_count", 0)) > 0)
    contradiction_reports = sum(
        1 for report in reports
        if int(report.get("disconfirming_evidence_count", 0)) > 0
    )
    report_count = len(reports)
    hypothesis_count = len(hypotheses)
    verified_count = len(supported_reports)

    metrics = {
        "valid_hypothesis_rate": _rate(hypothesis_count, hypothesis_count),
        "rejected_hallucination_rate": _rate(len(rejected_reports), report_count),
        "citation_coverage": _rate(citation_hypotheses + citation_reports, hypothesis_count + report_count),
        "contradiction_discovery_rate": _rate(contradiction_reports, max(1, len(selected_ids))),
        "time_to_verified_shortlist_seconds": duration_seconds,
        "token_cost_per_verified_hypothesis": _per_verified(token_count, verified_count),
        "usd_cost_per_verified_hypothesis": _per_verified(cost_usd, verified_count),
        "agent_turns": total_turns,
        "human_edits_needed": human_edits_needed,
        "artifact_quality": _artifact_quality_score(hypothesis_count, report_count, bool(run_state.get("final_report_artifact_id"))),
        "citation_quality": _rate(citation_hypotheses, hypothesis_count),
        "expert_accepted": expert_accepted,
        "verified_hypothesis_count": verified_count,
        "hypothesis_count": hypothesis_count,
        "verification_report_count": report_count,
    }
    return {
        "run_id": run_id,
        "workflow_type": "two_session_co_scientist",
        "phase": run_state.get("phase"),
        "metrics": metrics,
        "traceability_score": _traceability_score(metrics),
        "quality_score": _quality_score(metrics),
    }


def evaluate_workflow_result(result: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize one manually supplied benchmark workflow result."""
    workflow_type = result.get("workflow_type")
    if workflow_type not in WORKFLOW_TYPES:
        raise ValueError(f"workflow_type must be one of: {sorted(WORKFLOW_TYPES)}")

    total_hypotheses = _int(result.get("total_hypotheses"), 0)
    valid_hypotheses = _int(result.get("valid_hypotheses"), 0)
    verified_hypotheses = _int(result.get("verified_hypotheses"), 0)
    rejected_hallucinations = _int(result.get("rejected_hallucinations"), 0)
    citations = _int(result.get("citations"), 0)
    citation_slots = _int(result.get("citation_slots"), max(1, total_hypotheses))
    contradictions = _int(result.get("contradictions_found"), 0)
    selected = _int(result.get("selected_hypotheses"), max(1, verified_hypotheses))
    token_count = result.get("token_count")
    cost_usd = result.get("cost_usd")

    metrics = {
        "valid_hypothesis_rate": _rate(valid_hypotheses, total_hypotheses),
        "rejected_hallucination_rate": _rate(rejected_hallucinations, max(1, verified_hypotheses + rejected_hallucinations)),
        "citation_coverage": _rate(citations, citation_slots),
        "contradiction_discovery_rate": _rate(contradictions, selected),
        "time_to_verified_shortlist_seconds": result.get("latency_seconds"),
        "token_cost_per_verified_hypothesis": _per_verified(token_count, verified_hypotheses),
        "usd_cost_per_verified_hypothesis": _per_verified(cost_usd, verified_hypotheses),
        "agent_turns": _int(result.get("agent_turns"), 0),
        "human_edits_needed": result.get("human_edits_needed"),
        "artifact_quality": _clamp(result.get("artifact_quality", 0.0)),
        "citation_quality": _clamp(result.get("citation_quality", _rate(citations, citation_slots))),
        "expert_accepted": result.get("expert_accepted"),
        "verified_hypothesis_count": verified_hypotheses,
        "hypothesis_count": total_hypotheses,
        "verification_report_count": _int(result.get("verification_report_count"), verified_hypotheses + rejected_hallucinations),
    }
    return {
        "task_id": result.get("task_id"),
        "workflow_type": workflow_type,
        "metrics": metrics,
        "traceability_score": _traceability_score(metrics),
        "quality_score": _quality_score(metrics),
    }


def compare_workflows(results: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Compare benchmark results by workflow type and recommend a default."""
    evaluated = [
        item if "quality_score" in item and "traceability_score" in item else evaluate_workflow_result(item)
        for item in results
    ]
    grouped: Dict[str, List[Dict[str, Any]]] = {workflow: [] for workflow in WORKFLOW_TYPES}
    for item in evaluated:
        grouped[item["workflow_type"]].append(item)

    summaries = {
        workflow: _workflow_summary(items)
        for workflow, items in grouped.items()
        if items
    }
    recommendation = _recommend_workflow(summaries)
    return {
        "workflow_summaries": summaries,
        "evaluated_count": len(evaluated),
        "recommendation": recommendation,
    }


def _workflow_summary(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "runs": len(items),
        "mean_quality_score": _mean(item["quality_score"] for item in items),
        "mean_traceability_score": _mean(item["traceability_score"] for item in items),
        "mean_valid_hypothesis_rate": _mean(item["metrics"]["valid_hypothesis_rate"] for item in items),
        "mean_citation_coverage": _mean(item["metrics"]["citation_coverage"] for item in items),
        "mean_contradiction_discovery_rate": _mean(item["metrics"]["contradiction_discovery_rate"] for item in items),
    }


def _recommend_workflow(summaries: Dict[str, Dict[str, Any]]) -> Dict[str, str]:
    cosci = summaries.get("two_session_co_scientist")
    simpler_candidates = [
        summaries[workflow]
        for workflow in ("single_agent", "one_session_multi_agent")
        if workflow in summaries
    ]
    if not cosci:
        return {
            "default_workflow": "single_agent",
            "reason": "No two-session Co-Scientist benchmark data was supplied.",
        }
    simpler_best = max(
        simpler_candidates,
        key=lambda item: item["mean_quality_score"] + item["mean_traceability_score"],
        default=None,
    )
    if simpler_best is None:
        return {
            "default_workflow": "two_session_co_scientist",
            "reason": "Only Co-Scientist benchmark data was supplied.",
        }

    cosci_score = cosci["mean_quality_score"] + cosci["mean_traceability_score"]
    simple_score = simpler_best["mean_quality_score"] + simpler_best["mean_traceability_score"]
    if cosci_score >= simple_score + 0.1:
        return {
            "default_workflow": "two_session_co_scientist",
            "reason": "Two-session workflow shows a measurable quality or traceability improvement.",
        }
    return {
        "default_workflow": "simpler_workflow",
        "reason": "Two-session workflow did not clear the improvement threshold; keep the simpler workflow as default.",
    }


def _duration_seconds(run_state: Dict[str, Any]) -> Optional[float]:
    start = _parse_iso(run_state.get("created_at"))
    report_times = [
        _parse_iso(report.get("created_at"))
        for report in run_state.get("verification_reports", {}).values()
    ]
    report_times = [item for item in report_times if item is not None]
    if start is None or not report_times:
        return None
    return round((max(report_times) - start).total_seconds(), 3)


def _parse_iso(value: Any) -> Optional[_dt.datetime]:
    if not isinstance(value, str) or not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = _dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_dt.timezone.utc)
    return parsed


def _traceability_score(metrics: Dict[str, Any]) -> float:
    return round(
        _mean([
            metrics.get("valid_hypothesis_rate", 0.0),
            metrics.get("citation_coverage", 0.0),
            metrics.get("contradiction_discovery_rate", 0.0),
            metrics.get("artifact_quality", 0.0),
        ]),
        6,
    )


def _quality_score(metrics: Dict[str, Any]) -> float:
    accepted = 1.0 if metrics.get("expert_accepted") is True else 0.0 if metrics.get("expert_accepted") is False else 0.5
    human_edits = metrics.get("human_edits_needed")
    edit_score = 0.5 if human_edits is None else max(0.0, 1.0 - min(10, int(human_edits)) / 10.0)
    return round(
        _mean([
            metrics.get("valid_hypothesis_rate", 0.0),
            metrics.get("citation_quality", 0.0),
            metrics.get("artifact_quality", 0.0),
            accepted,
            edit_score,
        ]),
        6,
    )


def _artifact_quality_score(hypothesis_count: int, report_count: int, has_final_report: bool) -> float:
    if hypothesis_count == 0:
        return 0.0
    components = [
        _rate(report_count, hypothesis_count),
        1.0 if has_final_report else 0.5,
    ]
    return round(_mean(components), 6)


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(max(0.0, min(1.0, numerator / denominator)), 6)


def _per_verified(value: Optional[Any], verified_count: int) -> Optional[float]:
    if value is None or verified_count <= 0:
        return None
    return round(float(value) / verified_count, 6)


def _mean(values: Iterable[float]) -> float:
    items = [float(value) for value in values]
    if not items:
        return 0.0
    return sum(items) / len(items)


def _clamp(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return round(max(0.0, min(1.0, numeric)), 6)


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
