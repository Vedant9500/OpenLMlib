from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
import json
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone

from .settings import load_settings, write_default_settings
from . import db
from .schema import (
    Finding,
    FindingAudit,
    FindingText,
    ValidationIssue,
    compute_content_hash,
    make_embedding_id,
    new_finding_id,
    utc_now_iso,
)
from .embeddings import EmbeddingCache, SentenceTransformerEmbedder
from .embeddings import build_contextual_chunk
from .retrieval import RetrievalEngine, RetrievalFilters
from .sanitization import render_untrusted_context
from .evaluation import evaluate_retrieval, faithfulness_score, relevance_alignment
from .runtime import get_runtime, mark_dirty, maybe_flush
from .vector_store import create_vector_store, load_vector_store, save_vector_store
from .write_gate import WriteGate


def init_library(settings_path: Path) -> Dict[str, Any]:
    write_default_settings(settings_path)
    settings = load_settings(settings_path)
    settings.data_root.mkdir(parents=True, exist_ok=True)
    settings.findings_dir.mkdir(parents=True, exist_ok=True)

    conn = db.connect(settings.db_path)
    db.init_db(conn)
    conn.close()

    if not settings.vector_index_path.exists() or not settings.vector_meta_path.exists():
        store = create_vector_store(settings.embedding_dim, settings.embedding_metric)
        save_vector_store(store, settings.vector_index_path, settings.vector_meta_path)

    return {
        "status": "ok",
        "message": "Initialized OpenLMlib data layout and database",
        "db_path": str(settings.db_path),
        "vector_index_path": str(settings.vector_index_path),
    }


def rebuild_vector_index(settings_path: Path) -> Dict[str, Any]:
    settings = load_settings(settings_path)
    conn = db.connect(settings.db_path)
    db.init_db(conn)

    cache = EmbeddingCache(settings.embeddings_cache_path)
    embedder = SentenceTransformerEmbedder(
        settings.embedding_model,
        cache=cache,
        normalize=settings.embedding_metric == "cosine",
    )

    store = create_vector_store(settings.embedding_dim, settings.embedding_metric)
    rows = conn.execute("SELECT id FROM findings ORDER BY created_at ASC").fetchall()

    rebuilt = 0
    skipped = 0
    for row in rows:
        finding = db.get_finding(conn, row["id"])
        if finding is None:
            skipped += 1
            continue
        _hydrate_finding_from_json(settings, finding)
        embedding_text = build_contextual_chunk(
            claim=finding.claim,
            evidence=finding.text.evidence,
            reasoning=finding.text.reasoning,
            full_text=finding.full_text,
        )
        vec = embedder.encode([embedding_text])[0]
        store.add([finding.embedding_id], [vec])
        rebuilt += 1

    save_vector_store(store, settings.vector_index_path, settings.vector_meta_path)
    cache.save()
    conn.close()

    return {
        "status": "ok",
        "rebuilt": rebuilt,
        "skipped": skipped,
        "vector_backend": store.backend,
        "vector_count": store.count(),
    }


def _backup_dir_name(prefix: str = "backup") -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
    return f"{prefix}-{ts}"


def backup_library(settings_path: Path, output_dir: Optional[Path] = None) -> Dict[str, Any]:
    settings = load_settings(settings_path)
    root = output_dir or (settings.data_root / "backups")
    backup_dir = root / _backup_dir_name("openlmlib")
    backup_dir.mkdir(parents=True, exist_ok=False)

    copied_files: List[str] = []
    copied_dirs: List[str] = []

    if settings.db_path.exists():
        # Use SQLite Online Backup API for WAL-mode safety.
        # This creates a consistent snapshot even with concurrent connections,
        # without needing to checkpoint or copy -wal/-shm companion files.
        db_dest = backup_dir / "findings.db"
        try:
            src_conn = sqlite3.connect(str(settings.db_path))
            dest_conn = sqlite3.connect(str(db_dest))
            try:
                src_conn.backup(dest_conn)
            finally:
                dest_conn.close()
                src_conn.close()
        except sqlite3.DatabaseError:
            # Fallback for corrupted or non-SQLite files — copy raw bytes.
            shutil.copy2(settings.db_path, db_dest)
        copied_files.append(str(db_dest))

    if settings.vector_index_path.exists():
        vec_dest = backup_dir / settings.vector_index_path.name
        shutil.copy2(settings.vector_index_path, vec_dest)
        copied_files.append(str(vec_dest))

    if settings.vector_meta_path.exists():
        meta_dest = backup_dir / settings.vector_meta_path.name
        shutil.copy2(settings.vector_meta_path, meta_dest)
        copied_files.append(str(meta_dest))

    if settings.embeddings_cache_path.exists():
        cache_dest = backup_dir / settings.embeddings_cache_path.name
        shutil.copy2(settings.embeddings_cache_path, cache_dest)
        copied_files.append(str(cache_dest))

    if settings.findings_dir.exists():
        findings_dest = backup_dir / "findings"
        shutil.copytree(settings.findings_dir, findings_dest)
        copied_dirs.append(str(findings_dest))

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "settings_path": str(settings_path),
        "copied_files": copied_files,
        "copied_dirs": copied_dirs,
    }
    manifest_path = backup_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return {
        "status": "ok",
        "backup_dir": str(backup_dir),
        "manifest": str(manifest_path),
        "files": copied_files,
        "dirs": copied_dirs,
    }


