import sqlite3
import tempfile
import unittest
from pathlib import Path

from openlmlib.co_scientist.evidence import (
    evidence_quality_score,
    get_evidence_quality_rubric,
    validate_evidence_items,
    verify_citations,
)
from openlmlib.collab.db import init_collab_db


class TestCoScientistEvidence(unittest.TestCase):
    def test_rubric_exposes_labels_and_quality_levels(self):
        rubric = get_evidence_quality_rubric()

        self.assertIn("support", rubric["labels"])
        self.assertIn("refute", rubric["labels"])
        self.assertIn("primary_source", rubric["quality_levels"])

    def test_evidence_item_validation_requires_label_when_requested(self):
        issues = validate_evidence_items(
            [{"source": "fixture", "summary": "Missing label."}],
            require_label=True,
        )

        self.assertEqual(issues[0].field, "evidence[0].label")

    def test_evidence_quality_prefers_rubric_over_confidence(self):
        score = evidence_quality_score({"quality": "primary_source", "confidence": 0.1})

        self.assertEqual(score, 1.0)

    def test_verify_citations_resolves_url_workspace_file_and_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cited = root / "source.md"
            cited.write_text("source", encoding="utf-8")
            conn = sqlite3.connect(":memory:")
            conn.row_factory = sqlite3.Row
            init_collab_db(conn)
            conn.execute(
                """
                INSERT INTO artifacts (
                    artifact_id, session_id, created_by, title, artifact_type,
                    file_path, tags_json, word_count, created_at,
                    referenced_in_messages_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "art_123456789abc",
                    "sess_fixture",
                    "agent",
                    "Fixture",
                    "source",
                    str(cited),
                    "[]",
                    1,
                    "2026-01-01T00:00:00Z",
                    "[]",
                ),
            )

            result = verify_citations(
                ["https://example.com/source", "source.md", "art_123456789abc"],
                conn=conn,
                session_ids=["sess_fixture"],
                workspace_root=root,
            )

            self.assertTrue(result["valid"])
            self.assertEqual(
                [item["kind"] for item in result["citations"]],
                ["external_url", "local_path", "artifact"],
            )
            conn.close()

    def test_verify_citations_can_reject_unreachable_urls(self):
        from unittest.mock import patch

        with patch(
            "openlmlib.co_scientist.evidence._probe_url",
            return_value=(False, "URL not reachable: simulated"),
        ):
            result = verify_citations(
                ["https://example.invalid/missing"],
                check_url_reachability=True,
            )
        self.assertFalse(result["valid"])
        self.assertEqual(result["citations"][0]["kind"], "external_url")
        self.assertFalse(result["citations"][0]["resolved"])
        self.assertIn("not reachable", result["issues"][0]["message"].lower())

    def test_verify_citations_rejects_paths_outside_workspace(self):
        with tempfile.TemporaryDirectory() as root_tmp, tempfile.TemporaryDirectory() as outside_tmp:
            outside = Path(outside_tmp) / "outside.md"
            outside.write_text("outside", encoding="utf-8")

            result = verify_citations([str(outside)], workspace_root=Path(root_tmp))

            self.assertFalse(result["valid"])
            self.assertEqual(result["issues"][0]["field"], "citations[0]")


if __name__ == "__main__":
    unittest.main()
