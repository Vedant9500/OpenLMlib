from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Tuple
import json
import math
import os

import numpy as np

try:
    import faiss  # type: ignore
except ImportError:  # pragma: no cover
    faiss = None


@dataclass
class VectorStoreMeta:
    backend: str
    dim: int
    metric: str
    index_path: str

    def to_dict(self) -> dict:
        return {
            "backend": self.backend,
            "dim": self.dim,
            "metric": self.metric,
            "index_path": self.index_path,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "VectorStoreMeta":
        return cls(
            backend=data["backend"],
            dim=int(data["dim"]),
            metric=data["metric"],
            index_path=data["index_path"],
        )


class VectorStore:
    backend = "base"

    def __init__(self, dim: int, metric: str) -> None:
        self.dim = dim
        self.metric = metric

    def add(self, ids: Iterable[int], vectors: Iterable[Iterable[float]]) -> None:
        raise NotImplementedError

    def delete(self, ids: Iterable[int]) -> None:
        raise NotImplementedError

    def search(self, query_vector: Iterable[float], k: int) -> List[Tuple[int, float]]:
        raise NotImplementedError

    def count(self) -> int:
        raise NotImplementedError

    def save(self, index_path: Path) -> None:
        raise NotImplementedError


class FaissVectorStore(VectorStore):
    backend = "faiss"

    def __init__(self, dim: int, metric: str) -> None:
        if faiss is None:
            raise ImportError("faiss is not installed. Install faiss-cpu or faiss-gpu to use this backend.")
        super().__init__(dim, metric)
        self._pending_add_vectors: dict[int, np.ndarray] = {}
        self._pending_delete_ids: set[int] = set()
        if metric == "cosine":
            self._normalize = True
            index = faiss.IndexFlatIP(dim)
        elif metric == "l2":
            self._normalize = False
            index = faiss.IndexFlatL2(dim)
        else:
            raise ValueError(f"Unsupported metric: {metric}")

        self._index = faiss.IndexIDMap2(index)

    def add(self, ids: Iterable[int], vectors: Iterable[Iterable[float]]) -> None:
        vecs = np.asarray(vectors, dtype=np.float32)
        id_array = np.asarray(list(ids), dtype=np.int64)
        if vecs.size == 0:
            return
        if vecs.shape[1] != self.dim:
            raise ValueError("Vector dimension mismatch")
        if self._normalize:
            faiss.normalize_L2(vecs)
        self._index.add_with_ids(vecs, id_array)
        for idx, vec in zip(id_array, vecs):
            int_id = int(idx)
            self._pending_add_vectors[int_id] = np.asarray(vec, dtype=np.float32).copy()
            self._pending_delete_ids.discard(int_id)

    def delete(self, ids: Iterable[int]) -> None:
        id_array = np.asarray(list(ids), dtype=np.int64)
        if id_array.size == 0:
            return
        selector = faiss.IDSelectorBatch(id_array.size, faiss.swig_ptr(id_array))
        self._index.remove_ids(selector)
        for idx in id_array:
            int_id = int(idx)
            self._pending_add_vectors.pop(int_id, None)
            self._pending_delete_ids.add(int_id)

    def search(self, query_vector: Iterable[float], k: int) -> List[Tuple[int, float]]:
        query = np.asarray(list(query_vector), dtype=np.float32).reshape(1, -1)
        if query.shape[1] != self.dim:
            raise ValueError("Vector dimension mismatch")
        if self._normalize:
            faiss.normalize_L2(query)
        distances, ids = self._index.search(query, k)
        results: List[Tuple[int, float]] = []
        for idx, dist in zip(ids[0], distances[0]):
            if idx < 0:
                continue
            score = float(dist) if self.metric == "cosine" else float(-dist)
            results.append((int(idx), score))
        return results

    def count(self) -> int:
        return int(self._index.ntotal)

    def save(self, index_path: Path) -> None:
        index_path.parent.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._index, str(index_path))

    def clear_pending(self) -> None:
        self._pending_add_vectors.clear()
        self._pending_delete_ids.clear()

    @classmethod
    def load(cls, index_path: Path, metric: str) -> "FaissVectorStore":
        if faiss is None:
            raise ImportError("faiss is not installed.")
        index = faiss.read_index(str(index_path))
        store = cls(index.d, metric)
        store._index = index
        store.clear_pending()
        return store


class NumpyVectorStore(VectorStore):
    backend = "numpy"

    def __init__(self, dim: int, metric: str) -> None:
        super().__init__(dim, metric)
        self._vectors = {}
        self._deleted_ids: set[int] = set()

    def add(self, ids: Iterable[int], vectors: Iterable[Iterable[float]]) -> None:
        for idx, vec in zip(ids, vectors):
            idx = int(idx)
            arr = np.asarray(vec, dtype=np.float32)
            if arr.shape[0] != self.dim:
                raise ValueError("Vector dimension mismatch")
            self._vectors[idx] = arr
            self._deleted_ids.discard(idx)

    def delete(self, ids: Iterable[int]) -> None:
        for idx in ids:
            idx = int(idx)
            self._vectors.pop(idx, None)
            self._deleted_ids.add(idx)

    def search(self, query_vector: Iterable[float], k: int) -> List[Tuple[int, float]]:
        query = np.asarray(list(query_vector), dtype=np.float32)
        if query.shape[0] != self.dim:
            raise ValueError("Vector dimension mismatch")

        results: List[Tuple[int, float]] = []
        for idx, vec in self._vectors.items():
            score = _similarity(query, vec, self.metric)
            results.append((idx, score))

        results.sort(key=lambda item: item[1], reverse=True)
        return results[:k]

    def count(self) -> int:
        return len(self._vectors)

    def save(self, index_path: Path) -> None:
        index_path.parent.mkdir(parents=True, exist_ok=True)
        ids = np.asarray(list(self._vectors.keys()), dtype=np.int64)
        if ids.size:
            vectors = np.vstack([self._vectors[int(idx)] for idx in ids]).astype(np.float32)
        else:
            vectors = np.empty((0, self.dim), dtype=np.float32)
        with index_path.open("wb") as handle:
            np.savez(
                handle,
                dim=np.asarray([self.dim], dtype=np.int64),
                ids=ids,
                vectors=vectors,
            )

    @classmethod
    def load(cls, index_path: Path, metric: str) -> "NumpyVectorStore":
        with np.load(index_path, allow_pickle=False) as payload:
            dim = int(payload["dim"][0])
            ids = payload["ids"].astype(np.int64)
            vectors = payload["vectors"].astype(np.float32)
        store = cls(dim, metric)
        store._vectors = {
            int(idx): vectors[pos].copy()
            for pos, idx in enumerate(ids)
        }
        store._deleted_ids = set()
        return store


