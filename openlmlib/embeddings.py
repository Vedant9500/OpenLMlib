from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Optional
import hashlib
import json
import logging
import os

import numpy as np

logger = logging.getLogger(__name__)

# Pickle protocol files start with 0x80 followed by a protocol version byte
# (or, for protocol 0, are plain-ASCII marshal-ish text). The current cache
# format is JSON only; a pickle signature means a pre-0.2.x legacy cache.
_PICKLE_SIGNATURES = (b"\x80", b"(dp0", b"dp0")


def _looks_like_legacy_pickle(raw: bytes) -> bool:
    return raw[:1] == b"\x80" or raw.startswith(_PICKLE_SIGNATURES[1:])


class EmbeddingCache:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._loaded = False
        self._cache = {}

    def _read_raw(self) -> Optional[bytes]:
        try:
            return self.path.read_bytes()
        except OSError:
            return None

    def _load(self) -> None:
        if self._loaded:
            return
        if self.path.exists():
            raw = self._read_raw()
            if raw and _looks_like_legacy_pickle(raw):
                # Never deserialize legacy pickles (unsafe format); surface an
                # explicit migration warning instead of failing silently (M-12).
                logger.warning(
                    "Legacy pickle embedding cache detected at %s (%d bytes). "
                    "It will not be loaded or deserialized. A JSON-format copy is "
                    "preserved beside it on the next save; delete the .legacy file "
                    "after confirming the migration.",
                    self.path,
                    len(raw),
                )
            else:
                try:
                    payload = json.loads(raw.decode("utf-8")) if raw is not None else None
                    if isinstance(payload, dict):
                        self._cache = payload
                except Exception:
                    logger.warning(
                        "Embedding cache at %s is not valid JSON; starting empty.",
                        self.path,
                    )
                    self._cache = {}
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
        from .file_lock import interprocess_lock

        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        with interprocess_lock(lock_path, timeout_sec=60.0):
            raw = self._read_raw() if self.path.exists() else None
            if raw and _looks_like_legacy_pickle(raw):
                # Preserve the legacy artifact before the atomic replace so the
                # migration never silently destroys old vectors (M-12).
                backup_path = self.path.with_suffix(self.path.suffix + ".legacy")
                try:
                    backup_path.write_bytes(raw)
                    logger.warning(
                        "Legacy pickle cache preserved at %s before JSON rewrite.",
                        backup_path,
                    )
                except OSError as exc:
                    raise RuntimeError(
                        f"Refusing to overwrite unreadable legacy embedding cache "
                        f"at {self.path}: could not preserve it ({exc})."
                    ) from exc
            elif raw is not None:
                # Merge disk state so concurrent processes do not drop each other's keys.
                try:
                    disk_payload = json.loads(raw.decode("utf-8"))
                    if isinstance(disk_payload, dict):
                        merged = dict(disk_payload)
                        merged.update(self._cache)
                        self._cache = merged
                except Exception:
                    pass
            tmp_path = self.path.with_suffix(self.path.suffix + f".{os.getpid()}.tmp")
            payload = {
                key: np.asarray(value, dtype=np.float32).tolist()
                for key, value in self._cache.items()
            }
            tmp_path.write_text(json.dumps(payload), encoding="utf-8")
            os.replace(tmp_path, self.path)


# Quiet sentence-transformers logger to avoid noisy HTTP checks and init logs
logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
logging.getLogger("transformers").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)


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

        # Try to load from local cache first to avoid slow Hugging Face Hub network checks.
        # This can save 2-5 seconds per cold start.
        try:
            self._model = SentenceTransformer(model_name, local_files_only=True)
        except Exception:
            # Fallback to normal load if not cached or if local_files_only fails
            self._model = SentenceTransformer(model_name)
        
        self._cache = cache
        self._normalize = normalize
        self.model_name = model_name

    def encode(self, texts: Iterable[str], batch_size: int = 32) -> np.ndarray:
        text_list = list(texts)
        if not text_list:
            return np.empty((0, 0), dtype=np.float32)

        encode_kwargs = {
            "convert_to_numpy": True,
            "normalize_embeddings": self._normalize,
            "batch_size": batch_size,
        }

        if self._cache is None:
            return self._model.encode(text_list, **encode_kwargs).astype("float32")

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
            encoded = self._model.encode(missing_texts, **encode_kwargs).astype("float32")
            for i, vec in enumerate(encoded):
                idx = missing_indexes[i]
                vectors[idx] = vec
                key = _cache_key(self.model_name, missing_texts[i])
                self._cache.set(key, vec)

        return np.vstack(vectors)


def _trim_tokens(text: str, max_tokens: int) -> str:
    tokens = text.split()
    if len(tokens) <= max_tokens:
        return text.strip()
    return " ".join(tokens[:max_tokens]).strip()


def build_contextual_chunk(
    claim: str,
    evidence: Optional[List[str]] = None,
    reasoning: str = "",
    full_text: str = "",
    context_tokens: int = 80,
) -> str:
    evidence = evidence or []
    evidence_text = " ".join(evidence)
    source = "\n".join([claim.strip(), reasoning.strip(), evidence_text.strip(), full_text.strip()]).strip()
    context = _trim_tokens(source, max_tokens=context_tokens)
    body = "\n".join(
        [
            f"Claim: {claim.strip()}",
            f"Evidence: {evidence_text.strip()}",
            f"Reasoning: {reasoning.strip()}",
        ]
    )
    if context:
        return f"Context: {context}\n{body}".strip()
    return body.strip()


def build_contextual_query(query: str, project: Optional[str] = None, tags: Optional[List[str]] = None) -> str:
    tags = tags or []
    scope_bits: List[str] = []
    if project:
        scope_bits.append(f"project={project}")
    if tags:
        scope_bits.append("tags=" + ",".join(tags))

    scope = " ".join(scope_bits)
    if not scope:
        return query.strip()
    return f"{query.strip()}\nScope: {scope}".strip()
