import uuid
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, Integer

from app.core.database import get_db
from app.core.config import settings
from app.core.logging import logger
from app.api.v1.auth import get_current_admin_user, get_current_active_user
from app.models.auth import User
from app.models.knowledge import Document, DocumentChunk
from app.models.metrics import QueryLog, Evaluation
from app.schemas.metrics import AnalyticsDashboardResponse

router = APIRouter()

@router.get("/dashboard", response_model=AnalyticsDashboardResponse)
async def get_admin_dashboard_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user)
) -> Any:
    # Single query utilizing scalar subqueries to reduce network roundtrips from 8 to 1
    query = select(
        select(func.count(User.id)).scalar_subquery().label("total_users"),
        select(func.count(Document.id)).scalar_subquery().label("total_documents"),
        select(func.count(DocumentChunk.id)).scalar_subquery().label("total_chunks"),
        select(func.count(QueryLog.id)).scalar_subquery().label("total_queries"),
        select(func.avg(QueryLog.latency)).scalar_subquery().label("avg_latency"),
        select(func.avg(QueryLog.retrieval_score)).scalar_subquery().label("avg_score"),
        select(func.avg(Evaluation.context_precision)).scalar_subquery().label("avg_precision"),
        select(func.avg(Evaluation.context_recall)).scalar_subquery().label("avg_recall"),
        select(func.avg(Evaluation.answer_relevancy)).scalar_subquery().label("avg_relevancy"),
        select(func.avg(Evaluation.faithfulness)).scalar_subquery().label("avg_faithfulness"),
        select(func.avg(QueryLog.hallucination_rate)).scalar_subquery().label("avg_hallucination"),
        select(func.count(QueryLog.id)).where(QueryLog.rating != None).scalar_subquery().label("total_ratings"),
        select(func.count(QueryLog.id)).where(QueryLog.rating == 1).scalar_subquery().label("helpful_ratings")
    )
    
    result = await db.execute(query)
    row = result.first()
    
    total_users = row.total_users if row and row.total_users is not None else 0
    total_documents = row.total_documents if row and row.total_documents is not None else 0
    total_chunks = row.total_chunks if row and row.total_chunks is not None else 0
    total_queries = row.total_queries if row and row.total_queries is not None else 0
    avg_latency = row.avg_latency if row and row.avg_latency is not None else 0.0
    avg_score = row.avg_score if row and row.avg_score is not None else 0.0
    avg_precision = row.avg_precision if row and row.avg_precision is not None else 0.0
    avg_recall = row.avg_recall if row and row.avg_recall is not None else 0.0
    avg_relevancy = row.avg_relevancy if row and row.avg_relevancy is not None else 0.0
    avg_faithfulness = row.avg_faithfulness if row and row.avg_faithfulness is not None else 0.0
    avg_hallucination = row.avg_hallucination if row and row.avg_hallucination is not None else 0.0
    total_ratings = row.total_ratings if row and row.total_ratings is not None else 0
    helpful_ratings = row.helpful_ratings if row and row.helpful_ratings is not None else 0
    
    # None, not 100.0: with no ratings there is no satisfaction rate to report.
    # Defaulting to a perfect score invented a metric out of missing data.
    user_satisfaction_rate = (helpful_ratings / total_ratings * 100.0) if total_ratings > 0 else None

    return {
        "total_users": total_users,
        "total_documents": total_documents,
        "total_chunks": total_chunks,
        "total_queries": total_queries,
        "average_latency": round(float(avg_latency), 3),
        "average_retrieval_score": round(float(avg_score), 4),
        "average_context_precision": round(float(avg_precision), 4),
        "average_context_recall": round(float(avg_recall), 4),
        "average_answer_relevancy": round(float(avg_relevancy), 4),
        "average_hallucination_rate": round(float(avg_hallucination), 4),
        "average_faithfulness": round(float(avg_faithfulness), 4),
        "user_satisfaction_rate": (
            round(float(user_satisfaction_rate), 2) if user_satisfaction_rate is not None else None
        )
    }


@router.get("/observability")
async def get_observability_metrics(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user)
) -> Any:
    """
    Returns time-series logs for latency (query, embedding, retrieval) and hallucination rates.
    """
    # Fetch last 50 query logs to create a historical graph
    result = await db.execute(
        select(QueryLog)
        .order_by(QueryLog.created_at.desc())
        .limit(50)
    )
    # Newest 50, re-sorted oldest-first so the time-series charts read left to right.
    logs = list(reversed(result.scalars().all()))
    
    time_series = []
    for log in logs:
        time_series.append({
            "timestamp": log.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "query_latency": round(log.latency * 1000, 2), # ms
            "embedding_latency": round((log.embedding_latency or 0.0) * 1000, 2),
            "retrieval_latency": round((log.retrieval_latency or 0.0) * 1000, 2),
            "hallucination_rate": log.hallucination_rate or 0.0,
            "retrieval_score": log.retrieval_score or 0.0
        })
    return time_series

