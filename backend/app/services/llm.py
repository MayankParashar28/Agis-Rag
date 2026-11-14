"""One small helper for every non-streaming LLM call in the app.

Walks the configured provider chain (Gemini, then OpenAI, honouring quota
cool-downs), returns the text plus a token usage record so cost can be
tracked, and never raises: a missing or failing provider returns None and
the caller falls back to a heuristic.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from app.core.config import settings
from app.core.logging import logger
from app.services.llm_providers import mark_exhausted, provider_chain


@dataclass
class Usage:
    provider: str = ""
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def cost_usd(self) -> float:
        return cost_usd(self.model, self.prompt_tokens, self.completion_tokens)

    def add(self, other: Optional["Usage"]) -> "Usage":
        if other:
            self.prompt_tokens += other.prompt_tokens
            self.completion_tokens += other.completion_tokens
            self.provider = self.provider or other.provider
            self.model = self.model or other.model
        return self


# USD per 1M tokens (input, output). Override with LLM_PRICING_JSON, e.g.
# {"gpt-4o": [2.5, 10]}. Unknown models use the "default" row so cost is an
# estimate rather than zero.
_DEFAULT_PRICING: Dict[str, Tuple[float, float]] = {
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "o4-mini": (1.10, 4.40),
    "gemini-flash": (0.30, 2.50),
    "gemini-flash-lite": (0.10, 0.40),
    "gemini-pro": (1.25, 10.00),
    "default": (0.50, 1.50),
}


def _pricing() -> Dict[str, Tuple[float, float]]:
    table = dict(_DEFAULT_PRICING)
    if settings.LLM_PRICING_JSON:
        try:
            for k, v in json.loads(settings.LLM_PRICING_JSON).items():
                table[k] = (float(v[0]), float(v[1]))
        except Exception as e:
            logger.warning(f"LLM_PRICING_JSON is not valid: {e}")
    return table


def cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    table = _pricing()
    m = (model or "").lower()
    rate = table.get(m)
    if rate is None:
        if "gemini" in m:
            rate = table["gemini-flash-lite"] if "lite" in m else table["gemini-pro"] if "pro" in m else table["gemini-flash"]
        else:
            # Longest matching prefix, e.g. "gpt-4o-mini-2024-07-18" -> gpt-4o-mini
            best = ""
            for k in table:
                if m.startswith(k) and len(k) > len(best):
                    best = k
            rate = table[best] if best else table["default"]
    return round((prompt_tokens * rate[0] + completion_tokens * rate[1]) / 1_000_000, 6)


def estimate_tokens(text: str) -> int:
    """Rough count for providers that do not report usage (~4 chars/token)."""
    return max(1, len(text or "") // 4)


def usage_from_response(provider_label: str, model: str, usage_obj: Any,
                        prompt_text: str = "", completion_text: str = "") -> Usage:
    pt = getattr(usage_obj, "prompt_tokens", None) if usage_obj else None
    ct = getattr(usage_obj, "completion_tokens", None) if usage_obj else None
    return Usage(
        provider=provider_label,
        model=model,
        prompt_tokens=int(pt) if pt else estimate_tokens(prompt_text),
        completion_tokens=int(ct) if ct else estimate_tokens(completion_text),
    )


def _strip_fences(text: str) -> str:
    text = text.strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    return m.group(1) if m else text


async def complete(system: str, user: str, *, json_mode: bool = False, temperature: float = 0.2,
                   max_tokens: Optional[int] = None, timeout: float = 40.0) -> Tuple[Optional[str], Optional[Usage]]:
    """Return (text, usage) from the first provider that answers, or (None, None)."""
    import openai

    for provider in provider_chain():
        try:
            client = (openai.AsyncOpenAI(api_key=provider.api_key, base_url=provider.base_url, timeout=timeout, max_retries=1)
                      if provider.base_url else openai.AsyncOpenAI(api_key=provider.api_key, timeout=timeout, max_retries=1))
            kwargs: Dict[str, Any] = dict(
                model=provider.model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=temperature,
            )
            if max_tokens:
                kwargs["max_tokens"] = max_tokens
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            resp = await client.chat.completions.create(**kwargs)
            text = resp.choices[0].message.content or ""
            usage = usage_from_response(provider.label, provider.model, getattr(resp, "usage", None), system + user, text)
            return (_strip_fences(text) if json_mode else text), usage
        except Exception as e:
            mark_exhausted(provider.label, e)
            logger.warning(f"{provider.label} call failed: {e}")
    return None, None


async def complete_json(system: str, user: str, **kw) -> Tuple[Optional[dict], Optional[Usage]]:
    text, usage = await complete(system, user, json_mode=True, **kw)
    if text is None:
        return None, usage
    try:
        data = json.loads(text)
        return (data if isinstance(data, dict) else None), usage
    except ValueError:
        logger.warning("LLM returned invalid JSON")
        return None, usage


def llm_available() -> bool:
    return bool(settings.GEMINI_API_KEY or settings.OPENAI_API_KEY)
