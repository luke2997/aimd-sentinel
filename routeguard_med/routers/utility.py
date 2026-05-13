"""Value-aligned router using explicit expected utility."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from routeguard_med.schemas import Action, EvidenceSnippet, RouterDecision
from .base import BaseRouter
from .heuristic import HeuristicRouter


@dataclass
class UtilityConfig:
    reward_correct_answer: float = 5.0
    reward_useful_retrieval: float = 2.0
    reward_correct_clarify: float = 2.0
    reward_correct_abstain: float = 2.5
    reward_correct_escalate: float = 3.0
    cost_retrieval: float = 0.35
    cost_clarify: float = 0.25
    cost_abstain: float = 0.15
    cost_escalate: float = 0.75
    unsupported_claim_penalty: float = 6.0
    wrong_action_penalty: float = 1.0


class UtilityRouter(BaseRouter):
    name = "value_aligned_utility"

    def __init__(self, config: UtilityConfig | None = None):
        self.config = config or UtilityConfig()
        self.heuristic = HeuristicRouter()

    @staticmethod
    def evidence_score(evidence: List[EvidenceSnippet]) -> float:
        if not evidence:
            return 0.0
        best = max(e.score for e in evidence)
        # Hybrid scores are normalized-ish; clamp.
        return max(0.0, min(1.0, best))

    @staticmethod
    def ambiguity_score(query: str) -> float:
        q = query.lower()
        vague = ["this device", "the device", "is it safe", "should we", "which", "what about"]
        return min(1.0, sum(1 for v in vague if v in q) / 2.0)

    @staticmethod
    def risk_score(query: str) -> float:
        q = query.lower()
        risky = ["diagnose", "treat", "prescribe", "patient", "caused", "incidence", "safe", "legal", "lawsuit"]
        return min(1.0, sum(1 for r in risky if r in q) / 3.0)

    def route(self, query: str, evidence: List[EvidenceSnippet] | None = None) -> RouterDecision:
        evidence = evidence or []
        c = self.config
        es = self.evidence_score(evidence)
        amb = self.ambiguity_score(query)
        risk = self.risk_score(query)

        # Utility estimates. The answer utility is high only when evidence is strong and risk is moderate.
        utilities: Dict[Action, float] = {
            Action.ANSWER: c.reward_correct_answer * es - c.unsupported_claim_penalty * (1 - es) - 2.0 * risk,
            Action.RETRIEVE: c.reward_useful_retrieval * (1 - es) - c.cost_retrieval,
            Action.CLARIFY: c.reward_correct_clarify * amb - c.cost_clarify,
            Action.ABSTAIN: c.reward_correct_abstain * max(0.0, risk - es) - c.cost_abstain,
            Action.ESCALATE: c.reward_correct_escalate * risk - c.cost_escalate,
        }

        # Give prompt-injection/clinical-advice patterns a hard safety prior via heuristic.
        h = self.heuristic.route(query, evidence)
        if h.action == Action.ESCALATE and h.confidence > 0.85:
            utilities[Action.ESCALATE] += 2.0
        if h.action == Action.CLARIFY and h.confidence > 0.75:
            utilities[Action.CLARIFY] += 1.0
        if h.action == Action.ABSTAIN and h.confidence > 0.75:
            utilities[Action.ABSTAIN] += 1.0

        action = max(utilities, key=utilities.get)
        best = utilities[action]
        # Soft confidence from gap between top two utilities.
        ordered = sorted(utilities.values(), reverse=True)
        gap = ordered[0] - ordered[1] if len(ordered) > 1 else ordered[0]
        confidence = max(0.05, min(0.95, 0.5 + gap / 10.0))
        return RouterDecision(
            action=action,
            confidence=confidence,
            rationale=f"Expected utility selected {action.value}; evidence={es:.2f}, ambiguity={amb:.2f}, risk={risk:.2f}.",
            expected_utility=best,
            requires_evidence=action in {Action.ANSWER, Action.RETRIEVE},
            needs_human_review=action == Action.ESCALATE,
            citations=[e.source_id for e in evidence[:3]] if action == Action.ANSWER else [],
            debug={"utilities": {k.value: v for k, v in utilities.items()}, "evidence_score": es, "ambiguity_score": amb, "risk_score": risk},
        )
