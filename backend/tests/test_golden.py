import sys
import types

sys.modules.setdefault("app.services.models", types.SimpleNamespace(get_embedding_model=lambda: None, get_reranker=lambda: None))

from app.services.golden import overlap  # noqa: E402


def test_overlap_scores():
    assert overlap("Refunds are allowed within 30 days of purchase", "30 days refund") == 1.0
    assert overlap("Nothing relevant here", "30 days refund") == 0.0
    assert 0 < overlap("Refunds take 30 days", "refund within 14 days") < 1
    assert overlap("anything", "") == 0.0


def test_extract_items_accepts_common_shapes():
    from app.services.golden import _extract_items
    one = [{"question": "Q?", "expected_answer": "A."}]
    assert _extract_items({"items": one}) == one
    assert _extract_items({"questions": [{"question": "Q?", "answer": "A."}]}) == one
    assert _extract_items({"golden": [{"q": "Q?", "a": "A."}]}) == one
    assert _extract_items(one) == one
    assert _extract_items({"items": [{"question": "no answer"}]}) == []
    assert _extract_items("nonsense") == []


def test_heuristic_drafts_skip_headings_and_prefer_facts():
    from app.services.golden import _heuristic_drafts
    passage = ("# Data Cleaning\n\nIntro.\n\nIn 2019, researchers found that 27% of published studies "
               "contained duplicated records that changed their conclusions. Cleaning matters.")
    drafts = _heuristic_drafts([(passage, "paper.pdf")], 5)
    assert len(drafts) == 1
    assert "27%" in drafts[0]["expected_answer"] and "Data Cleaning" not in drafts[0]["expected_answer"]
    assert drafts[0]["question"].startswith("What does paper.pdf say about")
    assert _heuristic_drafts([("# Title\n\nShort.", "x.pdf")], 5) == []


async def test_llm_empty_reply_falls_through_to_next_provider(monkeypatch):
    import types
    from app.services import llm

    providers = [types.SimpleNamespace(label="Gemini", model="g", api_key="k", base_url="u"),
                 types.SimpleNamespace(label="OpenAI", model="o", api_key="k", base_url=None)]
    monkeypatch.setattr(llm, "provider_chain", lambda **kw: providers)
    sent = []

    class FakeClient:
        def __init__(self, **kw):
            self.base_url = kw.get("base_url")
            self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self.create))

        async def create(self, **kw):
            sent.append(kw)
            content = "" if self.base_url else "hello"
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=content), finish_reason="length")], usage=None)

    import openai
    monkeypatch.setattr(openai, "AsyncOpenAI", FakeClient)
    text, usage = await llm.complete("sys", "user", max_tokens=50)
    assert text == "hello" and usage.provider == "OpenAI"
    assert "max_tokens" not in sent[0]   # Gemini: no output cap (reasoning tokens count against it)
    assert sent[1]["max_tokens"] == 50
