"""Final reporting and verified-finding export for Co-Scientist runs."""

from __future__ import annotations

import json
import sqlite3
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from openlmlib.collab.artifact_store import ArtifactStore
from openlmlib.collab.message_bus import MessageBus
from openlmlib.library import add_finding
from openlmlib.schema import utc_now_iso

from .orchestrator import (
    CoScientistRunError,
    _load_hypothesis_packet,
    _load_run_state,
    _selected_reports_complete,
    _write_run_state_to_sessions,
)


FINAL_REPORT_ARTIFACT_TYPE = "co_scientist_report"
SUPPORTED_EXPORT_VERDICTS = frozenset({"supported", "partially_supported"})
REJECTED_REPORT_VERDICTS = frozenset({"contradicted", "unsafe_or_out_of_scope"})


def create_final_report(
    conn: sqlite3.Connection,
    sessions_dir: Path,
    run_id: str,
    *,
    created_by: Optional[str] = None,
    created_at: Optional[str] = None,
    mark_complete: bool = True,
) -> Dict[str, Any]:
    """Create a final Co-Scientist report artifact for a completed verification run."""
    run_state, _ = _load_run_state(conn, run_id)
    if not _selected_reports_complete(run_state):
        raise CoScientistRunError(
            "Cannot create final report before selected hypotheses have verification reports",
            error_type="run_not_ready",
            issues=[
                {
                    "field": "verification_reports",
                    "message": "All selected hypotheses must have verification reports",
                    "severity": "error",
                }
            ],
        )

    created_at = created_at or utc_now_iso()
    actor = created_by or run_state["verification_orchestrator_agent_id"]
    existing_artifact_id = run_state.get("final_report_artifact_id")
    if existing_artifact_id:
        store = ArtifactStore(conn, sessions_dir)
        existing = store.get_artifact(run_state["verification_session_id"], existing_artifact_id)
        if mark_complete and run_state.get("phase") != "complete":
            run_state["phase"] = "complete"
            run_state["updated_at"] = created_at
            _write_run_state_to_sessions(conn, run_state, updated_by=actor, updated_at=created_at)
        return {
            "run_id": run_id,
            "phase": run_state["phase"],
            "final_report_artifact_id": existing_artifact_id,
            "final_report_path": existing.get("file_path") if existing else None,
            "memory_summary_paths": list(run_state.get("memory_summary_paths", [])),
            "verified_claim_count": len(get_supported_hypothesis_ids(run_state)),
            "rejected_hypothesis_count": len(get_rejected_hypothesis_ids(run_state)),
            "remaining_unknown_count": len(get_remaining_unknown_hypothesis_ids(run_state)),
            "existing": True,
        }
    report_payload = synthesize_final_report_payload(conn, sessions_dir, run_state)
    markdown = render_final_report_markdown(report_payload)

    store = ArtifactStore(conn, sessions_dir)
    artifact = store.save(
        session_id=run_state["verification_session_id"],
        created_by=actor,
        title=f"Co-Scientist Final Report {run_id}",
        content=markdown,
        created_at=created_at,
        artifact_type=FINAL_REPORT_ARTIFACT_TYPE,
        tags=["co_scientist", f"run_id:{run_id}", "final_report"],
        shared=True,
    )

    memory_summary = render_run_memory_summary(report_payload)
    memory_paths = [
        store.save_summary(run_state["generation_session_id"], memory_summary, created_at),
        store.save_summary(run_state["verification_session_id"], memory_summary, created_at),
    ]

    run_state["final_report_artifact_id"] = artifact["artifact_id"]
    run_state["final_report_created_at"] = created_at
    run_state["memory_summary_paths"] = memory_paths
    if mark_complete:
        run_state["phase"] = "complete"
    run_state["updated_at"] = created_at
    _write_run_state_to_sessions(conn, run_state, updated_by=actor, updated_at=created_at)

    MessageBus(conn, sessions_dir).send(
        session_id=run_state["verification_session_id"],
        from_agent=actor,
        msg_type="artifact",
        content=f"Co-Scientist final report created for {run_id}: {artifact['artifact_id']}",
        created_at=created_at,
        metadata={
            "run_id": run_id,
            "artifact_id": artifact["artifact_id"],
            "artifact_type": FINAL_REPORT_ARTIFACT_TYPE,
        },
    )

    return {
        "run_id": run_id,
        "phase": run_state["phase"],
        "final_report_artifact_id": artifact["artifact_id"],
        "final_report_path": artifact["file_path"],
        "memory_summary_paths": memory_paths,
        "verified_claim_count": len(report_payload["best_supported_hypotheses"]),
        "rejected_hypothesis_count": len(report_payload["rejected_hypotheses"]),
        "remaining_unknown_count": len(report_payload["remaining_unknowns"]),
    }


