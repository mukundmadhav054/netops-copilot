"""Hybrid dense (mock embeddings) + BM25 re-rank retrieval, top-3.

Qdrant client: in-memory fake by default. If `qdrant-client` is installed
and QDRANT_URL is set, a real client can be used; otherwise all ops run
against the in-process store below (cosine similarity + payload index).
"""
from __future__ import annotations

import hashlib
import math
import os
import re
from dataclasses import dataclass, field

DIM = 64


def mock_embed(text: str, dim: int = DIM) -> list[float]:
    """Deterministic mock embedding: hashed token buckets, L2-normalized."""
    vec = [0.0] * dim
    for tok in re.findall(r"[a-z0-9]+", text.lower()):
        h = int(hashlib.sha256(tok.encode()).hexdigest(), 16)
        vec[h % dim] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _bm25_score(query_terms: list[str], doc_terms: list[str], avg_len: float, n_docs: int, doc_freq: dict[str, int]) -> float:
    k1, b = 1.5, 0.75
    score = 0.0
    dl = len(doc_terms) or 1
    tf: dict[str, int] = {}
    for t in doc_terms:
        tf[t] = tf.get(t, 0) + 1
    for t in query_terms:
        f = tf.get(t, 0)
        if f == 0:
            continue
        df = doc_freq.get(t, 1)
        idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
        score += idf * (f * (k1 + 1)) / (f + k1 * (1 - b + b * dl / (avg_len or 1)))
    return score


@dataclass
class Document:
    id: str
    text: str
    payload: dict = field(default_factory=dict)


class InMemoryQdrant:
    """Fake Qdrant collection: cosine vector search + payload filter."""

    def __init__(self, distance: str = "cosine"):
        self.distance = distance
        self.docs: list[Document] = []
        self.vectors: list[list[float]] = []

    def upsert(self, docs: list[Document]) -> None:
        for d in docs:
            self.docs.append(d)
            self.vectors.append(mock_embed(d.text))

    def search(self, query_vector: list[float], limit: int = 3, payload_filter: dict | None = None):
        scored = []
        for d, v in zip(self.docs, self.vectors):
            if payload_filter:
                if any(d.payload.get(k) != val for k, val in payload_filter.items()):
                    continue
            scored.append((d, _cosine(query_vector, v)))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]


class HybridRetriever:
    """Dense pre-filter + BM25 re-rank fusion, returns top-k dicts."""

    def __init__(self, alpha: float = 0.5):
        self.alpha = alpha
        self.store = InMemoryQdrant(distance="cosine")
        self._terms: list[list[str]] = []

    def add(self, texts: list[str], metadatas: list[dict] | None = None) -> None:
        docs = []
        for i, t in enumerate(texts):
            payload = dict((metadatas or [])[i]) if metadatas and i < len(metadatas) else {}
            payload.setdefault("source", f"doc-{len(self.store.docs) + i}")
            docs.append(Document(id=f"d{len(self.store.docs) + i}", text=t, payload=payload))
        self.store.upsert(docs)
        self._terms = [re.findall(r"[a-z0-9]+", d.text.lower()) for d in self.store.docs]

    def search(self, query: str, top_k: int = 3, payload_filter: dict | None = None) -> list[dict]:
        if not self.store.docs:
            return []
        qvec = mock_embed(query)
        dense = self.store.search(qvec, limit=len(self.store.docs), payload_filter=payload_filter)
        q_terms = re.findall(r"[a-z0-9]+", query.lower())
        n = len(self._terms)
        avg_len = sum(len(t) for t in self._terms) / max(n, 1)
        df: dict[str, int] = {}
        for terms in self._terms:
            for t in set(terms):
                df[t] = df.get(t, 0) + 1
        # dense rank normalization
        max_d = max((s for _, s in dense), default=1.0) or 1.0
        fused = []
        idx_of = {id(d): i for i, d in enumerate(self.store.docs)}
        for doc, dscore in dense:
            di = idx_of[id(doc)]
            bscore = _bm25_score(q_terms, self._terms[di], avg_len, n, df)
            combo = self.alpha * (dscore / max_d) + (1 - self.alpha) * (bscore / (bscore + 2.0))
            fused.append({"id": doc.id, "text": doc.text, "payload": doc.payload,
                          "dense_score": round(dscore, 4), "bm25_score": round(bscore, 4),
                          "score": round(combo, 4)})
        fused.sort(key=lambda x: x["score"], reverse=True)
        return fused[:top_k]


def get_qdrant_client():
    """Return real QdrantClient if QDRANT_URL set + lib installed, else None (use in-memory)."""
    url = os.getenv("QDRANT_URL", "")
    if not url:
        return None
    try:
        from qdrant_client import QdrantClient  # type: ignore

        return QdrantClient(url=url)
    except Exception:
        return None
