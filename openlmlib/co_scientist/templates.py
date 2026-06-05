"""Built-in Co-Scientist CollabSession templates."""

from __future__ import annotations

from typing import Dict


VERIFICATION_VERDICTS: Dict[str, str] = {
    "supported": "Evidence supports the claim and no serious contradiction was found.",
    "partially_supported": (
        "Some evidence supports the claim, but assumptions or scope remain weak."
    ),
    "inconclusive": "Insufficient evidence was found or no reliable test was possible.",
    "contradicted": "Credible evidence refutes the claim.",
    "unsafe_or_out_of_scope": (
        "The hypothesis should not be pursued in this workflow."
    ),
}

VERIFICATION_CONFIDENCE_RULES: Dict[str, object] = {
    "range": "0.0 to 1.0",
    "calibration": {
        "0.80-1.00": "Strong direct evidence or reproducible test result.",
        "0.60-0.79": "Multiple credible signals with limited residual uncertainty.",
        "0.40-0.59": "Mixed evidence, indirect evidence, or meaningful caveats.",
        "0.20-0.39": "Weak evidence or mostly speculative support/refutation.",
        "0.00-0.19": "Unsupported, unreliable, unsafe, or contradicted by high-quality evidence.",
    },
    "requirements": [
        "Confidence must be justified in the verification_report artifact.",
        "Disconfirming evidence must be listed even when the verdict is supported.",
        "Unsafe or out-of-scope findings must use verdict unsafe_or_out_of_scope.",
    ],
}


CO_SCIENTIST_GENERATE_TEMPLATE: Dict[str, object] = {
    "name": "Co-Scientist Hypothesis Generation",
    "description": (
        "Generate, critique, deduplicate, evolve, and rank hypothesis packets "
        "for independent verification."
    ),
    "rules": {
        "max_agents": 7,
        "require_assignment": True,
        "max_message_length": 6000,
        "require_artifact_for_results": True,
        "auto_compact_after_messages": 20,
        "max_pending_tasks": 12,
        "co_scientist_phase": "generation",
        "required_gates": [
            "screen_co_scientist_scope before session creation",
            "get_hypothesis_packet_schema before writing candidate packets",
            "validate_hypothesis_packet before shortlist handoff",
        ],
        "expected_artifacts": [
            "research_context",
            "candidate_hypotheses",
            "reflection_review",
            "dedup_map",
            "evolved_hypotheses",
            "hypothesis_shortlist",
        ],
        "handoff_policy": (
            "Save detailed outputs as artifacts. Send concise result messages "
            "that reference artifact IDs and only include decision-critical facts."
        ),
    },
    "plan": [
        {
            "step": 1,
            "task": (
                "Research Scout: Gather relevant context, prior work, project "
                "constraints, known failure modes, and safety boundaries. Save "
                "artifact_type `research_context` and send a concise handoff "
                "with artifact ID, key facts, and open questions."
            ),
            "assigned_to": "any",
        },
        {
            "step": 2,
            "task": (
                "Hypothesis Generator: Use the research_context artifact and "
                "get_hypothesis_packet_schema to create diverse candidate "
                "hypothesis packets. Save artifact_type `candidate_hypotheses`; "
                "do not send full packet JSON in chat unless requested."
            ),
            "assigned_to": "any",
        },
        {
            "step": 3,
            "task": (
                "Reflection Critic: Review candidate_hypotheses for novelty, "
                "plausibility, evidence quality, citation gaps, weak assumptions, "
                "and unsafe or out-of-scope claims. Save artifact_type "
                "`reflection_review` with specific keep/drop/revise guidance."
            ),
            "assigned_to": "any",
        },
        {
            "step": 3,
            "task": (
                "Proximity/Dedup Agent: Cluster overlapping hypotheses, identify "
                "near duplicates, and recommend merge/drop decisions. Save "
                "artifact_type `dedup_map` with cluster labels and retained IDs."
            ),
            "assigned_to": "any",
        },
        {
            "step": 4,
            "task": (
                "Evolution Agent: Improve the strongest retained hypotheses using "
                "reflection_review and dedup_map. Preserve lineage.parent_hypothesis_ids "
                "and increment lineage.version. Save artifact_type "
                "`evolved_hypotheses`."
            ),
            "assigned_to": "any",
        },
        {
            "step": 5,
            "task": (
                "Ranker/Meta-reviewer: Perform pairwise comparisons, validate each "
                "shortlisted packet with validate_hypothesis_packet, and save "
                "artifact_type `hypothesis_shortlist` containing the top hypotheses, "
                "scores, validation results, and verification handoff notes."
            ),
            "assigned_to": "orchestrator",
        },
    ],
}


