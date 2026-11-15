import datetime as dt
import types

from app.core.config import settings
from app.services import usage as U


def _user(role="user", q=None, t=None):
    return types.SimpleNamespace(id="u1", role=role, daily_question_limit=q, daily_token_limit=t)


def test_limits_default_custom_unlimited_and_admin(monkeypatch):
    monkeypatch.setattr(settings, "DAILY_QUESTION_LIMIT", 100)
    monkeypatch.setattr(settings, "DAILY_TOKEN_LIMIT", 300000)
    monkeypatch.setattr(settings, "ADMINS_UNLIMITED", True)
    assert U.limits_for(_user()) == (100, 300000)
    assert U.limits_for(_user(q=10, t=0)) == (10, 0)        # own question cap, unlimited tokens
    assert U.limits_for(_user("admin")) == (0, 0)            # admins unlimited by default
    assert U.limits_for(_user("admin", q=5)) == (5, 300000)  # unless given their own limit


def test_blocked_reason():
    base = dict(cost_usd=0.0, resets_at="x", custom_limits=False)
    assert U.UsageToday(questions=99, tokens=10, question_limit=100, token_limit=0, **base).blocked_reason is None
    assert "100 questions" in U.UsageToday(questions=100, tokens=10, question_limit=100, token_limit=0, **base).blocked_reason
    assert "tokens" in U.UsageToday(questions=1, tokens=5000, question_limit=0, token_limit=5000, **base).blocked_reason
    assert U.UsageToday(questions=10**6, tokens=10**9, question_limit=0, token_limit=0, **base).as_dict()["blocked"] is False


def test_day_boundaries_are_utc():
    now = dt.datetime(2026, 11, 15, 22, 30, tzinfo=dt.timezone.utc)
    assert U.day_start(now) == dt.datetime(2026, 11, 15, tzinfo=dt.timezone.utc)
    assert U.resets_at(now) == dt.datetime(2026, 11, 16, tzinfo=dt.timezone.utc)
    assert U.friendly_wait(now) == "1 h 30 min"
    ist = dt.datetime(2026, 11, 16, 2, 0, tzinfo=dt.timezone(dt.timedelta(hours=5, minutes=30)))
    assert U.day_start(ist) == dt.datetime(2026, 11, 15, tzinfo=dt.timezone.utc)
