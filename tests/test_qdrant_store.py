"""Vector-store backend tests: real Qdrant in-memory by default."""
import pytest

from src.retrieval.hybrid import HybridRetriever, build_store, mock_embed

qdrant = pytest.importorskip("qdrant_client")


def test_build_store_prefers_real_qdrant():
    store = build_store()
    assert type(store).__name__ == "QdrantStore"
    assert store.mode == "qdrant-memory"


def test_qdrant_roundtrip_and_payload_filter():
    from src.retrieval.hybrid import Document

    store = build_store()
    store.upsert([
        Document(id="d0", text="ospf neighbor troubleshooting", payload={"source": "rfc"}),
        Document(id="d1", text="bgp path selection", payload={"source": "bgp"}),
    ])
    assert store.dim == 64  # mock space
    q = store.embed_query("ospf neighbor down")
    hits = store.search(q, limit=2)
    assert [d.id for d, _ in hits] == ["d0", "d1"] or hits[0][0].id == "d0"
    only_bgp = store.search(q, limit=2, payload_filter={"source": "bgp"})
    assert [d.id for d, _ in only_bgp] == ["d1"]


def test_qdrant_dim_flip_reembeds_corpus():
    from src.retrieval.hybrid import Document

    store = build_store()
    store.upsert([Document(id="d0", text="ospf neighbor", payload={})])
    assert store.dim == 64
    store.embed_fn = lambda texts: [[1.0, 2.0, 3.0] for _ in texts]
    store.upsert([Document(id="d1", text="bgp session", payload={})])
    assert store.dim == 3
    hits = store.search([1.0, 2.0, 3.0], limit=2)
    assert len(hits) == 2  # whole corpus usable again in the new space


def test_hybrid_retriever_end_to_end_on_qdrant():
    r = HybridRetriever()
    assert type(r.store).__name__ == "QdrantStore"
    r.add(["ospf neighbor troubleshooting full state", "bgp path selection"])
    hits = r.search("ospf neighbor stuck", top_k=2)
    assert hits and hits[0]["text"].startswith("ospf")
    assert mock_embed  # mock path still importable for offline use
