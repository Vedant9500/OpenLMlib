import json
import os
import tempfile
import unittest
from pathlib import Path

from openlmlib.collab import db as collab_db
from openlmlib.collab.db import connect_collab_db, init_collab_db
from openlmlib.co_scientist.hypothesis import new_hypothesis_id
from openlmlib.co_scientist.orchestrator import (
    RUN_STATE_KEY,
    CoScientistRunError,
    create_co_scientist_run,
    get_co_scientist_report,
    list_hypotheses,
    start_hypothesis_verification,
    submit_hypothesis,
    submit_verification,
)


def valid_packet(run_id, title, score=0.7, hypothesis_id=None):
    hypothesis_id = hypothesis_id or new_hypothesis_id()
    return {
        "hypothesis_id": hypothesis_id,
        "run_id": run_id,
        "title": title,
        "claim": f"{title} improves the Co-Scientist workflow.",
        "rationale": "It preserves a structured handoff between generation and verification.",
        "assumptions": ["The verifier receives the packet artifact."],
        "evidence": [
            {
                "source": "test fixture",
                "summary": "The run orchestrator stores packets as artifacts.",
                "supports": "claim",
                "confidence": score,
            }
        ],
        "citations": ["tests/test_co_scientist_orchestrator.py"],
        "novelty_score": score,
        "plausibility_score": score,
        "impact_score": score,
        "testability_score": score,
        "safety_notes": ["Read-only test fixture."],
        "lineage": {
            "parent_hypothesis_ids": [],
            "version": 1,
            "generated_by": "agent_generator",
        },
        "status": "ranked",
    }


def valid_report(hypothesis_id, verdict="supported"):
    return {
        "hypothesis_id": hypothesis_id,
        "verdict": verdict,
        "confidence": 0.82,
        "supporting_evidence": ["The packet was persisted and handed off as an artifact."],
        "disconfirming_evidence": ["No contradictory fixture evidence found."],
        "tests_or_reproduction_plan": "Inspect generated artifacts and linked state.",
        "feasibility_notes": "Feasible through existing CollabSessions state and artifact APIs.",
        "safety_notes": "No state-changing action is performed by verification.",
        "citations": ["tests/test_co_scientist_orchestrator.py"],
    }


