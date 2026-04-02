from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from time import monotonic
import os

from . import db
from .embeddings import EmbeddingCache, SentenceTransformerEmbedder
from .settings import load_settings
from .vector_store import create_vector_store, load_vector_store


@dataclass
class RuntimeState:
    settings_path: Path
    settings: object
    conn: object
    cache: EmbeddingCache
    embedder: SentenceTransformerEmbedder
    store: object
    dirty_vector: bool = False
    dirty_cache: bool = False
    writes_since_flush: int = 0
    last_flush_ts: float = 0.0
    write_lock: RLock = field(default_factory=RLock)


_RUNTIME_LOCK = RLock()
_RUNTIMES: dict[str, RuntimeState] = {}


def _runtime_key(settings_path: Path) -> str:
    return str(settings_path.resolve()).lower()


def get_runtime(settings_path: Path) -> RuntimeState:
    key = _runtime_key(settings_path)
    with _RUNTIME_LOCK:
        existing = _RUNTIMES.get(key)
        if existing is not None:
            return existing

        settings = load_settings(settings_path)
        settings.data_root.mkdir(parents=True, exist_ok=True)
        settings.findings_dir.mkdir(parents=True, exist_ok=True)

        conn = db.connect(settings.db_path)
        db.init_db(conn)

        cache = EmbeddingCache(settings.embeddings_cache_path)
        embedder = SentenceTransformerEmbedder(
            settings.embedding_model,
            cache=cache,
            normalize=settings.embedding_metric == "cosine",
        )

        if settings.vector_index_path.exists() and settings.vector_meta_path.exists():
            store = load_vector_store(settings.vector_index_path, settings.vector_meta_path)
        else:
            store = create_vector_store(settings.embedding_dim, settings.embedding_metric)

        state = RuntimeState(
            settings_path=settings_path,
            settings=settings,
            conn=conn,
            cache=cache,
            embedder=embedder,
            store=store,
            last_flush_ts=monotonic(),
        )
        if os.environ.get("OPENLMLIB_EMBED_PREWARM", "1") != "0":
            # Force lazy model internals to initialize once at startup for better first-query latency.
            _ = embedder.encode(["openlmlib runtime prewarm"])
            cache.save()
        _RUNTIMES[key] = state
        return state


def shutdown_runtime(settings_path: Path) -> bool:
    """
    Shut down and remove a cached runtime.

    Closes the SQLite connection and removes the runtime from the cache.
    The next call to get_runtime() will create a fresh runtime with
    connections to the current files on disk.

    Returns True if a runtime was found and shut down, False otherwise.
    """
    key = _runtime_key(settings_path)
    with _RUNTIME_LOCK:
        state = _RUNTIMES.pop(key, None)
        if state is None:
            return False

    # Close outside the lock to avoid blocking other threads.
    # Connection may already be closed in edge cases.
    try:
        state.conn.close()
    except Exception:
        pass

    return True


def mark_dirty(state: RuntimeState, vector: bool = False, cache: bool = False) -> None:
    if vector:
        state.dirty_vector = True
    if cache:
        state.dirty_cache = True
    state.writes_since_flush += 1


def maybe_flush(state: RuntimeState, force: bool = False) -> bool:
    flush_every = int(os.environ.get("OPENLMLIB_FLUSH_EVERY", "5"))
    flush_interval_sec = float(os.environ.get("OPENLMLIB_FLUSH_INTERVAL_SEC", "30"))

    due_to_count = state.writes_since_flush >= max(1, flush_every)
    due_to_time = (monotonic() - state.last_flush_ts) >= max(1.0, flush_interval_sec)
    should_flush = force or due_to_count or due_to_time
    if not should_flush:
        return False

    if state.dirty_vector:
        from .vector_store import save_vector_store

        save_vector_store(state.store, state.settings.vector_index_path, state.settings.vector_meta_path)
        state.dirty_vector = False

    if state.dirty_cache:
        state.cache.save()
        state.dirty_cache = False

    state.writes_since_flush = 0
    state.last_flush_ts = monotonic()
    return True