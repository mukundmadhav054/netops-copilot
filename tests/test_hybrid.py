from src.retrieval.hybrid import HybridRetriever, InMemoryQdrant, mock_embed


def _seeded():
    r = HybridRetriever()
    r.add(
        ["OSPF neighbor FULL state EXSTART MTU", "BGP TCP 179 path selection summary",
         "ping traceroute packet loss diagnostics"],
        [{"source": "a"}, {"source": "b"}, {"source": "c"}],
    )
    return r


def test_mock_embed_normalized():
    v = mock_embed("ospf neighbor")
    assert len(v) == 64
    assert abs(sum(x * x for x in v) - 1.0) < 1e-6


def test_hybrid_top3_recall():
    r = _seeded()
    hits = r.search("OSPF neighbor EXSTART", top_k=3)
    assert len(hits) == 3
    assert hits[0]["payload"]["source"] == "a"
    assert set(hits[0]) >= {"id", "text", "payload", "score"}


def test_payload_filter():
    r = _seeded()
    hits = r.search("OSPF", top_k=3, payload_filter={"source": "b"})
    assert all(h["payload"]["source"] == "b" for h in hits)


def test_qdrant_cosine_default():
    q = InMemoryQdrant()
    assert q.distance == "cosine"
