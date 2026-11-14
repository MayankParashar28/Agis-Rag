import sys
import types

sys.modules.setdefault("app.services.models", types.SimpleNamespace(get_embedding_model=lambda: None, get_reranker=lambda: None))

from app.services.golden import overlap  # noqa: E402


def test_overlap_scores():
    assert overlap("Refunds are allowed within 30 days of purchase", "30 days refund") == 1.0
    assert overlap("Nothing relevant here", "30 days refund") == 0.0
    assert 0 < overlap("Refunds take 30 days", "refund within 14 days") < 1
    assert overlap("anything", "") == 0.0