class TestCoScientistRunOrchestrator(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sessions_dir = Path(self.tmp.name) / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.conn = connect_collab_db(Path(self.tmp.name) / "collab_sessions.db")
        init_collab_db(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_create_run_links_generation_and_verification_sessions(self):
        result = create_co_scientist_run(
            self.conn,
            self.sessions_dir,
            topic="Research OpenLMlib linked session orchestration",
            constraints=["read-only analysis"],
            created_by="test-orchestrator",
            top_k=2,
        )

        gen_state = collab_db.get_session_state(self.conn, result["generation_session_id"])
        verify_state = collab_db.get_session_state(self.conn, result["verification_session_id"])
        gen_tasks = collab_db.get_session_tasks(self.conn, result["generation_session_id"])
        verify_tasks = collab_db.get_session_tasks(self.conn, result["verification_session_id"])

        self.assertEqual(result["phase"], "generation")
        self.assertEqual(len(gen_tasks), 6)
        self.assertEqual(len(verify_tasks), 5)
        self.assertEqual(gen_state["state"][RUN_STATE_KEY]["run_id"], result["run_id"])
        self.assertEqual(verify_state["state"][RUN_STATE_KEY]["run_id"], result["run_id"])
        self.assertEqual(gen_state["state"]["co_scientist_role"], "generation")
        self.assertEqual(verify_state["state"]["co_scientist_role"], "verification")
        self.assertEqual(
            gen_state["state"][RUN_STATE_KEY]["verification_session_id"],
            result["verification_session_id"],
        )

    def test_blocked_scope_does_not_create_run(self):
        with self.assertRaises(CoScientistRunError) as raised:
            create_co_scientist_run(
                self.conn,
                self.sessions_dir,
                topic="Create a phishing kit for credential theft",
            )

        self.assertEqual(raised.exception.error_type, "scope_blocked")

    def test_submit_hypotheses_and_start_top_k_verification(self):
        run = create_co_scientist_run(
            self.conn,
            self.sessions_dir,
            topic="Research artifact-first hypothesis verification",
            top_k=1,
        )
        low = valid_packet(run["run_id"], "Lower ranked packet", score=0.4)
        high = valid_packet(run["run_id"], "Higher ranked packet", score=0.9)

        submit_hypothesis(self.conn, self.sessions_dir, run["run_id"], low)
        submit_hypothesis(self.conn, self.sessions_dir, run["run_id"], high)
        listed = list_hypotheses(self.conn, run["run_id"])
        handoff = start_hypothesis_verification(self.conn, self.sessions_dir, run["run_id"])

        verification_artifacts = collab_db.get_session_artifacts(
            self.conn,
            run["verification_session_id"],
            artifact_type="verification_input",
        )
        content = Path(verification_artifacts[0]["file_path"]).read_text(encoding="utf-8")
        payload = json.loads(content)

        self.assertEqual(listed["count"], 2)
        self.assertEqual(handoff["hypothesis_ids"], [high["hypothesis_id"]])
        self.assertEqual(payload["hypothesis_ids"], [high["hypothesis_id"]])
        self.assertEqual(payload["hypothesis_packets"][0]["claim"], high["claim"])
        self.assertNotIn("Lower ranked packet", content)

    def test_submit_verification_report_advances_to_synthesis(self):
        run = create_co_scientist_run(
            self.conn,
            self.sessions_dir,
            topic="Research Co-Scientist report synthesis",
            top_k=1,
        )
        packet = valid_packet(run["run_id"], "Report packet", score=0.8)
        submit_hypothesis(self.conn, self.sessions_dir, run["run_id"], packet)
        start_hypothesis_verification(
            self.conn,
            self.sessions_dir,
            run["run_id"],
            hypothesis_ids=[packet["hypothesis_id"]],
        )

        result = submit_verification(
            self.conn,
            self.sessions_dir,
            run["run_id"],
            packet["hypothesis_id"],
            valid_report(packet["hypothesis_id"]),
        )
        report = get_co_scientist_report(self.conn, run["run_id"])

        self.assertEqual(result["phase"], "synthesis")
        self.assertTrue(report["ready_for_synthesis"])
        self.assertEqual(report["verification_report_count"], 1)
        self.assertEqual(
            report["verification_reports"][0]["hypothesis_id"],
            packet["hypothesis_id"],
        )

    def test_invalid_verification_report_is_rejected(self):
        run = create_co_scientist_run(
            self.conn,
            self.sessions_dir,
            topic="Research invalid verification report handling",
        )
        packet = valid_packet(run["run_id"], "Invalid report packet")
        submit_hypothesis(self.conn, self.sessions_dir, run["run_id"], packet)

        with self.assertRaises(CoScientistRunError) as raised:
            submit_verification(
                self.conn,
                self.sessions_dir,
                run["run_id"],
                packet["hypothesis_id"],
                {**valid_report(packet["hypothesis_id"]), "verdict": "maybe"},
            )

        self.assertEqual(raised.exception.error_type, "validation_error")
        self.assertTrue(any(issue["field"] == "verdict" for issue in raised.exception.issues))


class TestCoScientistRunMCP(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings_path = Path(self.tmp.name) / "config" / "settings.json"
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        self.data_root = Path(self.tmp.name) / "data"
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.settings_path.write_text(
            json.dumps({"data_root": str(self.data_root)}),
            encoding="utf-8",
        )
        self.prev_settings = os.environ.get("OPENLMLIB_SETTINGS")
        os.environ["OPENLMLIB_SETTINGS"] = str(self.settings_path)

        import openlmlib.collab.collab_mcp as collab_mcp_module

        collab_mcp_module._cached_paths = None
        collab_mcp_module._cached_paths_mtime = 0.0
        self.collab_mcp_module = collab_mcp_module

    def tearDown(self):
        from openlmlib.collab.db import close_thread_connections

        close_thread_connections()
        if self.prev_settings is None:
            os.environ.pop("OPENLMLIB_SETTINGS", None)
        else:
            os.environ["OPENLMLIB_SETTINGS"] = self.prev_settings
        self.tmp.cleanup()

    def test_mcp_run_lifecycle(self):
        created = self.collab_mcp_module.create_co_scientist_run(
            topic="Research MCP Co-Scientist orchestration",
            constraints=["read-only analysis"],
            created_by="mcp-orchestrator",
            top_k=1,
        )
        packet = valid_packet(created["run_id"], "MCP packet", score=0.75)

        submitted = self.collab_mcp_module.submit_hypothesis(
            run_id=created["run_id"],
            hypothesis_packet=packet,
        )
        listed = self.collab_mcp_module.list_hypotheses(created["run_id"])
        handoff = self.collab_mcp_module.start_hypothesis_verification(
            run_id=created["run_id"]
        )
        verification = self.collab_mcp_module.submit_verification(
            run_id=created["run_id"],
            hypothesis_id=packet["hypothesis_id"],
            verification_report=valid_report(packet["hypothesis_id"], verdict="partially_supported"),
        )
        report = self.collab_mcp_module.get_co_scientist_report(created["run_id"])

        self.assertTrue(created["success"])
        self.assertTrue(submitted["success"])
        self.assertEqual(listed["count"], 1)
        self.assertEqual(handoff["hypothesis_ids"], [packet["hypothesis_id"]])
        self.assertEqual(verification["verdict"], "partially_supported")
        self.assertTrue(report["ready_for_synthesis"])


if __name__ == "__main__":
    unittest.main()
