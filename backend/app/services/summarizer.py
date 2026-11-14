"""Short summary and keywords for every indexed document.

Used in three places: shown on the Documents page and in the chat document
picker, prepended to every chunk before embedding (contextual retrieval), and
as the seed for follow-up question suggestions. An LLM writes it when one is
configured; otherwise a cheap local heuristic does.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Dict, List, Optional

from app.services import llm

_STOP = set("""a an the and or but if then else of in on at to for with from by as is are was were be been
being this that these those it its into about over under between through during before after above below up down
out off again further than too very can will just not no nor so such only own same other some any each all both
few more most he she they them his her their we you your our i me my us what which who whom when where why how
has have had do does did doing would could should may might must shall also there here per via""".split())


def heuristic_summary(text: str, max_chars: int = 360) -> str:
    clean = re.sub(r"\s+", " ", re.sub(r"[#*|>`_]+", " ", text)).strip()
    if len(clean) <= max_chars:
        return clean
    cut = clean[:max_chars]
    return cut[: cut.rfind(" ")].rstrip(",;:") + "…"


def heuristic_keywords(text: str, n: int = 8) -> List[str]:
    words = re.findall(r"[A-Za-z][A-Za-z\-]{3,}", text.lower())
    counts = Counter(w for w in words if w not in _STOP)
    return [w for w, _ in counts.most_common(n)]


def _sample(text: str, budget: int = 9000) -> str:
    if len(text) <= budget:
        return text
    head = text[: int(budget * 0.6)]
    mid_start = len(text) // 2
    mid = text[mid_start: mid_start + int(budget * 0.25)]
    tail = text[-int(budget * 0.15):]
    return f"{head}\n…\n{mid}\n…\n{tail}"


async def summarize_document(filename: str, text: str) -> Dict:
    """Returns {"summary", "keywords", "method", "usage"}."""
    text = text or ""
    fallback = {"summary": heuristic_summary(text), "keywords": heuristic_keywords(text), "method": "heuristic", "usage": None}
    if not text.strip() or not llm.llm_available():
        return fallback

    data, usage = await llm.complete_json(
        "You summarise documents for a search index. Reply with JSON only: "
        '{"summary": "<2-3 plain sentences saying what the document is and what it covers>", '
        '"keywords": ["<5-8 short topical keywords or phrases>"]}. No markdown.',
        f"Document name: {filename}\n\nContent (excerpts):\n{_sample(text)}",
        temperature=0.1, max_tokens=400,
    )
    if not data or not isinstance(data.get("summary"), str):
        return fallback
    kws = data.get("keywords") or []
    return {
        "summary": data["summary"].strip()[:1000],
        "keywords": [str(k).strip()[:40] for k in kws if str(k).strip()][:10] or heuristic_keywords(text),
        "method": "llm",
        "usage": usage,
    }


def context_prefix(filename: str, summary: Optional[str], section: Optional[str]) -> str:
    """The text prepended to a chunk before embedding (never stored as content)."""
    parts = [f"Document: {filename}"]
    if summary:
        parts.append(f"About: {summary[:300]}")
    if section:
        parts.append(f"Section: {section}")
    return "\n".join(parts) + "\n\n"
