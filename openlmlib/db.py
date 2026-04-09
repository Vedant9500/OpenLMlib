from __future__ import annotations

import json
import sqlite3
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .schema import Finding, FindingAudit, FindingText


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    conn.execute("PRAGMA temp_store = MEMORY;")
    conn.execute("PRAGMA cache_size = -20000;")
    conn.execute("PRAGMA wal_autocheckpoint = 4000;")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS findings (
          id TEXT PRIMARY KEY,
          project TEXT,
          claim TEXT NOT NULL,
          confidence REAL,
          created_at TEXT,
          embedding_id INTEGER,
          content_hash TEXT,
          status TEXT
        );

        CREATE TABLE IF NOT EXISTS findings_text (
          id TEXT PRIMARY KEY,
          tags TEXT,
          evidence TEXT,
          caveats TEXT,
          reasoning TEXT,
          full_text TEXT DEFAULT '',
          FOREIGN KEY (id) REFERENCES findings(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS findings_audit (
          id TEXT PRIMARY KEY,
          proposed_by TEXT,
          evidence_provided INTEGER,
          reasoning_length INTEGER,
          failure_log TEXT,
          confidence_history TEXT,
          FOREIGN KEY (id) REFERENCES findings(id) ON DELETE CASCADE
        );

                CREATE TABLE IF NOT EXISTS retrieval_usage (
                    query_id TEXT NOT NULL,
                    finding_id TEXT NOT NULL,
                    rank INTEGER NOT NULL,
                    cited INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    query TEXT NOT NULL,
                    project TEXT,
                    tags TEXT,
                    PRIMARY KEY (query_id, finding_id),
                    FOREIGN KEY (finding_id) REFERENCES findings(id) ON DELETE CASCADE
                );

        CREATE VIRTUAL TABLE IF NOT EXISTS findings_fts USING fts5(
          id UNINDEXED,
          claim,
          evidence,
          reasoning
        );

        CREATE INDEX IF NOT EXISTS idx_findings_project ON findings(project);
        CREATE INDEX IF NOT EXISTS idx_findings_created_at ON findings(created_at);
        CREATE INDEX IF NOT EXISTS idx_findings_status ON findings(status);
        CREATE INDEX IF NOT EXISTS idx_findings_embedding_id ON findings(embedding_id);
        CREATE INDEX IF NOT EXISTS idx_retrieval_usage_query_id ON retrieval_usage(query_id);
        CREATE INDEX IF NOT EXISTS idx_retrieval_usage_finding_id ON retrieval_usage(finding_id);
        CREATE INDEX IF NOT EXISTS idx_retrieval_usage_created_at ON retrieval_usage(created_at);
        """
    )
    _migrate_schema(conn)
    conn.commit()


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row["name"]) for row in rows}


def _migrate_schema(conn: sqlite3.Connection) -> None:
    findings_text_columns = _table_columns(conn, "findings_text")
    if "full_text" not in findings_text_columns:
        conn.execute("ALTER TABLE findings_text ADD COLUMN full_text TEXT DEFAULT ''")


def _json_dump(value) -> str:
    return json.dumps(value, separators=(",", ":"))


def _json_load(value: Optional[str], default):
    if value is None:
        return default
    return json.loads(value)


def _normalize_fts_query(query: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9_]+", query)
    if not tokens:
        return ""
    return " ".join(tokens)


def insert_finding(conn: sqlite3.Connection, finding: Finding) -> None:
    text = finding.text
    audit = finding.audit

    with conn:
        conn.execute(
            """
            INSERT INTO findings (id, project, claim, confidence, created_at, embedding_id, content_hash, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                finding.id,
                finding.project,
                finding.claim,
                finding.confidence,
                finding.created_at,
                finding.embedding_id,
                finding.content_hash,
                finding.status,
            ),
        )
        conn.execute(
            """
            INSERT INTO findings_text (id, tags, evidence, caveats, reasoning, full_text)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                finding.id,
                _json_dump(text.tags),
                _json_dump(text.evidence),
                _json_dump(text.caveats),
                text.reasoning,
                finding.full_text,
            ),
        )
        conn.execute(
            """
            INSERT INTO findings_audit (id, proposed_by, evidence_provided, reasoning_length, failure_log, confidence_history)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                finding.id,
                audit.proposed_by,
                1 if audit.evidence_provided else 0,
                audit.reasoning_length,
                _json_dump(audit.failure_log),
                _json_dump(audit.confidence_history),
            ),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO findings_fts (id, claim, evidence, reasoning)
            VALUES (?, ?, ?, ?)
            """,
            (finding.id, finding.claim, " ".join(text.evidence), text.reasoning),
        )


def delete_finding(conn: sqlite3.Connection, finding_id: str) -> None:
    with conn:
        conn.execute("DELETE FROM findings_fts WHERE id = ?", (finding_id,))
        conn.execute("DELETE FROM findings WHERE id = ?", (finding_id,))


def get_finding(conn: sqlite3.Connection, finding_id: str) -> Optional[Finding]:
    row = conn.execute("SELECT * FROM findings WHERE id = ?", (finding_id,)).fetchone()
    if row is None:
        return None

    text_row = conn.execute("SELECT * FROM findings_text WHERE id = ?", (finding_id,)).fetchone()
    audit_row = conn.execute("SELECT * FROM findings_audit WHERE id = ?", (finding_id,)).fetchone()

    text = FindingText(
        tags=_json_load(text_row["tags"], []) if text_row else [],
        evidence=_json_load(text_row["evidence"], []) if text_row else [],
        caveats=_json_load(text_row["caveats"], []) if text_row else [],
        reasoning=text_row["reasoning"] if text_row else "",
    )
    audit = FindingAudit(
        proposed_by=audit_row["proposed_by"] if audit_row else "",
        evidence_provided=bool(audit_row["evidence_provided"]) if audit_row else False,
        reasoning_length=int(audit_row["reasoning_length"]) if audit_row else 0,
        failure_log=_json_load(audit_row["failure_log"], []) if audit_row else [],
        confidence_history=_json_load(audit_row["confidence_history"], []) if audit_row else [],
    )

    return Finding(
        id=row["id"],
        project=row["project"],
        claim=row["claim"],
        confidence=float(row["confidence"]) if row["confidence"] is not None else 0.0,
        created_at=row["created_at"],
        embedding_id=int(row["embedding_id"]) if row["embedding_id"] is not None else 0,
        content_hash=row["content_hash"],
        status=row["status"],
        text=text,
        audit=audit,
        full_text=text_row["full_text"] if text_row and "full_text" in text_row.keys() else "",
    )


def get_finding_by_embedding_id(conn: sqlite3.Connection, embedding_id: int) -> Optional[str]:
    row = conn.execute("SELECT id FROM findings WHERE embedding_id = ?", (embedding_id,)).fetchone()
    return row["id"] if row else None


def list_findings(conn: sqlite3.Connection, limit: int = 50, offset: int = 0) -> List[Dict[str, str]]:
    rows = conn.execute(
        """
        SELECT id, project, claim, confidence, created_at, status
        FROM findings
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
        """,
        (limit, offset),
    ).fetchall()

    return [dict(row) for row in rows]


def search_findings(conn: sqlite3.Connection, query: str, limit: int = 10) -> List[Dict[str, str]]:
    normalized_query = _normalize_fts_query(query)
    if not normalized_query:
        return []
    rows = conn.execute(
        """
        SELECT f.id, f.project, f.claim, f.confidence, f.created_at, f.status
        FROM findings_fts AS fts
        JOIN findings AS f ON f.id = fts.id
        WHERE findings_fts MATCH ?
        ORDER BY rank
        LIMIT ?
        """,
        (normalized_query, limit),
    ).fetchall()

    return [dict(row) for row in rows]


def _append_filters(
    base_sql: str,
    params: List,
    project: Optional[str] = None,
    tags: Optional[List[str]] = None,
    created_after: Optional[str] = None,
    created_before: Optional[str] = None,
    confidence_min: Optional[float] = None,
) -> str:
    clauses: List[str] = []

    if project:
        clauses.append("f.project = ?")
        params.append(project)

    if created_after:
        clauses.append("f.created_at >= ?")
        params.append(created_after)

    if created_before:
        clauses.append("f.created_at <= ?")
        params.append(created_before)

    if confidence_min is not None:
        clauses.append("f.confidence >= ?")
        params.append(float(confidence_min))

    if tags:
        for tag in tags:
            clauses.append(
                "EXISTS (SELECT 1 FROM json_each(ft.tags) AS je WHERE je.value = ?)"
            )
            params.append(tag)

    if clauses:
        return base_sql + " AND " + " AND ".join(clauses)
    return base_sql


def search_findings_filtered(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 10,
    project: Optional[str] = None,
    tags: Optional[List[str]] = None,
    created_after: Optional[str] = None,
    created_before: Optional[str] = None,
    confidence_min: Optional[float] = None,
) -> List[Dict[str, str]]:
    normalized_query = _normalize_fts_query(query)
    if not normalized_query:
        return []

    params: List = [normalized_query]
    sql = """
        SELECT f.id, f.project, f.claim, f.confidence, f.created_at, f.status, rank AS lexical_rank
        FROM findings_fts AS fts
        JOIN findings AS f ON f.id = fts.id
        JOIN findings_text AS ft ON ft.id = f.id
        WHERE findings_fts MATCH ?
    """
    sql = _append_filters(
        sql,
        params,
        project=project,
        tags=tags,
        created_after=created_after,
        created_before=created_before,
        confidence_min=confidence_min,
    )
    sql += " ORDER BY rank LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, tuple(params)).fetchall()
    return [dict(row) for row in rows]


def get_findings_by_embedding_ids(
    conn: sqlite3.Connection,
    embedding_ids: Iterable[int],
) -> Dict[int, Dict[str, str]]:
    embedding_id_list = [int(value) for value in embedding_ids]
    if not embedding_id_list:
        return {}

    placeholders = ",".join(["?"] * len(embedding_id_list))
    rows = conn.execute(
        f"""
        SELECT
            f.id,
            f.embedding_id,
            f.project,
            f.claim,
            f.confidence,
            f.created_at,
            f.status,
            ft.tags,
            ft.evidence,
            ft.reasoning,
            ft.caveats
        FROM findings AS f
        JOIN findings_text AS ft ON ft.id = f.id
        WHERE f.embedding_id IN ({placeholders})
        """,
        tuple(embedding_id_list),
    ).fetchall()

    result: Dict[int, Dict[str, str]] = {}
    for row in rows:
        payload = dict(row)
        payload["tags"] = _json_load(payload.get("tags"), [])
        payload["evidence"] = _json_load(payload.get("evidence"), [])
        payload["caveats"] = _json_load(payload.get("caveats"), [])
        result[int(row["embedding_id"])] = payload
    return result


def log_retrieval_usage(
    conn: sqlite3.Connection,
    query_id: str,
    query: str,
    created_at: str,
    items: List[Dict[str, str]],
    project: Optional[str] = None,
    tags: Optional[List[str]] = None,
) -> None:
    tags_json = _json_dump(tags or [])
    with conn:
        for rank, item in enumerate(items, start=1):
            finding_id = str(item.get("id") or "").strip()
            if not finding_id:
                continue
            conn.execute(
                """
                INSERT OR REPLACE INTO retrieval_usage
                  (query_id, finding_id, rank, cited, created_at, query, project, tags)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    query_id,
                    finding_id,
                    rank,
                    1,
                    created_at,
                    query,
                    project,
                    tags_json,
                ),
            )


def list_retrieval_usage(conn: sqlite3.Connection, query_id: str) -> List[Dict[str, str]]:
    rows = conn.execute(
        """
        SELECT query_id, finding_id, rank, cited, created_at, query, project, tags
        FROM retrieval_usage
        WHERE query_id = ?
        ORDER BY rank ASC
        """,
        (query_id,),
    ).fetchall()

    items: List[Dict[str, str]] = []
    for row in rows:
        payload = dict(row)
        payload["tags"] = _json_load(payload.get("tags"), [])
        payload["cited"] = bool(payload.get("cited"))
        items.append(payload)
    return items
