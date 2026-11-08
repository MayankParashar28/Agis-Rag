import os
import uuid
import asyncio
import hashlib
import mimetypes
import shutil
import time
from typing import Any, List
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, BackgroundTasks, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel
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
from app.services import doc_store, progress
from app.services.url_import import fetch_url, safe_filename, UrlImportError
from app.core.logging import logger
from app.core.config import settings
from app.worker import process_document_task, queue_name

router = APIRouter()

# Permanent directory to store documents (inside the workspace)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

async def _dispatch_processing(doc_id: str, file_path: str, filename: str,
                               chunk_size: int, chunk_overlap: int) -> None:
    """Stage the document in Redis and queue the Celery job that consumes it.

    The worker reads the bytes from Redis (so it does not need to share a disk
    with the API) and deletes the key in the same atomic step. If Redis cannot
    take the file, the job still carries the file path as a fallback.
    """
    redis_key = await asyncio.to_thread(doc_store.stage_document, doc_id, file_path)
    await asyncio.to_thread(progress.report, doc_id, "queued")
    try:
        process_document_task.apply_async(
            args=[doc_id, file_path, filename, chunk_size, chunk_overlap],
            kwargs={"redis_key": redis_key},
            queue=queue_name,
        )
    except Exception:
        # The job never reached the queue: do not leave the bytes in Redis.
        if redis_key:
            await asyncio.to_thread(doc_store.discard_document, redis_key)
        raise


async def _find_duplicate(db: AsyncSession, kb_id: uuid.UUID, sha256: str):
    """An existing document in this KB with identical bytes, if any."""
    rows = await db.execute(select(Document).where(Document.kb_id == kb_id))
    for existing in rows.scalars().all():
        if (existing.meta_info or {}).get("sha256") == sha256 and existing.status != "failed":
            return existing
    return None


async def _get_accessible_doc(db: AsyncSession, doc_id: uuid.UUID, user: User) -> Document:
    """A document the user owns (via its KB), or any document for an admin."""
    query = select(Document).where(Document.id == doc_id)
    if user.role != "admin":
        query = query.join(KnowledgeBase, KnowledgeBase.id == Document.kb_id).where(
            KnowledgeBase.user_id == user.id)
    doc = (await db.execute(query)).scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found or access denied.")
    return doc


async def _get_owned_kb(db: AsyncSession, kb_id: uuid.UUID, user: User) -> KnowledgeBase:
    kb = (await db.execute(select(KnowledgeBase).where(
        KnowledgeBase.id == kb_id, KnowledgeBase.user_id == user.id))).scalar_one_or_none()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found or access denied.")
    return kb


