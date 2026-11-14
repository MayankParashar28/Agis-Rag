"""Follow-up questions generated from the answer and the passages it used."""
from __future__ import annotations

from typing import List, Optional, Tuple

from app.services import llm


async def suggest_follow_ups(question: str, answer: str, chunks: list, n: int = 3) -> Tuple[List[str], Optional[llm.Usage]]:
    if not llm.llm_available() or not answer.strip():
        return [], None
    context = "\n\n".join((c.get("content") or "")[:700] for c in chunks[:4])
    data, usage = await llm.complete_json(
        f"Suggest {n} short follow-up questions the user could ask next. They must be answerable from the "
        "SOURCE EXCERPTS below (not from general knowledge), be different from the original question, and "
        'be at most 12 words each. Reply with JSON only: {"questions": ["...", "..."]}.',
        f"Original question: {question}\n\nAnswer given:\n{answer[:1500]}\n\nSOURCE EXCERPTS:\n{context}",
        temperature=0.4, max_tokens=200,
    )
    qs = (data or {}).get("questions") if data else None
    if not isinstance(qs, list):
        return [], usage
    out = []
    for q in qs:
        q = str(q).strip()
        if q and q.lower() != question.strip().lower():
            out.append(q if q.endswith("?") else q + "?")
    return out[:n], usage
