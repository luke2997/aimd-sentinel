"""Learned router using a lightweight classifier.

This is intentionally small and easy to train from the benchmark CSV. For a richer
variant, replace the TF-IDF vectorizer with bge-m3 embeddings.
"""
from __future__ import annotations

from typing import List

from routeguard_med.schemas import Action, EvidenceSnippet, PromptExample, RouterDecision
from .base import BaseRouter


class LearnedRouter(BaseRouter):
    name = "learned_tfidf_logreg"

    def __init__(self):
        self.pipeline = None
        self.labels: List[str] = []

    def fit(self, examples: List[PromptExample]) -> "LearnedRouter":
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.linear_model import LogisticRegression
            from sklearn.pipeline import Pipeline
        except Exception as e:
            raise RuntimeError("Install scikit-learn to use LearnedRouter: pip install scikit-learn") from e

        X = [ex.query for ex in examples]
        y = [ex.expected_action.value for ex in examples]
        self.pipeline = Pipeline([
            ("tfidf", TfidfVectorizer(ngram_range=(1, 2), max_features=30000)),
            ("clf", LogisticRegression(max_iter=1000, class_weight="balanced")),
        ])
        self.pipeline.fit(X, y)
        self.labels = sorted(set(y))
        return self

    def route(self, query: str, evidence: List[EvidenceSnippet] | None = None) -> RouterDecision:
        if self.pipeline is None:
            raise RuntimeError("LearnedRouter must be fit() before route().")
        pred = self.pipeline.predict([query])[0]
        confidence = 0.65
        try:
            probs = self.pipeline.predict_proba([query])[0]
            confidence = float(max(probs))
        except Exception:
            pass
        return RouterDecision(
            action=Action(pred),
            confidence=confidence,
            rationale="Classifier prediction from labelled routing benchmark.",
            requires_evidence=pred in {Action.ANSWER.value, Action.RETRIEVE.value},
        )
