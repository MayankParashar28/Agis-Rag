"""Semantic answer cache in Redis.

When a new question means (almost) the same as one already answered for the
same knowledge base, the stored answer and citations are returned instantly
instead of running retrieval, reranking and the LLM again.

Correctness rules:
- Only first questions in a conversation use the cache. A follow-up such as
  "and the second one?" depends on earlier turns, so it is never served from it.
- Keys include the KB's content version. Indexing or deleting a document bumps
  the version, so stale answers are never served; their keys simply expire.
- Only answers the judge scored confidently are stored.
- Every key has a TTL and each bucket is trimmed, so Redis cleans itself up.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.logging import logger

VERSION_PREFIX = "kb:ver:"
BUCKET_PREFIX = "ans:"


def _redis():
    from app.core.redis_client import redis_client
    return redis_client


def _scope(document_ids: Optional[List[Any]], web_search: bool) -> str:
    ids = ",".join(sorted(str(d) for d in (document_ids or [])))
    return hashlib.md5(f"{ids}|{int(bool(web_search))}".encode()).hexdigest()[:12]


async def _kb_version(r, kb_id) -> str:
    v = await r.get(f"{VERSION_PREFIX}{kb_id}")
    return str(v or "0")


def bump_kb_version_sync(kb_id) -> None:
    """Invalidate cached answers for a KB (called from the worker / indexer)."""
    try:
        from app.services import doc_store
        doc_store.get_client().incr(f"{VERSION_PREFIX}{kb_id}")
    except Exception as e:
        logger.debug(f"answer_cache: version bump skipped for {kb_id}: {e}")


async def get_query_embedding(query: str) -> Optional[List[float]]:
    """Normalised query embedding, sharing the retriever's Redis cache key."""
    r = _redis()
    key = f"emb:{hashlib.md5(query.strip().lower().encode('utf-8')).hexdigest()}"
    try:
        if r is not None:
            cached = await r.get(key)
            if cached:
                return json.loads(cached)
        from app.services.search import retrieval_pipeline
        vec = await asyncio.to_thread(retrieval_pipeline.embed_model.encode, query, normalize_embeddings=True)
        vec = vec.tolist()
        if r is not None:
            await r.setex(key, 86400, json.dumps(vec))
        return vec
    except Exception as e:
        logger.debug(f"answer_cache: embedding unavailable: {e}")
        return None


def _cosine(a: List[float], b: List[float]) -> float:
    # Both vectors are L2-normalised by the embedding model.
    return sum(x * y for x, y in zip(a, b))


async def _bucket_key(r, kb_id, document_ids, web_search) -> str:
    version = await _kb_version(r, kb_id)
    return f"{BUCKET_PREFIX}{kb_id}:{version}:{_scope(document_ids, web_search)}"


async def lookup(kb_id, query: str, embedding: Optional[List[float]],
                 document_ids=None, web_search: bool = False) -> Optional[Dict[str, Any]]:
    if not settings.ANSWER_CACHE_ENABLED or embedding is None:
        return None
    r = _redis()
    if r is None:
        return None
    try:
        key = await _bucket_key(r, kb_id, document_ids, web_search)
        entries = await r.lrange(key, 0, -1)
        best, best_sim = None, 0.0
        for raw in entries:
            entry = json.loads(raw)
            sim = _cosine(embedding, entry["embedding"])
            if sim > best_sim:
                best, best_sim = entry, sim
        if best and best_sim >= settings.ANSWER_CACHE_SIMILARITY:
            logger.info(f"Answer cache hit (similarity {best_sim:.3f}) for: '{query}'")
            return {**best, "similarity": round(best_sim, 4)}
    except Exception as e:
        logger.warning(f"answer_cache lookup failed: {e}")
    return None


async def store(kb_id, query: str, embedding: Optional[List[float]], answer: str,
                citations: list, confidence: float, document_ids=None,
                web_search: bool = False) -> None:
    if (not settings.ANSWER_CACHE_ENABLED or embedding is None or not answer.strip()
            or confidence < settings.ANSWER_CACHE_MIN_CONFIDENCE):
        return
    r = _redis()
    if r is None:
        return
    try:
        key = await _bucket_key(r, kb_id, document_ids, web_search)
        entry = {"query": query, "embedding": embedding, "answer": answer, "citations": citations,
                 "confidence": confidence, "created_at": time.time()}
        pipe = r.pipeline()
        pipe.lpush(key, json.dumps(entry))
        pipe.ltrim(key, 0, settings.ANSWER_CACHE_MAX_ENTRIES - 1)
        pipe.expire(key, settings.ANSWER_CACHE_TTL_SECONDS)
        await pipe.execute()
    except Exception as e:
        logger.warning(f"answer_cache store failed: {e}")
