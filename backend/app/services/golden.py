"""Golden question sets: questions with known good answers, scored on demand
and nightly in CI so a change that hurts answer quality fails a check.

Each run answers every question with the real pipeline (hybrid retrieval,
reranking, the same guarded prompt as chat) and scores it:
- correctness: does the answer agree with the expected answer?
- faithfulness: is the answer supported by the retrieved passages?
- context_recall: do the retrieved passages contain the expected answer?
An LLM judge scores correctness and faithfulness when one is configured;
otherwise lexical-overlap heuristics do, and the run says so.
"""
from __future__ import annotations

import random
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import logger
from app.models.knowledge import Document, DocumentChunk
from app.models.metrics import Evaluation, GoldenQuestion
from app.services import llm
from app.services.guard import SOURCE_RULES, build_context
from app.services.search import retrieval_pipeline

_STOP = set("the a an and or of to in on for with by is are was were be been it its this that these those as at from".split())


def _stem(w: str) -> str:
    for suf in ("ing", "ies", "es", "s", "ed"):
        if len(w) > len(suf) + 2 and w.endswith(suf):
            return w[: -len(suf)] + ("y" if suf == "ies" else "")
    return w


def _terms(text: str) -> set:
    return {_stem(w) for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if w not in _STOP and len(w) > 2}


def overlap(a: str, b: str) -> float:
    """Fraction of b's content words that appear in a."""
    ta, tb = _terms(a), _terms(b)
    if not tb:
        return 0.0
    return len(ta & tb) / len(tb)


async def _answer(question: str, chunks: List[Dict[str, Any]]) -> Tuple[str, Optional[llm.Usage]]:
    context, _ = build_context(chunks)
    system = (
        "Answer the question using ONLY the sources. If they do not contain the answer say "
        "'I cannot find the answer in the provided documents.' Cite sources as [Source N].\n\n"
        f"{SOURCE_RULES}\n\nSources:\n{context}"
    )
    text, usage = await llm.complete(system, question, temperature=0.0, max_tokens=600)
    if text is None:
        from app.services.agent import synthesize_context_fallback
        return synthesize_context_fallback(question, chunks), None
    return text, usage


async def _judge(question: str, expected: str, answer: str, chunks: List[Dict[str, Any]]) -> Tuple[Dict[str, float], str, Optional[llm.Usage]]:
    heur = {
        "correctness": round(overlap(answer, expected), 3),
        "faithfulness": round(overlap("\n".join(c.get("content", "") for c in chunks), answer), 3),
    }
    if not llm.llm_available():
        return heur, "heuristic", None
    context = "\n\n".join(c.get("content", "")[:1200] for c in chunks[:5])
    data, usage = await llm.complete_json(
        "You are a strict grader. Score two things from 0.0 to 1.0:\n"
        "- correctness: how well the ANSWER conveys the same facts as the EXPECTED answer (1 = fully equivalent, 0 = wrong or missing).\n"
        "- faithfulness: the fraction of claims in the ANSWER that are supported by the SOURCES.\n"
        'Reply with JSON only: {"correctness": <number>, "faithfulness": <number>, "reason": "<one sentence>"}.',
        f"QUESTION: {question}\n\nEXPECTED: {expected}\n\nANSWER: {answer}\n\nSOURCES:\n{context}",
        temperature=0.0, max_tokens=200,
    )
    if not data:
        return heur, "heuristic", usage
    try:
        scores = {
            "correctness": max(0.0, min(1.0, float(data.get("correctness", 0)))),
            "faithfulness": max(0.0, min(1.0, float(data.get("faithfulness", 0)))),
        }
        if data.get("reason"):
            scores["reason"] = str(data["reason"])[:300]
        return scores, "llm", usage
    except (TypeError, ValueError):
        return heur, "heuristic", usage


