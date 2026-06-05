"""Co-Scientist workflow scope and safety policy.

Phase 0 keeps this deliberately deterministic: the policy is a small
rule-based pre-run screen that later orchestration tools can call before
creating generation or verification sessions.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Dict, Iterable, List, Optional, Pattern, Sequence


class CoScientistScopeError(ValueError):
    """Raised when a Co-Scientist request is outside the allowed scope."""


ACCEPTED_DOMAINS: List[str] = [
    "software architecture and codebase research",
    "safe technical literature review",
    "safe scientific and engineering ideation",
    "benchmark, reproducibility, and implementation feasibility analysis",
    "hypothesis generation followed by independent verification",
]

BLOCKED_DOMAINS: List[str] = [
    "harmful biological, chemical, radiological, or weapons research",
    "exploit development, malware, credential theft, phishing, or stealth abuse",
    "privacy invasion, doxxing, stalking, or personal-data exfiltration",
    "instructions to bypass safety controls, access controls, or monitoring",
]

PHASE_0_LIMITS: List[str] = [
    "artifact/session orchestration only",
    "read-mostly research by default",
    "no autonomous Codex or external worker spawning",
    "no automatic code edits from generated hypotheses",
    "no automatic export of speculative findings",
]

APPROVAL_REQUIRED_ACTIONS: List[str] = [
    "spending money or consuming paid external services",
    "running long jobs, benchmarks, or experiments",
    "modifying code, files, repositories, databases, or external systems",
    "calling external services beyond ordinary read-only research",
    "acting on scientific, biomedical, clinical, legal, or financial conclusions",
]


@dataclass(frozen=True)
class ScopeRule:
    category: str
    label: str
    pattern: Pattern[str]
    reason: str


@dataclass(frozen=True)
class ScopeDecision:
    allowed: bool
    risk_level: str
    categories: List[str]
    reasons: List[str]
    required_approvals: List[str]
    accepted_domains: List[str]
    blocked_domains: List[str]
    phase_0_limits: List[str]

    def to_dict(self) -> Dict[str, object]:
        return {
            "allowed": self.allowed,
            "risk_level": self.risk_level,
            "categories": self.categories,
            "reasons": self.reasons,
            "required_approvals": self.required_approvals,
            "accepted_domains": self.accepted_domains,
            "blocked_domains": self.blocked_domains,
            "phase_0_limits": self.phase_0_limits,
            "next_step": (
                "Proceed with Co-Scientist planning under Phase 0 limits."
                if self.allowed
                else "Do not create a Co-Scientist session for this request."
            ),
        }


def _compile(pattern: str) -> Pattern[str]:
    return re.compile(pattern, re.IGNORECASE | re.DOTALL)


BLOCK_RULES: Sequence[ScopeRule] = (
    ScopeRule(
        "biological_harm",
        "harmful biological protocol",
        _compile(r"\b(engineer|enhance|optimi[sz]e|release|spread|weaponi[sz]e)\b.{0,100}\b(pathogen|virus|bacteria|toxin|bioweapon)\b"),
        "The request appears to seek harmful biological capability or weaponization.",
    ),
    ScopeRule(
        "biological_harm",
        "gain-of-function misuse",
        _compile(r"\bgain[-\s]?of[-\s]?function\b|\benhance\b.{0,80}\b(transmissibility|virulence|pathogenicity)\b"),
        "The request appears to involve gain-of-function or enhanced pathogen capability.",
    ),
    ScopeRule(
        "chemical_or_weapon_harm",
        "explosive or weapon construction",
        _compile(r"\b(build|make|construct|manufacture|synthesize|assemble)\b.{0,100}\b(bomb|explosive|detonator|nerve agent|chemical weapon|radiological weapon)\b"),
        "The request appears to seek construction or synthesis of a weapon or dangerous agent.",
    ),
    ScopeRule(
        "cyber_abuse",
        "malware or ransomware",
        _compile(r"\b(write|build|create|deploy|improve|evade|hide|persist)\b.{0,100}\b(malware|ransomware|keylogger|botnet|rootkit)\b|\bransomware\b"),
        "The request appears to seek malware, ransomware, evasion, or persistence capability.",
    ),
    ScopeRule(
        "cyber_abuse",
        "credential theft or phishing",
        _compile(r"\b(credential theft|steal credentials|phishing kit|phishing page|session hijack|cookie theft)\b"),
        "The request appears to seek credential theft, phishing, or account-compromise capability.",
    ),
    ScopeRule(
        "cyber_abuse",
        "unauthorized exploitation",
        _compile(r"\b(exploit|bypass|privilege escalation|exfiltrate)\b.{0,100}\b(third[-\s]?party|production|target|victim|unauthorized|without permission)\b"),
        "The request appears to target unauthorized exploitation or data exfiltration.",
    ),
    ScopeRule(
        "privacy_abuse",
        "privacy invasion",
        _compile(r"\b(doxx|deanonymi[sz]e|stalk|track a person|exfiltrate personal data|scrape personal data)\b"),
        "The request appears to involve privacy invasion or personal-data abuse.",
    ),
    ScopeRule(
        "safety_bypass",
        "safety or access-control bypass",
        _compile(r"\b(bypass|evade|disable)\b.{0,100}\b(safety controls|moderation|access controls|audit logs|monitoring|rate limits)\b"),
        "The request appears to seek bypassing safety, access-control, or monitoring systems.",
    ),
)

APPROVAL_RULES: Sequence[ScopeRule] = (
    ScopeRule(
        "external_spend",
        "paid external action",
        _compile(r"\b(spend money|paid api|paid service|purchase|buy credits|cloud cost|billing)\b"),
        "Human approval is required before spending money or consuming paid services.",
    ),
    ScopeRule(
        "long_running_job",
        "long-running execution",
        _compile(r"\b(long[-\s]?running|overnight|benchmark suite|large experiment|train model|fine[-\s]?tune)\b"),
        "Human approval is required before running long jobs or expensive experiments.",
    ),
    ScopeRule(
        "modifies_code_or_systems",
        "state-changing action",
        _compile(r"\b(modify|rewrite|delete|migrate|deploy|commit|push|write files|edit files|change database)\b"),
        "Human approval is required before state-changing actions from a Co-Scientist run.",
    ),
    ScopeRule(
        "external_services",
        "external service call",
        _compile(r"\b(call external|send request|post to|upload to|invoke api|webhook)\b"),
        "Human approval is required before calling external services beyond read-only research.",
    ),
    ScopeRule(
        "scientific_or_medical_conclusion",
        "scientific or medical actionability",
        _compile(r"\b(patient|clinical|diagnosis|treatment|therapy|drug repurposing|disease|biomedical|legal advice|financial advice)\b"),
        "Human approval is required before acting on scientific, medical, legal, or financial conclusions.",
    ),
)


def _normalize_parts(topic: str, constraints: Optional[Iterable[str]]) -> str:
    parts = [topic or ""]
    if constraints:
        parts.extend(str(item) for item in constraints if item is not None)
    return "\n".join(parts).strip()


def _matching_rules(text: str, rules: Sequence[ScopeRule]) -> List[ScopeRule]:
    return [rule for rule in rules if rule.pattern.search(text)]


def get_co_scientist_scope_policy() -> Dict[str, object]:
    """Return the Phase 0 Co-Scientist scope policy."""
    return {
        "accepted_domains": list(ACCEPTED_DOMAINS),
        "blocked_domains": list(BLOCKED_DOMAINS),
        "approval_required_actions": list(APPROVAL_REQUIRED_ACTIONS),
        "phase_0_limits": list(PHASE_0_LIMITS),
        "screening": "deterministic rule-based pre-run screen",
    }


def screen_co_scientist_scope(
    topic: str,
    constraints: Optional[List[str]] = None,
) -> Dict[str, object]:
    """Screen a proposed Co-Scientist run before session creation.

    The result is intentionally conservative: blocked topics return
    allowed=False, while state-changing or high-stakes topics return
    allowed=True with explicit approval requirements.
    """
    text = _normalize_parts(topic, constraints)
    if not text:
        decision = ScopeDecision(
            allowed=False,
            risk_level="invalid",
            categories=["invalid_request"],
            reasons=["A Co-Scientist run requires a non-empty research topic."],
            required_approvals=[],
            accepted_domains=list(ACCEPTED_DOMAINS),
            blocked_domains=list(BLOCKED_DOMAINS),
            phase_0_limits=list(PHASE_0_LIMITS),
        )
        return decision.to_dict()

    blocked = _matching_rules(text, BLOCK_RULES)
    approvals = _matching_rules(text, APPROVAL_RULES)

    if blocked:
        decision = ScopeDecision(
            allowed=False,
            risk_level="blocked",
            categories=sorted({rule.category for rule in blocked}),
            reasons=[rule.reason for rule in blocked],
            required_approvals=[],
            accepted_domains=list(ACCEPTED_DOMAINS),
            blocked_domains=list(BLOCKED_DOMAINS),
            phase_0_limits=list(PHASE_0_LIMITS),
        )
        return decision.to_dict()

    required_approvals = sorted({rule.category for rule in approvals})
    decision = ScopeDecision(
        allowed=True,
        risk_level="approval_required" if required_approvals else "low",
        categories=required_approvals or ["safe_research"],
        reasons=[rule.reason for rule in approvals] or [
            "The topic is within the Phase 0 safe research scope."
        ],
        required_approvals=required_approvals,
        accepted_domains=list(ACCEPTED_DOMAINS),
        blocked_domains=list(BLOCKED_DOMAINS),
        phase_0_limits=list(PHASE_0_LIMITS),
    )
    return decision.to_dict()


def ensure_co_scientist_scope_allowed(
    topic: str,
    constraints: Optional[List[str]] = None,
) -> Dict[str, object]:
    """Return the screening decision or raise CoScientistScopeError if blocked."""
    decision = screen_co_scientist_scope(topic, constraints)
    if not decision.get("allowed"):
        reasons = decision.get("reasons") or ["Co-Scientist scope check failed."]
        raise CoScientistScopeError("; ".join(str(reason) for reason in reasons))
    return decision
