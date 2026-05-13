"""RouteGuard-Med agent pipeline."""
from __future__ import annotations

import time
from typing import List, Optional

from .generation import grounded_answer
from .retrieval.hybrid import HybridRetriever
from .routers.base import BaseRouter
from .schemas import Action, AgentResult, EvidenceSnippet


class RouteGuardAgent:
    def __init__(self, router: BaseRouter, retriever: Optional[HybridRetriever] = None, top_k: int = 5):
        self.router = router
        self.retriever = retriever
        self.top_k = top_k

    def run(self, query: str) -> AgentResult:
        t0 = time.perf_counter()
        retrieved: List[EvidenceSnippet] = []

        # First pass without evidence decides whether retrieval/clarification/abstention is needed.
        first = self.router.route(query, evidence=[])

        if first.action == Action.RETRIEVE and self.retriever is not None:
            # For routing evaluation, "retrieve" is the selected action. We still
            # return evidence snippets, but we do not silently convert the action
            # into "answer" after retrieval. A production agent could run a second
            # pass in a separate answer-generation step.
            retrieved = self.retriever.search(query, top_k=self.top_k)
            decision = first
        else:
            decision = first
            if decision.action == Action.ANSWER and self.retriever is not None:
                retrieved = self.retriever.search(query, top_k=self.top_k)

        answer = grounded_answer(query, decision, retrieved)
        latency_ms = (time.perf_counter() - t0) * 1000
        estimated_tokens = max(1, len(query.split()) + len(answer.split()) + sum(len(e.text.split()) for e in retrieved))
        return AgentResult(
            query=query,
            router_name=self.router.name,
            decision=decision,
            answer=answer,
            retrieved=retrieved,
            latency_ms=latency_ms,
            estimated_token_cost=estimated_tokens / 1000.0,
        )
