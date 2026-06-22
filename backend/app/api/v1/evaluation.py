import uuid
from typing import Any, List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.api.v1.auth import get_current_active_user
from app.models.auth import User
from app.models.knowledge import KnowledgeBase
from app.models.metrics import Evaluation
from app.schemas.metrics import RagasEvaluationBase, RagasEvaluationResponse
from app.services.evaluator import ragas_evaluator

router = APIRouter()

@router.post("/run", response_model=RagasEvaluationResponse)
async def trigger_ragas_evaluation(
    eval_in: RagasEvaluationBase,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    # 1. Verify user owns KB
    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == eval_in.kb_id,
            KnowledgeBase.user_id == current_user.id
        )
    )
    kb = result.scalar_one_or_none()
    if not kb:
        raise HTTPException(
            status_code=404,
            detail="Knowledge base not found or access denied."
        )
        
    # 2. Run evaluation (awaits computation, returns results)
    eval_results = await ragas_evaluator.run_evaluation(db, eval_in.kb_id)
    
    # 3. Retrieve database record that was saved
    eval_id = uuid.UUID(eval_results["id"])
    record_result = await db.execute(select(Evaluation).where(Evaluation.id == eval_id))
    return record_result.scalar_one()


@router.get("/results/{kb_id}", response_model=List[RagasEvaluationResponse])
async def get_evaluation_history(
    kb_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    # 1. Verify user owns KB
    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.user_id == current_user.id
        )
    )
    kb = result.scalar_one_or_none()
    if not kb:
        raise HTTPException(
            status_code=404,
            detail="Knowledge base not found or access denied."
        )

    # 2. Fetch evaluation runs history
    eval_query = (
        select(Evaluation)
        .where(Evaluation.kb_id == kb_id)
        .order_by(Evaluation.created_at.asc())
    )
    evals_result = await db.execute(eval_query)
    evals = evals_result.scalars().all()
    return evals
