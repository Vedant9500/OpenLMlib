"""Finding read APIs enforce documented result bounds (M-10)."""

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from openlmlib.library import (
    FINDINGS_LIMIT_MAX,
    _clamp_limit,
    list_findings,
    search_fts,
)


class TestClampLimit(unittest.TestCase):
    def test_negative_limit_becomes_default(self):
        # SQLite reads negative LIMIT as unbounded; must never reach SQL.
        self.assertEqual(_clamp_limit(-99, default=50), 50)
        self.assertEqual(_clamp_limit(-1, default=10), 10)

    def test_zero_and_invalid_become_default(self):
        self.assertEqual(_clamp_limit(0, default=50), 50)
        self.assertIs(_clamp_limit("abc", default=10), 10)
        self.assertIs(_clamp_limit(None, default=25), 25)

    def test_huge_limit_is_capped(self):
        self.assertEqual(_clamp_limit(10_000_000, default=10), FINDINGS_LIMIT_MAX)

    def test_normal_values_pass_through(self):
        self.assertEqual(_clamp_limit(7, default=50), 7)


class TestReadBoundsApplied(unittest.TestCase):
    def test_list_findings_clamps_negative_limit_and_offset(self):
        conn = MagicMock()
        with patch("openlmlib.library.load_settings") as load, \
             patch("openlmlib.library.db") as db_mock:
            load.return_value.db_path = Path("/tmp/unused.db")
            db_mock.connect.return_value = conn
            list_findings(Path("/tmp/settings.json"), limit=-99, offset=-99)

        kwargs = db_mock.list_findings.call_args.kwargs
        self.assertEqual(kwargs["limit"], 50)   # default floor for invalid
        self.assertEqual(kwargs["offset"], 0)

    def test_list_findings_caps_oversized_limit(self):
        conn = MagicMock()
        with patch("openlmlib.library.load_settings") as load, \
             patch("openlmlib.library.db") as db_mock:
            load.return_value.db_path = Path("/tmp/unused.db")
            db_mock.connect.return_value = conn
            list_findings(Path("/tmp/settings.json"), limit=100_000)

        self.assertEqual(db_mock.list_findings.call_args.kwargs["limit"], FINDINGS_LIMIT_MAX)

    def test_search_fts_clamps_limit(self):
        conn = MagicMock()
        with patch("openlmlib.library.load_settings") as load, \
             patch("openlmlib.library.db") as db_mock:
            load.return_value.db_path = Path("/tmp/unused.db")
            db_mock.connect.return_value = conn
            search_fts(Path("/tmp/settings.json"), "query", limit=-5)

        self.assertEqual(db_mock.search_findings.call_args.kwargs["limit"], 10)


if __name__ == "__main__":
    unittest.main()
