import uuid
from typing import Any, List
from fastapi import APIRouter, Depends, HTTPException, status, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.api.v1.auth import get_current_active_user
from app.models.auth import User
from app.models.knowledge import KnowledgeBase, Document, DocumentChunk
from app.schemas.knowledge import KnowledgeBaseCreate, KnowledgeBaseResponse, KnowledgeBaseStats

router = APIRouter()

@router.get("", response_model=List[KnowledgeBaseResponse])
async def list_knowledge_bases(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    result = await db.execute(
        select(KnowledgeBase).where(KnowledgeBase.user_id == current_user.id)
    )
    return result.scalars().all()


@router.post("", response_model=KnowledgeBaseResponse, status_code=status.HTTP_201_CREATED)
async def create_knowledge_base(
    kb_in: KnowledgeBaseCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    db_obj = KnowledgeBase(
        name=kb_in.name,
        description=kb_in.description,
        embedding_model=kb_in.embedding_model or "BAAI/bge-large-en-v1.5",
        user_id=current_user.id
    )
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj


@router.delete("/{kb_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_knowledge_base(
    kb_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.user_id == current_user.id
        )
    )
    kb = result.scalar_one_or_none()
    if not kb:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge base not found"
        )
    
    # Delete from DB (associated documents and chunks are deleted cascade)
    await db.delete(kb)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{kb_id}/stats", response_model=KnowledgeBaseStats)
async def get_knowledge_base_stats(
    kb_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    # Verify ownership
    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.user_id == current_user.id
        )
    )
    kb = result.scalar_one_or_none()
    if not kb:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge base not found"
        )
    
    # Count total documents
    doc_count_res = await db.execute(
        select(func.count(Document.id)).where(Document.kb_id == kb_id)
    )
    total_docs = doc_count_res.scalar() or 0
    
    # Count total chunks
    chunk_count_res = await db.execute(
        select(func.count(DocumentChunk.id))
        .join(Document, Document.id == DocumentChunk.doc_id)
        .where(Document.kb_id == kb_id)
    )
    total_chunks = chunk_count_res.scalar() or 0
    
    # Last indexed date
    last_indexed_res = await db.execute(
        select(func.max(Document.updated_at)).where(Document.kb_id == kb_id)
    )
    last_indexed = last_indexed_res.scalar()
    
    return {
        "total_documents": total_docs,
        "total_chunks": total_chunks,
        "embedding_model": kb.embedding_model,
        "vector_count": total_chunks,  # Each chunk has 1 vector in Qdrant
        "last_indexed_date": last_indexed
    }
