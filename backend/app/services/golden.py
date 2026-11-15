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

from sqlalchemy import func, select
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


def _sentences(text: str) -> List[str]:
    text = re.sub(r"^#+\s.*$", "", text, flags=re.M)      # drop Markdown headings
    text = re.sub(r"\s+", " ", text.replace("|", " ")).strip()
    return [x.strip() for x in re.split(r"(?<=[.!?])\s+", text) if x.strip()]


def _heuristic_drafts(sample, n: int) -> List[Dict[str, str]]:
    """Drafts without a model: pick the most informative sentence of each
    passage (prefer ones with numbers, dates or names) and ask about it."""
    out: List[Dict[str, str]] = []
    for content, filename in sample:
        best = None
        for sent in _sentences(content):
            if not 40 <= len(sent) <= 300:
                continue
            score = len(re.findall(r"\d", sent)) * 3 + len(re.findall(r"\b[A-Z][a-z]+", sent)) + min(len(sent), 200) / 100
            if best is None or score > best[0]:
                best = (score, sent)
        if best:
            sent = best[1]
            topic = " ".join(sent.split()[:8]).rstrip(",;:")
            out.append({"question": f"What does {filename} say about \"{topic}…\"?", "expected_answer": sent})
        if len(out) >= n:
            break
    return out


def _extract_items(data: Any) -> List[Dict[str, str]]:
    """Accept the shapes models actually return: {"items": [...]},
    {"questions": [...]}, any list-valued key, or a bare list; and
    question/answer field name variants."""
    if isinstance(data, dict):
        lists = [v for v in data.values() if isinstance(v, list)]
        data = data.get("items") or data.get("questions") or (lists[0] if lists else [])
    if not isinstance(data, list):
        return []
    out = []
    for it in data:
        if not isinstance(it, dict):
            continue
        q = it.get("question") or it.get("q")
        a = it.get("expected_answer") or it.get("answer") or it.get("expected") or it.get("a")
        if q and a:
            out.append({"question": str(q).strip(), "expected_answer": str(a).strip()})
    return out


async def suggest_questions(db: AsyncSession, kb_id: uuid.UUID, n: int = 5) -> Tuple[List[Dict[str, str]], Optional[str], str]:
    """Draft golden questions from random passages of the knowledge base.

    Returns (items, reason, method). `reason` explains an empty result;
    `method` is "llm" or "heuristic".
    """
    import json

    total_docs = (await db.execute(select(func.count(Document.id)).where(Document.kb_id == kb_id))).scalar() or 0
    rows = (await db.execute(
        select(DocumentChunk.content, Document.filename)
        .join(Document, Document.id == DocumentChunk.doc_id)
        .where(Document.kb_id == kb_id, Document.status == "indexed")
    )).all()
    if not rows:
        reason = ("This knowledge base has no documents yet. Upload one on the Documents page first."
                  if total_docs == 0 else
                  "None of this knowledge base's documents has finished indexing yet. Try again when they show Ready.")
        return [], reason, "none"

    sample = random.sample(rows, min(len(rows), 12))
    if llm.llm_available():
        excerpts = "\n\n".join(f"[{i + 1}] ({fn}) {c[:900]}" for i, (c, fn) in enumerate(sample))
        text, _ = await llm.complete(
            f"From the excerpts, write {n} test questions a user might really ask, each answerable from ONE excerpt, "
            "with a concise expected answer taken from that excerpt (no outside knowledge). Prefer questions about "
            'specific facts, numbers, dates or rules. Reply with JSON only: {"items": [{"question": "...", "expected_answer": "..."}]}.',
            excerpts, json_mode=True, temperature=0.5,
        )
        items: List[Dict[str, str]] = []
        if text:
            try:
                items = _extract_items(json.loads(text))
            except ValueError:
                logger.warning(f"Golden draft: model reply was not JSON: {text[:200]!r}")
        if items:
            return items[:n], None, "llm"
        logger.warning("Golden draft: the model returned no usable questions; drafting from the text instead.")

    drafts = _heuristic_drafts(sample, n)
    if drafts:
        return drafts, None, "heuristic"
    return [], "The indexed passages are too short to draft questions from. Add questions manually with Add.", "none"
