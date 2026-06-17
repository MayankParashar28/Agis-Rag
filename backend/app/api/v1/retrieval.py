import uuid
from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.api.v1.auth import get_current_active_user
from app.models.auth import User
from app.models.knowledge import KnowledgeBase
from app.services.search import retrieval_pipeline
from pydantic import BaseModel

router = APIRouter()

class DebugQuery(BaseModel):
    kb_id: uuid.UUID
    query: str

@router.post("/debug")
async def debug_retrieval(
    query_in: DebugQuery,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    # 1. Verify user owns KB
    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == query_in.kb_id,
            KnowledgeBase.user_id == current_user.id
        )
    )
    kb = result.scalar_one_or_none()
    if not kb:
        raise HTTPException(
            status_code=404,
            detail="Knowledge base not found or access denied."
        )

    # 2. Run retrieval & reranking
    search_res = await retrieval_pipeline.retrieve_and_rerank(
        db=db,
        kb_id=query_in.kb_id,
        query=query_in.query
    )
    
    # 3. Format and return results
    return {
        "pre_rerank": search_res.get("candidates_pre_rerank", []),
        "post_rerank": search_res.get("chunks", []),
        "latencies": {
            "retrieval_ms": round(search_res.get("retrieval_latency", 0.0) * 1000, 2),
            "rerank_ms": round(search_res.get("rerank_latency", 0.0) * 1000, 2),
            "total_ms": round(search_res.get("total_latency", 0.0) * 1000, 2)
        }
    }
