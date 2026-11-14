import os
import types

import pytest

from app.services import storage


@pytest.fixture
def local_store(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "_upload_dir", lambda: str(tmp_path))
    monkeypatch.setattr(storage.settings, "STORAGE_BACKEND", "local")
    storage.reset()
    yield storage.get_storage()
    storage.reset()


def test_local_storage_roundtrip(tmp_path, local_store):
    src = tmp_path / "src.bin"
    src.write_bytes(b"\x00\x01binary")
    key = storage.storage_key("abc", ".BIN")
    assert key == "uploads/abc.bin"
    local_store.put_file(key, str(src))
    assert local_store.exists(key)
    assert b"".join(local_store.stream(key)) == b"\x00\x01binary"
    assert local_store.size(key) == 8
    local_store.delete(key)
    assert not local_store.exists(key)
    local_store.delete(key)  # idempotent


async def test_fetch_to_temp(tmp_path, local_store):
    src = tmp_path / "s.pdf"
    src.write_bytes(b"%PDF")
    local_store.put_file("uploads/x.pdf", str(src))
    path = await storage.fetch_to_temp("uploads/x.pdf", ".pdf")
    try:
        assert path.endswith(".pdf") and open(path, "rb").read() == b"%PDF"
    finally:
        os.remove(path)
    assert await storage.fetch_to_temp("uploads/missing.pdf", ".pdf") is None


def test_s3_misconfigured_falls_back_to_local(monkeypatch):
    monkeypatch.setattr(storage.settings, "STORAGE_BACKEND", "s3")
    monkeypatch.setattr(storage.settings, "S3_BUCKET", None)
    storage.reset()
    assert storage.get_storage().backend == "local"
    storage.reset()


def _conversation_markdown():
    from app.services.export import conversation_to_markdown
    return conversation_to_markdown


def test_export_markdown_footnotes():
    conversation_to_markdown = _conversation_markdown()
    conv = types.SimpleNamespace(title="Refund chat", kb_id=None)
    msgs = [
        types.SimpleNamespace(sender="user", content="How long?", citations=None),
        types.SimpleNamespace(sender="assistant", content="30 days [Source 1]. Credit after [Source 2].",
                              citations=[{"index": 1, "source_doc": "policy.pdf", "page": 2},
                                         {"index": 2, "source_doc": "faq", "page": None, "url": "https://x/y"}]),
    ]
    md = conversation_to_markdown(conv, msgs, "Support")
    assert md.startswith("# Refund chat")
    assert "30 days [^1]. Credit after [^2]." in md
    assert "[^1]: policy.pdf, page 2" in md
    assert "[^2]: faq <https://x/y>" in md
    assert "Knowledge base: Support" in md
