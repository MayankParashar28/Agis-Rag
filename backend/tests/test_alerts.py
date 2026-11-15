import asyncio

from app.core.config import settings
from app.services import alerts


def _reset(monkeypatch, **kw):
    alerts._last_sent.clear()
    for k, v in {"ALERTS_ENABLED": True, "ALERT_EMAIL": None, "EMAIL_API_KEY": None,
                 "SLACK_WEBHOOK_URL": None, "ALERT_COOLDOWN_SECONDS": 3600, **kw}.items():
        monkeypatch.setattr(settings, k, v)


def test_channels(monkeypatch):
    _reset(monkeypatch)
    assert alerts.channels() == []
    _reset(monkeypatch, ALERT_EMAIL="ops@example.com")
    assert alerts.channels() == []                      # e-mail also needs the Resend key
    _reset(monkeypatch, ALERT_EMAIL="ops@example.com", EMAIL_API_KEY="k", SLACK_WEBHOOK_URL="https://hooks.slack.test/x")
    assert alerts.channels() == ["email", "slack"]


def test_same_alert_is_sent_once_per_cooldown(monkeypatch):
    _reset(monkeypatch)
    assert alerts._should_send("a:x", now=1000)
    assert not alerts._should_send("a:x", now=1000 + 3599)
    assert alerts._should_send("a:y", now=1001)          # a different key is its own alert
    assert alerts._should_send("a:x", now=1000 + 3601)


async def test_delivers_to_email_and_slack(monkeypatch):
    _reset(monkeypatch, ALERT_EMAIL="ops@example.com, cto@example.com", EMAIL_API_KEY="re_key",
           SLACK_WEBHOOK_URL="https://hooks.slack.test/x")
    sent = []

    class FakeResponse:
        status_code = 200
        text = ""

    class FakeClient:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            sent.append((url, headers, json))
            return FakeResponse()

    monkeypatch.setattr(alerts.httpx, "AsyncClient", FakeClient)
    alerts.alert("indexing_failed", "A document failed to index", {"document": "a<b>.pdf", "reason": "boom"}, key="boom")
    alerts.alert("indexing_failed", "A document failed to index", {"document": "c.pdf", "reason": "boom"}, key="boom")
    await asyncio.gather(*list(alerts._pending))
    assert len(sent) == 2                                # one e-mail + one Slack post; the repeat was suppressed
    email = next(j for u, h, j in sent if u == alerts.RESEND_URL)
    assert email["to"] == ["ops@example.com", "cto@example.com"] and "a&lt;b&gt;.pdf" in email["html"]
    slack = next(j for u, h, j in sent if u.startswith("https://hooks.slack.test"))
    assert "A document failed to index" in slack["text"]


def test_alert_never_raises(monkeypatch):
    _reset(monkeypatch, SLACK_WEBHOOK_URL="https://hooks.slack.test/x")
    monkeypatch.setattr(alerts, "_format", lambda *a: (_ for _ in ()).throw(RuntimeError("bad")))
    alerts.alert("x", "y")                              # logged, not raised
