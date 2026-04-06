"""OpenRouter API integration for CollabSessions.

Provides model listing, selection, and configuration for multi-agent
collaboration sessions. Agents can browse available models and choose
the right one for their task.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, Optional


OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"
MODELS_CACHE_FILE = "openrouter_models.json"
MODELS_CACHE_TTL_SECONDS = 3600


def _get_api_key() -> Optional[str]:
    """Get OpenRouter API key from environment."""
    return os.environ.get("OPENROUTER_API_KEY")


def _get_cache_path(sessions_dir: Optional[Path] = None) -> Path:
    """Get the path to the models cache file."""
    if sessions_dir:
        return sessions_dir / MODELS_CACHE_FILE
    return Path("data") / MODELS_CACHE_FILE


def _is_cache_valid(cache_path: Path) -> bool:
    """Check if the cache file exists and is not expired."""
    if not cache_path.exists():
        return False
    import time
    mtime = cache_path.stat().st_mtime
    return (time.time() - mtime) < MODELS_CACHE_TTL_SECONDS


def _load_cached_models(cache_path: Path) -> Optional[List[Dict]]:
    """Load models from cache file."""
    if not cache_path.exists():
        return None
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def _save_cache(cache_path: Path, models: List[Dict]) -> None:
    """Save models to cache file."""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(models, f, indent=2, ensure_ascii=False)


def _request_json_with_retry(req: urllib.request.Request, timeout: int, operation: str, max_attempts: int = 5, base_delay: float = 1.0) -> Dict:
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last_error = e
            if e.code in {429, 500, 502, 503, 504} and attempt < max_attempts:
                retry_after = None
                if getattr(e, "headers", None):
                    retry_after = e.headers.get("Retry-After")
                delay = base_delay * (2 ** (attempt - 1))
                if retry_after:
                    try:
                        delay = max(delay, float(retry_after))
                    except ValueError:
                        pass
                time.sleep(delay)
                continue
            raise

    if last_error is not None:
        raise last_error
    raise RuntimeError(f"{operation} failed")


def fetch_openrouter_models(
    sessions_dir: Optional[Path] = None,
    force_refresh: bool = False,
) -> Dict:
    """Fetch available models from OpenRouter API.

    Uses a local cache to avoid excessive API calls.
    Cache is valid for 1 hour by default.

    Args:
        sessions_dir: Optional sessions directory for cache location
        force_refresh: Force a fresh API call, ignoring cache

    Returns:
        Dict with models list and metadata
    """
    cache_path = _get_cache_path(sessions_dir)

    if not force_refresh and _is_cache_valid(cache_path):
        cached = _load_cached_models(cache_path)
        if cached is not None:
            return {
                "models": cached,
                "count": len(cached),
                "source": "cache",
            }

    api_key = _get_api_key()
    if not api_key:
        return {
            "error": "OPENROUTER_API_KEY environment variable not set",
            "models": [],
            "count": 0,
            "source": "none",
        }

    try:
        url = f"{OPENROUTER_API_BASE}/models"
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Bearer {api_key}")
        req.add_header("Content-Type", "application/json")
        req.add_header("HTTP-Referer", "https://github.com/openlmlib")

        data = _request_json_with_retry(req, timeout=30, operation="Fetching OpenRouter models")

        models = data.get("data", [])
        _save_cache(cache_path, models)

        return {
            "models": models,
            "count": len(models),
            "source": "api",
        }
    except urllib.error.HTTPError as e:
        return {
            "error": f"API error: {e.code} {e.reason}",
            "models": [],
            "count": 0,
            "source": "error",
        }
    except urllib.error.URLError as e:
        return {
            "error": f"Connection error: {e.reason}",
            "models": [],
            "count": 0,
            "source": "error",
        }
    except Exception as e:
        return {
            "error": str(e),
            "models": [],
            "count": 0,
            "source": "error",
        }


def filter_models(
    models: List[Dict],
    search: Optional[str] = None,
    provider: Optional[str] = None,
    max_price_per_million: Optional[float] = None,
    context_length_min: Optional[int] = None,
    is_free: bool = False,
) -> List[Dict]:
    """Filter models by various criteria.

    Args:
        models: List of model dicts from OpenRouter
        search: Search term in model name or description
        provider: Filter by provider (e.g., 'openai', 'anthropic', 'google')
        max_price_per_million: Max combined input+output price per 1M tokens
        context_length_min: Minimum context length in tokens
        is_free: Only include free models

    Returns:
        Filtered list of models
    """
    results = list(models)

    if search:
        search_lower = search.lower()
        results = [
            m for m in results
            if search_lower in m.get("id", "").lower()
            or search_lower in m.get("name", "").lower()
            or search_lower in m.get("description", "").lower()
        ]

    if provider:
        provider_lower = provider.lower()
        results = [
            m for m in results
            if provider_lower in m.get("id", "").lower()
        ]

    if max_price_per_million is not None:
        def get_total_price(m: Dict) -> float:
            pricing = m.get("pricing", {})
            input_price = float(pricing.get("prompt", 0))
            output_price = float(pricing.get("completion", 0))
            return (input_price + output_price) * 1_000_000

        results = [m for m in results if get_total_price(m) <= max_price_per_million]

    if context_length_min is not None:
        results = [
            m for m in results
            if m.get("context_length", 0) >= context_length_min
        ]

    if is_free:
        results = [
            m for m in results
            if float(m.get("pricing", {}).get("prompt", 0)) == 0
            and float(m.get("pricing", {}).get("completion", 0)) == 0
        ]

    return results


def format_model_summary(model: Dict) -> str:
    """Format a model dict into a human-readable summary string."""
    lines = []
    lines.append(f"ID: {model.get('id', 'unknown')}")
    lines.append(f"Name: {model.get('name', 'unknown')}")

    pricing = model.get("pricing", {})
    input_price = float(pricing.get("prompt", 0))
    output_price = float(pricing.get("completion", 0))
    if input_price == 0 and output_price == 0:
        lines.append("Price: FREE")
    else:
        lines.append(f"Price: ${input_price * 1_000_000:.2f}/1M input, ${output_price * 1_000_000:.2f}/1M output")

    context_length = model.get("context_length")
    if context_length:
        lines.append(f"Context: {context_length:,} tokens")

    architecture = model.get("architecture", {})
    if architecture:
        modality = architecture.get("modality", "")
        if modality:
            lines.append(f"Modality: {modality}")
        tokenizer = architecture.get("tokenizer", "")
        if tokenizer:
            lines.append(f"Tokenizer: {tokenizer}")

    top_provider = model.get("top_provider", "")
    if top_provider:
        lines.append(f"Provider: {top_provider}")

    description = model.get("description", "")
    if description:
        desc_preview = description[:200] + "..." if len(description) > 200 else description
        lines.append(f"Description: {desc_preview}")

    return "\n".join(lines)


def get_recommended_models_for_task(task_type: str) -> List[str]:
    """Get recommended model IDs for a given task type.

    Args:
        task_type: Type of task (research, coding, analysis, writing, summarization)

    Returns:
        List of recommended model IDs
    """
    recommendations = {
        "research": [
            "anthropic/claude-sonnet-4",
            "google/gemini-2.5-pro",
            "openai/gpt-4.1",
            "anthropic/claude-opus-4.1",
        ],
        "coding": [
            "openai/gpt-4.1",
            "anthropic/claude-sonnet-4",
            "google/gemini-2.5-pro",
            "qwen/qwen3-coder",
        ],
        "analysis": [
            "anthropic/claude-sonnet-4",
            "google/gemini-2.5-pro",
            "openai/gpt-4.1",
        ],
        "writing": [
            "anthropic/claude-sonnet-4",
            "anthropic/claude-opus-4.1",
            "google/gemini-2.5-pro",
        ],
        "summarization": [
            "anthropic/claude-sonnet-4",
            "google/gemini-2.5-pro",
            "openai/gpt-4.1-mini",
        ],
        "orchestrator": [
            "anthropic/claude-opus-4.1",
            "openai/gpt-4.1",
            "google/gemini-2.5-pro",
        ],
        "worker": [
            "anthropic/claude-sonnet-4",
            "openai/gpt-4.1-mini",
            "google/gemini-2.5-flash",
            "qwen/qwen3-coder",
        ],
    }
    return recommendations.get(task_type.lower(), recommendations["research"])
