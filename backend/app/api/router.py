from fastapi import APIRouter, Depends
from app.api.v1 import auth, knowledge_bases, documents, chat, retrieval, analytics, evaluation, notes
from app.api.v1.auth import get_current_admin_user

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(knowledge_bases.router, prefix="/knowledge-bases", tags=["knowledge-bases"])
api_router.include_router(documents.router, prefix="/documents", tags=["documents"])
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
# Evaluation and the retrieval debugger are admin tools: runs spend LLM quota.
api_router.include_router(retrieval.router, prefix="/retrieval", tags=["retrieval"], dependencies=[Depends(get_current_admin_user)])
api_router.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
api_router.include_router(evaluation.router, prefix="/evaluation", tags=["evaluation"], dependencies=[Depends(get_current_admin_user)])
api_router.include_router(notes.router, prefix="/notes", tags=["notes"])