@router.get("/costs")
async def get_costs(
    days: int = 30,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user)
) -> Any:
    """Token usage and estimated cost: per day, per knowledge base, per model."""
    from datetime import datetime, timedelta, timezone
    from app.models.knowledge import KnowledgeBase

    days = max(1, min(days, 365))
    since = datetime.now(timezone.utc) - timedelta(days=days)
    day = func.date_trunc("day", QueryLog.created_at)

    per_day = (await db.execute(
        select(day.label("day"), func.count(QueryLog.id), func.coalesce(func.sum(QueryLog.prompt_tokens), 0),
               func.coalesce(func.sum(QueryLog.completion_tokens), 0), func.coalesce(func.sum(QueryLog.cost_usd), 0.0),
               func.coalesce(func.sum(func.cast(QueryLog.cached, Integer)), 0))
        .where(QueryLog.created_at >= since).group_by(day).order_by(day)
    )).all()

    per_kb = (await db.execute(
        select(KnowledgeBase.name, QueryLog.kb_id, func.count(QueryLog.id),
               func.coalesce(func.sum(QueryLog.prompt_tokens), 0), func.coalesce(func.sum(QueryLog.completion_tokens), 0),
               func.coalesce(func.sum(QueryLog.cost_usd), 0.0), func.avg(QueryLog.latency))
        .outerjoin(KnowledgeBase, KnowledgeBase.id == QueryLog.kb_id)
        .where(QueryLog.created_at >= since).group_by(KnowledgeBase.name, QueryLog.kb_id)
        .order_by(func.sum(QueryLog.cost_usd).desc().nullslast())
    )).all()

    per_model = (await db.execute(
        select(QueryLog.model, func.count(QueryLog.id), func.coalesce(func.sum(QueryLog.prompt_tokens), 0),
               func.coalesce(func.sum(QueryLog.completion_tokens), 0), func.coalesce(func.sum(QueryLog.cost_usd), 0.0))
        .where(QueryLog.created_at >= since).group_by(QueryLog.model)
    )).all()

    total_cost = sum(float(r[4] or 0) for r in per_day)
    total_queries = sum(int(r[1] or 0) for r in per_day)
    return {
        "days": days,
        "totals": {
            "queries": total_queries,
            "cached": sum(int(r[5] or 0) for r in per_day),
            "prompt_tokens": sum(int(r[2] or 0) for r in per_day),
            "completion_tokens": sum(int(r[3] or 0) for r in per_day),
            "cost_usd": round(total_cost, 4),
            "avg_cost_per_query_usd": round(total_cost / total_queries, 6) if total_queries else 0.0,
        },
        "per_day": [{"day": r[0].strftime("%Y-%m-%d"), "queries": int(r[1]), "prompt_tokens": int(r[2]),
                     "completion_tokens": int(r[3]), "cost_usd": round(float(r[4] or 0), 4), "cached": int(r[5] or 0)} for r in per_day],
        "per_kb": [{"kb_id": str(r[1]) if r[1] else None, "kb_name": r[0] or "(deleted / unknown)", "queries": int(r[2]),
                    "prompt_tokens": int(r[3]), "completion_tokens": int(r[4]), "cost_usd": round(float(r[5] or 0), 4),
                    "avg_latency": round(float(r[6] or 0), 2)} for r in per_kb],
        "per_model": [{"model": r[0] or "(local fallback)", "queries": int(r[1]), "prompt_tokens": int(r[2]),
                       "completion_tokens": int(r[3]), "cost_usd": round(float(r[4] or 0), 4)} for r in per_model],
        "note": "Costs are estimates from the pricing table (override with LLM_PRICING_JSON). Token counts come from the "
                "provider when it reports them, otherwise from a 4-characters-per-token estimate.",
    }


