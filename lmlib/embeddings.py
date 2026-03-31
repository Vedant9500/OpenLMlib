from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Optional
import hashlib
import pickle

import numpy as np


class EmbeddingCache:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._loaded = False
        self._cache = {}

    def _load(self) -> None:
        if self._loaded:
            return
        if self.path.exists():
            with self.path.open("rb") as handle:
                self._cache = pickle.load(handle)
        self._loaded = True

    def get(self, key: str):
        self._load()
        return self._cache.get(key)

    def set(self, key: str, vector) -> None:
        self._load()
        self._cache[key] = vector

    def save(self) -> None:
        if not self._loaded:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("wb") as handle:
            pickle.dump(self._cache, handle)


def _cache_key(model_name: str, text: str) -> str:
    payload = f"{model_name}::{text}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class SentenceTransformerEmbedder:
    def __init__(
        self,
        model_name: str,
        cache: Optional[EmbeddingCache] = None,
        normalize: bool = True,
    ) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise ImportError(
                "sentence-transformers is required for embeddings. Install it with 'pip install sentence-transformers'."
            ) from exc

        self._model = SentenceTransformer(model_name)
        self._cache = cache
        self._normalize = normalize
        self.model_name = model_name

    def encode(self, texts: Iterable[str]) -> np.ndarray:
        text_list = list(texts)
        if not text_list:
            return np.empty((0, 0), dtype=np.float32)

        if self._cache is None:
            return self._model.encode(
                text_list,
                convert_to_numpy=True,
                normalize_embeddings=self._normalize,
            ).astype("float32")

        vectors: List[np.ndarray] = [None] * len(text_list)  # type: ignore[list-item]
        missing_texts: List[str] = []
        missing_indexes: List[int] = []

        for idx, text in enumerate(text_list):
            key = _cache_key(self.model_name, text)
            cached = self._cache.get(key)
            if cached is None:
                missing_texts.append(text)
                missing_indexes.append(idx)
            else:
                vectors[idx] = np.asarray(cached, dtype=np.float32)

        if missing_texts:
            encoded = self._model.encode(
                missing_texts,
                convert_to_numpy=True,
                normalize_embeddings=self._normalize,
            ).astype("float32")
            for i, vec in enumerate(encoded):
                idx = missing_indexes[i]
                vectors[idx] = vec
                key = _cache_key(self.model_name, missing_texts[i])
                self._cache.set(key, vec)

        return np.vstack(vectors)
