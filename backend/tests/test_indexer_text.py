import sys
import types

# The indexer imports the embedding model module; stub it so no torch is needed.
sys.modules.setdefault(
    "app.services.models",
    types.SimpleNamespace(get_embedding_model=lambda: None, get_reranker=lambda: None),
)

from app.services.indexer import DocumentIndexer, clean_text  # noqa: E402


def test_clean_text_strips_nul_and_control_chars():
    assert clean_text("a\x00b\x07c\nd\te") == "abc\nd\te"


def test_split_large_text_keeps_every_character():
    splitter = DocumentIndexer.split_text_recursive
    text = ("word " * 60_000).strip()  # ~300 KB
    chunks = splitter(None, text, 1000, 0)
    assert all(len(c) <= 1000 for c in chunks)
    assert "".join(chunks).replace(" ", "") == text.replace(" ", "")


def test_overlap_is_bounded():
    chunks = DocumentIndexer.split_text_recursive(None, ("word " * 5000).strip(), 1000, 200)
    assert all(len(c) <= 1200 for c in chunks)
