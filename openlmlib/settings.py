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
    validity_days: int = 90


@dataclass
class RerankingSettings:
    model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    top_k: int = 10
    enabled: bool = True
    batch_size: int = 32
    alpha: float = 0.7


@dataclass
class QueryExpansionSettings:
    enabled: bool = False
    max_variants: int = 3
    strategy: str = "rule_based"


@dataclass
class DecompositionSettings:
    enabled: bool = True
    min_relevance_threshold: float = 0.3
    include_caveats: bool = True
    max_evidence_items: int = 3


@dataclass
class PackingSettings:
    max_tokens: int = 4000
    enabled: bool = True


@dataclass
class Phase4Settings:
    reranking: RerankingSettings
    query_expansion: QueryExpansionSettings
    decomposition: DecompositionSettings
    packing: PackingSettings


@dataclass
class MemoryInjectionSettings:
    enabled: bool = True
    observations_at_session_start: int = 50
    auto_log_tool_use: bool = True
    progressive_disclosure: bool = True
    max_context_tokens: int = 4000
    privacy_filtering: bool = True
    compression_enabled: bool = True
    max_observations_per_session: int = 500
    session_cleanup_days: int = 30
    caveman_enabled: bool = True
    caveman_intensity: str = 'ultra'


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
    phase4: Phase4Settings
    memory: MemoryInjectionSettings

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
        phase4_data = data.get("phase4", {})
        memory_data = data.get("memory", {})

        reranking_data = phase4_data.get("reranking", {})
        expansion_data = phase4_data.get("query_expansion", {})
        decomposition_data = phase4_data.get("decomposition", {})
        packing_data = phase4_data.get("packing", {})

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
                validity_days=int(retrieval_data.get("validity_days", 90)),
            ),
            phase4=Phase4Settings(
                reranking=RerankingSettings(
                    model_name=reranking_data.get("model_name", "cross-encoder/ms-marco-MiniLM-L-6-v2"),
                    top_k=int(reranking_data.get("top_k", 10)),
                    enabled=bool(reranking_data.get("enabled", True)),
                    batch_size=int(reranking_data.get("batch_size", 32)),
                    alpha=float(reranking_data.get("alpha", 0.7)),
                ),
                query_expansion=QueryExpansionSettings(
                    enabled=bool(expansion_data.get("enabled", False)),
                    max_variants=int(expansion_data.get("max_variants", 3)),
                    strategy=expansion_data.get("strategy", "rule_based"),
                ),
                decomposition=DecompositionSettings(
                    enabled=bool(decomposition_data.get("enabled", True)),
                    min_relevance_threshold=float(decomposition_data.get("min_relevance_threshold", 0.3)),
                    include_caveats=bool(decomposition_data.get("include_caveats", True)),
                    max_evidence_items=int(decomposition_data.get("max_evidence_items", 3)),
                ),
                packing=PackingSettings(
                    max_tokens=int(packing_data.get("max_tokens", 4000)),
                    enabled=bool(packing_data.get("enabled", True)),
                ),
            ),
            memory=MemoryInjectionSettings(
                enabled=bool(memory_data.get("enabled", True)),
                observations_at_session_start=int(memory_data.get("observations_at_session_start", 50)),
                auto_log_tool_use=bool(memory_data.get("auto_log_tool_use", True)),
                progressive_disclosure=bool(memory_data.get("progressive_disclosure", True)),
                max_context_tokens=int(memory_data.get("max_context_tokens", 4000)),
                privacy_filtering=bool(memory_data.get("privacy_filtering", True)),
                compression_enabled=bool(memory_data.get("compression_enabled", True)),
                max_observations_per_session=int(memory_data.get("max_observations_per_session", 500)),
                session_cleanup_days=int(memory_data.get("session_cleanup_days", 30)),
                caveman_enabled=bool(memory_data.get("caveman_enabled", True)),
                caveman_intensity=memory_data.get("caveman_intensity", "ultra"),
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
        "validity_days": 90,
    },
    "phase4": {
        "reranking": {
            "model_name": "cross-encoder/ms-marco-MiniLM-L-6-v2",
            "top_k": 10,
            "enabled": True,
            "batch_size": 32,
            "alpha": 0.7,
        },
        "query_expansion": {
            "enabled": False,
            "max_variants": 3,
            "strategy": "rule_based",
        },
        "decomposition": {
            "enabled": True,
            "min_relevance_threshold": 0.3,
            "include_caveats": True,
            "max_evidence_items": 3,
        },
        "packing": {
            "max_tokens": 4000,
            "enabled": True,
        },
    },
    "memory": {
        "enabled": True,
        "observations_at_session_start": 50,
        "auto_log_tool_use": True,
        "progressive_disclosure": True,
        "max_context_tokens": 4000,
        "privacy_filtering": True,
        "compression_enabled": True,
        "max_observations_per_session": 500,
        "session_cleanup_days": 30,
        "caveman_enabled": True,
        "caveman_intensity": "ultra",
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
