"""Artifact store for CollabSessions.

Manages file-based artifact storage with per-agent workspaces
and shared artifact directories.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Dict, List, Optional

import sqlite3

from . import db


class ArtifactStore:
    """File-based artifact storage with SQLite metadata index."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        sessions_dir: Path,
    ):
        self.conn = conn
        self.sessions_dir = sessions_dir

    def _session_dir(self, session_id: str) -> Path:
        return self.sessions_dir / session_id

    def _agent_dir(self, session_id: str, agent_id: str) -> Path:
        safe_id = agent_id.replace(":", "_").replace("/", "_").replace("\\", "_")
        d = self._session_dir(session_id) / "artifacts" / safe_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _shared_dir(self, session_id: str) -> Path:
        d = self._session_dir(session_id) / "artifacts" / "shared"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _summaries_dir(self, session_id: str) -> Path:
        d = self._session_dir(session_id) / "summaries"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save(
        self,
        session_id: str,
        created_by: str,
        title: str,
        content: str,
        created_at: str,
        artifact_type: Optional[str] = None,
        tags: Optional[List[str]] = None,
        shared: bool = False,
        referenced_in_messages: Optional[List[str]] = None,
        artifact_id: Optional[str] = None,
    ) -> Dict:
        """Save an artifact to disk and register in the index."""
        artifact_id = artifact_id or f"art_{uuid.uuid4().hex[:8]}"

        if shared:
            base_dir = self._shared_dir(session_id)
        else:
            base_dir = self._agent_dir(session_id, created_by)

        safe_title = self._safe_filename(title)
        file_path = base_dir / f"{artifact_id}_{safe_title}.md"
        file_path.write_text(content, encoding="utf-8")

        word_count = len(content.split())

        db.insert_artifact(
            self.conn,
            artifact_id=artifact_id,
            session_id=session_id,
            created_by=created_by,
            title=title,
            file_path=str(file_path),
            created_at=created_at,
            artifact_type=artifact_type,
            tags=tags,
            word_count=word_count,
            referenced_in_messages=referenced_in_messages,
        )

        return {
            "artifact_id": artifact_id,
            "title": title,
            "file_path": str(file_path),
            "word_count": word_count,
            "created_by": created_by,
            "created_at": created_at,
            "artifact_type": artifact_type,
            "tags": tags or [],
            "shared": shared,
        }

    def save_summary(
        self,
        session_id: str,
        summary: str,
        created_at: str,
        summary_id: Optional[str] = None,
    ) -> str:
        """Save a session summary to the summaries directory."""
        summary_id = summary_id or f"sum_{uuid.uuid4().hex[:8]}"
        summaries_dir = self._summaries_dir(session_id)
        file_path = summaries_dir / f"{summary_id}.md"
        file_path.write_text(summary, encoding="utf-8")
        return str(file_path)

    def get_content(self, artifact_id: str, session_id: Optional[str] = None) -> Optional[str]:
        """Read the full content of an artifact."""
        if session_id is None:
            row = self.conn.execute(
                "SELECT file_path FROM artifacts WHERE artifact_id = ?",
                (artifact_id,),
            ).fetchone()
            if row is None:
                return None
            file_path = Path(row["file_path"])
            if file_path.exists():
                return file_path.read_text(encoding="utf-8")
            return None

        artifacts = db.get_session_artifacts(self.conn, session_id)
        for art in artifacts:
            if art["artifact_id"] == artifact_id:
                file_path = Path(art["file_path"])
                if file_path.exists():
                    return file_path.read_text(encoding="utf-8")
        return None

    def get_content_by_id(
        self, session_id: str, artifact_id: str
    ) -> Optional[str]:
        """Read artifact content by artifact_id within a session."""
        artifacts = db.get_session_artifacts(self.conn, session_id)
        for art in artifacts:
            if art["artifact_id"] == artifact_id:
                file_path = Path(art["file_path"])
                if file_path.exists():
                    return file_path.read_text(encoding="utf-8")
        return None

    def list_artifacts(
        self,
        session_id: str,
        created_by: Optional[str] = None,
        artifact_type: Optional[str] = None,
    ) -> List[Dict]:
        """List artifacts for a session."""
        return db.get_session_artifacts(
            self.conn, session_id, created_by, artifact_type
        )

    def list_summaries(self, session_id: str) -> List[Path]:
        """List all summaries for a session."""
        summaries_dir = self._summaries_dir(session_id)
        if not summaries_dir.exists():
            return []
        return sorted(summaries_dir.glob("*.md"))

    def get_latest_summary(self, session_id: str) -> Optional[str]:
        """Get the content of the most recent summary."""
        summaries = self.list_summaries(session_id)
        if not summaries:
            return None
        return summaries[-1].read_text(encoding="utf-8")

    def grep_artifacts(
        self,
        session_id: str,
        pattern: str,
        created_by: Optional[str] = None,
    ) -> List[Dict]:
        """Search artifact content for a pattern.

        Returns matching artifacts with the matching lines.
        """
        artifacts = db.get_session_artifacts(self.conn, session_id, created_by)
        matches = []
        for art in artifacts:
            file_path = Path(art["file_path"])
            if not file_path.exists():
                continue
            content = file_path.read_text(encoding="utf-8")
            if pattern.lower() in content.lower():
                lines = content.splitlines()
                matching_lines = []
                for i, line in enumerate(lines, 1):
                    if pattern.lower() in line.lower():
                        matching_lines.append(f"L{i}: {line.strip()}")
                        if len(matching_lines) >= 5:
                            break
                matches.append({
                    "artifact_id": art["artifact_id"],
                    "title": art["title"],
                    "created_by": art["created_by"],
                    "matching_lines": matching_lines,
                })
        return matches

    @staticmethod
    def _safe_filename(title: str, max_len: int = 60) -> str:
        """Convert a title to a safe filename component."""
        safe = "".join(
            c if c.isalnum() or c in (" ", "-", "_") else "_"
            for c in title
        )
        safe = safe.strip()[:max_len]
        if not safe:
            safe = "artifact"
        return safe.lower().replace(" ", "_")
