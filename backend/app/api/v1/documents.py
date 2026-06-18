import os
import uuid
import shutil
import time
from typing import Any, List
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, BackgroundTasks, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
import aiofiles

from app.core.database import get_db, SessionLocal
from app.api.v1.auth import get_current_active_user, get_current_admin_user
from app.models.auth import User

from app.models.knowledge import KnowledgeBase, Document, DocumentChunk
from app.schemas.knowledge import DocumentResponse, DocumentChunkResponse
from app.services.parser import document_parser
from app.services.indexer import document_indexer
from app.core.logging import logger
from app.worker import process_document_task, queue_name

router = APIRouter()

# Permanent directory to store documents (inside the workspace)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Background task to parse, chunk, and index the document
async def process_document_background(
    doc_id: uuid.UUID, 
    file_path: str, 
    filename: str, 
    chunk_size: int = 1000, 
    chunk_overlap: int = 200
):
    logger.info(f"Background Task: Starting indexing pipeline for document {filename} ({doc_id})...")
    # We must open a separate DB session for background task since the request session might be closed
    async with SessionLocal() as db:
        try:
            # Step 1: Parse the document
            parsed_pages = await document_parser.parse_file(file_path, filename)
            
            # Step 2: Index in Qdrant and PostgreSQL
            await document_indexer.index_document(db, doc_id, parsed_pages, chunk_size, chunk_overlap)
            
        except Exception as e:
            logger.error(f"Background Task Error: Failed to index document {filename}: {str(e)}")
            # Mark document as failed
            result = await db.execute(select(Document).where(Document.id == doc_id))
            doc = result.scalar_one_or_none()
            if doc:
                doc.status = "failed"
                doc.meta_info = {
                    **(doc.meta_info or {}),
                    "error_msg": str(e),
                    "failed_at": time.strftime("%Y-%m-%d %H:%M:%S") if 'time' in globals() else "now"
                }
                await db.commit()


@router.post("/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    kb_id: str = Form(...),
    file: UploadFile = File(...),
    chunk_size: int = Form(1000),
    chunk_overlap: int = Form(200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    # Convert kb_id
    try:
        kb_uuid = uuid.UUID(kb_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid Knowledge Base ID format.")

    # 1. Verify user owns the knowledge base
    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_uuid,
            KnowledgeBase.user_id == current_user.id
        )
    )
    kb = result.scalar_one_or_none()
    if not kb:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge base not found or access denied."
        )

    # 2. Verify file extension
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in [".pdf", ".docx", ".txt", ".csv"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type '{ext}'. Allowed: .pdf, .docx, .txt, .csv"
        )

    # 3. Save file to permanent uploads directory
    doc_id = uuid.uuid4()
    save_filename = f"{doc_id}{ext}"
    dest_path = os.path.join(UPLOAD_DIR, save_filename)
    
    try:
        async with aiofiles.open(dest_path, "wb") as buffer:
            while content := await file.read(1024 * 1024):  # 1MB chunks
                await buffer.write(content)
    except Exception as e:
        logger.error(f"Failed to save file locally: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to save uploaded file.")

    # 4. Create Document record in PostgreSQL with status 'processing'
    db_doc = Document(
        id=doc_id,
        kb_id=kb_uuid,
        filename=file.filename,
        file_type=ext.replace(".", "").upper(),
        file_size=os.path.getsize(dest_path),
        status="processing",
        meta_info={
            "local_path": dest_path,
            "original_filename": file.filename,
            "upload_date": time.strftime("%Y-%m-%d %H:%M:%S") if 'time' in globals() else "now"
        }
    )
    db.add(db_doc)
    await db.commit()
    await db.refresh(db_doc)

    # 5. Delegate processing to Celery background task
    process_document_task.apply_async(
        args=[
            str(db_doc.id),
            dest_path,
            file.filename,
            chunk_size,
            chunk_overlap
        ],
        queue=queue_name
    )

    return db_doc


