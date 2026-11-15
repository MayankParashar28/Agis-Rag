"""The order in which OpenAI-compatible LLM providers are tried.

Three call sites used to decide this independently, each with an
`if GEMINI_API_KEY: ... else: ...`. That is not a fallback - it picks by which
key is *set*, so a configured-but-exhausted Gemini key made the OpenAI branch
unreachable and every caller dropped to a local heuristic while a working key
sat unused. Callers now walk this list and stop at the first provider that
answers.
"""
import time
from typing import Dict, List, NamedTuple, Optional

from app.core.config import settings
from app.core.logging import logger
from app.services.llm_errors import is_quota_exhausted, quota_reset_seconds

# label -> unix time it is worth trying again. A spent daily quota does not
# clear for hours, so re-attempting it on every request buys nothing and costs
# a failed round trip each time - measured at roughly 4-5s per message against
# Gemini's free tier. Process-local on purpose: it is a latency optimisation,
# not a correctness mechanism, and it is self-correcting across restarts.
_cooldown_until: Dict[str, float] = {}

# Used when the provider says the quota is spent but not when it returns.
_DEFAULT_COOLDOWN_SECONDS = 15 * 60


def mark_exhausted(label: str, exc: Exception) -> None:
    """Record that `label` is out of quota, so the chain skips it for a while."""
    if not is_quota_exhausted(exc):
        return
    wait = quota_reset_seconds(exc) or _DEFAULT_COOLDOWN_SECONDS
    _cooldown_until[label] = time.time() + wait
    logger.warning(
        f"{label} quota exhausted; skipping it for {wait / 60:.0f} minutes."
    )
    from app.services.alerts import alert
    alert("llm_quota", f"{label} quota exhausted", {"provider": label, "retry in": f"{wait / 60:.0f} minutes"}, key=label)


def _cooling_down(label: str) -> bool:
    until = _cooldown_until.get(label)
    if until is None:
        return False
    if time.time() >= until:
        del _cooldown_until[label]
        return False
    return True


class LLMProvider(NamedTuple):
    label: str
    model: str
    api_key: str
    base_url: Optional[str]


# Lite models the provider rejected as unknown: skipped for the life of the
# process so a wrong model name costs one failed call, not one per request.
_lite_unavailable: set = set()


def mark_model_unavailable(provider: "LLMProvider", exc: Exception) -> None:
    """Remember a lite model the provider does not offer."""
    if not provider.label.endswith(" lite"):
        return
    text = str(exc).lower()
    if getattr(exc, "status_code", None) == 404 or "not found" in text or "does not exist" in text or "unknown model" in text:
        _lite_unavailable.add(provider.model)
        logger.warning(f"{provider.label} model '{provider.model}' is not available; using the main model for side tasks.")


def provider_chain(prefer_paid: bool = False, lite: bool = False) -> List[LLMProvider]:
    """Configured providers, best first.

    Gemini leads by default: a single answer or audit fits inside its free
    tier. `prefer_paid` puts OpenAI first for work that issues many calls at
    once - one RAGAS run spends dozens, which a 20-requests/day tier cannot
    finish.
    """
    gemini = (
        LLMProvider(
            "Gemini",
            settings.GEMINI_MODEL,
            settings.GEMINI_API_KEY,
            settings.GEMINI_OPENAI_BASE_URL,
        )
        if settings.GEMINI_API_KEY
        else None
    )
    openai_p = (
        LLMProvider("OpenAI", settings.OPENAI_MODEL, settings.OPENAI_API_KEY, None)
        if settings.OPENAI_API_KEY
        else None
    )

    ordered = [p for p in ([openai_p, gemini] if prefer_paid else [gemini, openai_p])
               if p is not None]

    # Side tasks try each provider's cheaper model first, then its main one.
    if lite and settings.USE_LITE_MODELS:
        lite_model = {"Gemini": settings.GEMINI_LITE_MODEL, "OpenAI": settings.OPENAI_LITE_MODEL}
        expanded = []
        for p in ordered:
            m = lite_model.get(p.label)
            if m and m != p.model and m not in _lite_unavailable:
                expanded.append(LLMProvider(f"{p.label} lite", m, p.api_key, p.base_url))
            expanded.append(p)
        ordered = expanded

    available = [p for p in ordered if not _cooling_down(p.label)]
    # If every provider is cooling down, try them anyway rather than returning
    # nothing: a stale cooldown must never be the reason a request gets no
    # answer at all.
    return available or ordered
