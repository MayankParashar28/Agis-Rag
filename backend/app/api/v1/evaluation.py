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
from app.core.logging import logger
from app.services import golden, audit
from app.models.metrics import GoldenQuestion
from pydantic import BaseModel
from typing import Optional

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
    try:
        eval_results = await ragas_evaluator.run_evaluation(db, eval_in.kb_id)
    except HTTPException:
        raise
    except Exception as e:
        # Say what failed instead of the generic 500 text.
        logger.error(f"Evaluation failed for KB {eval_in.kb_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=502,
            detail=f"The evaluation could not finish ({type(e).__name__}: {str(e)[:200]}). Check the backend logs.",
        )
    
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
        .where(Evaluation.kb_id == kb_id, (Evaluation.kind == None) | (Evaluation.kind == "ragas"))  # noqa: E711
        .order_by(Evaluation.created_at.asc())
    )
    evals_result = await db.execute(eval_query)
    evals = evals_result.scalars().all()
    return evals


# ---------------------------------------------------------------------------
# Golden question sets
# ---------------------------------------------------------------------------
class GoldenQuestionIn(BaseModel):
    kb_id: uuid.UUID
    question: str
    expected_answer: str


class GoldenRunIn(BaseModel):
    kb_id: uuid.UUID
    threshold: Optional[float] = None


class GoldenSuggestIn(BaseModel):
    kb_id: uuid.UUID
    n: int = 5


async def _owned_kb(db: AsyncSession, kb_id: uuid.UUID, user: User) -> KnowledgeBase:
    q = select(KnowledgeBase).where(KnowledgeBase.id == kb_id)
    if user.role != "admin":
        q = q.where(KnowledgeBase.user_id == user.id)
    kb = (await db.execute(q)).scalar_one_or_none()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found or access denied.")
    return kb


def _gq(q: GoldenQuestion) -> dict:
    return {"id": str(q.id), "kb_id": str(q.kb_id), "question": q.question,
            "expected_answer": q.expected_answer, "created_at": q.created_at.isoformat() if q.created_at else None}


@router.get("/golden/{kb_id}")
async def list_golden_questions(kb_id: uuid.UUID, db: AsyncSession = Depends(get_db),
                                current_user: User = Depends(get_current_active_user)) -> Any:
    await _owned_kb(db, kb_id, current_user)
    rows = (await db.execute(select(GoldenQuestion).where(GoldenQuestion.kb_id == kb_id).order_by(GoldenQuestion.created_at))).scalars().all()
    return [_gq(q) for q in rows]


@router.post("/golden", status_code=201)
async def add_golden_question(body: GoldenQuestionIn, db: AsyncSession = Depends(get_db),
                              current_user: User = Depends(get_current_active_user)) -> Any:
    await _owned_kb(db, body.kb_id, current_user)
    if not body.question.strip() or not body.expected_answer.strip():
        raise HTTPException(status_code=400, detail="Both the question and the expected answer are required.")
    q = GoldenQuestion(kb_id=body.kb_id, question=body.question.strip(), expected_answer=body.expected_answer.strip(),
                       created_by=current_user.id)
    db.add(q)
    await db.commit()
    await db.refresh(q)
    return _gq(q)


@router.delete("/golden/{question_id}", status_code=204)
async def delete_golden_question(question_id: uuid.UUID, db: AsyncSession = Depends(get_db),
                                 current_user: User = Depends(get_current_active_user)):
    q = (await db.execute(select(GoldenQuestion).where(GoldenQuestion.id == question_id))).scalar_one_or_none()
    if not q:
        raise HTTPException(status_code=404, detail="Question not found.")
    await _owned_kb(db, q.kb_id, current_user)
    await db.delete(q)
    await db.commit()
    from fastapi import Response
    return Response(status_code=204)


@router.post("/golden/suggest")
async def suggest_golden_questions(body: GoldenSuggestIn, db: AsyncSession = Depends(get_db),
                                   current_user: User = Depends(get_current_active_user)) -> Any:
    """Draft questions from the KB's own passages; nothing is saved until added."""
    await _owned_kb(db, body.kb_id, current_user)
    return {"items": await golden.suggest_questions(db, body.kb_id, max(1, min(body.n, 10)))}


@router.post("/golden/run")
async def run_golden_set(body: GoldenRunIn, db: AsyncSession = Depends(get_db),
                         current_user: User = Depends(get_current_active_user)) -> Any:
    """Answer every golden question with the real pipeline and score it.
    `pass` is false when the average score is below the threshold - CI uses it."""
    kb = await _owned_kb(db, body.kb_id, current_user)
    try:
        result = await golden.run_golden(db, body.kb_id, body.threshold)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Golden run failed for KB {body.kb_id}: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail=f"The golden run could not finish ({type(e).__name__}: {str(e)[:200]}).")
    await audit.record(db, current_user, "evaluation.golden_run", "knowledge_base", kb.id,
                       {"kb_name": kb.name, "score": result.get("overall_score"), "pass": result.get("pass")})
    return result


@router.get("/golden/{kb_id}/runs")
async def golden_run_history(kb_id: uuid.UUID, limit: int = 20, db: AsyncSession = Depends(get_db),
                             current_user: User = Depends(get_current_active_user)) -> Any:
    await _owned_kb(db, kb_id, current_user)
    rows = (await db.execute(
        select(Evaluation).where(Evaluation.kb_id == kb_id, Evaluation.kind == "golden")
        .order_by(Evaluation.created_at.desc()).limit(max(1, min(limit, 100)))
    )).scalars().all()
    out = []
    for r in rows:
        d = r.details or {}
        out.append({"id": str(r.id), "created_at": r.created_at.isoformat(), "method": r.method,
                    "overall_score": d.get("overall_score"), "passed": d.get("passed"), "total": d.get("total"),
                    "pass": d.get("pass"), "threshold": d.get("threshold"), "faithfulness": r.faithfulness,
                    "correctness": r.answer_relevancy, "context_recall": r.context_recall,
                    "results": d.get("results", [])})
    return out