def synthesize_final_report_payload(
    conn: sqlite3.Connection,
    sessions_dir: Path,
    run_state: Dict[str, Any],
) -> Dict[str, Any]:
    """Build a deterministic final report payload from run state and artifacts."""
    packets, reports = _load_run_payloads(conn, sessions_dir, run_state)
    hypotheses = [
        deepcopy(run_state["hypotheses"][hypothesis_id])
        for hypothesis_id in run_state.get("hypothesis_ids", [])
        if hypothesis_id in run_state.get("hypotheses", {})
    ]
    ranked = sorted(
        hypotheses,
        key=lambda item: (-float(item.get("overall_score", 0.0)), item.get("hypothesis_id", "")),
    )

    verdict_rows = []
    best_supported = []
    rejected = []
    remaining_unknowns = []
    suggested_next_steps: List[str] = []
    safety_notes: List[str] = []

    for hypothesis in ranked:
        hypothesis_id = hypothesis["hypothesis_id"]
        packet = packets.get(hypothesis_id, {})
        report = reports.get(hypothesis_id)
        row = {
            "hypothesis_id": hypothesis_id,
            "title": hypothesis.get("title"),
            "claim": hypothesis.get("claim"),
            "overall_score": hypothesis.get("overall_score"),
            "artifact_id": hypothesis.get("artifact_id"),
            "verdict": report.get("verdict") if report else None,
            "confidence": report.get("confidence") if report else None,
            "verification_report_artifact_id": hypothesis.get("verification_report_artifact_id"),
        }
        verdict_rows.append(row)
        safety_notes.extend(str(item) for item in packet.get("safety_notes", []) if str(item).strip())

        if report and report.get("verdict") in SUPPORTED_EXPORT_VERDICTS:
            best_supported.append({
                **row,
                "supporting_evidence": list(report.get("supporting_evidence", [])),
                "citations": list(report.get("citations", [])),
                "tests_or_reproduction_plan": report.get("tests_or_reproduction_plan", ""),
            })
            if report.get("tests_or_reproduction_plan"):
                suggested_next_steps.append(str(report["tests_or_reproduction_plan"]).strip())
        elif report and report.get("verdict") in REJECTED_REPORT_VERDICTS:
            rejected.append({
                **row,
                "reason": "; ".join(str(item) for item in report.get("disconfirming_evidence", []))
                or report.get("safety_notes", "")
                or "Rejected by verification verdict.",
            })
        else:
            remaining_unknowns.append({
                **row,
                "reason": "No supported verification verdict was recorded.",
            })

    return {
        "run_id": run_state["run_id"],
        "topic": run_state["topic"],
        "constraints": list(run_state.get("constraints", [])),
        "phase": run_state["phase"],
        "generation_session_id": run_state["generation_session_id"],
        "verification_session_id": run_state["verification_session_id"],
        "hypothesis_count": len(hypotheses),
        "selected_hypothesis_ids": list(run_state.get("selected_hypothesis_ids", [])),
        "ranked_hypotheses": ranked,
        "verification_verdicts": verdict_rows,
        "best_supported_hypotheses": best_supported,
        "rejected_hypotheses": rejected,
        "remaining_unknowns": remaining_unknowns,
        "suggested_next_experiments": _dedupe_non_empty(suggested_next_steps),
        "safety_and_scope_notes": _dedupe_non_empty([
            *safety_notes,
            *run_state.get("scope_decision", {}).get("required_approvals", []),
            *run_state.get("scope_decision", {}).get("reasons", []),
        ]),
        "scope_decision": deepcopy(run_state.get("scope_decision", {})),
    }