@router.get("/{kb_id}", response_model=List[DocumentResponse])
async def list_documents(
    kb_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    # Verify KB ownership
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
            detail="Knowledge base not found or access denied."
        )

    # Get documents
    doc_result = await db.execute(
        select(Document).where(Document.kb_id == kb_id).order_by(Document.created_at.desc())
    )
    return doc_result.scalars().all()


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    doc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    # Fetch document and verify ownership via KB relation
    result = await db.execute(
        select(Document)
        .join(KnowledgeBase, KnowledgeBase.id == Document.kb_id)
        .where(
            Document.id == doc_id,
            KnowledgeBase.user_id == current_user.id
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found or access denied."
        )

    # Delete local file if exists
    local_path = doc.meta_info.get("local_path") if doc.meta_info else None
    if local_path and os.path.exists(local_path):
        try:
            os.remove(local_path)
        except Exception as e:
            logger.error(f"Error removing local file {local_path}: {str(e)}")

    # Use indexer to delete from PostgreSQL and Qdrant
    await document_indexer.delete_document(db, doc_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{doc_id}/reindex", response_model=DocumentResponse)
async def reindex_document(
    doc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    # Fetch document and verify ownership
    result = await db.execute(
        select(Document)
        .join(KnowledgeBase, KnowledgeBase.id == Document.kb_id)
        .where(
            Document.id == doc_id,
            KnowledgeBase.user_id == current_user.id
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found or access denied."
        )

    local_path = doc.meta_info.get("local_path") if doc.meta_info else None
    if not local_path or not os.path.exists(local_path):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Source document file could not be found locally for reindexing. Please re-upload."
        )

    # 1. Clear old chunks from PostgreSQL and vectors from Qdrant
    # We do a partial reset: delete chunks first
    from sqlalchemy import delete
    from app.models.knowledge import DocumentChunk
    await db.execute(delete(DocumentChunk).where(DocumentChunk.doc_id == doc_id))
    
    # Delete from Qdrant
    collection_name = f"kb_{str(doc.kb_id).replace('-', '_')}"
    try:
        from qdrant_client.http import models as qmodels
        document_indexer.qclient.delete(
            collection_name=collection_name,
            points_selector=qmodels.FilterSelector(
                filter=qmodels.Filter(
                    must=[
                        qmodels.FieldCondition(
                            key="doc_id",
                            match=qmodels.MatchValue(value=str(doc_id))
                        )
                    ]
                )
            )
        )
    except Exception as e:
        logger.error(f"Failed to clear Qdrant during reindex: {str(e)}")

    # Update document status to processing
    doc.status = "processing"
    await db.commit()
    await db.refresh(doc)

    # Start indexing in background via Celery
    process_document_task.apply_async(
        args=[
            str(doc.id),
            local_path,
            doc.filename
        ],
        queue=queue_name
    )

    return doc


@router.get("/admin/all")
async def admin_list_all_documents(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user)
) -> Any:
    """
    Retrieve all documents globally. Restricted to admin.
    """
    result = await db.execute(
        select(Document)
        .options(selectinload(Document.chunks), selectinload(Document.knowledge_base))
        .order_by(Document.created_at.desc())
    )
    docs = result.scalars().all()
    
    response_data = []
    for doc in docs:
        response_data.append({
            "id": str(doc.id),
            "kb_id": str(doc.kb_id),
            "kb_name": doc.knowledge_base.name if doc.knowledge_base else "Unknown",
            "filename": doc.filename,
            "file_type": doc.file_type,
            "file_size": doc.file_size,
            "status": doc.status,
            "chunk_count": len(doc.chunks),
            "created_at": doc.created_at
        })
    return response_data


@router.delete("/admin/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete_document(
    doc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user)
):
    """
    Delete any document globally. Restricted to admin.
    """
    result = await db.execute(select(Document).where(Document.id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
        
    local_path = doc.meta_info.get("local_path") if doc.meta_info else None
    if local_path and os.path.exists(local_path):
        try:
            os.remove(local_path)
        except Exception as e:
            logger.error(f"Error removing local file {local_path}: {str(e)}")

    await document_indexer.delete_document(db, doc_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/admin/{doc_id}/reindex")
async def admin_reindex_document(
    doc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user)
) -> Any:
    """
    Trigger reindexing for any document globally. Restricted to admin.
    """
    result = await db.execute(select(Document).where(Document.id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    local_path = doc.meta_info.get("local_path") if doc.meta_info else None
    if not local_path or not os.path.exists(local_path):
        raise HTTPException(
            status_code=400,
            detail="Source document file could not be found locally for reindexing."
        )

    # Clear old chunks from PostgreSQL
    from sqlalchemy import delete
    from app.models.knowledge import DocumentChunk
    await db.execute(delete(DocumentChunk).where(DocumentChunk.doc_id == doc_id))
    
    # Delete from Qdrant
    collection_name = f"kb_{str(doc.kb_id).replace('-', '_')}"
    try:
        from qdrant_client.http import models as qmodels
        document_indexer.qclient.delete(
            collection_name=collection_name,
            points_selector=qmodels.FilterSelector(
                filter=qmodels.Filter(
                    must=[
                        qmodels.FieldCondition(
                            key="doc_id",
                            match=qmodels.MatchValue(value=str(doc_id))
                        )
                    ]
                )
            )
        )
    except Exception as e:
        logger.error(f"Failed to clear Qdrant during reindex: {str(e)}")

    doc.status = "processing"
    await db.commit()
    await db.refresh(doc)

    process_document_task.apply_async(
        args=[
            str(doc.id),
            local_path,
            doc.filename
        ],
        queue=queue_name
    )

    return {"status": "success", "message": "Reindexing scheduled successfully."}


@router.get("/{doc_id}/chunks", response_model=List[DocumentChunkResponse])
async def list_document_chunks(
    doc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """
    Retrieve all chunks belonging to a specific document.
    """
    # Fetch document and verify user ownership of the parent KB
    result = await db.execute(
        select(Document)
        .join(KnowledgeBase, KnowledgeBase.id == Document.kb_id)
        .where(
            Document.id == doc_id,
            KnowledgeBase.user_id == current_user.id
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        # Check if the user is admin (admin should also be allowed to view all chunks)
        if current_user.role == "admin":
            result = await db.execute(select(Document).where(Document.id == doc_id))
            doc = result.scalar_one_or_none()
            
        if not doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found or access denied."
            )
            
    chunk_res = await db.execute(
        select(DocumentChunk)
        .where(DocumentChunk.doc_id == doc_id)
        .order_by(DocumentChunk.chunk_index.asc())
    )
    return chunk_res.scalars().all()


@router.get("/kb/{kb_id}/guide")
async def generate_kb_guide(
    kb_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """
    Generate an automatic briefing guide, FAQ list, and terms glossary for a knowledge base.
    """
    # 1. Verify KB ownership or admin access
    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.user_id == current_user.id
        )
    )
    kb = result.scalar_one_or_none()
    if not kb:
        if current_user.role == "admin":
            result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id))
            kb = result.scalar_one_or_none()
            
        if not kb:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Knowledge base not found or access denied."
            )

    # 2. Fetch representative chunks
    chunk_res = await db.execute(
        select(DocumentChunk.content, Document.filename)
        .join(Document, Document.id == DocumentChunk.doc_id)
        .where(Document.kb_id == kb_id)
        .order_by(DocumentChunk.chunk_index.asc())
        .limit(20)
    )
    rows = chunk_res.all()
    if not rows:
        return {
            "summary": "This Knowledge Base is currently empty. Upload documents to generate a guide.",
            "faqs": [],
            "key_terms": []
        }

    corpus_text = "\n\n".join([f"Source [{row[1]}]: {row[0]}" for row in rows])

    # 3. Define prompt & call LLM
    system_prompt = (
        "You are an expert document analyst. You will be provided with some core sections of a Knowledge Base. "
        "Your task is to analyze these sources and generate a structured JSON document containing:\n"
        "1. 'summary': A high-level briefing/summary of what these documents are about, their main subjects, and key insights (2-3 paragraphs).\n"
        "2. 'key_terms': A list of up to 5 key terms, acronyms, or concepts defined in the text, formatted as a list of dicts with 'term' and 'definition'.\n"
        "3. 'faqs': A list of 5-8 Frequently Asked Questions (FAQs) that users might ask about this corpus, with concise answers, formatted as a list of dicts with 'question' and 'answer'.\n\n"
        "Respond ONLY with a valid JSON object matching this schema. Do not write any markdown code blocks, explanations, or text outside the JSON."
    )

    import openai
    import json
    from app.core.config import settings

    guide_data = None
    if settings.GEMINI_API_KEY or settings.OPENAI_API_KEY:
        try:
            if settings.GEMINI_API_KEY:
                client = openai.AsyncOpenAI(
                    api_key=settings.GEMINI_API_KEY,
                    base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
                )
                model_name = settings.GEMINI_MODEL
            else:
                client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
                model_name = "gpt-4o"

            completion = await client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": corpus_text[:15000]}
                ],
                response_format={"type": "json_object"},
                temperature=0.3
            )
            raw_content = completion.choices[0].message.content
            if raw_content.startswith("```json"):
                raw_content = raw_content.replace("```json", "").replace("```", "").strip()
            elif raw_content.startswith("```"):
                raw_content = raw_content.replace("```", "").strip()

            guide_data = json.loads(raw_content)
        except Exception as e:
            logger.error(f"Failed to generate KB guide with LLM: {str(e)}")

    if not guide_data:
        # Fallback generator
        doc_res = await db.execute(
            select(Document.filename).where(Document.kb_id == kb_id)
        )
        filenames = [r[0] for r in doc_res.all()]
        files_str = ", ".join(filenames) if filenames else "No documents uploaded"
        guide_data = {
            "summary": f"This Knowledge Base contains the following files: {files_str}. The search engine has chunked and indexed these documents to enable semantic RAG query retrieval.",
            "key_terms": [
                {"term": "Hybrid Search", "definition": "Combines dense semantic vector retrieval (Qdrant) and sparse keyword match (BM25) for high-precision retrieval."},
                {"term": "Reranking", "definition": "A secondary ranking phase utilizing a CrossEncoder (BGE Reranker) to evaluate the exact similarity score between query and retrieved chunks."}
            ],
            "faqs": [
                {"question": "What files are indexed in this knowledge base?", "answer": f"The indexed files include: {files_str}."},
                {"question": "How do I query this knowledge base?", "answer": "You can launch the Chat Console from the sidebar and submit queries directly to the AI assistant."}
            ]
        }

    return guide_data