async def run_golden(db: AsyncSession, kb_id: uuid.UUID, threshold: Optional[float] = None) -> Dict[str, Any]:
    threshold = settings.GOLDEN_PASS_THRESHOLD if threshold is None else threshold
    questions = (await db.execute(
        select(GoldenQuestion).where(GoldenQuestion.kb_id == kb_id).order_by(GoldenQuestion.created_at)
    )).scalars().all()
    if not questions:
        raise ValueError("This knowledge base has no golden questions yet.")

    results: List[Dict[str, Any]] = []
    usage_total = llm.Usage()
    methods = set()
    started = time.time()
    for q in questions:
        t0 = time.time()
        try:
            retrieval = await retrieval_pipeline.retrieve_and_rerank(db, kb_id, q.question)
            chunks = retrieval.get("chunks", [])
        except Exception as e:
            logger.error(f"Golden retrieval failed for '{q.question[:60]}': {e}")
            chunks = []
        answer, u1 = await _answer(q.question, chunks)
        scores, method, u2 = await _judge(q.question, q.expected_answer, answer, chunks)
        usage_total.add(u1).add(u2)
        methods.add(method)
        recall = round(overlap("\n".join(c.get("content", "") for c in chunks), q.expected_answer), 3)
        score = round((scores["correctness"] + scores["faithfulness"]) / 2, 3)
        results.append({
            "question_id": str(q.id),
            "question": q.question,
            "expected_answer": q.expected_answer,
            "answer": answer,
            "correctness": scores["correctness"],
            "faithfulness": scores["faithfulness"],
            "context_recall": recall,
            "score": score,
            "passed": score >= threshold,
            "reason": scores.get("reason"),
            "sources": [{"source_doc": c.get("filename"), "page": c.get("page_number"), "chunk_id": c.get("chunk_id")} for c in chunks[:5]],
            "latency": round(time.time() - t0, 2),
        })

    n = len(results)
    avg = lambda k: round(sum(r[k] for r in results) / n, 4) if n else None  # noqa: E731
    overall = avg("score")
    passed = sum(1 for r in results if r["passed"])
    method = "llm" if methods == {"llm"} else ("heuristic" if methods == {"heuristic"} else "mixed")

    record = Evaluation(
        kb_id=kb_id,
        faithfulness=avg("faithfulness"),
        answer_relevancy=avg("correctness"),
        context_recall=avg("context_recall"),
        context_precision=None,
        method=method,
        kind="golden",
        details={
            "threshold": threshold,
            "overall_score": overall,
            "passed": passed,
            "total": n,
            "pass": overall is not None and overall >= threshold,
            "results": results,
            "usage": {"prompt_tokens": usage_total.prompt_tokens, "completion_tokens": usage_total.completion_tokens,
                      "cost_usd": usage_total.cost_usd, "model": usage_total.model},
            "duration_s": round(time.time() - started, 1),
        },
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return {"id": str(record.id), "kb_id": str(kb_id), "method": method, "created_at": record.created_at.isoformat(), **record.details}


async def suggest_questions(db: AsyncSession, kb_id: uuid.UUID, n: int = 5) -> List[Dict[str, str]]:
    """Draft golden questions from random passages of the knowledge base."""
    rows = (await db.execute(
        select(DocumentChunk.content, Document.filename)
        .join(Document, Document.id == DocumentChunk.doc_id)
        .where(Document.kb_id == kb_id, Document.status == "indexed")
    )).all()
    if not rows:
        return []
    sample = random.sample(rows, min(len(rows), 12))
    if not llm.llm_available():
        # Without a model: turn the first sentence of a passage into a prompt.
        out = []
        for content, filename in sample[:n]:
            first = re.split(r"(?<=[.!?])\s+", content.strip())[0][:200]
            if len(first) > 30:
                out.append({"question": f"According to {filename}, what is stated about: \"{first[:80]}…\"?",
                            "expected_answer": first})
        return out
    excerpts = "\n\n".join(f"[{i + 1}] ({fn}) {c[:900]}" for i, (c, fn) in enumerate(sample))
    data, _ = await llm.complete_json(
        f"From the excerpts, write {n} test questions a user might really ask, each answerable from ONE excerpt, "
        "with a concise expected answer taken from that excerpt (no outside knowledge). Prefer questions about "
        'specific facts, numbers, dates or rules. Reply with JSON only: {"items": [{"question": "...", "expected_answer": "..."}]}.',
        excerpts, temperature=0.5, max_tokens=900,
    )
    items = (data or {}).get("items") if data else None
    if not isinstance(items, list):
        return []
    return [{"question": str(i.get("question", "")).strip(), "expected_answer": str(i.get("expected_answer", "")).strip()}
            for i in items if isinstance(i, dict) and i.get("question") and i.get("expected_answer")][:n]
