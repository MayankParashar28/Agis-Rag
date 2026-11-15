"""Operational alerts by e-mail (Resend) and/or Slack.

Sent when something breaks that users would otherwise report first: an
unhandled server error, a failed document, startup problems, or every AI
provider failing. Each kind of alert is sent at most once per
ALERT_COOLDOWN_SECONDS for the same key, so an outage produces one message,
not hundreds.

Configure either channel (or both):
  ALERT_EMAIL        recipient address(es), comma-separated; needs EMAIL_API_KEY
                     (a Resend API key) and EMAIL_FROM_ADDRESS
  SLACK_WEBHOOK_URL  a Slack "Incoming Webhook" URL

With neither set, alerts are only logged. Sending never raises and never
blocks the request that triggered it.
"""
from __future__ import annotations

import asyncio
import html
import time
from typing import Any, Dict, Optional, Set

import httpx

from app.core.config import settings
from app.core.logging import logger

RESEND_URL = "https://api.resend.com/emails"

_last_sent: Dict[str, float] = {}
_pending: Set[asyncio.Task] = set()


def channels() -> list:
    out = []
    if settings.ALERT_EMAIL and settings.EMAIL_API_KEY:
        out.append("email")
    if settings.SLACK_WEBHOOK_URL:
        out.append("slack")
    return out


def _should_send(dedupe_key: str, now: Optional[float] = None) -> bool:
    now = now if now is not None else time.time()
    last = _last_sent.get(dedupe_key)
    if last is not None and now - last < settings.ALERT_COOLDOWN_SECONDS:
        return False
    _last_sent[dedupe_key] = now
    return True


def _format(title: str, details: Dict[str, Any]) -> tuple[str, str, str]:
    env = settings.PROJECT_NAME
    lines = [f"{k}: {v}" for k, v in details.items() if v not in (None, "")]
    text = f"[{env}] {title}\n" + "\n".join(lines)
    rows = "".join(f"<tr><td style='padding:2px 12px 2px 0;color:#666'>{html.escape(str(k))}</td>"
                   f"<td style='padding:2px 0'>{html.escape(str(v))}</td></tr>"
                   for k, v in details.items() if v not in (None, ""))
    body = (f"<p style='font:14px sans-serif'><strong>{html.escape(title)}</strong></p>"
            f"<table style='font:13px sans-serif;border-collapse:collapse'>{rows}</table>"
            f"<p style='font:12px sans-serif;color:#888'>Repeats of this alert are suppressed for "
            f"{settings.ALERT_COOLDOWN_SECONDS // 60} minutes.</p>")
    return f"[{env}] {title}", text, body


async def _deliver(subject: str, text: str, body: str) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        if settings.ALERT_EMAIL and settings.EMAIL_API_KEY:
            try:
                r = await client.post(RESEND_URL, headers={"Authorization": f"Bearer {settings.EMAIL_API_KEY}"}, json={
                    "from": settings.EMAIL_FROM_ADDRESS,
                    "to": [a.strip() for a in settings.ALERT_EMAIL.split(",") if a.strip()],
                    "subject": subject[:200],
                    "html": body,
                    "text": text,
                })
                if r.status_code >= 300:
                    logger.warning(f"Alert e-mail was refused ({r.status_code}): {r.text[:200]}")
            except Exception as e:
                logger.warning(f"Alert e-mail failed: {e}")
        if settings.SLACK_WEBHOOK_URL:
            try:
                r = await client.post(settings.SLACK_WEBHOOK_URL, json={"text": text[:3500]})
                if r.status_code >= 300:
                    logger.warning(f"Slack alert was refused ({r.status_code}): {r.text[:200]}")
            except Exception as e:
                logger.warning(f"Slack alert failed: {e}")


def alert(kind: str, title: str, details: Optional[Dict[str, Any]] = None, key: Optional[str] = None) -> None:
    """Send an alert in the background. Safe to call from sync or async code."""
    try:
        if not settings.ALERTS_ENABLED:
            return
        details = dict(details or {})
        dedupe_key = f"{kind}:{key or ''}"
        if not _should_send(dedupe_key):
            return
        logger.warning(f"ALERT {kind}: {title} {details}")
        if not channels():
            return
        subject, text, body = _format(title, details)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is None:
            asyncio.run(_deliver(subject, text, body))   # e.g. a Celery worker thread
            return
        task = loop.create_task(_deliver(subject, text, body))
        _pending.add(task)
        task.add_done_callback(_pending.discard)
    except Exception as e:  # alerts must never break the caller
        logger.warning(f"Could not send alert {kind}: {e}")
