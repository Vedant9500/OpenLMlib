import os
import tempfile
import time
import unittest
from pathlib import Path

from openlmlib.file_lock import (
    _lock_is_reclaimable,
    _pid_is_alive,
    interprocess_lock,
)


class TestFileLock(unittest.TestCase):
    def test_pid_is_alive_self(self):
        self.assertTrue(_pid_is_alive(os.getpid()))

    def test_pid_is_alive_missing(self):
        self.assertFalse(_pid_is_alive(2_000_000_001))

    def test_reclaim_empty_lock_after_grace(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "test.lock"
            lock_path.write_text("", encoding="utf-8")
            old = time.time() - 5.0
            os.utime(lock_path, (old, old))
            self.assertTrue(_lock_is_reclaimable(lock_path, stale_after_sec=2.0))

    def test_reclaim_invalid_pid_after_grace(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "test.lock"
            lock_path.write_text("not-a-pid", encoding="utf-8")
            old = time.time() - 5.0
            os.utime(lock_path, (old, old))
            self.assertTrue(_lock_is_reclaimable(lock_path, stale_after_sec=2.0))

    def test_interprocess_lock_recovers_empty_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "test.lock"
            lock_path.write_text("", encoding="utf-8")
            old = time.time() - 5.0
            os.utime(lock_path, (old, old))
            with interprocess_lock(lock_path, timeout_sec=2.0, poll_interval_sec=0.05):
                self.assertTrue(lock_path.exists())
                self.assertEqual(lock_path.read_text(encoding="utf-8").strip(), str(os.getpid()))


if __name__ == "__main__":
    unittest.main()