async def _create_and_dispatch(db: AsyncSession, kb_id: uuid.UUID, doc_id: uuid.UUID, dest_path: str,
                               filename: str, ext: str, sha256: str, chunk_size: int,
                               chunk_overlap: int, extra_meta: dict | None = None) -> Document:
    db_doc = Document(
        id=doc_id,
        kb_id=kb_id,
        filename=filename,
        file_type=ext.replace(".", "").upper(),
        file_size=os.path.getsize(dest_path),
        status="processing",
        meta_info={
            "local_path": dest_path,
            "original_filename": filename,
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
            "sha256": sha256,
            "upload_date": time.strftime("%Y-%m-%d %H:%M:%S"),
            **(extra_meta or {}),
        }
    )
    db.add(db_doc)
    await db.commit()
    await db.refresh(db_doc)
    # Stage the file in Redis and hand it to the Celery worker. The worker
    # deletes the Redis copy as soon as it takes it.
    await _dispatch_processing(str(db_doc.id), dest_path, filename, chunk_size, chunk_overlap)
    return db_doc


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
    chunk_size: int = Form(settings.DEFAULT_CHUNK_SIZE),
    chunk_overlap: int = Form(settings.DEFAULT_CHUNK_OVERLAP),
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

    # 2b. Enforce max file size (50 MB)
    MAX_FILE_SIZE_BYTES = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    # Read file size from content-length header or by seeking
    if file.size and file.size > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Maximum allowed size is {settings.MAX_UPLOAD_SIZE_MB} MB."
        )

    # 2c. Validate content-type matches extension to prevent disguised uploads
    ALLOWED_CONTENT_TYPES = {
        ".pdf": ["application/pdf"],
        ".docx": ["application/vnd.openxmlformats-officedocument.wordprocessingml.document"],
        ".txt": ["text/plain", "application/octet-stream"],
        ".csv": ["text/csv", "text/plain", "application/octet-stream"],
    }
    if file.content_type and file.content_type not in ALLOWED_CONTENT_TYPES.get(ext, []):
        logger.warning(f"Upload content-type mismatch: ext={ext}, content_type={file.content_type}, filename={file.filename}")
        # Allow it with a warning rather than blocking (browsers are inconsistent with MIME detection)

    # 3. Save file to permanent uploads directory, hashing as we go and
    #    enforcing the size cap even when the client sent no Content-Length.
    doc_id = uuid.uuid4()
    save_filename = f"{doc_id}{ext}"
    dest_path = os.path.join(UPLOAD_DIR, save_filename)
    hasher = hashlib.sha256()
    written = 0
    try:
        async with aiofiles.open(dest_path, "wb") as buffer:
            while content := await file.read(1024 * 1024):  # 1MB chunks
                written += len(content)
                if written > MAX_FILE_SIZE_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"File too large. Maximum allowed size is {settings.MAX_UPLOAD_SIZE_MB} MB."
                    )
                hasher.update(content)
                await buffer.write(content)
    except HTTPException:
        if os.path.exists(dest_path):
            os.remove(dest_path)
        raise
    except Exception as e:
        logger.error(f"Failed to save file locally: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to save uploaded file.")

    # 3b. Skip exact duplicates: same bytes already indexed in this KB.
    sha256 = hasher.hexdigest()
    duplicate = await _find_duplicate(db, kb_uuid, sha256)
    if duplicate:
        os.remove(dest_path)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This file is already in the knowledge base as '{duplicate.filename}'."
        )

    # 4. Create the Document record and hand it to the worker.
    return await _create_and_dispatch(
        db, kb_uuid, doc_id, dest_path, file.filename, ext, sha256, chunk_size, chunk_overlap)


class UrlImportRequest(BaseModel):
    kb_id: uuid.UUID
    url: str
    chunk_size: int = settings.DEFAULT_CHUNK_SIZE
    chunk_overlap: int = settings.DEFAULT_CHUNK_OVERLAP


