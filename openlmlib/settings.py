from __future__ import annotations

import copy
from dataclasses import dataclass
import json
from pathlib import Path


@dataclass
class WriteGateSettings:
    min_confidence: float = 0.6
    min_reasoning_length: int = 50
    min_claim_evidence_sim: float = 0.7


@dataclass
class NoveltySettings:
    similarity_threshold: float = 0.85
    top_k: int = 5


@dataclass
class RetrievalSettings:
    semantic_k: int = 20
    lexical_k: int = 20
    final_k: int = 5
    semantic_oversample_factor: int = 3


@dataclass
class Settings:
    data_root: Path
    db_path: Path
    vector_index_path: Path
    vector_meta_path: Path
    findings_dir: Path
    embeddings_cache_path: Path
    embedding_model: str
    embedding_dim: int
    embedding_metric: str
    write_gate: WriteGateSettings
    novelty: NoveltySettings
    retrieval: RetrievalSettings

    @classmethod
    def from_dict(cls, data: dict, base_dir: Path) -> "Settings":
        def resolve_path(value: str, default: str) -> Path:
            raw = data.get(value, default)
            path = Path(raw)
            if path.is_absolute():
                return path
            return base_dir / path

        write_gate_data = data.get("write_gate", {})
        novelty_data = data.get("novelty", {})
        retrieval_data = data.get("retrieval", {})

        return cls(
            data_root=resolve_path("data_root", "data"),
            db_path=resolve_path("db_path", "data/findings.db"),
            vector_index_path=resolve_path("vector_index_path", "data/embeddings.faiss"),
            vector_meta_path=resolve_path("vector_meta_path", "data/embeddings_meta.json"),
            findings_dir=resolve_path("findings_dir", "data/findings"),
            embeddings_cache_path=resolve_path("embeddings_cache_path", "data/embeddings_cache.pkl"),
            embedding_model=data.get("embedding_model", "sentence-transformers/all-MiniLM-L6-v2"),
            embedding_dim=int(data.get("embedding_dim", 384)),
            embedding_metric=data.get("embedding_metric", "cosine"),
            write_gate=WriteGateSettings(
                min_confidence=float(write_gate_data.get("min_confidence", 0.6)),
                min_reasoning_length=int(write_gate_data.get("min_reasoning_length", 50)),
                min_claim_evidence_sim=float(write_gate_data.get("min_claim_evidence_sim", 0.7)),
            ),
            novelty=NoveltySettings(
                similarity_threshold=float(novelty_data.get("similarity_threshold", 0.85)),
                top_k=int(novelty_data.get("top_k", 5)),
            ),
            retrieval=RetrievalSettings(
                semantic_k=int(retrieval_data.get("semantic_k", 20)),
                lexical_k=int(retrieval_data.get("lexical_k", 20)),
                final_k=int(retrieval_data.get("final_k", 5)),
                semantic_oversample_factor=int(retrieval_data.get("semantic_oversample_factor", 3)),
            ),
        )


DEFAULT_SETTINGS_DATA = {
    "data_root": "data",
    "db_path": "data/findings.db",
    "vector_index_path": "data/embeddings.faiss",
    "vector_meta_path": "data/embeddings_meta.json",
    "findings_dir": "data/findings",
    "embeddings_cache_path": "data/embeddings_cache.pkl",
    "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
    "embedding_dim": 384,
    "embedding_metric": "cosine",
    "write_gate": {
        "min_confidence": 0.6,
        "min_reasoning_length": 50,
        "min_claim_evidence_sim": 0.7,
    },
    "novelty": {
        "similarity_threshold": 0.85,
        "top_k": 5,
    },
    "retrieval": {
        "semantic_k": 20,
        "lexical_k": 20,
        "final_k": 5,
        "semantic_oversample_factor": 3,
    },
}


def default_settings_payload() -> dict:
    return copy.deepcopy(DEFAULT_SETTINGS_DATA)


def default_settings(base_dir: Path) -> Settings:
    return Settings.from_dict(default_settings_payload(), base_dir)


def load_settings(path: Path) -> Settings:
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        base_dir = path.parent.parent if path.parent.name == "config" else path.parent
        return Settings.from_dict(data, base_dir)

    base_dir = path.parent.parent if path.parent.name == "config" else path.parent
    return default_settings(base_dir)


def write_default_settings(path: Path) -> Path:
    if path.exists():
        return path

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(default_settings_payload(), indent=2), encoding="utf-8")
    return path


def resolve_global_settings_path() -> Path:
    return Path.home() / ".openlmlib" / "config" / "settings.json"


def resolve_hybrid_settings_path() -> Path:
    """Returns local settings if they exist, otherwise global ~/.openlmlib/config/settings.json."""
    local_path = Path("config/settings.json").resolve()
    if local_path.exists():
        return local_path
    return resolve_global_settings_path()
