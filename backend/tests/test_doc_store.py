from app.services import doc_store


def test_stage_and_take_deletes_key(tmp_path, sync_redis):
    src = tmp_path / "a.pdf"
    data = bytes(range(256)) * 100  # binary, not valid UTF-8
    src.write_bytes(data)

    key = doc_store.stage_document("doc-1", str(src))
    assert key == "doc:handover:doc-1"
    assert 0 < sync_redis.ttl(key) <= 3600
    assert doc_store.count_staged() == 1

    assert doc_store.take_document(key) == data
    assert not sync_redis.exists(key)
    assert doc_store.count_staged() == 0
    # A second worker gets nothing.
    assert doc_store.take_document(key) is None


def test_stage_failure_returns_none(tmp_path, sync_redis):
    assert doc_store.stage_document("doc-2", str(tmp_path / "missing.pdf")) is None


def test_write_temp_file_keeps_extension(tmp_path):
    path = doc_store.write_temp_file(b"hello", "Report.PDF")
    try:
        assert path.endswith(".pdf")
        assert open(path, "rb").read() == b"hello"
    finally:
        import os
        os.remove(path)
