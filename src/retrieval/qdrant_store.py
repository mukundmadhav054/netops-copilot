"""Real Qdrant vector store with the same interface as the in-memory fake.

Default is zero-infra in-memory mode (`QdrantClient(":memory:")`); set
`QDRANT_URL` to attach to a real Qdrant service (e.g. the compose `qdrant`
service) instead. Cosine distance with payload filtering in both modes.

`embed_fn`, when given, replaces mock embeddings (e.g. Gemini). It must
take a list of texts and return a list of vectors, or a falsy value to
fall back to mock. Like the fake, dimension flips re-embed the corpus so
query and docs always share one space.
"""
from __future__ import annotations

import os

from src.retrieval.hybrid import Document, mock_embed_batch


def _collection_name(dim: int) -> str:
    return f"netops-{dim}"


class QdrantStore:
    def __init__(self, distance: str = "cosine", embed_fn=None):
        from qdrant_client import QdrantClient

        url = os.getenv("QDRANT_URL", "")
        self.client = QdrantClient(url=url) if url else QdrantClient(":memory:")
        self.mode = "qdrant-remote" if url else "qdrant-memory"
        self.embed_fn = embed_fn
        self.docs: list[Document] = []
        self.dim: int | None = None
        self._coll: str | None = None

    # -- embedding (same contract as the fake) ---------------------------
    def _batch(self, texts: list[str]) -> list[list[float]]:
        if self.embed_fn is not None:
            try:
                vecs = self.embed_fn(texts)
                if vecs and len(vecs) == len(texts) and all(len(v) > 0 for v in vecs):
                    return [list(map(float, v)) for v in vecs]
            except Exception:
                pass
        return mock_embed_batch(texts)

    def _ensure_collection(self, dim: int) -> None:
        from qdrant_client.models import Distance, VectorParams

        name = _collection_name(dim)
        if self._coll != name:
            if self.client.collection_exists(name):
                self.client.delete_collection(name)
            self.client.create_collection(
                name, vectors_config=VectorParams(size=dim, distance=Distance.COSINE)
            )
            self._coll = name

    def _points(self, docs: list[Document], vecs: list[list[float]], start: int):
        from qdrant_client.models import PointStruct

        return [
            PointStruct(
                id=start + i,
                vector=v,
                payload={"source": d.payload.get("source", d.id), "doc_id": d.id},
            )
            for i, (d, v) in enumerate(zip(docs, vecs))
        ]

    def upsert(self, docs: list[Document]) -> None:
        if not docs:
            return
        vecs = self._batch([d.text for d in docs])
        dim = len(vecs[0])
        if self.dim is not None and dim != self.dim:
            # provider flipped mid-life: rebuild whole corpus in the new space
            self.docs.extend(docs)
            self._ensure_collection(dim)
            vecs = self._batch([d.text for d in self.docs])
            dim = len(vecs[0])
            self._ensure_collection(dim)
            self.client.upsert(self._coll, points=self._points(self.docs, vecs, 0))
        else:
            self._ensure_collection(dim)
            self.client.upsert(
                self._coll, points=self._points(docs, vecs, len(self.docs))
            )
            self.docs.extend(docs)
        self.dim = dim

    def search(self, query_vector: list[float], limit: int = 3, payload_filter: dict | None = None):
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        if self._coll is None or not query_vector or len(query_vector) != self.dim:
            return []
        qfilter = None
        if payload_filter:
            qfilter = Filter(
                must=[FieldCondition(key=k, match=MatchValue(value=v)) for k, v in payload_filter.items()]
            )
        try:
            res = self.client.query_points(
                self._coll, query=list(map(float, query_vector)), limit=limit, query_filter=qfilter
            )
        except Exception:
            return []
        out = []
        for p in res.points:
            doc = self.docs[p.id] if isinstance(p.id, int) and 0 <= p.id < len(self.docs) else None
            if doc is not None:
                out.append((doc, float(p.score)))
        return out

    def embed_query(self, text: str) -> list[float]:
        vecs = self._batch([text])
        q = vecs[0] if vecs else []
        if self.dim is not None and len(q) != self.dim:
            from src.retrieval.hybrid import mock_embed

            q = mock_embed(text)  # transient provider miss: stay in corpus space
            if len(q) != self.dim:
                return []
        return q
