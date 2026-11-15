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
            events.append(("pool_recreated",))
            return self

    class Parser:
        async def parse_file(self, path, filename):
            events.append(("parsed", open(path, "rb").read(), path))
            return [{"content": "x", "page_number": 1}]

    class Indexer:
        async def index_document(self, db, doc_id, pages, cs, co, **kw):
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

    assert stubs[0] == ("pool_recreated",)  # worker mode resets the forked pool
    kind, data, temp_path = stubs[1]
    assert (kind, data) == ("parsed", b"from redis")
    assert stubs[2] == ("indexed", 500, 50)
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


async def test_inprocess_mode_indexes_without_redis(tmp_path, stubs, monkeypatch):
    """Single-container mode: the API runs the job itself; no Redis, no pool reset."""
    import asyncio
    from app.core.config import settings
    from app.services import doc_store, ingest
    monkeypatch.setattr(settings, "INDEXING_MODE", "inprocess")

    def no_redis():
        raise AssertionError("in-process mode must not touch Redis")
    monkeypatch.setattr(doc_store, "get_client", no_redis)

    src = tmp_path / "f.txt"
    src.write_bytes(b"local file")
    doc_id = str(uuid.uuid4())
    ingest.submit_inprocess(doc_id, str(src), "f.txt", 400, 40)
    assert ingest.queued_inprocess() == 1
    for _ in range(100):
        if ingest.queued_inprocess() == 0:
            break
        await asyncio.sleep(0.01)

    kinds = [e[0] for e in stubs]
    assert "parsed" in kinds and ("indexed", 400, 40) in stubs
    assert "pool_recreated" not in kinds  # the API's shared pool is left alone
    assert progress.get_many([doc_id])[doc_id]["stage"] == "summarizing"  # last stage this stub reports
    assert src.exists()  # the API's own copy is kept for re-indexing
