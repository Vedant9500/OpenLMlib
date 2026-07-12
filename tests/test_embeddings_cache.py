import tempfile
import unittest
from pathlib import Path

from openlmlib.embeddings import EmbeddingCache


class TestEmbeddingCache(unittest.TestCase):
    def test_save_merges_disk_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cache.pkl"
            a = EmbeddingCache(path)
            a.set("a", [1.0, 0.0])
            a.save()

            b = EmbeddingCache(path)
            b.set("b", [0.0, 1.0])
            b.save()

            # Stale process A overwrites after B saved — must not drop b.
            a.set("a", [1.0, 0.0])
            a.save()

            reloaded = EmbeddingCache(path)
            self.assertIsNotNone(reloaded.get("a"))
            self.assertIsNotNone(reloaded.get("b"))


if __name__ == "__main__":
    unittest.main()
