# Co-Scientist Phase 0 Scope Policy

## Purpose

Phase 0 defines the safe operating boundary for OpenLMlib's Co-Scientist workflow before generation or verification sessions are created.

The workflow is allowed to help with safe research planning, hypothesis generation, critique, ranking, and verification. It is not allowed to become an autonomous actor that runs experiments, modifies systems, spends money, or acts on high-stakes conclusions without explicit human approval.

## Accepted Domains

- Software architecture and codebase research.
- Safe technical literature review.
- Safe scientific and engineering ideation.
- Benchmark, reproducibility, and implementation feasibility analysis.
- Hypothesis generation followed by independent verification.

## Blocked Domains

Do not create a Co-Scientist session for requests that seek:

- Harmful biological, chemical, radiological, or weapons capability.
- Exploit development, malware, credential theft, phishing, or stealth abuse.
- Privacy invasion, doxxing, stalking, or personal-data exfiltration.
- Instructions to bypass safety controls, access controls, monitoring, or rate limits.

The initial screen is deterministic and rule-based. It is intentionally narrow so defensive work such as code review, security audit, malware analysis, or abuse-prevention research is not blocked unless the request asks for harmful capability, evasion, unauthorized exploitation, or abuse.

## Approval Gates

Human approval is required before a Co-Scientist run can trigger any of these:

- Spending money or consuming paid external services.
- Running long jobs, benchmarks, experiments, training, or fine-tuning.
- Modifying code, files, repositories, databases, or external systems.
- Calling external services beyond ordinary read-only research.
- Acting on scientific, biomedical, clinical, legal, or financial conclusions.

## Phase 0 Limits

- Artifact/session orchestration only.
- Read-mostly research by default.
- No autonomous Codex or external worker spawning.
- No automatic code edits from generated hypotheses.
- No automatic export of speculative findings.

## MCP Tools

`get_co_scientist_scope_policy` returns the current policy.

`screen_co_scientist_scope` screens a proposed run before session creation:

```json
{
  "topic": "Evaluate whether OpenLMlib should add linked generation and verification sessions",
  "constraints": ["read-only research", "no code edits"]
}
```

If the result has `allowed=false`, the caller must not create a Co-Scientist session. If the result has `risk_level="approval_required"`, the caller may continue with planning only, but must request human approval before the matched gated action.

## Implementation Boundary

The policy implementation lives in `openlmlib/co_scientist/`. CollabSessions exposes it through MCP as a thin adapter. Later phases should call the same policy functions before creating generation or verification sessions.
