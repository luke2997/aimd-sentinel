"""Rule-based router for fast, reproducible demos."""
from __future__ import annotations

import re
from typing import List

from routeguard_med.schemas import Action, EvidenceSnippet, RouterDecision
from .base import BaseRouter

DEVICE_HINTS = [
    "unid", "spine analyzer", "lung vision", "red dot", "magnetom", "air recon", "overjet",
    "syngo", "vitrea", "centricity", "critical care suite", "510", "k19", "k21", "k18"
]
CLINICAL_DECISION_TERMS = ["diagnose", "treat", "prescribe", "safe for patient", "should this patient", "medical advice"]
PROMPT_INJECTION_TERMS = ["ignore previous", "ignore the system", "developer message", "reveal", "jailbreak", "bypass"]
AMBIGUOUS_TERMS = ["which device", "what device", "this device", "that ai", "the product", "is it safe", "should we buy"]
EVIDENCE_TERMS = ["adverse", "recall", "enforcement", "510", "k-number", "evidence", "source", "public record", "what happened", "reports"]


def _contains_any(q: str, terms: List[str]) -> bool:
    return any(t in q for t in terms)


class HeuristicRouter(BaseRouter):
    name = "heuristic"

    def route(self, query: str, evidence: List[EvidenceSnippet] | None = None) -> RouterDecision:
        q = (query or "").lower().strip()
        evidence = evidence or []
        has_evidence = bool(evidence)
        has_device_hint = _contains_any(q, DEVICE_HINTS)

        if _contains_any(q, PROMPT_INJECTION_TERMS):
            return RouterDecision(
                action=Action.ESCALATE,
                confidence=0.92,
                rationale="Prompt-injection or policy-bypass language detected; escalate for human review.",
                needs_human_review=True,
            )

        if _contains_any(q, CLINICAL_DECISION_TERMS):
            return RouterDecision(
                action=Action.ESCALATE,
                confidence=0.88,
                rationale="Question requests clinical decision-making or patient-specific advice.",
                needs_human_review=True,
            )

        if not has_device_hint and _contains_any(q, AMBIGUOUS_TERMS):
            return RouterDecision(
                action=Action.CLARIFY,
                confidence=0.84,
                rationale="The question is ambiguous and lacks a specific device/manufacturer context.",
            )

        if any(term in q for term in ["prove", "guarantee", "rate of", "incidence", "caused by", "causal"]):
            return RouterDecision(
                action=Action.ABSTAIN,
                confidence=0.80,
                rationale="Question asks for causal/incidence claims that passive public reports cannot establish.",
            )

        if _contains_any(q, EVIDENCE_TERMS) or has_device_hint:
            if has_evidence:
                return RouterDecision(
                    action=Action.ANSWER,
                    confidence=0.78,
                    rationale="Device/evidence question with retrieved context available; answer with citations.",
                    requires_evidence=True,
                    citations=[e.source_id for e in evidence[:3]],
                )
            return RouterDecision(
                action=Action.RETRIEVE,
                confidence=0.82,
                rationale="Question appears answerable only after retrieving source evidence.",
                requires_evidence=True,
            )

        return RouterDecision(
            action=Action.RETRIEVE,
            confidence=0.55,
            rationale="Defaulting to retrieval for a regulated evidence question.",
            requires_evidence=True,
        )
