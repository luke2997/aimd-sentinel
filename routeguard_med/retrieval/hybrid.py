"""Hybrid BM25 + dense retriever."""
from __future__ import annotations

from typing import Dict, List, Sequence

from routeguard_med.schemas import EvidenceSnippet
from .bm25 import BM25Retriever
from .dense import DenseRetriever


class HybridRetriever:
    def __init__(
        self,
        corpus: Sequence[EvidenceSnippet],
        embedding_model: str = "BAAI/bge-m3",
        weight_bm25: float = 0.55,
        weight_dense: float = 0.45,
    ):
        self.corpus = list(corpus)
        self.bm25 = BM25Retriever(self.corpus)
        self.dense = DenseRetriever(self.corpus, model_name=embedding_model)
        self.weight_bm25 = weight_bm25
        self.weight_dense = weight_dense

    @staticmethod
    def _normalize(results: List[EvidenceSnippet]) -> Dict[str, float]:
        if not results:
            return {}
        max_score = max(r.score for r in results) or 1.0
        return {r.source_id: r.score / max_score for r in results}

    def search(self, query: str, top_k: int = 5) -> List[EvidenceSnippet]:
        bm25_results = self.bm25.search(query, top_k=max(top_k * 3, 10))
        dense_results = self.dense.search(query, top_k=max(top_k * 3, 10))
        bm25_scores = self._normalize(bm25_results)
        dense_scores = self._normalize(dense_results)

        by_id = {r.source_id: r for r in bm25_results + dense_results}
        combined = []
        for sid, item in by_id.items():
            score = self.weight_bm25 * bm25_scores.get(sid, 0.0) + self.weight_dense * dense_scores.get(sid, 0.0)
            merged = item.model_copy()
            merged.score = float(score)
            merged.metadata = dict(merged.metadata or {})
            merged.metadata["bm25_score"] = bm25_scores.get(sid, 0.0)
            merged.metadata["dense_score"] = dense_scores.get(sid, 0.0)
            merged.metadata["dense_backend"] = self.dense.backend
            combined.append(merged)

        combined.sort(key=lambda x: x.score, reverse=True)
        return combined[:top_k]