CO_SCIENTIST_VERIFY_TEMPLATE: Dict[str, object] = {
    "name": "Co-Scientist Hypothesis Verification",
    "description": (
        "Independently verify hypothesis packets with evidence review, "
        "contradiction search, test design, feasibility analysis, and verdicts."
    ),
    "rules": {
        "max_agents": 6,
        "require_assignment": True,
        "max_message_length": 6000,
        "require_artifact_for_results": True,
        "auto_compact_after_messages": 20,
        "max_pending_tasks": 10,
        "co_scientist_phase": "verification",
        "expected_input_artifacts": [
            "hypothesis_shortlist",
        ],
        "expected_artifacts": [
            "evidence_verification",
            "contradiction_review",
            "test_design",
            "feasibility_review",
            "verification_report",
        ],
        "artifact_cardinality": {
            "verification_report": "one artifact per input hypothesis_id",
        },
        "verification_verdicts": VERIFICATION_VERDICTS,
        "confidence_rules": VERIFICATION_CONFIDENCE_RULES,
        "required_report_fields": [
            "hypothesis_id",
            "verdict",
            "confidence",
            "supporting_evidence",
            "disconfirming_evidence",
            "tests_or_reproduction_plan",
            "feasibility_notes",
            "safety_notes",
            "citations",
        ],
        "handoff_policy": (
            "Verification agents should receive structured hypothesis packets and "
            "declared evidence, not the full generation transcript unless a human "
            "explicitly requests it."
        ),
    },
    "plan": [
        {
            "step": 1,
            "task": (
                "Evidence Verifier: For each input hypothesis packet, validate cited "
                "sources, look for stronger supporting evidence, and record source "
                "quality. Save artifact_type `evidence_verification` with citations "
                "and per-hypothesis notes."
            ),
            "assigned_to": "any",
        },
        {
            "step": 1,
            "task": (
                "Contradiction Hunter: Search for refuting evidence, edge cases, "
                "counterexamples, unsafe assumptions, and scope violations. Save "
                "artifact_type `contradiction_review` and explicitly list "
                "disconfirming evidence for every hypothesis."
            ),
            "assigned_to": "any",
        },
        {
            "step": 2,
            "task": (
                "Reproduction/Test Designer: Define concrete checks, experiments, "
                "benchmarks, code probes, or manual validation steps for each "
                "hypothesis. Save artifact_type `test_design` with expected "
                "observations and failure conditions."
            ),
            "assigned_to": "any",
        },
        {
            "step": 2,
            "task": (
                "Feasibility Reviewer: Estimate implementation effort, dependencies, "
                "project fit, operational risk, and what human approval would be "
                "needed before action. Save artifact_type `feasibility_review`."
            ),
            "assigned_to": "any",
        },
        {
            "step": 3,
            "task": (
                "Final Adjudicator: Write one artifact_type `verification_report` per "
                "input hypothesis_id. Each report must include verdict, confidence, "
                "supporting evidence, disconfirming evidence, test plan, feasibility "
                "notes, safety notes, and citations. Verdict must be one of: "
                f"{', '.join(sorted(VERIFICATION_VERDICTS))}."
            ),
            "assigned_to": "orchestrator",
        },
    ],
}
