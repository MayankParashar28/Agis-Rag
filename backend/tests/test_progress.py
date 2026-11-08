from app.services import progress


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