def render_final_report_markdown(report: Dict[str, Any]) -> str:
    """Render a final report payload as markdown."""
    lines = [
        f"# Co-Scientist Final Report: {report['run_id']}",
        "",
        "## Research Objective",
        report["topic"],
        "",
        "## Generation Session Summary",
        f"- Generation session: `{report['generation_session_id']}`",
        f"- Verification session: `{report['verification_session_id']}`",
        f"- Generated hypotheses: {report['hypothesis_count']}",
        f"- Selected for verification: {len(report['selected_hypothesis_ids'])}",
        "",
        "## Ranked Hypotheses",
    ]
    for item in report["ranked_hypotheses"]:
        lines.append(
            f"- `{item['hypothesis_id']}` score={float(item.get('overall_score', 0.0)):.3f}: {item['title']}"
        )

    lines.extend(["", "## Verification Verdicts"])
    for item in report["verification_verdicts"]:
        verdict = item.get("verdict") or "unverified"
        confidence = item.get("confidence")
        confidence_text = "" if confidence is None else f" confidence={float(confidence):.2f}"
        lines.append(f"- `{item['hypothesis_id']}` {verdict}{confidence_text}: {item['claim']}")

    lines.extend(["", "## Best-Supported Hypotheses"])
    if report["best_supported_hypotheses"]:
        for item in report["best_supported_hypotheses"]:
            lines.append(f"- `{item['hypothesis_id']}` {item['verdict']}: {item['claim']}")
    else:
        lines.append("- None.")

    lines.extend(["", "## Rejected Hypotheses And Why"])
    if report["rejected_hypotheses"]:
        for item in report["rejected_hypotheses"]:
            lines.append(f"- `{item['hypothesis_id']}` {item['verdict']}: {item['reason']}")
    else:
        lines.append("- None.")

    lines.extend(["", "## Remaining Unknowns"])
    if report["remaining_unknowns"]:
        for item in report["remaining_unknowns"]:
            lines.append(f"- `{item['hypothesis_id']}`: {item['reason']}")
    else:
        lines.append("- None.")

    lines.extend(["", "## Suggested Next Experiments Or Implementation Steps"])
    if report["suggested_next_experiments"]:
        for item in report["suggested_next_experiments"]:
            lines.append(f"- {item}")
    else:
        lines.append("- None.")

    lines.extend(["", "## Safety And Scope Notes"])
    if report["safety_and_scope_notes"]:
        for item in report["safety_and_scope_notes"]:
            lines.append(f"- {item}")
    else:
        lines.append("- No additional safety notes recorded.")

    return "\n".join(lines).strip() + "\n"


def render_run_memory_summary(report: Dict[str, Any]) -> str:
    """Render a compact run summary for future session recall."""
    supported = ", ".join(
        f"{item['hypothesis_id']}:{item['verdict']}"
        for item in report["best_supported_hypotheses"]
    ) or "none"
    rejected = ", ".join(
        f"{item['hypothesis_id']}:{item['verdict']}"
        for item in report["rejected_hypotheses"]
    ) or "none"
    unknown = ", ".join(item["hypothesis_id"] for item in report["remaining_unknowns"]) or "none"
    return "\n".join([
        f"Co-Scientist run {report['run_id']}: {report['topic']}",
        f"Supported: {supported}",
        f"Rejected: {rejected}",
        f"Remaining unknowns: {unknown}",
        f"Generation session: {report['generation_session_id']}",
        f"Verification session: {report['verification_session_id']}",
    ])


def export_supported_findings(
    settings_path: Path,
    conn: sqlite3.Connection,
    sessions_dir: Path,
    run_id: str,
    *,
    project: Optional[str] = None,
    tags: Optional[List[str]] = None,
    proposed_by: Optional[str] = None,
) -> Dict[str, Any]:
    """Export only supported Co-Scientist claims into the main library."""
    run_state, _ = _load_run_state(conn, run_id)
    packets, reports = _load_run_payloads(conn, sessions_dir, run_state)
    base_tags = list(tags or [])
    project_name = project or f"Co-Scientist: {run_state['topic']}"
    exported: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []

    for hypothesis_id in run_state.get("selected_hypothesis_ids", []):
        summary = run_state.get("hypotheses", {}).get(hypothesis_id, {})
        report = reports.get(hypothesis_id)
        packet = packets.get(hypothesis_id, {})
        if not report:
            skipped.append({"hypothesis_id": hypothesis_id, "reason": "missing verification report"})
            continue
        verdict = report.get("verdict")
        if verdict not in SUPPORTED_EXPORT_VERDICTS:
            skipped.append({"hypothesis_id": hypothesis_id, "verdict": verdict, "reason": "not a supported claim"})
            continue

        confidence = _export_confidence(verdict, report.get("confidence", 0.0))
        evidence = _export_evidence(packet, report)
        reasoning = _export_reasoning(run_state, summary, report)
        try:
            result = add_finding(
                settings_path=settings_path,
                project=project_name,
                claim=summary.get("claim") or packet.get("claim") or hypothesis_id,
                confidence=confidence,
                evidence=evidence,
                reasoning=reasoning,
                caveats=list(report.get("disconfirming_evidence", [])),
                tags=_dedupe_non_empty([
                    *base_tags,
                    "co_scientist",
                    f"run:{run_id}",
                    f"hypothesis:{hypothesis_id}",
                    f"verdict:{verdict}",
                ]),
                full_text=json.dumps(
                    {
                        "run_id": run_id,
                        "hypothesis_packet": packet,
                        "verification_report": report,
                    },
                    indent=2,
                    sort_keys=True,
                ),
                proposed_by=proposed_by or report.get("created_by") or run_state.get("created_by", "co_scientist"),
                confirm=True,
            )
        except Exception as exc:
            failed.append({"hypothesis_id": hypothesis_id, "reason": str(exc)})
            continue

        if result.get("status") == "ok":
            exported.append({
                "hypothesis_id": hypothesis_id,
                "finding_id": result.get("id"),
                "confidence": result.get("confidence", confidence),
                "verdict": verdict,
            })
        else:
            failed.append({
                "hypothesis_id": hypothesis_id,
                "status": result.get("status"),
                "reason": result.get("message") or result.get("error") or "export rejected",
            })

    return {
        "run_id": run_id,
        "project": project_name,
        "exported": len(exported),
        "failed": len(failed),
        "skipped": skipped,
        "findings": exported,
        "failures": failed,
    }


