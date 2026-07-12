import tempfile
import unittest
from pathlib import Path

from openlmlib import db
from openlmlib.usage_analytics import get_tool_selection_accuracy, log_tool_selection


class TestUsageAnalytics(unittest.TestCase):
    def test_log_tool_selection_unknown_is_null(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.connect(Path(tmp) / "findings.db")
            db.init_db(conn)
            selection_id = log_tool_selection(
                conn,
                query="how do I search?",
                selected_tool="search_knowledge",
            )
            row = conn.execute(
                "SELECT is_correct FROM tool_selections WHERE id = ?",
                (selection_id,),
            ).fetchone()
            self.assertIsNone(row["is_correct"])

            log_tool_selection(
                conn,
                query="how do I search?",
                selected_tool="search_knowledge",
                expected_tool="search_knowledge",
            )
            metrics = get_tool_selection_accuracy(conn, days=7)
            self.assertEqual(metrics["total_selections"], 2)
            self.assertEqual(metrics["labeled_selections"], 1)
            self.assertEqual(metrics["correct_selections"], 1)
            self.assertEqual(metrics["accuracy_rate"], 1.0)
            conn.close()


if __name__ == "__main__":
    unittest.main()
