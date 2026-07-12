import unittest

from openlmlib.settings import _parse_bool


class TestParseBool(unittest.TestCase):
    def test_bool_passthrough(self):
        self.assertTrue(_parse_bool(True, False))
        self.assertFalse(_parse_bool(False, True))

    def test_int_zero_one(self):
        self.assertTrue(_parse_bool(1, False))
        self.assertFalse(_parse_bool(0, True))

    def test_string_forms(self):
        self.assertTrue(_parse_bool("yes", False))
        self.assertFalse(_parse_bool("off", True))

    def test_none_uses_default(self):
        self.assertTrue(_parse_bool(None, True))
        self.assertFalse(_parse_bool(None, False))

    def test_rejects_other_ints(self):
        with self.assertRaises(ValueError):
            _parse_bool(2, False)


if __name__ == "__main__":
    unittest.main()
