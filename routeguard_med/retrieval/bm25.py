"""Small dependency-light BM25 implementation.

This is intentionally simple so the public demo can run without Elasticsearch.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Iterable, List, Sequence

from routeguard_med.schemas import EvidenceSnippet

TOKEN_RE = re.compile(r"[A-Za-z0-9_\-]+")


def tokenize(text: str) -> List[str]:
    return [t.lower() for t in TOKEN_RE.findall(text or "")]


class BM25Retriever:
    def __init__(self, corpus: Sequence[EvidenceSnippet], k1: float = 1.5, b: float = 0.75):
        self.corpus = list(corpus)
        self.k1 = k1
        self.b = b
        self.docs = [tokenize(f"{d.title} {d.device_name or ''} {d.evidence_type or ''} {d.text}") for d in self.corpus]
        self.doc_len = [len(d) for d in self.docs]
        self.avgdl = sum(self.doc_len) / max(1, len(self.doc_len))
        self.term_freqs = [Counter(d) for d in self.docs]
        df = Counter()
        for doc in self.docs:
            df.update(set(doc))
        n = max(1, len(self.docs))
        self.idf = {term: math.log(1 + (n - freq + 0.5) / (freq + 0.5)) for term, freq in df.items()}

    def search(self, query: str, top_k: int = 5) -> List[EvidenceSnippet]:
        q_terms = tokenize(query)
        scored = []
        for i, tf in enumerate(self.term_freqs):
            score = 0.0
            dl = self.doc_len[i] or 1
            for term in q_terms:
                if term not in tf:
                    continue
                freq = tf[term]
                denom = freq + self.k1 * (1 - self.b + self.b * dl / max(self.avgdl, 1e-9))
                score += self.idf.get(term, 0.0) * (freq * (self.k1 + 1)) / max(denom, 1e-9)
            if score > 0:
                item = self.corpus[i].model_copy()
                item.score = float(score)
                scored.append(item)
        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:top_k]
