"""Session templates for CollabSessions.

Predefined session plans for common research patterns that agents
can use to quickly start structured collaboration sessions.

Templates are loaded from built-in defaults and can be extended
with custom templates persisted to disk as JSON files.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

TEMPLATES: Dict[str, Dict] = {
    "deep_research": {
        "name": "Deep Research",
        "description": "Comprehensive research on a topic with literature review, analysis, and synthesis",
        "rules": {
            "max_agents": 5,
            "require_assignment": True,
            "max_message_length": 8000,
            "require_artifact_for_results": True,
            "auto_compact_after_messages": 30,
        },
        "plan": [
            {"step": 1, "task": "Literature review: Find and summarize key papers/sources", "assigned_to": "any"},
            {"step": 2, "task": "Technical analysis: Deep-dive into the most important findings", "assigned_to": "any"},
            {"step": 3, "task": "Comparative analysis: Compare approaches, methods, results", "assigned_to": "any"},
            {"step": 4, "task": "Synthesis: Combine findings into a comprehensive report", "assigned_to": "orchestrator"},
            {"step": 5, "task": "Review and validation: Check accuracy, identify gaps", "assigned_to": "any"},
        ],
    },
    "code_review": {
        "name": "Multi-Agent Code Review",
        "description": "Thorough code review with security, performance, and architecture analysis",
        "rules": {
            "max_agents": 4,
            "require_assignment": True,
            "max_message_length": 6000,
            "require_artifact_for_results": True,
            "auto_compact_after_messages": 20,
        },
        "plan": [
            {"step": 1, "task": "Architecture review: Evaluate design patterns, modularity, coupling", "assigned_to": "any"},
            {"step": 2, "task": "Security audit: Identify vulnerabilities, input validation, auth issues", "assigned_to": "any"},
            {"step": 3, "task": "Performance analysis: Identify bottlenecks, complexity issues, memory leaks", "assigned_to": "any"},
            {"step": 4, "task": "Code quality: Style, readability, test coverage, documentation", "assigned_to": "any"},
            {"step": 5, "task": "Consolidated report: Combine all findings with prioritized recommendations", "assigned_to": "orchestrator"},
        ],
    },
    "market_analysis": {
        "name": "Market/Competitor Analysis",
        "description": "Analyze market landscape, competitors, and opportunities",
        "rules": {
            "max_agents": 4,
            "require_assignment": False,
            "max_message_length": 6000,
            "require_artifact_for_results": False,
            "auto_compact_after_messages": 25,
        },
        "plan": [
            {"step": 1, "task": "Market overview: Size, growth, trends, key drivers", "assigned_to": "any"},
            {"step": 2, "task": "Competitor analysis: Key players, products, positioning, strengths/weaknesses", "assigned_to": "any"},
            {"step": 3, "task": "Technology landscape: Emerging tech, adoption rates, disruption potential", "assigned_to": "any"},
            {"step": 4, "task": "Opportunity identification: Gaps, white spaces, strategic recommendations", "assigned_to": "orchestrator"},
        ],
    },
    "incident_investigation": {
        "name": "Incident Investigation",
        "description": "Structured investigation of a production incident or bug",
        "rules": {
            "max_agents": 3,
            "require_assignment": True,
            "max_message_length": 10000,
            "require_artifact_for_results": True,
            "auto_compact_after_messages": 15,
        },
        "plan": [
            {"step": 1, "task": "Timeline reconstruction: What happened, when, in what order", "assigned_to": "any"},
            {"step": 2, "task": "Root cause analysis: Identify the underlying cause(s)", "assigned_to": "any"},
            {"step": 3, "task": "Impact assessment: What was affected, scope, severity", "assigned_to": "any"},
            {"step": 4, "task": "Remediation plan: Immediate fixes and long-term prevention", "assigned_to": "orchestrator"},
        ],
    },
    "literature_review": {
        "name": "Academic Literature Review",
        "description": "Systematic review of academic papers on a specific topic",
        "rules": {
            "max_agents": 5,
            "require_assignment": True,
            "max_message_length": 8000,
            "require_artifact_for_results": True,
            "auto_compact_after_messages": 40,
        },
        "plan": [
            {"step": 1, "task": "Search strategy: Define search terms, databases, inclusion criteria", "assigned_to": "orchestrator"},
            {"step": 2, "task": "Paper collection: Gather relevant papers from multiple sources", "assigned_to": "any"},
            {"step": 3, "task": "Quality assessment: Evaluate methodology, rigor, relevance", "assigned_to": "any"},
            {"step": 4, "task": "Thematic analysis: Group findings by theme, identify patterns", "assigned_to": "any"},
            {"step": 5, "task": "Gap analysis: Identify what's missing, open questions", "assigned_to": "any"},
            {"step": 6, "task": "Write review: Comprehensive literature review document", "assigned_to": "orchestrator"},
        ],
    },
}

_custom_templates_dir: Optional[Path] = None


def _get_custom_templates_dir() -> Path:
    """Get the directory for custom template JSON files."""
    global _custom_templates_dir
    if _custom_templates_dir is not None:
        return _custom_templates_dir

    import os
    settings_path_str = os.environ.get("OPENLMLIB_SETTINGS")
    if settings_path_str:
        settings_path = Path(settings_path_str)
    else:
         try:
             from openlmlib.settings import resolve_global_settings_path
             settings_path = resolve_global_settings_path()
         except ImportError:
            settings_path = Path("settings.json")

    if settings_path.exists():
        with open(settings_path) as f:
            cfg = json.load(f)
        data_root = Path(cfg.get("data_root", "data"))
    else:
        data_root = Path("data")

    _custom_templates_dir = data_root / "collab_templates"
    _custom_templates_dir.mkdir(parents=True, exist_ok=True)
    return _custom_templates_dir


def _load_custom_templates() -> Dict[str, Dict]:
    """Load custom templates from disk JSON files."""
    templates_dir = _get_custom_templates_dir()
    custom = {}
    for fpath in templates_dir.glob("*.json"):
        try:
            with open(fpath) as f:
                data = json.load(f)
            if "template_id" in data and "plan" in data:
                custom[data["template_id"]] = data
        except (json.JSONDecodeError, KeyError):
            continue
    return custom


def _save_custom_template(template_id: str, data: Dict) -> Path:
    """Save a custom template to disk as JSON."""
    templates_dir = _get_custom_templates_dir()
    fpath = templates_dir / f"{template_id}.json"
    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return fpath


def _delete_custom_template(template_id: str) -> bool:
    """Delete a custom template from disk."""
    templates_dir = _get_custom_templates_dir()
    fpath = templates_dir / f"{template_id}.json"
    if fpath.exists():
        fpath.unlink()
        return True
    return False


def list_templates() -> List[Dict]:
    """List all available session templates (built-in + custom)."""
    custom = _load_custom_templates()
    all_templates = {**TEMPLATES, **custom}
    return [
        {
            "template_id": tid,
            "name": t["name"],
            "description": t["description"],
            "steps": len(t["plan"]),
            "max_agents": t["rules"].get("max_agents", 5),
            "source": "custom" if tid in custom else "built-in",
        }
        for tid, t in all_templates.items()
    ]


def get_template(template_id: str) -> Optional[Dict]:
    """Get a session template by ID (checks custom then built-in)."""
    custom = _load_custom_templates()
    if template_id in custom:
        template = custom[template_id]
        return {
            "template_id": template_id,
            "name": template["name"],
            "description": template["description"],
            "plan": template["plan"],
            "rules": template.get("rules", {}),
            "source": "custom",
        }
    template = TEMPLATES.get(template_id)
    if template is None:
        return None
    return {
        "template_id": template_id,
        "name": template["name"],
        "description": template["description"],
        "plan": template["plan"],
        "rules": template["rules"],
        "source": "built-in",
    }


def create_template(
    template_id: str,
    name: str,
    description: str,
    plan: List[Dict],
    rules: Optional[Dict] = None,
) -> Dict:
    """Register a custom session template and persist to disk.

    Args:
        template_id: Unique identifier for the template
        name: Human-readable name
        description: Template description
        plan: List of task dicts with 'step', 'task', 'assigned_to'
        rules: Optional session rules

    Returns:
        The registered template dict
    """
    from .rules_engine import DEFAULT_RULES
    template = {
        "template_id": template_id,
        "name": name,
        "description": description,
        "plan": plan,
        "rules": {**DEFAULT_RULES, **(rules or {})},
    }
    _save_custom_template(template_id, template)
    return template


def delete_template(template_id: str) -> bool:
    """Delete a custom template. Cannot delete built-in templates.

    Args:
        template_id: Template to delete

    Returns:
        True if deleted, False if built-in or not found
    """
    if template_id in TEMPLATES:
        return False
    return _delete_custom_template(template_id)
