"""Co-Scientist run orchestration over CollabSessions.

Phase 4 deliberately keeps run metadata in linked session state and stores
large hypothesis/report payloads as artifacts. This avoids a new run database
until real workflows show that cross-run querying is worth the migration cost.
"""

from __future__ import annotations

import json
import sqlite3
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from openlmlib.schema import utc_now_iso

from .evidence import (
    evidence_issues_to_dicts,
    validate_hypothesis_grounding,
    verify_citations,
)
from .hypothesis import (
    SCORE_FIELDS,
    new_co_scientist_run_id,
    validate_hypothesis_packet,
    validation_issues_to_dicts,
)
from .policy import screen_co_scientist_scope
from .ranking import score_hypothesis
from .templates import VERIFICATION_VERDICTS
from openlmlib.collab import db as collab_db
from openlmlib.collab.artifact_store import ArtifactStore
from openlmlib.collab.errors import AgentNotAuthorizedError, AgentNotFoundError
from openlmlib.collab.message_bus import MessageBus
from openlmlib.collab.security import verify_agent_in_session
from openlmlib.collab.session import create_collab_session
from openlmlib.collab.templates import get_template

# Task description markers used to close only phase-boundary work (not whole plans).
_GENERATION_HANDOFF_MARKERS = (
    "hypothesis_shortlist",
    "ranker",
    "meta-reviewer",
    "verification handoff",
)
_VERIFICATION_SYNTHESIS_MARKERS = (
    "verification_report",
    "final adjudicator",
    "adjudicator",
)


RUN_STATE_KEY = "co_scientist_run"

DEFAULT_VERIFICATION_POLICY = {
    "require_citations": True,
    "require_contradiction_search": True,
    "require_human_approval_before_action": True,
}

PHASES = frozenset({"generation", "verification", "synthesis", "complete"})


class CoScientistRunError(Exception):
    """Raised when a Co-Scientist run operation cannot continue."""

    def __init__(
        self,
        message: str,
        *,
        error_type: str = "co_scientist_run_error",
        issues: Optional[List[Dict[str, str]]] = None,
    ):
        super().__init__(message)
        self.error_type = error_type
        self.issues = issues or []


