from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
import json

from .settings import load_settings
from . import db
from .schema import (
    Finding,
    FindingAudit,
    FindingText,
    compute_content_hash,
    make_embedding_id,
    new_finding_id,
    utc_now_iso,
)
from .embeddings import EmbeddingCache, SentenceTransformerEmbedder
from .vector_store import create_vector_store, load_vector_store, save_vector_store
from .write_gate import WriteGate


def init_library(settings_path: Path) -> Dict[str, Any]:
    settings = load_settings(settings_path)
    settings.data_root.mkdir(parents=True, exist_ok=True)
    settings.findings_dir.mkdir(parents=True, exist_ok=True)

    conn = db.connect(settings.db_path)
    db.init_db(conn)
    conn.close()

    store = create_vector_store(settings.embedding_dim, settings.embedding_metric)
    save_vector_store(store, settings.vector_index_path, settings.vector_meta_path)

    return {
        "status": "ok",
        "message": "Initialized LMlib data layout and database",
        "db_path": str(settings.db_path),
        "vector_index_path": str(settings.vector_index_path),
    }


def _load_store(settings):
    store = load_vector_store(settings.vector_index_path, settings.vector_meta_path)
    if store.dim == 0:
        store = create_vector_store(settings.embedding_dim, settings.embedding_metric)
    return store


def _serialize_issues(issues) -> List[Dict[str, str]]:
    return [
        {"field": issue.field, "message": issue.message, "severity": issue.severity}
        for issue in issues
    ]


def add_finding(
    settings_path: Path,
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
) -> Dict[str, Any]:
    if not confirm:
        return {
            "status": "confirmation_required",
            "message": "Set confirm=true to add a finding.",
        }

    settings = load_settings(settings_path)
    settings.findings_dir.mkdir(parents=True, exist_ok=True)

    conn = db.connect(settings.db_path)
    db.init_db(conn)

    finding_id = finding_id or new_finding_id()
    embedding_id = make_embedding_id(finding_id)
    existing_id = db.get_finding_by_embedding_id(conn, embedding_id)
    if existing_id and existing_id != finding_id:
        conn.close()
        return {
            "status": "error",
            "message": "embedding_id collision detected. Try a different id.",
        }

    evidence = evidence or []
    tags = tags or []
    caveats = caveats or []

    cache = EmbeddingCache(settings.embeddings_cache_path)
    embedder = SentenceTransformerEmbedder(
        settings.embedding_model,
        cache=cache,
        normalize=settings.embedding_metric == "cosine",
    )
    store = _load_store(settings)

    gate = WriteGate(
        min_confidence=settings.write_gate.min_confidence,
        min_reasoning_length=settings.write_gate.min_reasoning_length,
        min_claim_evidence_sim=settings.write_gate.min_claim_evidence_sim,
        novelty_similarity_threshold=settings.novelty.similarity_threshold,
        novelty_top_k=settings.novelty.top_k,
        embedder=embedder,
        vector_store=store,
    )

    issues = gate.validate(claim, evidence, reasoning, confidence)
    issues_payload = _serialize_issues(issues)
    if not gate.is_allowed(issues):
        conn.close()
        return {
            "status": "rejected",
            "issues": issues_payload,
        }

    created_at = utc_now_iso()
    audit = FindingAudit(
        proposed_by=proposed_by,
        evidence_provided=bool(evidence),
        reasoning_length=len(reasoning.strip()),
        failure_log=[],
        confidence_history=[{"timestamp": created_at, "confidence": confidence, "reason": "initial"}],
    )
    text = FindingText(tags=tags, evidence=evidence, caveats=caveats, reasoning=reasoning)

    finding = Finding(
        id=finding_id,
        project=project,
        claim=claim,
        confidence=confidence,
        created_at=created_at,
        embedding_id=embedding_id,
        content_hash="",
        status="active",
        text=text,
        audit=audit,
        full_text=full_text,
    )
    finding.content_hash = compute_content_hash(finding.to_content_dict(include_hash=False))

    json_path = settings.findings_dir / f"{finding.id}.json"
    try:
        json_path.write_text(
            json.dumps(finding.to_content_dict(), indent=2),
            encoding="utf-8",
        )
        db.insert_finding(conn, finding)
        evidence_text = " ".join(finding.text.evidence)
        embedding_text = f"{finding.claim}\n{evidence_text}"
        embedding_vec = embedder.encode([embedding_text])[0]
        store.add([finding.embedding_id], [embedding_vec])
        save_vector_store(store, settings.vector_index_path, settings.vector_meta_path)
        cache.save()
    except Exception as exc:
        db.delete_finding(conn, finding.id)
        try:
            store.delete([finding.embedding_id])
            save_vector_store(store, settings.vector_index_path, settings.vector_meta_path)
        except Exception:
            pass
        if json_path.exists():
            json_path.unlink()
        conn.close()
        return {
            "status": "error",
            "message": f"failed to add finding: {exc}",
            "issues": issues_payload,
        }
    finally:
        conn.close()

    return {
        "status": "ok",
        "id": finding.id,
        "issues": issues_payload,
    }


