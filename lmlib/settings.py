from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json


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
        )


def default_settings(base_dir: Path) -> Settings:
    return Settings.from_dict({}, base_dir)


def load_settings(path: Path) -> Settings:
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        base_dir = path.parent.parent if path.parent.name == "config" else path.parent
        return Settings.from_dict(data, base_dir)

    base_dir = path.parent.parent if path.parent.name == "config" else path.parent
    return default_settings(base_dir)
