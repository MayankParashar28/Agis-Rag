import asyncio
import sys
import types

sys.modules.setdefault("app.services.models", types.SimpleNamespace(get_embedding_model=lambda: None, get_reranker=lambda: None))

from app.services import decompose as D  # noqa: E402


async def test_separate_questions_split_without_a_model_call(monkeypatch):
    from app.services import llm

    async def boom(*a, **k):
        raise AssertionError("model should not be called")
    monkeypatch.setattr(llm, "complete_json", boom)
    monkeypatch.setattr(llm, "llm_available", lambda: True)
    subs, usage = await D.decompose("What is the refund window? Who approves exceptions?")
    assert subs == ["What is the refund window?", "Who approves exceptions?"] and usage is None


async def test_simple_question_is_not_split(monkeypatch):
    subs, usage = await D.decompose("What is the refund window for annual plans?")
    assert subs == ["What is the refund window for annual plans?"] and usage is None


async def test_session_lock_serialises_database_step():
    from app.services.search import _session_lock

    class FakeSession:
        pass

    db = FakeSession()
    active, peak = 0, 0

    async def query():
        nonlocal active, peak
        async with _session_lock(db):
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1

    await asyncio.gather(*[query() for _ in range(5)])
    assert peak == 1
    assert _session_lock(db) is _session_lock(db)
    assert _session_lock(FakeSession()) is not _session_lock(db)
