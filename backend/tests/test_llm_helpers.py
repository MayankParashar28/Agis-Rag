import json

from app.services import llm
from app.services.decompose import heuristic_split, looks_compound
from app.services.summarizer import context_prefix, heuristic_keywords, heuristic_summary


def test_cost_known_and_prefix_models():
    assert llm.cost_usd("gpt-4o-mini", 1_000_000, 0) == 0.15
    assert llm.cost_usd("gpt-4o-mini-2024-07-18", 0, 1_000_000) == 0.60
    assert llm.cost_usd("gemini-3.5-flash", 1_000_000, 1_000_000) == 2.80
    assert llm.cost_usd("something-else", 1_000_000, 0) == 0.50


def test_pricing_override(monkeypatch):
    monkeypatch.setattr(llm.settings, "LLM_PRICING_JSON", json.dumps({"gpt-4o": [1, 2]}))
    assert llm.cost_usd("gpt-4o", 1_000_000, 1_000_000) == 3.0


def test_usage_accumulates_and_estimates():
    u = llm.usage_from_response("OpenAI", "gpt-4o", None, "x" * 400, "y" * 80)
    assert (u.prompt_tokens, u.completion_tokens) == (100, 20)
    total = llm.Usage().add(u).add(llm.Usage("Gemini", "gemini-3.5-flash", 10, 5))
    assert (total.prompt_tokens, total.completion_tokens, total.model) == (110, 25, "gpt-4o")


def test_compound_detection_and_split():
    q = "What is the refund window and who approves exceptions?"
    assert looks_compound(q)
    assert heuristic_split(q) == ["What is the refund window?", "who approves exceptions?"]
    assert not looks_compound("What is the refund window?")
    assert heuristic_split("Short and sweet?") == ["Short and sweet?"]


def test_heuristic_summary_and_keywords():
    text = ("# Title\n\nRefund policy refund policy applies to every order. " * 20)
    s = heuristic_summary(text, 80)
    assert len(s) <= 81 and s.endswith("…") and "#" not in s
    assert heuristic_keywords(text)[:2] == ["refund", "policy"]


def test_context_prefix():
    p = context_prefix("a.pdf", "About refunds", "Returns > Exceptions")
    assert p == "Document: a.pdf\nAbout: About refunds\nSection: Returns > Exceptions\n\n"
    assert context_prefix("a.pdf", None, None) == "Document: a.pdf\n\n"