def restore_library(
    settings_path: Path,
    backup_dir: Path,
    confirm: bool = False,
    create_pre_restore_backup: bool = True,
) -> Dict[str, Any]:
    if not confirm:
        return {
            "status": "confirmation_required",
            "message": "Set confirm=true to restore library data.",
        }

    settings = load_settings(settings_path)
    if not backup_dir.exists() or not backup_dir.is_dir():
        return {"status": "error", "message": "Backup directory does not exist."}

    manifest_path = backup_dir / "manifest.json"
    if not manifest_path.exists():
        return {"status": "error", "message": "manifest.json not found in backup directory."}

    pre_restore = None
    if create_pre_restore_backup:
        pre_restore = backup_library(settings_path)

    settings.data_root.mkdir(parents=True, exist_ok=True)
    settings.findings_dir.parent.mkdir(parents=True, exist_ok=True)

    mapping = [
        (backup_dir / "findings.db", settings.db_path),
        (backup_dir / settings.vector_index_path.name, settings.vector_index_path),
        (backup_dir / settings.vector_meta_path.name, settings.vector_meta_path),
        (backup_dir / settings.embeddings_cache_path.name, settings.embeddings_cache_path),
    ]

    restored_files: List[str] = []
    for source, target in mapping:
        if source.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            restored_files.append(str(target))

    findings_source = backup_dir / "findings"
    if findings_source.exists() and findings_source.is_dir():
        if settings.findings_dir.exists():
            shutil.rmtree(settings.findings_dir)
        shutil.copytree(findings_source, settings.findings_dir)

    # Invalidate the cached runtime so the next get_runtime() creates fresh
    # connections to the restored files on disk.
    from .runtime import shutdown_runtime
    shutdown_runtime(settings_path)

    return {
        "status": "ok",
        "restored_from": str(backup_dir),
        "restored_files": restored_files,
        "pre_restore_backup": pre_restore,
    }


def _load_store(settings):
    store = load_vector_store(settings.vector_index_path, settings.vector_meta_path)
    if store.dim == 0:
        store = create_vector_store(settings.embedding_dim, settings.embedding_metric)
    return store


