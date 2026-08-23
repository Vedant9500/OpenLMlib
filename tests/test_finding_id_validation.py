"""Caller-supplied finding IDs must not control filesystem paths (M-19)."""

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from openlmlib.library import FINDING_ID_RE, add_finding

VALID_ID = "fnd-abcdef123456"
BAD_IDS = [
    "../escape",
    "/etc/passwd",
    "fnd-../../escape",
    "nested/fnd-abcdef123456",
    "back\\slash",
    "",
    "fnd-short",
    "fnd-zzzzzzzzzzzz",  # non-hex tail
]


class TestFindingIdValidation(unittest.TestCase):
    def _add(self, finding_id):
        return add_finding(
            settings_path=Path("/tmp/unused-settings.json"),
            project="p",
            claim="Some claim about caching behavior",
            confidence=0.9,
            evidence=["evidence"],
            reasoning="r" * 40,
            confirm=True,
            finding_id=finding_id,
        )

    def test_canonical_format_regex(self):
        self.assertTrue(FINDING_ID_RE.fullmatch(VALID_ID))
        self.assertFalse(FINDING_ID_RE.fullmatch("fnd-ABCDEF123456"))
        self.assertFalse(FINDING_ID_RE.fullmatch("fnd-abcdef12345"))

    def test_traversal_and_separator_ids_rejected_before_runtime(self):
        with patch("openlmlib.library.get_runtime") as get_runtime:
            for bad in BAD_IDS:
                result = self._add(bad)
                self.assertEqual(result["status"], "error", bad)
                self.assertIn("finding_id", result["message"])
            get_runtime.assert_not_called()

    def test_valid_id_passes_gate_into_runtime_construction(self):
        # Valid ID proceeds past validation (runtime mocked; the save itself
        # is not the subject here — only that the gate does not reject it).
        runtime = MagicMock()
        runtime.settings.write_gate.min_confidence = 0.5
        runtime.settings.write_gate.min_reasoning_length = 10
        runtime.settings.write_gate.min_claim_evidence_sim = 0.0
        runtime.settings.novelty.similarity_threshold = 0.9
        runtime.settings.novelty.top_k = 3
        runtime.settings.findings_dir = Path("/tmp/unused-findings")
        runtime.embedder = None
        with patch("openlmlib.library.get_runtime", return_value=runtime) as get_runtime, \
             patch("openlmlib.library.db") as db_mock:
            db_mock.get_finding.return_value = None
            db_mock.get_finding_by_embedding_id.return_value = None
            with patch("openlmlib.library.WriteGate") as gate_cls:
                gate = gate_cls.return_value
                gate.validate.return_value = []
                gate.is_allowed.return_value = False  # stop before persistence
                gate.adjust_confidence.return_value = 0.9
                result = self._add(VALID_ID)

        get_runtime.assert_called_once()
        self.assertNotEqual(result["status"], "error")


if __name__ == "__main__":
    unittest.main()
