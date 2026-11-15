import types

from app.core.config import settings
from app.services import llm, llm_providers as P


def _keys(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "g")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "o")
    monkeypatch.setattr(settings, "GEMINI_MODEL", "gemini-main")
    monkeypatch.setattr(settings, "GEMINI_LITE_MODEL", "gemini-lite")
    monkeypatch.setattr(settings, "OPENAI_MODEL", "gpt-main")
    monkeypatch.setattr(settings, "OPENAI_LITE_MODEL", "gpt-lite")
    monkeypatch.setattr(settings, "USE_LITE_MODELS", True)
    P._lite_unavailable.clear()
    P._cooldown_until.clear()


def test_lite_chain_tries_cheaper_model_first(monkeypatch):
    _keys(monkeypatch)
    assert [p.model for p in P.provider_chain()] == ["gemini-main", "gpt-main"]
    assert [p.model for p in P.provider_chain(lite=True)] == ["gemini-lite", "gemini-main", "gpt-lite", "gpt-main"]
    monkeypatch.setattr(settings, "USE_LITE_MODELS", False)
    assert [p.model for p in P.provider_chain(lite=True)] == ["gemini-main", "gpt-main"]


async def test_unknown_lite_model_falls_back_and_is_remembered(monkeypatch):
    _keys(monkeypatch)
    calls = []

    class NotFound(Exception):
        status_code = 404

    class FakeClient:
        def __init__(self, **kw):
            self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self.create))

        async def create(self, **kw):
            calls.append(kw["model"])
            if kw["model"] == "gemini-lite":
                raise NotFound("model gemini-lite not found")
            assert "max_tokens" not in kw    # Gemini (lite or main) never gets an output cap
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="ok"), finish_reason="stop")], usage=None)

    import openai
    monkeypatch.setattr(openai, "AsyncOpenAI", FakeClient)
    text, usage = await llm.complete("s", "u", lite=True, max_tokens=50)
    assert text == "ok" and calls == ["gemini-lite", "gemini-main"]
    calls.clear()
    await llm.complete("s", "u", lite=True)
    assert calls == ["gemini-main"]          # the missing lite model is not retried
