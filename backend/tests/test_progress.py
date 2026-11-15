import pytest

from app.core.config import settings
from app.services import progress


@pytest.fixture(autouse=True)
def redis_mode(monkeypatch):
    # These tests cover the Redis-backed progress used in celery mode.
    monkeypatch.setattr(settings, "INDEXING_MODE", "celery")


def test_report_and_read(sync_redis):
    progress.report("d1", "parsing")
    got = progress.get_many(["d1", "d2"])
    assert set(got) == {"d1"}
    assert got["d1"]["stage"] == "parsing"
    assert got["d1"]["percent"] == progress.STAGES["parsing"]
    assert got["d1"]["label"] == "Reading document"
    assert sync_redis.ttl("doc:progress:d1") > progress.FINAL_TTL_SECONDS



def test_embedding_progress_maps_into_band(sync_redis):
    progress.embedding_progress("d1", 50, 100)
    pct = progress.get_many(["d1"])["d1"]["percent"]
    assert progress.STAGES["embedding"] < pct < progress.STAGES["saving"]


def test_final_state_expires_quickly(sync_redis):
    progress.report("d1", "done")
    assert 0 < sync_redis.ttl("doc:progress:d1") <= progress.FINAL_TTL_SECONDS


def test_report_never_raises_without_redis(monkeypatch):
    from app.services import doc_store

    def boom():
        raise ConnectionError("down")
    monkeypatch.setattr(doc_store, "get_client", boom)
    progress.report("d1", "parsing")  # must not raise
    assert progress.get_many(["d1"]) == {}


def test_default_mode_is_inprocess_and_needs_no_redis(monkeypatch):
    from app.core.config import Settings
    assert Settings(SECRET_KEY="x").INDEXING_MODE == "inprocess"
    monkeypatch.setattr(settings, "INDEXING_MODE", "inprocess")
    from app.services import doc_store

    def no_redis():
        raise AssertionError("in-process progress must not touch Redis")
    monkeypatch.setattr(doc_store, "get_client", no_redis)
    progress.report("d9", "embedding", 50)
    assert progress.get_many(["d9"])["d9"]["percent"] == 50


def test_idle_worker_polls_slowly():
    from app.worker import celery_app
    opts = celery_app.conf.broker_transport_options
    assert opts["polling_interval"] >= 10  # Kombu default is 1 s (~86k commands/day)
    assert celery_app.conf.worker_enable_remote_control is False