def create_co_scientist_run(
    conn: sqlite3.Connection,
    sessions_dir: Path,
    topic: str,
    constraints: Optional[List[str]] = None,
    created_by: str = "orchestrator",
    top_k: int = 5,
    created_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Create linked generation and verification sessions for one run."""
    if not isinstance(topic, str) or not topic.strip():
        raise CoScientistRunError(
            "topic is required",
            error_type="validation_error",
        )
    if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k < 1:
        raise CoScientistRunError(
            "top_k must be an integer >= 1",
            error_type="validation_error",
        )

    scope = screen_co_scientist_scope(topic, constraints)
    if not scope.get("allowed"):
        raise CoScientistRunError(
            "Co-Scientist scope check failed",
            error_type="scope_blocked",
            issues=[{"field": "topic", "message": reason, "severity": "error"} for reason in scope.get("reasons", [])],
        )

    created_at = created_at or utc_now_iso()
    run_id = new_co_scientist_run_id()
    constraints = list(constraints or [])

    generation_template = _require_template("co_scientist_generate")
    verification_template = _require_template("co_scientist_verify")

    generation_session = create_collab_session(
        conn=conn,
        sessions_dir=sessions_dir,
        title=f"Co-Scientist Generation: {_short_title(topic)}",
        created_by=created_by,
        description=_session_description(run_id, topic, constraints, "generation"),
        plan=generation_template["plan"],
        rules=_rules_with_run(generation_template["rules"], run_id, "generation"),
        created_at=created_at,
    )
    verification_session = create_collab_session(
        conn=conn,
        sessions_dir=sessions_dir,
        title=f"Co-Scientist Verification: {_short_title(topic)}",
        created_by=created_by,
        description=_session_description(run_id, topic, constraints, "verification"),
        plan=verification_template["plan"],
        rules=_rules_with_run(verification_template["rules"], run_id, "verification"),
        created_at=created_at,
    )

    run_state = {
        "run_id": run_id,
        "topic": topic.strip(),
        "constraints": constraints,
        "generation_session_id": generation_session["session_id"],
        "verification_session_id": verification_session["session_id"],
        "generation_orchestrator_agent_id": generation_session["agent_id"],
        "verification_orchestrator_agent_id": verification_session["agent_id"],
        "phase": "generation",
        "top_k": top_k,
        "hypothesis_ids": [],
        "hypotheses": {},
        "selected_hypothesis_ids": [],
        "verification_input_artifact_id": None,
        "verification_reports": {},
        "verification_report_ids": [],
        "final_report_artifact_id": None,
        "final_report_created_at": None,
        "memory_summary_paths": [],
        "verification_policy": dict(DEFAULT_VERIFICATION_POLICY),
        "scope_decision": scope,
        "created_by": created_by,
        "created_at": created_at,
        "updated_at": created_at,
    }

    _write_run_state_to_sessions(conn, run_state, updated_by=created_by, updated_at=created_at)
    _announce_run_created(conn, sessions_dir, run_state, created_at)

    return {
        "run_id": run_id,
        "topic": topic.strip(),
        "phase": "generation",
        "generation_session_id": generation_session["session_id"],
        "verification_session_id": verification_session["session_id"],
        "generation_agent_id": generation_session["agent_id"],
        "verification_agent_id": verification_session["agent_id"],
        "top_k": top_k,
        "scope_decision": scope,
        "next_steps": [
            "Use the generation session to produce hypothesis packets.",
            "Call submit_hypothesis for each validated packet.",
            "Call start_hypothesis_verification to hand top packets to the verification session.",
        ],
    }


def submit_hypothesis(
    conn: sqlite3.Connection,
    sessions_dir: Path,
    run_id: str,
    hypothesis_packet: Dict[str, Any],
    created_by: Optional[str] = None,
    created_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Persist one validated hypothesis packet and index it in run state."""
    run_state, _ = _load_run_state(conn, run_id)
    created_at = created_at or utc_now_iso()

    issues = validate_hypothesis_packet(hypothesis_packet)
    if issues:
        raise CoScientistRunError(
            "Invalid hypothesis packet",
            error_type="validation_error",
            issues=validation_issues_to_dicts(issues),
        )
    if hypothesis_packet["run_id"] != run_id:
        raise CoScientistRunError(
            "hypothesis_packet.run_id must match run_id",
            error_type="validation_error",
            issues=[
                {
                    "field": "run_id",
                    "message": "hypothesis_packet.run_id must match the target run_id",
                    "severity": "error",
                }
            ],
        )

    hypothesis_id = hypothesis_packet["hypothesis_id"]
    if hypothesis_id in run_state.get("hypotheses", {}):
        raise CoScientistRunError(
            f"Hypothesis {hypothesis_id} already exists in run {run_id}",
            error_type="duplicate_hypothesis",
        )

    actor = _require_run_actor(
        conn,
        run_state,
        created_by,
        session_key="generation_session_id",
        default_agent_key="generation_orchestrator_agent_id",
        action="submit_hypothesis",
    )
    store = ArtifactStore(conn, sessions_dir)
    artifact = store.save(
        session_id=run_state["generation_session_id"],
        created_by=actor,
        title=f"Hypothesis Packet {hypothesis_id}",
        content=json.dumps(hypothesis_packet, indent=2, sort_keys=True),
        created_at=created_at,
        artifact_type="hypothesis_packet",
        tags=["co_scientist", f"run_id:{run_id}", f"hypothesis_id:{hypothesis_id}"],
        shared=True,
    )

    hypothesis_summary = _hypothesis_summary(hypothesis_packet, artifact["artifact_id"], created_at, actor)
    run_state["hypothesis_ids"].append(hypothesis_id)
    run_state["hypotheses"][hypothesis_id] = hypothesis_summary
    run_state["updated_at"] = created_at
    _write_run_state_to_sessions(conn, run_state, updated_by=actor, updated_at=created_at)

    MessageBus(conn, sessions_dir).send(
        session_id=run_state["generation_session_id"],
        from_agent=actor,
        msg_type="artifact",
        content=f"Hypothesis packet submitted: {hypothesis_id}",
        created_at=created_at,
        metadata={
            "run_id": run_id,
            "hypothesis_id": hypothesis_id,
            "artifact_id": artifact["artifact_id"],
            "artifact_type": "hypothesis_packet",
        },
    )

    return {
        "run_id": run_id,
        "hypothesis_id": hypothesis_id,
        "artifact_id": artifact["artifact_id"],
        "hypothesis_count": len(run_state["hypothesis_ids"]),
        "phase": run_state["phase"],
    }


def list_hypotheses(
    conn: sqlite3.Connection,
    run_id: str,
    status: Optional[str] = None,
) -> Dict[str, Any]:
    """List indexed hypothesis packet summaries for a run."""
    run_state, _ = _load_run_state(conn, run_id)
    hypotheses = [
        deepcopy(run_state["hypotheses"][hypothesis_id])
        for hypothesis_id in run_state.get("hypothesis_ids", [])
        if hypothesis_id in run_state.get("hypotheses", {})
    ]
    if status:
        hypotheses = [item for item in hypotheses if item.get("status") == status]

    return {
        "run_id": run_id,
        "phase": run_state["phase"],
        "count": len(hypotheses),
        "hypotheses": hypotheses,
    }


def start_hypothesis_verification(
    conn: sqlite3.Connection,
    sessions_dir: Path,
    run_id: str,
    hypothesis_ids: Optional[List[str]] = None,
    top_k: Optional[int] = None,
    created_by: Optional[str] = None,
    created_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a compact verification handoff artifact for selected hypotheses."""
    run_state, _ = _load_run_state(conn, run_id)
    created_at = created_at or utc_now_iso()
    # Handoff is an orchestration action: allow either session orchestrator.
    actor = _require_run_actor(
        conn,
        run_state,
        created_by,
        session_key="generation_session_id",
        default_agent_key="generation_orchestrator_agent_id",
        action="start_hypothesis_verification",
        require_orchestrator=True,
        alternate_session_key="verification_session_id",
        alternate_default_agent_key="verification_orchestrator_agent_id",
    )
    selected_ids = _select_hypothesis_ids(run_state, hypothesis_ids, top_k)
    packets = [_load_hypothesis_packet(conn, sessions_dir, run_state, hypothesis_id) for hypothesis_id in selected_ids]
    grounding_issues = _validate_handoff_grounding(conn, run_state, packets)
    if grounding_issues:
        raise CoScientistRunError(
            "Selected hypotheses do not satisfy evidence grounding requirements",
            error_type="grounding_error",
            issues=grounding_issues,
        )

    handoff = {
        "run_id": run_id,
        "topic": run_state["topic"],
        "generation_session_id": run_state["generation_session_id"],
        "verification_session_id": run_state["verification_session_id"],
        "hypothesis_ids": selected_ids,
        "hypothesis_packets": packets,
        "verification_policy": run_state["verification_policy"],
        "instructions": [
            "Verify structured packets and declared evidence only.",
            "Do not rely on the full generation transcript unless a human requests it.",
            "Create one verification_report artifact per hypothesis_id.",
        ],
    }

    store = ArtifactStore(conn, sessions_dir)
    artifact = store.save(
        session_id=run_state["verification_session_id"],
        created_by=actor,
        title=f"Verification Input {run_id}",
        content=json.dumps(handoff, indent=2, sort_keys=True),
        created_at=created_at,
        artifact_type="verification_input",
        tags=["co_scientist", f"run_id:{run_id}", "verification_input"],
        shared=True,
    )

    run_state["phase"] = "verification"
    run_state["selected_hypothesis_ids"] = selected_ids
    run_state["verification_input_artifact_id"] = artifact["artifact_id"]
    for hypothesis_id in selected_ids:
        run_state["hypotheses"][hypothesis_id]["status"] = "sent_to_verification"
        run_state["hypotheses"][hypothesis_id]["sent_to_verification_at"] = created_at
    run_state["updated_at"] = created_at
    _write_run_state_to_sessions(conn, run_state, updated_by=actor, updated_at=created_at)
    completed_generation_tasks = _complete_open_session_tasks(
        conn,
        run_state["generation_session_id"],
        completed_at=created_at,
        description_markers=_GENERATION_HANDOFF_MARKERS,
    )

    MessageBus(conn, sessions_dir).send(
        session_id=run_state["verification_session_id"],
        from_agent=actor,
        msg_type="task",
        content=(
            f"Verify Co-Scientist run {run_id}. Use verification input artifact "
            f"{artifact['artifact_id']} and produce one verification_report per hypothesis_id: "
            f"{', '.join(selected_ids)}."
        ),
        created_at=created_at,
        to_agent="any",
        metadata={
            "run_id": run_id,
            "artifact_id": artifact["artifact_id"],
            "hypothesis_ids": selected_ids,
        },
    )

    return {
        "run_id": run_id,
        "phase": "verification",
        "verification_session_id": run_state["verification_session_id"],
        "verification_input_artifact_id": artifact["artifact_id"],
        "hypothesis_ids": selected_ids,
        "count": len(selected_ids),
        "completed_generation_task_ids": [task["task_id"] for task in completed_generation_tasks],
    }


def submit_verification(
    conn: sqlite3.Connection,
    sessions_dir: Path,
    run_id: str,
    hypothesis_id: str,
    verification_report: Dict[str, Any],
    created_by: Optional[str] = None,
    created_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Persist one verification report and update run state."""
    run_state, _ = _load_run_state(conn, run_id)
    created_at = created_at or utc_now_iso()
    actor = _require_run_actor(
        conn,
        run_state,
        created_by,
        session_key="verification_session_id",
        default_agent_key="verification_orchestrator_agent_id",
        action="submit_verification",
    )

    if hypothesis_id not in run_state.get("hypotheses", {}):
        raise CoScientistRunError(
            f"Hypothesis {hypothesis_id} is not part of run {run_id}",
            error_type="not_found",
        )

    report = dict(verification_report)
    report.setdefault("hypothesis_id", hypothesis_id)
    issues = validate_verification_report(report, hypothesis_id)
    citation_result = verify_citations(
        report.get("citations"),
        conn=conn,
        session_ids=[run_state["generation_session_id"], run_state["verification_session_id"]],
        workspace_root=Path.cwd(),
    )
    if not citation_result["valid"]:
        issues.extend(citation_result["issues"])
    if issues:
        raise CoScientistRunError(
            "Invalid verification report",
            error_type="validation_error",
            issues=issues,
        )

    verdict = report["verdict"]
    store = ArtifactStore(conn, sessions_dir)
    artifact = store.save(
        session_id=run_state["verification_session_id"],
        created_by=actor,
        title=f"Verification Report {hypothesis_id}",
        content=json.dumps(report, indent=2, sort_keys=True),
        created_at=created_at,
        artifact_type="verification_report",
        tags=[
            "co_scientist",
            f"run_id:{run_id}",
            f"hypothesis_id:{hypothesis_id}",
            f"verdict:{verdict}",
        ],
        shared=True,
    )

    run_state["verification_reports"][hypothesis_id] = {
        "hypothesis_id": hypothesis_id,
        "artifact_id": artifact["artifact_id"],
        "verdict": verdict,
        "confidence": float(report["confidence"]),
        "citation_count": len(report.get("citations", [])),
        "supporting_evidence_count": len(report.get("supporting_evidence", [])),
        "disconfirming_evidence_count": len(report.get("disconfirming_evidence", [])),
        "created_by": actor,
        "created_at": created_at,
    }
    if artifact["artifact_id"] not in run_state["verification_report_ids"]:
        run_state["verification_report_ids"].append(artifact["artifact_id"])
    run_state["hypotheses"][hypothesis_id]["verification_status"] = verdict
    run_state["hypotheses"][hypothesis_id]["verification_report_artifact_id"] = artifact["artifact_id"]
    run_state["hypotheses"][hypothesis_id]["status"] = _hypothesis_status_for_verdict(verdict)
    completed_verification_tasks: List[Dict[str, Any]] = []
    if _selected_reports_complete(run_state):
        run_state["phase"] = "synthesis"
    run_state["updated_at"] = created_at
    _write_run_state_to_sessions(conn, run_state, updated_by=actor, updated_at=created_at)
    if _selected_reports_complete(run_state):
        completed_verification_tasks = _complete_open_session_tasks(
            conn,
            run_state["verification_session_id"],
            completed_at=created_at,
            description_markers=_VERIFICATION_SYNTHESIS_MARKERS,
        )

    MessageBus(conn, sessions_dir).send(
        session_id=run_state["verification_session_id"],
        from_agent=actor,
        msg_type="artifact",
        content=f"Verification report submitted for {hypothesis_id}: {verdict}",
        created_at=created_at,
        metadata={
            "run_id": run_id,
            "hypothesis_id": hypothesis_id,
            "artifact_id": artifact["artifact_id"],
            "verdict": verdict,
        },
    )

    return {
        "run_id": run_id,
        "hypothesis_id": hypothesis_id,
        "artifact_id": artifact["artifact_id"],
        "verdict": verdict,
        "phase": run_state["phase"],
        "verification_report_count": len(run_state["verification_reports"]),
        "completed_verification_task_ids": [task["task_id"] for task in completed_verification_tasks],
    }


def get_co_scientist_report(
    conn: sqlite3.Connection,
    run_id: str,
) -> Dict[str, Any]:
    """Return a synthesized run report from compact run state."""
    run_state, records = _load_run_state(conn, run_id)
    hypotheses = [
        deepcopy(run_state["hypotheses"][hypothesis_id])
        for hypothesis_id in run_state.get("hypothesis_ids", [])
        if hypothesis_id in run_state.get("hypotheses", {})
    ]
    hypotheses_by_id = {item["hypothesis_id"]: item for item in hypotheses}
    verification_reports = [
        deepcopy(run_state["verification_reports"][hypothesis_id])
        for hypothesis_id in run_state.get("selected_hypothesis_ids", [])
        if hypothesis_id in run_state.get("verification_reports", {})
    ]
    verified_claims = [
        hypotheses_by_id[hypothesis_id]
        for hypothesis_id, report in run_state.get("verification_reports", {}).items()
        if report.get("verdict") in {"supported", "partially_supported"}
        and hypothesis_id in hypotheses_by_id
    ]
    contradicted_claims = [
        hypotheses_by_id[hypothesis_id]
        for hypothesis_id, report in run_state.get("verification_reports", {}).items()
        if report.get("verdict") in {"contradicted", "unsafe_or_out_of_scope"}
        and hypothesis_id in hypotheses_by_id
    ]
    plausible_unverified = [
        item
        for item in hypotheses
        if item["hypothesis_id"] not in run_state.get("verification_reports", {})
        and item.get("status") != "rejected"
    ]

    return {
        "run_id": run_id,
        "topic": run_state["topic"],
        "phase": run_state["phase"],
        "generation_session_id": run_state["generation_session_id"],
        "verification_session_id": run_state["verification_session_id"],
        "top_k": run_state["top_k"],
        "hypothesis_count": len(hypotheses),
        "selected_hypothesis_ids": list(run_state.get("selected_hypothesis_ids", [])),
        "verification_report_count": len(verification_reports),
        "hypotheses": hypotheses,
        "verification_reports": verification_reports,
        "verified_claims": verified_claims,
        "contradicted_claims": contradicted_claims,
        "plausible_unverified_hypotheses": plausible_unverified,
        "verification_input_artifact_id": run_state.get("verification_input_artifact_id"),
        "final_report_artifact_id": run_state.get("final_report_artifact_id"),
        "final_report_created_at": run_state.get("final_report_created_at"),
        "memory_summary_paths": list(run_state.get("memory_summary_paths", [])),
        "verification_policy": deepcopy(run_state["verification_policy"]),
        "state_locations": [
            {"session_id": record["session_id"], "role": record["role"], "version": record["version"]}
            for record in records
        ],
        "ready_for_synthesis": _selected_reports_complete(run_state),
    }


def validate_verification_report(
    report: Any,
    expected_hypothesis_id: Optional[str] = None,
) -> List[Dict[str, str]]:
    """Validate a verification report payload."""
    issues: List[Dict[str, str]] = []
    if not isinstance(report, dict):
        return [{"field": "verification_report", "message": "Must be an object", "severity": "error"}]

    required = (
        "hypothesis_id",
        "verdict",
        "confidence",
        "supporting_evidence",
        "disconfirming_evidence",
        "tests_or_reproduction_plan",
        "feasibility_notes",
        "safety_notes",
        "citations",
    )
    for field in required:
        if field not in report:
            issues.append({"field": field, "message": "Field is required", "severity": "error"})
    if issues:
        return issues

    if expected_hypothesis_id and report.get("hypothesis_id") != expected_hypothesis_id:
        issues.append({
            "field": "hypothesis_id",
            "message": "Report hypothesis_id must match the submitted hypothesis_id",
            "severity": "error",
        })
    if report.get("verdict") not in VERIFICATION_VERDICTS:
        issues.append({
            "field": "verdict",
            "message": f"Verdict must be one of: {sorted(VERIFICATION_VERDICTS)}",
            "severity": "error",
        })
    confidence = report.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        issues.append({"field": "confidence", "message": "Must be a number", "severity": "error"})
    elif not 0.0 <= float(confidence) <= 1.0:
        issues.append({"field": "confidence", "message": "Must be between 0.0 and 1.0", "severity": "error"})

    for field in ("supporting_evidence", "disconfirming_evidence", "citations"):
        _validate_non_empty_string_list(report.get(field), field, issues)
    for field in ("tests_or_reproduction_plan", "feasibility_notes", "safety_notes"):
        if not isinstance(report.get(field), str) or not report.get(field, "").strip():
            issues.append({"field": field, "message": "Must be a non-empty string", "severity": "error"})

    return issues


def _require_template(template_id: str) -> Dict[str, Any]:
    template = get_template(template_id)
    if template is None:
        raise CoScientistRunError(
            f"Required template '{template_id}' is not available",
            error_type="template_not_found",
        )
    return template


def _short_title(topic: str, max_len: int = 72) -> str:
    text = " ".join(topic.strip().split())
    return text if len(text) <= max_len else text[: max_len - 3].rstrip() + "..."


def _session_description(run_id: str, topic: str, constraints: List[str], role: str) -> str:
    payload = {
        "run_id": run_id,
        "role": role,
        "topic": topic.strip(),
        "constraints": constraints,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _rules_with_run(rules: Dict[str, Any], run_id: str, role: str) -> Dict[str, Any]:
    merged = dict(rules)
    merged["co_scientist_run_id"] = run_id
    merged["co_scientist_session_role"] = role
    return merged


def _announce_run_created(
    conn: sqlite3.Connection,
    sessions_dir: Path,
    run_state: Dict[str, Any],
    created_at: str,
) -> None:
    bus = MessageBus(conn, sessions_dir)
    bus.send(
        session_id=run_state["generation_session_id"],
        from_agent=run_state["generation_orchestrator_agent_id"],
        msg_type="system",
        content=(
            f"Co-Scientist run {run_state['run_id']} created. Generate hypothesis "
            "packets and submit them with submit_hypothesis."
        ),
        created_at=created_at,
        metadata={"run_id": run_state["run_id"], "role": "generation"},
    )
    bus.send(
        session_id=run_state["verification_session_id"],
        from_agent=run_state["verification_orchestrator_agent_id"],
        msg_type="system",
        content=(
            f"Co-Scientist run {run_state['run_id']} verification session linked. "
            "Wait for start_hypothesis_verification before adjudication."
        ),
        created_at=created_at,
        metadata={"run_id": run_state["run_id"], "role": "verification"},
    )


def _write_run_state_to_sessions(
    conn: sqlite3.Connection,
    run_state: Dict[str, Any],
    updated_by: str,
    updated_at: str,
) -> None:
    """Atomically write the same run blob into both linked sessions.

    Uses one transaction and CAS on both session versions so a conflict cannot
    leave generation updated while verification is stale (or the reverse).
    Callers that receive state_conflict must reload run state and retry.
    """
    targets: List[Tuple[str, str, Dict[str, Any], int]] = []
    for session_id, role in (
        (run_state["generation_session_id"], "generation"),
        (run_state["verification_session_id"], "verification"),
    ):
        row = collab_db.get_session_state(conn, session_id)
        if row is None:
            raise CoScientistRunError(
                f"Session state missing for {session_id}",
                error_type="state_not_found",
            )
        state = dict(row["state"])
        # Keep non-run session keys; only replace the co_scientist_run blob.
        state[RUN_STATE_KEY] = deepcopy(run_state)
        state["co_scientist_role"] = role
        state["co_scientist_linked_session_id"] = (
            run_state["verification_session_id"]
            if role == "generation"
            else run_state["generation_session_id"]
        )
        state["current_phase"] = f"co_scientist:{run_state['phase']}"
        state["last_activity"] = updated_at
        targets.append((session_id, role, state, int(row["version"])))

    try:
        with conn:
            for session_id, _role, state, expected_version in targets:
                cursor = conn.execute(
                    """
                    UPDATE session_state
                    SET state_json = ?, version = version + 1, updated_at = ?, updated_by = ?
                    WHERE session_id = ? AND version = ?
                    """,
                    (
                        json.dumps(state, ensure_ascii=False),
                        updated_at,
                        updated_by,
                        session_id,
                        expected_version,
                    ),
                )
                if cursor.rowcount != 1:
                    raise CoScientistRunError(
                        (
                            f"Failed to update Co-Scientist state for {session_id} "
                            f"(version conflict; reload run state and retry)"
                        ),
                        error_type="state_conflict",
                        issues=[
                            {
                                "field": "session_state",
                                "message": (
                                    f"CAS mismatch for {session_id}; expected version "
                                    f"{expected_version}"
                                ),
                                "severity": "error",
                            }
                        ],
                    )
                collab_db.touch_session(conn, session_id, updated_at)
    except CoScientistRunError:
        raise
    except Exception as exc:
        raise CoScientistRunError(
            f"Failed to update Co-Scientist run state: {exc}",
            error_type="state_write_error",
        ) from exc


def _load_run_state(
    conn: sqlite3.Connection,
    run_id: str,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    records = _find_run_records(conn, run_id)
    if not records:
        raise CoScientistRunError(
            f"Co-Scientist run {run_id} not found",
            error_type="not_found",
        )
    generation = next((record for record in records if record["role"] == "generation"), records[0])
    return deepcopy(generation["run_state"]), records


def _find_run_records(conn: sqlite3.Connection, run_id: str) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT session_id, state_json, version FROM session_state WHERE state_json LIKE ?",
        (f"%{run_id}%",),
    ).fetchall()
    records: List[Dict[str, Any]] = []
    for row in rows:
        try:
            state = json.loads(row["state_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        run_state = state.get(RUN_STATE_KEY)
        if isinstance(run_state, dict) and run_state.get("run_id") == run_id:
            records.append({
                "session_id": row["session_id"],
                "role": state.get("co_scientist_role"),
                "version": row["version"],
                "run_state": run_state,
            })
    return records


def _hypothesis_summary(
    packet: Dict[str, Any],
    artifact_id: str,
    created_at: str,
    created_by: str,
) -> Dict[str, Any]:
    scores = {field: float(packet[field]) for field in SCORE_FIELDS}
    ranked_score = score_hypothesis(packet)
    evidence = packet.get("evidence", [])
    return {
        "hypothesis_id": packet["hypothesis_id"],
        "title": packet["title"],
        "claim": packet["claim"],
        "status": packet["status"],
        "artifact_id": artifact_id,
        "scores": scores,
        "scoring_axes": ranked_score["axes"],
        "overall_score": ranked_score["base_score"],
        "citation_count": len(packet.get("citations", [])),
        "evidence_labels": sorted({
            item.get("label", "unlabeled")
            for item in evidence
            if isinstance(item, dict)
        }),
        "lineage": deepcopy(packet["lineage"]),
        "submitted_by": created_by,
        "submitted_at": created_at,
        "verification_status": None,
        "verification_report_artifact_id": None,
    }


def _select_hypothesis_ids(
    run_state: Dict[str, Any],
    hypothesis_ids: Optional[List[str]],
    top_k: Optional[int],
) -> List[str]:
    if hypothesis_ids:
        selected = list(dict.fromkeys(hypothesis_ids))
    else:
        limit = top_k or run_state.get("top_k") or 1
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise CoScientistRunError(
                "top_k must be an integer >= 1",
                error_type="validation_error",
            )
        ranked = sorted(
            run_state.get("hypotheses", {}).values(),
            key=lambda item: (-float(item.get("overall_score", 0.0)), item.get("hypothesis_id", "")),
        )
        selected = [
            item["hypothesis_id"]
            for item in ranked
            if item.get("status") != "rejected"
        ][:limit]

    if not selected:
        raise CoScientistRunError(
            "No hypotheses available for verification",
            error_type="validation_error",
        )
    missing = [hypothesis_id for hypothesis_id in selected if hypothesis_id not in run_state.get("hypotheses", {})]
    if missing:
        raise CoScientistRunError(
            f"Hypotheses not found in run: {', '.join(missing)}",
            error_type="not_found",
        )
    return selected


def _validate_handoff_grounding(
    conn: sqlite3.Connection,
    run_state: Dict[str, Any],
    packets: Iterable[Dict[str, Any]],
) -> List[Dict[str, str]]:
    issues: List[Dict[str, str]] = []
    for packet in packets:
        hypothesis_id = packet.get("hypothesis_id", "unknown")
        packet_issues = validate_hypothesis_grounding(
            packet,
            conn=conn,
            session_ids=[run_state["generation_session_id"], run_state["verification_session_id"]],
            workspace_root=Path.cwd(),
        )
        for issue in evidence_issues_to_dicts(packet_issues):
            issues.append({
                "field": f"hypotheses[{hypothesis_id}].{issue['field']}",
                "message": issue["message"],
                "severity": issue.get("severity", "error"),
            })
    return issues


def _load_hypothesis_packet(
    conn: sqlite3.Connection,
    sessions_dir: Path,
    run_state: Dict[str, Any],
    hypothesis_id: str,
) -> Dict[str, Any]:
    artifact_id = run_state["hypotheses"][hypothesis_id]["artifact_id"]
    content = ArtifactStore(conn, sessions_dir).get_content(
        artifact_id,
        session_id=run_state["generation_session_id"],
    )
    if content is None:
        raise CoScientistRunError(
            f"Hypothesis artifact {artifact_id} not found",
            error_type="artifact_not_found",
        )
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise CoScientistRunError(
            f"Hypothesis artifact {artifact_id} is not valid JSON: {exc}",
            error_type="artifact_invalid",
        ) from exc


def _selected_reports_complete(run_state: Dict[str, Any]) -> bool:
    selected = run_state.get("selected_hypothesis_ids", [])
    if not selected:
        return False
    reports = run_state.get("verification_reports", {})
    return all(hypothesis_id in reports for hypothesis_id in selected)


def _hypothesis_status_for_verdict(verdict: str) -> str:
    if verdict in {"contradicted", "unsafe_or_out_of_scope"}:
        return "rejected"
    return "verified"


def _complete_open_session_tasks(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    completed_at: str,
    description_markers: Optional[Iterable[str]] = None,
) -> List[Dict[str, Any]]:
    """Close matching open tasks when a Co-Scientist phase boundary is crossed.

    When description_markers is set, only tasks whose description contains one of
    the markers (case-insensitive) are completed. This avoids marking scout/critic
    plan steps done merely because verification handoff ran.
    """
    markers = [m.lower() for m in (description_markers or []) if m]
    completed: List[Dict[str, Any]] = []
    for task in collab_db.get_session_tasks(conn, session_id):
        if task.get("status") in {"completed", "cancelled"}:
            continue
        description = str(task.get("description") or "").lower()
        if markers and not any(marker in description for marker in markers):
            continue
        collab_db.update_task_status(
            conn,
            task["task_id"],
            "completed",
            completed_at=completed_at,
        )
        updated = dict(task)
        updated["status"] = "completed"
        updated["completed_at"] = completed_at
        completed.append(updated)
    return completed


def _require_run_actor(
    conn: sqlite3.Connection,
    run_state: Dict[str, Any],
    created_by: Optional[str],
    *,
    session_key: str,
    default_agent_key: str,
    action: str,
    require_orchestrator: bool = False,
    alternate_session_key: Optional[str] = None,
    alternate_default_agent_key: Optional[str] = None,
) -> str:
    """Ensure the acting agent is a real session member (and orchestrator if required).

    Accepts either a session agent_id or a model/name that matches agents.model
    (MCP often passes the original created_by model string).
    """
    requested = (created_by or "").strip()
    session_ids = [run_state[session_key]]
    if alternate_session_key:
        session_ids.append(run_state[alternate_session_key])

    if not requested:
        raise CoScientistRunError(
            f"{action} requires created_by (session agent_id or model name)",
            error_type="authorization_error",
            issues=[
                {
                    "field": "created_by",
                    "message": "created_by is required; do not omit (no orchestrator default)",
                    "severity": "error",
                }
            ],
        )

    candidates: List[str] = [requested]
    # Resolve model/name identifiers to concrete agent_ids in run sessions.
    for session_id in session_ids:
        for row in conn.execute(
            """
            SELECT agent_id, role, model, status
            FROM agents
            WHERE session_id = ? AND status = 'active'
              AND (agent_id = ? OR model = ?)
            ORDER BY CASE role WHEN 'orchestrator' THEN 0 ELSE 1 END
            """,
            (session_id, requested, requested),
        ).fetchall():
            agent_id = row["agent_id"] if isinstance(row, sqlite3.Row) else row[0]
            if agent_id not in candidates:
                candidates.append(agent_id)

    membership = None
    actor = candidates[0]
    last_error: Optional[Exception] = None
    for candidate in candidates:
        for session_id in session_ids:
            try:
                membership = verify_agent_in_session(
                    conn, candidate, session_id, require_active=True
                )
                actor = candidate
                break
            except (AgentNotFoundError, AgentNotAuthorizedError) as exc:
                last_error = exc
                continue
        if membership is not None:
            break

    if membership is None:
        raise CoScientistRunError(
            f"{action} denied: agent is not an active member of the Co-Scientist sessions",
            error_type="authorization_error",
            issues=[
                {
                    "field": "created_by",
                    "message": str(last_error) if last_error else f"Agent {requested or actor} is not authorized",
                    "severity": "error",
                }
            ],
        )

    if require_orchestrator:
        allowed = {
            run_state.get(default_agent_key),
            run_state.get(alternate_default_agent_key) if alternate_default_agent_key else None,
        }
        allowed.discard(None)
        if actor not in allowed and membership.get("role") != "orchestrator":
            raise CoScientistRunError(
                f"{action} requires a session orchestrator",
                error_type="authorization_error",
                issues=[
                    {
                        "field": "created_by",
                        "message": f"Agent {actor} is not an orchestrator for this run",
                        "severity": "error",
                    }
                ],
            )
    return actor


def _validate_non_empty_string_list(
    value: Any,
    field: str,
    issues: List[Dict[str, str]],
) -> None:
    if not isinstance(value, list) or not value:
        issues.append({"field": field, "message": "Must be a non-empty list", "severity": "error"})
        return
    for idx, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            issues.append({
                "field": f"{field}[{idx}]",
                "message": "Must be a non-empty string",
                "severity": "error",
            })
