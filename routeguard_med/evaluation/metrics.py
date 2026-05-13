"""Evaluation metrics for routing and grounded generation."""
from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd

from routeguard_med.generation import extract_citations
from routeguard_med.schemas import Action, AgentResult, EvalRow, PromptExample


def citation_precision(citations: List[str], allowed_sources: List[str]) -> Optional[float]:
    if not citations:
        return None
    allowed = set(allowed_sources)
    return sum(1 for c in citations if c in allowed) / len(citations)


def unsupported_claim(answer: str, citations: List[str], predicted_action: Action) -> bool:
    if predicted_action not in {Action.ANSWER, Action.RETRIEVE}:
        return False
    # Baseline rule: if the system gives a factual-looking answer without any source markers, flag it.
    if not citations and answer and "cannot" not in answer.lower() and "clarify" not in answer.lower():
        return True
    return False


def net_utility(example: PromptExample, predicted: Action) -> float:
    mapping = {
        Action.ANSWER: example.utility_answer,
        Action.RETRIEVE: example.utility_retrieve,
        Action.CLARIFY: example.utility_clarify,
        Action.ABSTAIN: example.utility_abstain,
        Action.ESCALATE: example.utility_escalate,
    }
    return mapping.get(predicted, 0.0)


def make_eval_row(example: PromptExample, result: AgentResult) -> EvalRow:
    pred = result.decision.action
    citations = extract_citations(result.answer or "")
    retrieved_sources = [e.source_id for e in result.retrieved]
    allowed = list(set(example.gold_sources + retrieved_sources))
    cp = citation_precision(citations, allowed)
    retrieval_useful = None
    if pred in {Action.RETRIEVE, Action.ANSWER}:
        retrieval_useful = bool(set(example.gold_sources).intersection(retrieved_sources)) if example.gold_sources else None

    failure = ""
    if pred != example.expected_action:
        failure = f"wrong_action_expected_{example.expected_action.value}"
    elif unsupported_claim(result.answer or "", citations, pred):
        failure = "unsupported_claim"
    elif pred == Action.RETRIEVE and retrieval_useful is False:
        failure = "retrieval_missed_gold"

    return EvalRow(
        prompt_id=example.prompt_id,
        router=result.router_name,
        query=example.query,
        expected_action=example.expected_action,
        predicted_action=pred,
        action_correct=pred == example.expected_action,
        answer=result.answer,
        citations=citations,
        gold_sources=example.gold_sources,
        citation_precision=cp,
        unsupported_claim=unsupported_claim(result.answer or "", citations, pred),
        retrieval_useful=retrieval_useful,
        latency_ms=result.latency_ms,
        estimated_token_cost=result.estimated_token_cost,
        net_utility=net_utility(example, pred),
        category=example.category,
        language=example.language,
        failure_mode=failure,
    )


def leaderboard(rows: List[EvalRow]) -> pd.DataFrame:
    df = pd.DataFrame([r.model_dump() for r in rows])
    if df.empty:
        return df
    group = df.groupby("router")
    out = pd.DataFrame({
        "n": group.size(),
        "accuracy": group["action_correct"].mean(),
        "unsupported_claim_rate": group["unsupported_claim"].mean(),
        "citation_precision": group["citation_precision"].mean(),
        "correct_abstain": group.apply(lambda x: ((x.expected_action == Action.ABSTAIN.value) & (x.predicted_action == Action.ABSTAIN.value)).sum() / max(1, (x.expected_action == Action.ABSTAIN.value).sum()), include_groups=False),
        "correct_clarify": group.apply(lambda x: ((x.expected_action == Action.CLARIFY.value) & (x.predicted_action == Action.CLARIFY.value)).sum() / max(1, (x.expected_action == Action.CLARIFY.value).sum()), include_groups=False),
        "retrieval_usefulness": group["retrieval_useful"].mean(),
        "cost_per_query": group["estimated_token_cost"].mean(),
        "avg_latency_ms": group["latency_ms"].mean(),
        "net_utility": group["net_utility"].mean(),
    }).reset_index()
    return out.sort_values("net_utility", ascending=False)