def _similarity(vec_a: np.ndarray, vec_b: np.ndarray, metric: str) -> float:
    if metric == "cosine":
        denom = (np.linalg.norm(vec_a) * np.linalg.norm(vec_b))
        if denom == 0:
            return 0.0
        return float(np.dot(vec_a, vec_b) / denom)
    if metric == "l2":
        return float(-np.linalg.norm(vec_a - vec_b))
    raise ValueError(f"Unsupported metric: {metric}")


def load_meta(meta_path: Path) -> VectorStoreMeta:
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    return VectorStoreMeta.from_dict(data)


def save_meta(meta_path: Path, meta: VectorStoreMeta) -> None:
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = meta_path.with_suffix(meta_path.suffix + f".{os.getpid()}.tmp")
    tmp_path.write_text(json.dumps(meta.to_dict(), indent=2), encoding="utf-8")
    os.replace(tmp_path, meta_path)


def create_vector_store(dim: int, metric: str, prefer_faiss: bool = True) -> VectorStore:
    if prefer_faiss and faiss is not None:
        return FaissVectorStore(dim, metric)
    return NumpyVectorStore(dim, metric)


def load_vector_store(index_path: Path, meta_path: Path) -> VectorStore:
    if meta_path.exists():
        meta = load_meta(meta_path)
        resolved_index_path = Path(meta.index_path)
        if not resolved_index_path.is_absolute():
            # Legacy metadata may store a relative path. Use the explicit
            # index_path argument from current settings to avoid cwd-dependent
            # failures when loading from MCP server processes.
            resolved_index_path = Path(index_path)
        if meta.backend == "faiss":
            if faiss is None:
                raise RuntimeError("Vector index uses faiss, but faiss is not installed.")
            return FaissVectorStore.load(resolved_index_path, meta.metric)
        if meta.backend == "numpy":
            try:
                return NumpyVectorStore.load(resolved_index_path, meta.metric)
            except Exception:
                return NumpyVectorStore(dim=meta.dim, metric=meta.metric)
        raise RuntimeError(f"Unknown vector store backend: {meta.backend}")

    return create_vector_store(dim=0, metric="cosine", prefer_faiss=False)


def save_vector_store(
    store: VectorStore,
    index_path: Path,
    meta_path: Path,
    merge_existing: bool = True,
) -> None:
    from .file_lock import interprocess_lock

    lock_path = meta_path.with_suffix(meta_path.suffix + ".lock")
    with interprocess_lock(lock_path, timeout_sec=60.0):
        original_store = store
        if merge_existing and meta_path.exists():
            try:
                existing_meta = load_meta(meta_path)
                if existing_meta.backend == store.backend and existing_meta.metric == store.metric:
                    if existing_meta.backend == "faiss" and index_path.exists():
                        try:
                            existing_store = FaissVectorStore.load(index_path, existing_meta.metric)
                            pending_deletes = list(getattr(store, "_pending_delete_ids", set()))
                            pending_adds = dict(getattr(store, "_pending_add_vectors", {}))
                            if pending_deletes:
                                existing_store.delete(pending_deletes)
                            if pending_adds:
                                existing_store.add(pending_adds.keys(), pending_adds.values())
                            existing_store.clear_pending()
                            store = existing_store
                        except Exception:
                            pass
                    elif existing_meta.backend == "numpy" and index_path.exists():
                        try:
                            existing_store = NumpyVectorStore.load(index_path, existing_meta.metric)
                            if getattr(store, "_vectors", None) is not None:
                                existing_store._vectors.update(store._vectors)
                                for deleted_id in getattr(store, "_deleted_ids", set()):
                                    existing_store._vectors.pop(int(deleted_id), None)
                                existing_store._deleted_ids = set(getattr(store, "_deleted_ids", set()))
                                store = existing_store
                        except Exception:
                            pass
            except Exception:
                pass

        store.save(index_path)
        meta = VectorStoreMeta(
            backend=store.backend,
            dim=store.dim,
            metric=store.metric,
            index_path=str(index_path),
        )
        save_meta(meta_path, meta)
        if hasattr(store, "clear_pending"):
            store.clear_pending()
        if original_store is not store and hasattr(original_store, "clear_pending"):
            original_store.clear_pending()
        if hasattr(store, "_deleted_ids"):
            store._deleted_ids.clear()
        if original_store is not store and hasattr(original_store, "_deleted_ids"):
            original_store._deleted_ids.clear()
