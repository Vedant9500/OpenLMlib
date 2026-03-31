import unittest

from lmlib.schema import compute_content_hash, make_embedding_id


class TestSchema(unittest.TestCase):
    def test_content_hash_stable(self):
        data_a = {"a": 1, "b": [2, 3]}
        data_b = {"b": [2, 3], "a": 1}
        self.assertEqual(compute_content_hash(data_a), compute_content_hash(data_b))

    def test_embedding_id_deterministic(self):
        first = make_embedding_id("glassbox-001")
        second = make_embedding_id("glassbox-001")
        third = make_embedding_id("glassbox-002")
        self.assertEqual(first, second)
        self.assertNotEqual(first, third)


if __name__ == "__main__":
    unittest.main()
