import math

from app.services import answer_cache


def unit(*xs):
    n = math.sqrt(sum(x * x for x in xs))
    return [x / n for x in xs]


async def test_store_and_semantic_hit(async_redis, sync_redis, monkeypatch):
    # Version bumps go through the sync client; point both at shared state.
    await answer_cache.store("kb1", "What is the refund policy?", unit(1, 0, 0), "30 days.",
                             [{"source_doc": "p.pdf"}], 90.0)
    hit = await answer_cache.lookup("kb1", "what's the refund policy", unit(0.99, 0.05, 0))
    assert hit and hit["answer"] == "30 days."
    # An unrelated question misses.
    assert await answer_cache.lookup("kb1", "Who is the CEO?", unit(0, 1, 0)) is None


async def test_low_confidence_not_cached(async_redis):
    await answer_cache.store("kb1", "q", unit(1, 0), "maybe", [], 20.0)
    assert await answer_cache.lookup("kb1", "q", unit(1, 0)) is None


async def test_scope_by_document_filter(async_redis):
    await answer_cache.store("kb1", "q", unit(1, 0), "a", [], 90.0, document_ids=["d1"])
    assert await answer_cache.lookup("kb1", "q", unit(1, 0)) is None
    assert await answer_cache.lookup("kb1", "q", unit(1, 0), document_ids=["d1"])


async def test_version_bump_invalidates(async_redis, monkeypatch):
    await answer_cache.store("kb1", "q", unit(1, 0), "old", [], 90.0)
    await async_redis.incr("kb:ver:kb1")  # what bump_kb_version_sync does after indexing
    assert await answer_cache.lookup("kb1", "q", unit(1, 0)) is None
