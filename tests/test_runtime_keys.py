"""Runtime cache-key case handling (M-14)."""

import sys
import unittest
from pathlib import Path

from openlmlib.runtime import _runtime_key


class TestRuntimeKey(unittest.TestCase):
    def test_posix_keys_are_case_sensitive(self):
        if sys.platform.startswith("win"):
            self.skipTest("Windows paths are case-insensitive by design")
        # Case-distinct paths are distinct libraries on POSIX and must not
        # share cached runtime state.
        self.assertNotEqual(
            _runtime_key(Path("/tmp/A.json")),
            _runtime_key(Path("/tmp/a.json")),
        )

    def test_same_path_yields_stable_key(self):
        p = Path("/tmp/some-settings.json")
        self.assertEqual(_runtime_key(p), _runtime_key(Path("/tmp") / "some-settings.json"))

    def test_relative_and_absolute_resolve_together(self):
        base = Path(__file__).resolve().parent.parent
        key_abs = _runtime_key(base / "openlmlib" / ".." / "openlmlib")
        key_norm = _runtime_key(base / "openlmlib")
        self.assertEqual(key_abs, key_norm)


if __name__ == "__main__":
    unittest.main()
