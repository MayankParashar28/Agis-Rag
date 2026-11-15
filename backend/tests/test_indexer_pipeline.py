import sys
import threading
import types

import numpy as np
import pytest

sys.modules.setdefault(
    "app.services.models",
    types.SimpleNamespace(get_embedding_model=lambda: None, get_reranker=lambda: None),
)

from app.services import indexer as I  # noqa: E402


class FakeModel:
    def __init__(self):
        self.calls = []

    def encode(self, texts, **kw):
        self.calls.append(len(texts))
        # vector = position marker, so order can be checked afterwards
        return np.array([[float(len(t)), 1.0] for t in texts])


class FakeQdrant:
    def __init__(self, fail_on=None):
        self.points = []
        self.fail_on = fail_on
        self.lock = threading.Lock()
        self.n = 0

    def upsert(self, collection_name, points):
        with self.lock:
            self.n += 1
            if self.fail_on and self.n == self.fail_on:
                raise RuntimeError("qdrant down")
            self.points.extend(points)


def _indexer(qdrant):
    ix = I.DocumentIndexer.__new__(I.DocumentIndexer)
    ix.embed_model = FakeModel()
    ix.qclient = qdrant
    return ix


def test_group_bounds_small_first_group():
    assert I._group_bounds(10) == [(0, 10)]
    b = I._group_bounds(300)
    assert b[0] == (0, I.FIRST_GROUP) and b[-1][1] == 300
    assert all(b[i][1] == b[i + 1][0] for i in range(len(b) - 1))


async def test_pipeline_uploads_every_vector_in_order(monkeypatch):
    reports = []
    from app.services import progress
    monkeypatch.setattr(progress, "embedding_progress", lambda d, done, total, started_at=None: reports.append(done))
    q = FakeQdrant()
    ix = _indexer(q)
    texts = ["x" * (i + 1) for i in range(250)]
    infos = [{"text": t, "page_number": 1, "section": None, "kind": "text"} for t in texts]
    db_chunks, points, uploads = [], [], []
    await ix._embed_and_upload(texts, infos, "doc", "kb", "f.pdf", "c", db_chunks, points, uploads, 0.0, True)
    await I._finish_uploads(uploads)
    assert len(db_chunks) == len(points) == len(q.points) == 250
    assert [c.chunk_index for c in db_chunks] == list(range(250))
    assert all(p.vector[0] == len(texts[i]) for i, p in enumerate(points))     # vector matches its chunk
    assert {p.id for p in q.points} == {p.id for p in points}
    assert reports[0] == I.FIRST_GROUP and reports[-1] == 250


async def test_upload_failure_surfaces_after_all_uploads_finish():
    q = FakeQdrant(fail_on=2)
    ix = _indexer(q)
    texts = ["t"] * 200
    infos = [{"text": t, "page_number": 1} for t in texts]
    uploads = []
    await ix._embed_and_upload(texts, infos, "doc", "kb", "f", "c", [], [], uploads, 0.0, False)
    with pytest.raises(RuntimeError, match="qdrant down"):
        await I._finish_uploads(uploads)
    assert all(t.done() for t in uploads)       # nothing left running when the rollback starts


def test_eta_estimate(monkeypatch):
    from app.services import progress
    seen = {}
    monkeypatch.setattr(progress, "report", lambda d, stage, pct=None, msg=None, eta_seconds=None: seen.update(eta=eta_seconds))
    monkeypatch.setattr(progress.time, "time", lambda: 110.0)
    progress.embedding_progress("d", 20, 100, started_at=100.0)    # 20 chunks in 10 s -> 40 s for the other 80
    assert seen["eta"] == pytest.approx(40.0)
