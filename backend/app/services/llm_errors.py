"""Classifying LLM provider failures.

Shared by the chat and evaluation paths so both describe the same failure the
same way. The distinction that matters to a caller is whether the failure
clears by itself: an exhausted daily quota does, a rejected key does not, and
a timeout is worth retrying immediately.
"""
import re
from typing import Optional


def is_quota_exhausted(exc: Exception) -> bool:
    """True when the provider refused because the quota is spent.

    Retrying this is pointless - the reset is hours away - so callers should
    stop rather than work through a retry schedule. A per-minute rate limit
    looks similar but carries a short retryDelay, so it is excluded here.
    """
    text = str(exc)
    status = getattr(exc, "status_code", None) or getattr(
        getattr(exc, "response", None), "status_code", None
    )
    if status != 429 and "RESOURCE_EXHAUSTED" not in text:
        return False
    # A long reset (hours) means a daily cap, not a burst limit.
    return bool(re.search(r"retry in \d+h", text) or "per day" in text.lower()
                or "PerDay" in text)


def describe_llm_failure(exc: Exception, provider: str) -> str:
    """Turn an LLM client exception into a cause the reader can act on."""
    text = str(exc)
    status = getattr(exc, "status_code", None) or getattr(
        getattr(exc, "response", None), "status_code", None
    )

    if status == 429 or "RESOURCE_EXHAUSTED" in text or "quota" in text.lower():
        detail = f"the {provider} API quota is exhausted"
        # Google returns the wait as e.g. "Please retry in 22h37m31.2s".
        match = re.search(r"retry in (\d+h)?(\d+m)?", text)
        if match and match.group(0) != "retry in ":
            wait = (match.group(1) or "") + (match.group(2) or "")
            detail += f" (resets in about {wait})"
        return detail
    if status in (401, 403):
        return f"the {provider} API rejected the configured key"
    if "timeout" in text.lower():
        return f"the {provider} API timed out"
    return f"the {provider} API call failed ({type(exc).__name__})"


def quota_reset_seconds(exc: Exception) -> Optional[float]:
    """Seconds until an exhausted quota resets, when the provider says.

    Google reports it twice - a machine-readable `'retryDelay': '60158s'` and a
    prose "Please retry in 16h42m38s". The structured form is preferred; the
    prose is the fallback for providers that only phrase it that way.
    """
    text = str(exc)
    match = re.search(r"'retryDelay':\s*'(\d+)s'", text)
    if match:
        return float(match.group(1))

    match = re.search(r"retry in (?:(\d+)h)?(?:(\d+)m)?(?:([\d.]+)s)?", text)
    if match and any(match.groups()):
        hours, minutes, seconds = match.groups()
        return (
            float(hours or 0) * 3600
            + float(minutes or 0) * 60
            + float(seconds or 0)
        )
    return None