def _hydrate_finding_from_json(settings, finding: Finding) -> Finding:
    if finding.full_text:
        return finding

    json_path = settings.findings_dir / f"{finding.id}.json"
    if not json_path.exists():
        return finding

    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return finding

    full_text = payload.get("full_text")
    if isinstance(full_text, str):
        finding.full_text = full_text
    return finding


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

    runtime = get_runtime(settings_path)
    settings = runtime.settings
    conn = runtime.conn
    settings.findings_dir.mkdir(parents=True, exist_ok=True)

    finding_id = finding_id or new_finding_id()
    embedding_id = make_embedding_id(finding_id)
    existing_id = db.get_finding_by_embedding_id(conn, embedding_id)
    if existing_id and existing_id != finding_id:
        return {
            "status": "error",
            "message": "embedding_id collision detected. Try a different id.",
        }

    evidence = evidence or []
    tags = tags or []
    caveats = caveats or []

    embedder = runtime.embedder
    store = runtime.store

    gate = WriteGate(
        min_confidence=settings.write_gate.min_confidence,
        min_reasoning_length=settings.write_gate.min_reasoning_length,
        min_claim_evidence_sim=settings.write_gate.min_claim_evidence_sim,
        novelty_similarity_threshold=settings.novelty.similarity_threshold,
        novelty_top_k=settings.novelty.top_k,
        embedder=embedder,
        vector_store=store,
        finding_lookup=lambda embedding_id: db.get_findings_by_embedding_ids(conn, [embedding_id]).get(embedding_id),
    )

    with runtime.write_lock:
        issues = gate.validate(claim, evidence, reasoning, confidence)
    adjusted_confidence = gate.adjust_confidence(
        claim=claim,
        evidence=evidence,
        proposed_confidence=confidence,
        issues=issues,
    )
    if adjusted_confidence < settings.write_gate.min_confidence:
        issues.append(
            ValidationIssue(
                field="confidence",
                message=(
                    "Validator-adjusted confidence "
                    f"{adjusted_confidence:.2f} below threshold {settings.write_gate.min_confidence:.2f}"
                ),
            )
        )
    issues_payload = _serialize_issues(issues)
    if not gate.is_allowed(issues):
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
        confidence_history=[
            {"timestamp": created_at, "confidence": confidence, "reason": "proposed"},
            {"timestamp": created_at, "confidence": adjusted_confidence, "reason": "validator_adjusted"},
        ],
    )
    text = FindingText(tags=tags, evidence=evidence, caveats=caveats, reasoning=reasoning)

    finding = Finding(
        id=finding_id,
        project=project,
        claim=claim,
        confidence=adjusted_confidence,
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
        embedding_text = build_contextual_chunk(
            claim=finding.claim,
            evidence=finding.text.evidence,
            reasoning=finding.text.reasoning,
            full_text=finding.full_text,
        )
        embedding_vec = embedder.encode([embedding_text])[0]

        json_path.write_text(
            json.dumps(finding.to_content_dict(), indent=2),
            encoding="utf-8",
        )
        with runtime.write_lock:
            db.insert_finding(conn, finding)
            store.add([finding.embedding_id], [embedding_vec])
            mark_dirty(runtime, vector=True, cache=True)
            maybe_flush(runtime)
    except Exception as exc:
        with runtime.write_lock:
            db.delete_finding(conn, finding.id)
        try:
            with runtime.write_lock:
                store.delete([finding.embedding_id])
                mark_dirty(runtime, vector=True)
                maybe_flush(runtime, force=True)
        except Exception:
            pass
        if json_path.exists():
            json_path.unlink()
        return {
            "status": "error",
            "message": f"failed to add finding: {exc}",
            "issues": issues_payload,
        }

    return {
        "status": "ok",
        "id": finding.id,
        "confidence": finding.confidence,
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

    _hydrate_finding_from_json(settings, finding)
    return {"status": "ok", "finding": finding.to_content_dict()}


def search_fts(settings_path: Path, query: str, limit: int = 10) -> Dict[str, Any]:
    settings = load_settings(settings_path)
    conn = db.connect(settings.db_path)
    db.init_db(conn)
    results = db.search_findings(conn, query, limit=limit)
    conn.close()
    return {"status": "ok", "items": results}


def retrieve_findings(
    settings_path: Path,
    query: str,
    project: Optional[str] = None,
    tags: Optional[List[str]] = None,
    created_after: Optional[str] = None,
    created_before: Optional[str] = None,
    confidence_min: Optional[float] = None,
    semantic_k: Optional[int] = None,
    lexical_k: Optional[int] = None,
    final_k: Optional[int] = None,
) -> Dict[str, Any]:
    runtime = get_runtime(settings_path)
    settings = runtime.settings
    conn = runtime.conn
    embedder = runtime.embedder
    store = runtime.store
    engine = RetrievalEngine(conn=conn, embedder=embedder, vector_store=store, settings=settings)

    with runtime.write_lock:
        payload = engine.search(
            query=query,
            filters=RetrievalFilters(
                project=project,
                tags=tags,
                created_after=created_after,
                created_before=created_before,
                confidence_min=confidence_min,
            ),
            semantic_k=semantic_k,
            lexical_k=lexical_k,
            final_k=final_k,
        )

    query_id = "qry-" + uuid.uuid4().hex[:12]
    query_created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    db.log_retrieval_usage(
        conn,
        query_id=query_id,
        query=query,
        created_at=query_created_at,
        items=payload["items"],
        project=project,
        tags=tags,
    )

    maybe_flush(runtime)

    return {
        "status": "ok",
        "query_id": query_id,
        "query": payload["query"],
        "filters": payload["filters"],
        "items": payload["items"],
        "meta": payload["meta"],
    }


def retrieve_prompt_context(
    settings_path: Path,
    query: str,
    project: Optional[str] = None,
    tags: Optional[List[str]] = None,
    confidence_min: Optional[float] = None,
    final_k: Optional[int] = None,
) -> Dict[str, Any]:
    retrieval = retrieve_findings(
        settings_path=settings_path,
        query=query,
        project=project,
        tags=tags,
        confidence_min=confidence_min,
        final_k=final_k,
    )
    if retrieval.get("status") != "ok":
        return retrieval

    items = retrieval.get("items", [])
    return {
        "status": "ok",
        "query_id": retrieval.get("query_id"),
        "query": query,
        "items": items,
        "safe_context": render_untrusted_context(items),
        "meta": retrieval.get("meta", {}),
    }


def evaluate_dataset(
    settings_path: Path,
    dataset_path: Path,
    final_k: int = 10,
) -> Dict[str, Any]:
    runtime = get_runtime(settings_path)
    settings = runtime.settings
    if not dataset_path.exists():
        return {
            "status": "error",
            "message": f"Dataset not found: {dataset_path}",
        }

    try:
        dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "status": "error",
            "message": f"Failed to parse dataset: {exc}",
        }

    if not isinstance(dataset, list):
        return {
            "status": "error",
            "message": "Dataset must be a list of query entries.",
        }

    conn = runtime.conn
    embedder = runtime.embedder
    store = runtime.store
    engine = RetrievalEngine(conn=conn, embedder=embedder, vector_store=store, settings=settings)

    query_results: List[Dict[str, Any]] = []
    precision5_values: List[float] = []
    recall5_values: List[float] = []
    recall10_values: List[float] = []
    faithfulness_values: List[float] = []
    alignment_values: List[float] = []

    for idx, row in enumerate(dataset):
        if not isinstance(row, dict):
            continue
        query = str(row.get("query") or "").strip()
        expected_ids = [str(value) for value in (row.get("expected_ids") or [])]
        if not query:
            continue

        filters = RetrievalFilters(
            project=row.get("project"),
            tags=row.get("tags") or None,
            created_after=row.get("created_after"),
            created_before=row.get("created_before"),
            confidence_min=row.get("confidence_min"),
        )
        with runtime.write_lock:
            payload = engine.search(
                query=query,
                filters=filters,
                final_k=max(10, final_k),
            )
        items = payload.get("items", [])
        retrieved_ids = [str(item.get("id")) for item in items]

        metrics = evaluate_retrieval(expected_ids=expected_ids, retrieved_ids=retrieved_ids, k_values=(5, 10))
        p5 = float(metrics.precision_at_k.get(5, 0.0))
        r5 = float(metrics.recall_at_k.get(5, 0.0))
        r10 = float(metrics.recall_at_k.get(10, 0.0))
        precision5_values.append(p5)
        recall5_values.append(r5)
        recall10_values.append(r10)

        answer = str(row.get("answer") or "")
        faith: Optional[float] = None
        if answer:
            faith = float(faithfulness_score(answer, items))
            faithfulness_values.append(faith)
        alignment = float(relevance_alignment(query, items, embedder=embedder))
        alignment_values.append(alignment)

        query_results.append(
            {
                "index": idx,
                "query": query,
                "expected_count": len(expected_ids),
                "retrieved_count": len(retrieved_ids),
                "precision_at_5": p5,
                "recall_at_5": r5,
                "recall_at_10": r10,
                "faithfulness": faith,
                "alignment": alignment,
            }
        )

    maybe_flush(runtime)

    def _avg(values: List[float]) -> float:
        if not values:
            return 0.0
        return sum(values) / len(values)

    return {
        "status": "ok",
        "dataset_path": str(dataset_path),
        "queries_evaluated": len(query_results),
        "summary": {
            "precision_at_5": _avg(precision5_values),
            "recall_at_5": _avg(recall5_values),
            "recall_at_10": _avg(recall10_values),
            "faithfulness": _avg(faithfulness_values) if faithfulness_values else None,
            "alignment": _avg(alignment_values),
        },
        "results": query_results,
    }


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
        try:
            store = load_vector_store(settings.vector_index_path, settings.vector_meta_path)
        except Exception as exc:
            status["vector_backend"] = "error"
            status["vector_count"] = 0
            status["vector_dim"] = 0
            status["vector_error"] = str(exc)
            return {"status": "error", "health": status}

        status["vector_backend"] = store.backend
        status["vector_count"] = store.count()
        status["vector_dim"] = store.dim
    else:
        status["vector_backend"] = "none"
        status["vector_count"] = 0
        status["vector_dim"] = 0

    return {"status": "ok", "health": status}
