"""The document indexing job, shared by both execution modes.

- ``celery`` (docker-compose): the API stages the file in Redis and a Celery
  worker process runs this job.
- ``inprocess`` (Hugging Face Spaces and other single-container hosts): the
  API runs this job itself as a background task. No broker, no second copy of
  the embedding model, and nothing is lost when Redis is unreachable.
"""
from __future__ import annotations

import asyncio
import os
import time
import uuid
from typing import Optional, Set

from app.core.config import settings
from app.core.logging import logger


async def process_document(doc_id_str: str, file_path: Optional[str], filename: str,
                           chunk_size: Optional[int] = None, chunk_overlap: Optional[int] = None,
                           redis_key: Optional[str] = None, storage_key: Optional[str] = None,
                           in_worker: bool = False) -> None:
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models.knowledge import Document
    from app.services import doc_store, progress
    from app.services.indexer import document_indexer
    from app.services.parser import document_parser

    chunk_size = settings.DEFAULT_CHUNK_SIZE if chunk_size is None else chunk_size
    chunk_overlap = settings.DEFAULT_CHUNK_OVERLAP if chunk_overlap is None else chunk_overlap
    doc_id = uuid.UUID(doc_id_str)

    if in_worker:
        # A forked Celery child must not reuse connections inherited from the
        # parent. Never do this in the API process: it would pull the pool out
        # from under requests in flight.
        from app.core.database import engine
        engine.pool = engine.pool.recreate()

    async def mark_failed(message: str) -> None:
        progress.report(doc_id_str, "failed", message=message)
        # A fresh session: the one that failed may hold a broken connection.
        try:
            async with SessionLocal() as db:
                doc = (await db.execute(select(Document).where(Document.id == doc_id))).scalar_one_or_none()
                if doc:
                    doc.status = "failed"
                    doc.meta_info = {**(doc.meta_info or {}), "error_msg": message[:400],
                                     "failed_at": time.strftime("%Y-%m-%d %H:%M:%S")}
                    await db.commit()
        except Exception as e:
            logger.error(f"Could not mark {doc_id_str} as failed: {e}")

    progress.report(doc_id_str, "receiving")
    source_path = file_path
    temp_path = None
    try:
        # Step 0: take the bytes out of Redis (worker mode). GET+DEL is one
        # atomic step, so the Redis copy is gone the moment we have them.
        if redis_key:
            try:
                data = await asyncio.to_thread(doc_store.take_document, redis_key)
                if data is not None:
                    temp_path = await asyncio.to_thread(doc_store.write_temp_file, data, filename)
                    source_path = temp_path
                    logger.info(f"Took document {doc_id_str} from Redis ({len(data)} bytes); key deleted.")
                else:
                    logger.warning(f"Redis key {redis_key} missing; falling back to {file_path}.")
            except Exception as e:
                logger.warning(f"Could not read {redis_key} from Redis ({e}); falling back to {file_path}.")
                await asyncio.to_thread(doc_store.discard_document, redis_key)

        # Fall back to object storage (a worker on another machine, a file too
        # big for Redis, or a re-index after the local copy was wiped).
        if (not source_path or not os.path.exists(source_path)) and storage_key:
            from app.services import storage as object_storage
            fetched = await object_storage.fetch_to_temp(storage_key, os.path.splitext(filename)[1])
            if fetched:
                temp_path = source_path = fetched
                logger.info(f"Fetched {doc_id_str} from object storage ({storage_key}).")

        try:
            if not source_path or not os.path.exists(source_path):
                raise FileNotFoundError("The uploaded file was not found in Redis, on disk, or in object storage.")
            progress.report(doc_id_str, "parsing")
            parsed_pages = await document_parser.parse_file(source_path, filename)
        except Exception as e:
            await mark_failed(f"Parsing failed: {getattr(e, 'detail', None) or str(e) or type(e).__name__}")
            raise

        # Step 1b: summary + keywords (LLM, or a local heuristic).
        progress.report(doc_id_str, "summarizing")
        try:
            from app.services.summarizer import summarize_document
            full_text = "\n\n".join((p.get("content") or "") for p in parsed_pages)
            doc_summary = await summarize_document(filename, full_text)
        except Exception as e:
            logger.warning(f"Summary skipped for {doc_id_str}: {e}")
            doc_summary = None

        # Step 2: chunk, embed, store in Qdrant and Postgres.
        try:
            async with SessionLocal() as db:
                await document_indexer.index_document(db, doc_id, parsed_pages, chunk_size, chunk_overlap,
                                                      doc_summary=doc_summary)
        except Exception as e:
            await mark_failed(f"Indexing failed: {str(e)[:300]}")
            raise
    finally:
        # The temp copy only existed for the parser; never leave it on disk.
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# In-process mode
# ---------------------------------------------------------------------------
_running: Set[asyncio.Task] = set()
_slot: Optional[asyncio.Semaphore] = None


def _semaphore() -> asyncio.Semaphore:
    # One document at a time: embedding is CPU-heavy, and parallel jobs would
    # only slow the API and multiply peak memory.
    global _slot
    if _slot is None:
        _slot = asyncio.Semaphore(1)
    return _slot


def submit_inprocess(doc_id_str: str, file_path: str, filename: str, chunk_size: int, chunk_overlap: int,
                     storage_key: Optional[str] = None) -> None:
    async def _run():
        async with _semaphore():
            try:
                await process_document(doc_id_str, file_path, filename, chunk_size, chunk_overlap,
                                       storage_key=storage_key, in_worker=False)
            except Exception as e:
                # Already recorded on the document; keep the server running.
                logger.error(f"In-process indexing of {doc_id_str} failed: {e}")

    task = asyncio.get_running_loop().create_task(_run())
    _running.add(task)  # keep a reference so the task is not garbage-collected
    task.add_done_callback(_running.discard)


def queued_inprocess() -> int:
    return len(_running)


def is_inprocess() -> bool:
    return settings.INDEXING_MODE == "inprocess"
