import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openlmlib.collab import db as collab_db
from openlmlib.collab.db import connect_collab_db, init_collab_db
from openlmlib.co_scientist.hypothesis import new_hypothesis_id
from openlmlib.co_scientist.orchestrator import (
    CoScientistRunError,
    create_co_scientist_run,
    get_co_scientist_report,
    start_hypothesis_verification,
    submit_hypothesis,
    submit_verification,
)
from openlmlib.co_scientist.reporting import (
    create_final_report,
    export_supported_findings,
)


def packet(run_id, title, score=0.8, hypothesis_id=None):
    hypothesis_id = hypothesis_id or new_hypothesis_id()
    return {
        "hypothesis_id": hypothesis_id,
        "run_id": run_id,
        "title": title,
        "claim": f"{title} is useful for Co-Scientist runs.",
        "rationale": "The claim is represented as a structured packet.",
        "assumptions": ["The verifier receives this packet."],
        "evidence": [
            {
                "source": "tests/test_co_scientist_reporting.py",
                "summary": "The fixture supplies deterministic evidence.",
                "supports": "claim",
                "confidence": score,
                "label": "support",
                "quality": "reproducible",
            }
        ],
        "citations": ["tests/test_co_scientist_reporting.py"],
        "novelty_score": score,
        "plausibility_score": score,
        "impact_score": score,
        "testability_score": score,
        "safety_notes": ["Read-only reporting fixture."],
        "lineage": {
            "parent_hypothesis_ids": [],
            "version": 1,
            "generated_by": "agent_reporter",
        },
        "status": "ranked",
    }


def report(hypothesis_id, verdict="supported", confidence=0.84):
    return {
        "hypothesis_id": hypothesis_id,
        "verdict": verdict,
        "confidence": confidence,
        "supporting_evidence": ["The report fixture includes supporting evidence."],
        "disconfirming_evidence": ["No fixture contradiction found."],
        "tests_or_reproduction_plan": "Run the reporting tests.",
        "feasibility_notes": "Feasible with artifact-backed run state.",
        "safety_notes": "No external action required.",
        "citations": ["tests/test_co_scientist_reporting.py"],
    }


