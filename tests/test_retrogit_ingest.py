import unittest
from pathlib import Path
from unittest.mock import patch

from openlmlib.memory.retrogit_ingest import retroactive_ingest
from openlmlib.memory.storage import MemoryStorage
import sqlite3


class TestRetroactiveIngest(unittest.TestCase):
    def test_uses_provided_storage_not_hardcoded_settings(self):
        conn = sqlite3.connect(":memory:")
        storage = MemoryStorage(conn)

        with patch("openlmlib.memory.retrogit_ingest.get_modified_files", return_value=[]), \
             patch("openlmlib.memory.retrogit_ingest.get_recent_commits", return_value=[]), \
             patch("openlmlib.runtime.get_runtime") as get_runtime:
            result = retroactive_ingest(
                session_id="git-sess",
                storage=storage,
                include_uncommitted=True,
            )

        get_runtime.assert_not_called()
        self.assertEqual(result["session_id"], "git-sess")
        session = storage.get_session("git-sess")
        self.assertIsNotNone(session)
        conn.close()


if __name__ == "__main__":
    unittest.main()
