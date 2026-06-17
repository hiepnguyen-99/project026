from src.backend.app.workers.ingest import chunk_text, parse_document


def test_chunk_text_basic():
    text = " ".join(f"w{i}" for i in range(1000))
    chunks = chunk_text(text, chunk_words=400, overlap_words=80)
    assert len(chunks) >= 2
    # Mỗi chunk tối đa 400 từ.
    assert all(len(c.split()) <= 400 for c in chunks)


def test_chunk_text_overlap():
    text = " ".join(f"w{i}" for i in range(500))
    chunks = chunk_text(text, chunk_words=400, overlap_words=80)
    # step = 320 → chunk 2 bắt đầu từ w320, nên có overlap với chunk 1.
    first_words = set(chunks[0].split())
    second_words = set(chunks[1].split())
    assert first_words & second_words  # có giao nhau


def test_chunk_text_empty():
    assert chunk_text("") == []
    assert chunk_text("   ") == []


def test_parse_txt():
    pages = parse_document(b"xin chao the gioi", "note.txt")
    assert pages == [(None, "xin chao the gioi")]


def test_parse_unknown_ext_as_text():
    pages = parse_document(b"plain content", "file")
    assert pages[0][1] == "plain content"
