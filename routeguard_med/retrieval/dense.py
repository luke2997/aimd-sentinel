"""Dense retrieval with bge-m3/FAISS when available, plus a lightweight fallback.

Install optional dependencies:
    pip install sentence-transformers faiss-cpu scikit-learn
"""
from __future__ import annotations

from typing import List, Sequence
import numpy as np

from routeguard_med.schemas import EvidenceSnippet


class DenseRetriever:
    def __init__(self, corpus: Sequence[EvidenceSnippet], model_name: str = "BAAI/bge-m3"):
        self.corpus = list(corpus)
        self.model_name = model_name
        self.backend = "none"
        self.model = None
        self.index = None
        self.matrix = None
        self.vectorizer = None
        texts = [self._text(d) for d in self.corpus]

        try:
            from sentence_transformers import SentenceTransformer
            import faiss

            self.model = SentenceTransformer(model_name)
            emb = self.model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
            self.matrix = np.asarray(emb, dtype="float32")
            self.index = faiss.IndexFlatIP(self.matrix.shape[1])
            self.index.add(self.matrix)
            self.backend = "sentence-transformers+faiss"
        except Exception:
            try:
                from sklearn.feature_extraction.text import TfidfVectorizer
                from sklearn.preprocessing import normalize

                self.vectorizer = TfidfVectorizer(max_features=20000, ngram_range=(1, 2))
                self.matrix = normalize(self.vectorizer.fit_transform(texts))
                self.backend = "tfidf-fallback"
            except Exception:
                self.backend = "none"

    @staticmethod
    def _text(doc: EvidenceSnippet) -> str:
        return f"{doc.title}\n{doc.device_name or ''}\n{doc.evidence_type or ''}\n{doc.text}"

    def search(self, query: str, top_k: int = 5) -> List[EvidenceSnippet]:
        if not self.corpus or self.backend == "none":
            return []

        if self.backend == "sentence-transformers+faiss":
            q = self.model.encode([query], normalize_embeddings=True, show_progress_bar=False).astype("float32")
            scores, idx = self.index.search(q, top_k)
            results = []
            for score, i in zip(scores[0], idx[0]):
                if i < 0:
                    continue
                item = self.corpus[int(i)].model_copy()
                item.score = float(score)
                results.append(item)
            return results

        # TF-IDF fallback.
        q = self.vectorizer.transform([query])
        scores = (self.matrix @ q.T).toarray().ravel()
        order = np.argsort(-scores)[:top_k]
        results = []
        for i in order:
            if scores[i] <= 0:
                continue
            item = self.corpus[int(i)].model_copy()
            item.score = float(scores[i])
            results.append(item)
        return results
