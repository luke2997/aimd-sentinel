"""Grounded answer generation utilities."""
from __future__ import annotations

import re
from typing import List

from .schemas import Action, EvidenceSnippet, RouterDecision


def cite(source_id: str) -> str:
    return f"[S:{source_id}]"


def extract_citations(text: str) -> List[str]:
    return re.findall(r"\[S:([^\]]+)\]", text or "")


def grounded_answer(query: str, decision: RouterDecision, evidence: List[EvidenceSnippet]) -> str:
    """Generate a conservative extractive answer.

    This is not intended to be fluent final-product generation. It is a safe,
    reproducible baseline: every factual sentence points to retrieved evidence.
    """
    if decision.action == Action.CLARIFY:
        return "Please clarify the target device name, manufacturer, version, and whether you want authorization, adverse-event, recall, or procurement-review evidence."
    if decision.action == Action.ABSTAIN:
        return "I cannot answer this as stated from public evidence. The question asks for a causal, incidence, or unsupported claim that the available records cannot establish."
    if decision.action == Action.ESCALATE:
        return "This request should be escalated to human review because it may involve clinical advice, legal causality, prompt-injection risk, or high-risk uncertainty."
    if not evidence:
        return "No source evidence was retrieved, so I cannot provide a grounded answer."

    top = evidence[:3]
    lines = []
    lines.append("Based on the retrieved public evidence, the safest summary is:")
    for e in top:
        snippet = e.text.replace("\n", " ").strip()
        if len(snippet) > 420:
            snippet = snippet[:420].rstrip() + "..."
        lines.append(f"- {snippet} {cite(e.source_id)}")
    lines.append("This is a governance/evidence-review summary, not a clinical, legal, causal, or incidence conclusion.")
    return "\n".join(lines)
