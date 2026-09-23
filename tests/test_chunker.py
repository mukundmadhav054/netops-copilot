from src.ingestion.chunker import chunk_markdown, chunk_text


def test_chunk_text_basic():
    text = "OSPF neighbor states. " * 60
    chunks = chunk_text(text, chunk_size=200, overlap=20)
    assert len(chunks) > 1
    assert all(len(c) <= 320 for c in chunks)  # overlap slack
    assert all(c.strip() for c in chunks)


def test_chunk_text_empty():
    assert chunk_text("") == []
    assert chunk_text("   ") == []


def test_chunk_markdown_headers():
    md = "# OSPF\n" + ("neighbor detail. " * 40) + "\n## BGP\n" + ("path selection. " * 40)
    chunks = chunk_markdown(md, chunk_size=200, overlap=20)
    assert len(chunks) >= 2
    joined = " ".join(chunks)
    assert "OSPF" in joined and "BGP" in joined


def test_chunk_overlap_present():
    text = "word " * 300
    chunks = chunk_text(text, chunk_size=100, overlap=20)
    assert len(chunks) > 2