def list_findings(settings_path: Path, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
    settings = load_settings(settings_path)
    conn = db.connect(settings.db_path)
    db.init_db(conn)
    rows = db.list_findings(conn, limit=limit, offset=offset)
    conn.close()
    return {"status": "ok", "items": rows}


def get_finding(settings_path: Path, finding_id: str) -> Dict[str, Any]:
    settings = load_settings(settings_path)
    conn = db.connect(settings.db_path)
    db.init_db(conn)
    finding = db.get_finding(conn, finding_id)
    conn.close()

    if finding is None:
        return {"status": "not_found"}

    return {"status": "ok", "finding": finding.to_content_dict()}


def search_fts(settings_path: Path, query: str, limit: int = 10) -> Dict[str, Any]:
    settings = load_settings(settings_path)
    conn = db.connect(settings.db_path)
    db.init_db(conn)
    results = db.search_findings(conn, query, limit=limit)
    conn.close()
    return {"status": "ok", "items": results}


def delete_finding(settings_path: Path, finding_id: str, confirm: bool = False) -> Dict[str, Any]:
    if not confirm:
        return {
            "status": "confirmation_required",
            "message": "Set confirm=true to delete a finding.",
        }

    settings = load_settings(settings_path)
    conn = db.connect(settings.db_path)
    db.init_db(conn)
    finding = db.get_finding(conn, finding_id)
    if finding is None:
        conn.close()
        return {"status": "not_found"}

    json_path = settings.findings_dir / f"{finding.id}.json"
    try:
        db.delete_finding(conn, finding.id)
        if json_path.exists():
            json_path.unlink()
        store = _load_store(settings)
        store.delete([finding.embedding_id])
        save_vector_store(store, settings.vector_index_path, settings.vector_meta_path)
    except Exception as exc:
        conn.close()
        return {"status": "error", "message": f"failed to delete finding: {exc}"}
    finally:
        conn.close()

    return {"status": "ok", "id": finding.id}


def health(settings_path: Path) -> Dict[str, Any]:
    settings = load_settings(settings_path)
    status = {
        "db_path": str(settings.db_path),
        "findings_dir": str(settings.findings_dir),
        "vector_index_path": str(settings.vector_index_path),
        "vector_meta_path": str(settings.vector_meta_path),
    }

    if not settings.db_path.exists():
        status["db_exists"] = False
        return {"status": "ok", "health": status}

    conn = db.connect(settings.db_path)
    db.init_db(conn)
    row = conn.execute("SELECT COUNT(*) AS count FROM findings").fetchone()
    conn.close()
    status["db_exists"] = True
    status["findings_count"] = int(row["count"]) if row else 0

    if settings.vector_meta_path.exists():
        store = load_vector_store(settings.vector_index_path, settings.vector_meta_path)
        status["vector_backend"] = store.backend
        status["vector_count"] = store.count()
        status["vector_dim"] = store.dim
    else:
        status["vector_backend"] = "none"
        status["vector_count"] = 0
        status["vector_dim"] = 0

    return {"status": "ok", "health": status}