@router.post("/import-url", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def import_from_url(
    body: UrlImportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """Index a web page (or a linked PDF/DOCX/CSV/text file) by URL."""
    await _get_owned_kb(db, body.kb_id, current_user)
    try:
        fetched = await fetch_url(body.url, settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024)
    except UrlImportError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.warning(f"URL import failed for {body.url}: {e}")
        raise HTTPException(status_code=400, detail="Could not download that link. Check the address and try again.")

    sha256 = hashlib.sha256(fetched.content).hexdigest()
    duplicate = await _find_duplicate(db, body.kb_id, sha256)
    if duplicate:
        raise HTTPException(status_code=409, detail=f"This page is already in the knowledge base as '{duplicate.filename}'.")

    doc_id = uuid.uuid4()
    dest_path = os.path.join(UPLOAD_DIR, f"{doc_id}{fetched.ext}")
    async with aiofiles.open(dest_path, "wb") as f:
        await f.write(fetched.content)
    filename = safe_filename(fetched.title, fetched.final_url, fetched.ext)
    return await _create_and_dispatch(
        db, body.kb_id, doc_id, dest_path, filename, fetched.ext, sha256,
        body.chunk_size, body.chunk_overlap, {"source_url": fetched.final_url})


@router.get("/kb/{kb_id}/progress")
async def kb_indexing_progress(
    kb_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """Live progress for every document in the KB that is still processing
    (or just finished). Cheap enough to poll every second or two."""
    await _get_owned_kb(db, kb_id, current_user)
    rows = await db.execute(select(Document.id, Document.status).where(Document.kb_id == kb_id))
    docs = rows.all()
    live = await asyncio.to_thread(progress.get_many, [str(d[0]) for d in docs])
    out = {}
    for doc_id, doc_status in docs:
        key = str(doc_id)
        # Only real records: with none, the UI shows an honest "Indexing…"
        # instead of a made-up percentage.
        if key in live:
            out[key] = {**live[key], "status": doc_status}
    return out


@router.get("/{doc_id}/file")
async def download_document_file(
    doc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Serve the original file inline, so a citation can open it at its page."""
    doc = await _get_accessible_doc(db, doc_id, current_user)
    local_path = (doc.meta_info or {}).get("local_path")
    if not local_path or not os.path.exists(local_path):
        raise HTTPException(status_code=404, detail="The original file is no longer stored on the server.")
    media_type = mimetypes.guess_type(local_path)[0] or "application/octet-stream"
    if media_type.startswith("text/"):
        media_type += "; charset=utf-8"
    return FileResponse(local_path, media_type=media_type, filename=doc.filename,
                        content_disposition_type="inline",
                        headers={"Cache-Control": "private, max-age=3600"})


@router.get("/chunks/{chunk_id}/context")
async def chunk_context(
    chunk_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """A cited passage plus its neighbours, for the citation viewer."""
    chunk = (await db.execute(select(DocumentChunk).where(DocumentChunk.id == chunk_id))).scalar_one_or_none()
    if not chunk:
        raise HTTPException(status_code=404, detail="That passage no longer exists (the document may have been re-indexed).")
    doc = await _get_accessible_doc(db, chunk.doc_id, current_user)
    neighbours = []
    if chunk.chunk_index is not None:
        rows = await db.execute(
            select(DocumentChunk.chunk_index, DocumentChunk.content)
            .where(DocumentChunk.doc_id == doc.id,
                   DocumentChunk.chunk_index.in_([chunk.chunk_index - 1, chunk.chunk_index + 1]))
        )
        neighbours = {r[0]: r[1] for r in rows.all()}
    meta = doc.meta_info or {}
    local_path = meta.get("local_path")
    return {
        "chunk": {"id": str(chunk.id), "content": chunk.content, "page_number": chunk.page_number,
                  "chunk_index": chunk.chunk_index},
        "before": neighbours.get(chunk.chunk_index - 1) if neighbours else None,
        "after": neighbours.get(chunk.chunk_index + 1) if neighbours else None,
        "document": {"id": str(doc.id), "kb_id": str(doc.kb_id), "filename": doc.filename,
                     "file_type": doc.file_type, "source_url": meta.get("source_url"),
                     "has_file": bool(local_path and os.path.exists(local_path))},
    }


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
    await asyncio.to_thread(progress.clear, str(doc_id))
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
    # Reuse the chunk settings chosen at upload time instead of silently
    # falling back to the task's 1000/200 defaults.
    meta = doc.meta_info or {}
    await _dispatch_processing(
        str(doc.id),
        local_path,
        doc.filename,
        meta.get("chunk_size", settings.DEFAULT_CHUNK_SIZE),
        meta.get("chunk_overlap", settings.DEFAULT_CHUNK_OVERLAP),
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

    # Reuse the chunk settings chosen at upload time instead of silently
    # falling back to the task's 1000/200 defaults.
    meta = doc.meta_info or {}
    await _dispatch_processing(
        str(doc.id),
        local_path,
        doc.filename,
        meta.get("chunk_size", settings.DEFAULT_CHUNK_SIZE),
        meta.get("chunk_overlap", settings.DEFAULT_CHUNK_OVERLAP),
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
                model_name = settings.OPENAI_MODEL

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