@router.get("/audit")
async def get_audit_log(
    limit: int = 50,
    offset: int = 0,
    action: str | None = None,
    user: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user)
) -> Any:
    """Who did what: uploads, deletions, re-indexes, exports, role changes."""
    from app.models.metrics import AuditLog
    limit = max(1, min(limit, 200))
    q = select(AuditLog)
    cq = select(func.count(AuditLog.id))
    if action:
        q = q.where(AuditLog.action.like(f"{action}%"))
        cq = cq.where(AuditLog.action.like(f"{action}%"))
    if user:
        q = q.where(AuditLog.user_email.ilike(f"%{user}%"))
        cq = cq.where(AuditLog.user_email.ilike(f"%{user}%"))
    total = (await db.execute(cq)).scalar() or 0
    rows = (await db.execute(q.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit))).scalars().all()
    actions = [r[0] for r in (await db.execute(select(AuditLog.action).distinct().order_by(AuditLog.action))).all()]
    return {
        "total": total,
        "actions": actions,
        "items": [{"id": str(r.id), "user_email": r.user_email, "action": r.action, "target_type": r.target_type,
                   "target_id": r.target_id, "detail": r.detail or {}, "created_at": r.created_at.isoformat()} for r in rows],
    }


@router.get("/config-status")
async def get_config_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """
    Live status of backend dependencies and AI integrations.

    The connectivity flags are probed on each call. They used to be hardcoded
    to True, which meant the Settings page reported a healthy system while the
    database or cache was in fact unreachable.
    """
    # --- PostgreSQL ---
    postgres_connected = False
    try:
        await db.execute(select(1))
        postgres_connected = True
    except Exception as e:
        logger.warning(f"config-status: PostgreSQL probe failed: {e}")

    # --- Redis ---
    redis_connected = False
    redis_pending_documents = None
    try:
        from app.core.redis_client import redis_client
        if redis_client is not None:
            await redis_client.ping()
            redis_connected = True
            # Documents staged for a worker but not yet taken. This should
            # drain back to 0 once the worker has picked every upload up.
            import asyncio
            from app.services import doc_store
            redis_pending_documents = await asyncio.to_thread(doc_store.count_staged)
    except Exception as e:
        logger.warning(f"config-status: Redis probe failed: {e}")

    # --- Qdrant ---
    qdrant_connected = False
    collection_count = None
    try:
        import asyncio
        from app.services.search import retrieval_pipeline
        collections = await asyncio.to_thread(retrieval_pipeline.qclient.get_collections)
        qdrant_connected = True
        collection_count = len(collections.collections)
    except Exception as e:
        logger.warning(f"config-status: Qdrant probe failed: {e}")

    return {
        "postgres_connected": postgres_connected,
        "redis_connected": redis_connected,
        "redis_pending_documents": redis_pending_documents,
        "qdrant_connected": qdrant_connected,
        "qdrant_collections": collection_count,
        "openai_configured": bool(settings.OPENAI_API_KEY),
        "llamaparse_configured": bool(settings.LLAMAPARSE_API_KEY),
        "tavily_configured": bool(settings.TAVILY_API_KEY),
        "gemini_configured": bool(settings.GEMINI_API_KEY),
        "gemini_model": settings.GEMINI_MODEL,
        "openai_model": settings.OPENAI_MODEL,
        "embedding_model": settings.EMBEDDING_MODEL,
        "reranker_model": settings.RERANKER_MODEL,
        # Surface the retrieval tuning actually in effect, rather than letting
        # the UI restate numbers from the README.
        "retrieval_top_k": settings.RETRIEVAL_TOP_K,
        "rerank_top_n": settings.RERANK_TOP_N,
        "rerank_score_threshold": settings.RERANK_SCORE_THRESHOLD,
        "web_search_available": bool(settings.TAVILY_API_KEY),
        "storage": __import__("app.services.storage", fromlist=["describe"]).describe(),
        "features": {
            "query_decomposition": settings.QUERY_DECOMPOSITION,
            "follow_up_suggestions": settings.FOLLOW_UP_SUGGESTIONS,
            "contextual_embeddings": settings.CONTEXTUAL_EMBEDDINGS,
            "answer_cache": settings.ANSWER_CACHE_ENABLED,
        },
    }


@router.post("/query-logs/{log_id}/rate")
async def rate_query_log(
    log_id: uuid.UUID,
    rating_data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """
    Submit thumbs up (+1) or down (-1) helpfulness rating for a specific query log.
    """
    result = await db.execute(
        select(QueryLog).where(QueryLog.id == log_id, QueryLog.user_id == current_user.id)
    )
    query_log = result.scalar_one_or_none()
    if not query_log:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Query log not found."
        )
    
    rating = rating_data.get("rating")
    if rating not in [1, -1, 0, None]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid rating. Allowed: 1, -1, 0"
        )
        
    query_log.rating = rating
    await db.commit()
    return {"status": "success", "message": "Feedback recorded successfully."}

