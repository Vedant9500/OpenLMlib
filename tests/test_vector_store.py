import tempfile
import unittest
from pathlib import Path

from openlmlib.vector_store import (
    NumpyVectorStore,
    load_vector_store,
    save_vector_store,
)


class TestNumpyVectorStorePersistence(unittest.TestCase):
    def test_concurrent_merge_preserves_adds_and_deletes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            index_path = Path(tmpdir) / "embeddings.pkl"
            meta_path = Path(tmpdir) / "embeddings_meta.json"

            initial = NumpyVectorStore(dim=2, metric="cosine")
            save_vector_store(initial, index_path, meta_path)

            writer_a = load_vector_store(index_path, meta_path)
            writer_b = load_vector_store(index_path, meta_path)

            writer_a.add([101], [[1.0, 0.0]])
            save_vector_store(writer_a, index_path, meta_path)

            writer_b.add([202], [[0.0, 1.0]])
            save_vector_store(writer_b, index_path, meta_path)

            merged = load_vector_store(index_path, meta_path)
            self.assertEqual(merged.count(), 2)

            merged.delete([101])
            save_vector_store(merged, index_path, meta_path)

            reloaded = load_vector_store(index_path, meta_path)
            self.assertEqual(reloaded.count(), 1)
            self.assertEqual(reloaded.search([1.0, 0.0], 10)[0][0], 202)

    def test_rebuild_save_replaces_stale_vectors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            index_path = Path(tmpdir) / "embeddings.pkl"
            meta_path = Path(tmpdir) / "embeddings_meta.json"

            stale = NumpyVectorStore(dim=2, metric="cosine")
            stale.add([101, 202], [[1.0, 0.0], [0.0, 1.0]])
            save_vector_store(stale, index_path, meta_path)

            rebuilt = NumpyVectorStore(dim=2, metric="cosine")
            rebuilt.add([202], [[0.0, 1.0]])
            save_vector_store(rebuilt, index_path, meta_path, merge_existing=False)

            reloaded = load_vector_store(index_path, meta_path)
            self.assertEqual(reloaded.count(), 1)
            self.assertEqual(reloaded.search([1.0, 0.0], 10)[0][0], 202)


if __name__ == "__main__":
    unittest.main()