def get_supported_hypothesis_ids(run_state: Dict[str, Any]) -> List[str]:
    return [
        hypothesis_id
        for hypothesis_id, report in run_state.get("verification_reports", {}).items()
        if report.get("verdict") in SUPPORTED_EXPORT_VERDICTS
    ]


def get_rejected_hypothesis_ids(run_state: Dict[str, Any]) -> List[str]:
    return [
        hypothesis_id
        for hypothesis_id, report in run_state.get("verification_reports", {}).items()
        if report.get("verdict") in REJECTED_REPORT_VERDICTS
    ]


def get_remaining_unknown_hypothesis_ids(run_state: Dict[str, Any]) -> List[str]:
    reports = run_state.get("verification_reports", {})
    return [
        hypothesis_id
        for hypothesis_id in run_state.get("hypothesis_ids", [])
        if reports.get(hypothesis_id, {}).get("verdict") not in SUPPORTED_EXPORT_VERDICTS
        and reports.get(hypothesis_id, {}).get("verdict") not in REJECTED_REPORT_VERDICTS
    ]


def _load_run_payloads(
    conn: sqlite3.Connection,
    sessions_dir: Path,
    run_state: Dict[str, Any],
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    packets: Dict[str, Dict[str, Any]] = {}
    for hypothesis_id in run_state.get("hypothesis_ids", []):
        packets[hypothesis_id] = _load_hypothesis_packet(conn, sessions_dir, run_state, hypothesis_id)

    reports: Dict[str, Dict[str, Any]] = {}
    store = ArtifactStore(conn, sessions_dir)
    for hypothesis_id, summary in run_state.get("verification_reports", {}).items():
        artifact_id = summary.get("artifact_id")
        if not artifact_id:
            continue
        content = store.get_content(
            artifact_id,
            session_id=run_state["verification_session_id"],
        )
        if content is None:
            continue
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            payload = dict(summary)
        payload.setdefault("artifact_id", artifact_id)
        payload.setdefault("created_by", summary.get("created_by"))
        payload.setdefault("created_at", summary.get("created_at"))
        reports[hypothesis_id] = payload
    return packets, reports


def _export_confidence(verdict: str, confidence: Any) -> float:
    try:
        value = max(0.0, min(1.0, float(confidence)))
    except (TypeError, ValueError):
        value = 0.6
    if verdict == "partially_supported":
        return min(value, 0.75)
    return min(value, 0.9)


def _export_evidence(packet: Dict[str, Any], report: Dict[str, Any]) -> List[str]:
    evidence = [str(item) for item in report.get("supporting_evidence", []) if str(item).strip()]
    citations = [str(item) for item in report.get("citations", []) if str(item).strip()]
    packet_sources = [
        f"{item.get('source')}: {item.get('summary')}"
        for item in packet.get("evidence", [])
        if isinstance(item, dict) and item.get("source") and item.get("summary")
    ]
    return _dedupe_non_empty([*evidence, *packet_sources, *citations])


def _export_reasoning(
    run_state: Dict[str, Any],
    summary: Dict[str, Any],
    report: Dict[str, Any],
) -> str:
    return "\n".join([
        f"Exported from Co-Scientist run {run_state['run_id']} on topic: {run_state['topic']}.",
        f"Hypothesis: {summary.get('title', report.get('hypothesis_id', 'unknown'))}.",
        f"Verdict: {report.get('verdict')} at confidence {report.get('confidence')}.",
        f"Tests or reproduction plan: {report.get('tests_or_reproduction_plan', '')}",
        f"Feasibility notes: {report.get('feasibility_notes', '')}",
        f"Safety notes: {report.get('safety_notes', '')}",
    ])


def _dedupe_non_empty(items: List[Any]) -> List[str]:
    result: List[str] = []
    seen = set()
    for item in items:
        text = str(item).strip()
        if not text or text in seen:
            continue
        result.append(text)
        seen.add(text)
    return result