class TestCoScientistReporting(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.sessions_dir = self.root / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.conn = connect_collab_db(self.root / "collab_sessions.db")
        init_collab_db(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def create_verified_run(self):
        run = create_co_scientist_run(
            self.conn,
            self.sessions_dir,
            topic="Research final report generation",
            top_k=2,
        )
        supported = packet(run["run_id"], "Supported packet", score=0.9)
        rejected = packet(run["run_id"], "Rejected packet", score=0.7)
        gen = run["generation_agent_id"]
        ver = run["verification_agent_id"]
        submit_hypothesis(self.conn, self.sessions_dir, run["run_id"], supported, created_by=gen)
        submit_hypothesis(self.conn, self.sessions_dir, run["run_id"], rejected, created_by=gen)
        start_hypothesis_verification(
            self.conn,
            self.sessions_dir,
            run["run_id"],
            hypothesis_ids=[supported["hypothesis_id"], rejected["hypothesis_id"]],
            created_by=gen,
        )
        submit_verification(
            self.conn,
            self.sessions_dir,
            run["run_id"],
            supported["hypothesis_id"],
            report(supported["hypothesis_id"], "supported", 0.86),
            created_by=ver,
        )
        submit_verification(
            self.conn,
            self.sessions_dir,
            run["run_id"],
            rejected["hypothesis_id"],
            report(rejected["hypothesis_id"], "contradicted", 0.78),
            created_by=ver,
        )
        return run, supported, rejected

    def test_create_final_report_artifact_and_memory_summary(self):
        run, supported, rejected = self.create_verified_run()

        result = create_final_report(
            self.conn,
            self.sessions_dir,
            run["run_id"],
            created_by=run["verification_agent_id"],
        )
        state = get_co_scientist_report(self.conn, run["run_id"])
        artifacts = collab_db.get_session_artifacts(
            self.conn,
            run["verification_session_id"],
            artifact_type="co_scientist_report",
        )
        content = Path(artifacts[0]["file_path"]).read_text(encoding="utf-8")

        self.assertEqual(result["phase"], "complete")
        self.assertEqual(state["final_report_artifact_id"], result["final_report_artifact_id"])
        self.assertEqual(result["verified_claim_count"], 1)
        self.assertEqual(result["rejected_hypothesis_count"], 1)
        self.assertEqual(len(result["memory_summary_paths"]), 2)
        self.assertIn("## Best-Supported Hypotheses", content)
        self.assertIn(supported["hypothesis_id"], content)
        self.assertIn(rejected["hypothesis_id"], content)

    def test_final_report_creation_is_idempotent(self):
        run, _supported, _rejected = self.create_verified_run()
        ver = run["verification_agent_id"]

        first = create_final_report(self.conn, self.sessions_dir, run["run_id"], created_by=ver)
        second = create_final_report(self.conn, self.sessions_dir, run["run_id"], created_by=ver)
        artifacts = collab_db.get_session_artifacts(
            self.conn,
            run["verification_session_id"],
            artifact_type="co_scientist_report",
        )

        self.assertEqual(first["final_report_artifact_id"], second["final_report_artifact_id"])
        self.assertTrue(second["existing"])
        self.assertEqual(len(artifacts), 1)

    def test_final_report_requires_complete_verification(self):
        run = create_co_scientist_run(
            self.conn,
            self.sessions_dir,
            topic="Research incomplete final report rejection",
            top_k=1,
        )
        item = packet(run["run_id"], "Unverified packet")
        gen = run["generation_agent_id"]
        ver = run["verification_agent_id"]
        submit_hypothesis(self.conn, self.sessions_dir, run["run_id"], item, created_by=gen)
        start_hypothesis_verification(
            self.conn,
            self.sessions_dir,
            run["run_id"],
            hypothesis_ids=[item["hypothesis_id"]],
            created_by=gen,
        )

        with self.assertRaises(CoScientistRunError) as raised:
            create_final_report(
                self.conn,
                self.sessions_dir,
                run["run_id"],
                created_by=ver,
            )

        self.assertEqual(raised.exception.error_type, "run_not_ready")

    def test_export_supported_findings_skips_rejected_hypotheses(self):
        run, supported, rejected = self.create_verified_run()
        settings_path = self.root / "config" / "settings.json"
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(json.dumps({"data_root": str(self.root / "data")}), encoding="utf-8")

        with patch("openlmlib.co_scientist.reporting.add_finding") as add:
            add.return_value = {"status": "ok", "id": "fnd-supported", "confidence": 0.86}
            result = export_supported_findings(
                settings_path,
                self.conn,
                self.sessions_dir,
                run["run_id"],
                project="CoScientist Tests",
            )

        self.assertEqual(result["exported"], 1)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["findings"][0]["finding_id"], "fnd-supported")
        self.assertEqual(result["skipped"][0]["hypothesis_id"], rejected["hypothesis_id"])
        self.assertEqual(add.call_count, 1)
        self.assertIn(supported["claim"], add.call_args.kwargs["claim"])

    def test_export_supported_findings_surfaces_write_gate_issues(self):
        run, supported, _rejected = self.create_verified_run()
        settings_path = self.root / "config" / "settings.json"
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(json.dumps({"data_root": str(self.root / "data")}), encoding="utf-8")

        with patch("openlmlib.co_scientist.reporting.add_finding") as add:
            add.return_value = {
                "status": "rejected",
                "issues": [
                    {
                        "field": "claim_evidence_sim",
                        "message": "Claim/evidence similarity 0.20 below threshold 0.70",
                    }
                ],
            }
            result = export_supported_findings(
                settings_path,
                self.conn,
                self.sessions_dir,
                run["run_id"],
                project="CoScientist Tests",
            )

        self.assertEqual(result["exported"], 0)
        self.assertGreaterEqual(result["failed"], 1)
        failure = next(f for f in result["failures"] if f["hypothesis_id"] == supported["hypothesis_id"])
        self.assertEqual(failure["status"], "rejected")
        self.assertIn("similarity", failure["reason"].lower())
        self.assertEqual(failure["issues"][0]["field"], "claim_evidence_sim")


if __name__ == "__main__":
    unittest.main()
