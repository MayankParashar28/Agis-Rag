"""The real Celery task, with the database, parser and indexer stubbed out."""
import sys
import types
import uuid

import pytest

from app.services import doc_store, progress


@pytest.fixture
def stubs(monkeypatch):
    events = []

    class FakeDoc:
        id = "id"
        def __init__(self):
            self.status, self.meta_info = "processing", {}

    class Session:
        def __init__(self):
            self.doc = FakeDoc()
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def execute(self, q):
            return types.SimpleNamespace(scalar_one_or_none=lambda: self.doc)
        async def commit(self):
            events.append(("commit", self.doc.status, dict(self.doc.meta_info)))

    class Pool:
        def recreate(self):
            return self

    class Parser:
        async def parse_file(self, path, filename):
            events.append(("parsed", open(path, "rb").read(), path))
            return [{"content": "x", "page_number": 1}]

    class Indexer:
        async def index_document(self, db, doc_id, pages, cs, co):
            events.append(("indexed", cs, co))

    class Q:
        def where(self, *a):
            return self

    mods = {
        "app.core.database": types.SimpleNamespace(SessionLocal=Session, engine=types.SimpleNamespace(pool=Pool())),
        "app.services.parser": types.SimpleNamespace(document_parser=Parser()),
        "app.services.indexer": types.SimpleNamespace(document_indexer=Indexer()),
        "app.models.knowledge": types.SimpleNamespace(Document=FakeDoc),
        "sqlalchemy": types.SimpleNamespace(select=lambda *a: Q()),
    }
    for name, mod in mods.items():
        monkeypatch.setitem(sys.modules, name, mod)
    return events


def test_worker_takes_from_redis_and_cleans_up(tmp_path, sync_redis, stubs):
    from app.worker import process_document_task
    doc_id = str(uuid.uuid4())
    src = tmp_path / "f.txt"
    src.write_bytes(b"from redis")
    key = doc_store.stage_document(doc_id, str(src))
    src.unlink()  # prove the worker does not need the API's disk

    process_document_task.run(doc_id, str(src), "f.txt", 500, 50, redis_key=key)

    kind, data, temp_path = stubs[0]
    assert (kind, data) == ("parsed", b"from redis")
    assert stubs[1] == ("indexed", 500, 50)
    assert not sync_redis.exists(key)
    import os
    assert not os.path.exists(temp_path)


def test_missing_everywhere_marks_failed(sync_redis, stubs):
    from app.worker import process_document_task
    doc_id = str(uuid.uuid4())
    with pytest.raises(FileNotFoundError):
        process_document_task.run(doc_id, "/nope.pdf", "nope.pdf", redis_key=doc_store.handover_key(doc_id))
    assert stubs[-1][1] == "failed"
    assert progress.get_many([doc_id])[doc_id]["stage"] == "failed"
