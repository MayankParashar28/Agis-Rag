"""Query decomposition: split a compound question into focused sub-questions.

"What's the refund window and who approves exceptions?" retrieves poorly as
one query because the two halves pull towards different passages. Searching
for each half and merging the candidates (then reranking against the
original question) finds both.
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

from app.services import llm

MAX_SUB_QUESTIONS = 3
_QWORDS = r"(?:what|which|who|whom|whose|when|where|why|how|is|are|does|do|did|can|could|should|will)"
_SPLIT_RE = re.compile(rf"\s*(?:\?|;|,\s*and\s+(?=also\b|{_QWORDS}\b)|\s+and\s+(?=also\b|{_QWORDS}\b))\s*", re.I)


def looks_compound(query: str) -> bool:
    q = query.strip()
    if len(q) < 25:
        return False
    return q.count("?") > 1 or bool(re.search(rf"\b(and|also|as well as|plus)\s+{_QWORDS}\b", q, re.I)) or ";" in q


def heuristic_split(query: str) -> List[str]:
    parts = [p.strip(" ,.;") for p in _SPLIT_RE.split(query) if p and p.strip(" ,.;")]
    parts = [p if p.endswith("?") else p + "?" for p in parts if len(p) > 8]
    seen, out = set(), []
    for p in parts:
        k = p.lower()
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out[:MAX_SUB_QUESTIONS] if len(out) > 1 else [query]


async def decompose(query: str) -> Tuple[List[str], Optional[llm.Usage]]:
    """Return (sub_questions, usage). A simple question returns [query]."""
    if not looks_compound(query):
        return [query], None
    if llm.llm_available():
        data, usage = await llm.complete_json(
            "Split the user's question into the smallest set of independent, self-contained search questions "
            f"(at most {MAX_SUB_QUESTIONS}). Each must make sense alone and keep the original wording where possible. "
            'If the question is already a single question, return it unchanged. Reply with JSON only: {"sub_questions": ["..."]}.',
            query, temperature=0.0, max_tokens=200,
        )
        subs = (data or {}).get("sub_questions") if data else None
        if isinstance(subs, list):
            subs = [str(s).strip() for s in subs if str(s).strip()][:MAX_SUB_QUESTIONS]
            if subs:
                return subs, usage
        return heuristic_split(query), usage
    return heuristic_split(query), None
