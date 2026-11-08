import asyncio
import os
from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "enterprise_rag_worker",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND
)

import platform
is_local = (platform.system() == "Darwin")
queue_name = "local_queue" if is_local else "celery"

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,
    task_default_queue=queue_name,
    # On macOS, Python defaults to the "spawn" start method and Celery's prefork
    # pool then hands its children an empty task registry, so every task dies with
    # "ValueError: not enough values to unpack (expected 3, got 0)". The solo pool
    # sidesteps that, and is also the safe choice next to torch, which is not
    # fork-safe. Linux/containers keep the default prefork pool.
    worker_pool="solo" if is_local else "prefork",
    broker_connection_retry_on_startup=True,
    broker_connection_max_retries=None,  # Retry forever on connection loss
    broker_transport_options={
        "socket_timeout": 30,
        "socket_connect_timeout": 30,
        "socket_keepalive": True,
        "retry_on_timeout": True,
        "max_connections": 10,
    },
    # Keep Redis clean: any task results/state that are stored expire instead
    # of piling up as celery-task-meta-* keys.
    result_expires=settings.CELERY_RESULT_EXPIRES_SECONDS,
    redis_backend_health_check_interval=30,
    result_backend_transport_options={
        "socket_timeout": 30,
        "socket_connect_timeout": 30,
        "socket_keepalive": True,
        "retry_on_timeout": True,
    }
)

# Wrapper to run async functions in Celery
def run_async(func, *args, **kwargs):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(func(*args, **kwargs))
    finally:
        try:
            loop.close()
        except Exception:
            pass

from celery.signals import worker_process_init


@worker_process_init.connect
def _reset_redis_after_fork(**_kwargs):
    # A prefork child must not reuse a socket opened by the parent process.
    from app.services import doc_store
    doc_store.reset_client()


# ignore_result: nothing reads this task's return value (status lives in
# Postgres), so storing it would only leave keys behind in Redis.
@celery_app.task(bind=True, name="process_document_task", ignore_result=True)
def process_document_task(self, doc_id_str: str, file_path: str, filename: str,
                          chunk_size: int = None, chunk_overlap: int = None,
                          redis_key: str = None):
    import uuid
    from app.core.database import SessionLocal
    from app.services.parser import document_parser
    from app.services.indexer import document_indexer
    from sqlalchemy import select
    from app.models.knowledge import Document
    import time
    
    from app.core.config import settings as _settings
    chunk_size = _settings.DEFAULT_CHUNK_SIZE if chunk_size is None else chunk_size
    chunk_overlap = _settings.DEFAULT_CHUNK_OVERLAP if chunk_overlap is None else chunk_overlap

    doc_id = uuid.UUID(doc_id_str)
    
    from app.core.logging import logger
    from app.services import doc_store, progress

    progress.report(doc_id_str, "receiving")

    # Step 0: Take the document out of Redis. GET+DEL is one atomic step, so
    # the moment the worker has the bytes the Redis copy is already gone.
    source_path = file_path
    temp_path = None
    if redis_key:
        try:
            data = doc_store.take_document(redis_key)
            if data is not None:
                temp_path = doc_store.write_temp_file(data, filename)
                source_path = temp_path
                logger.info(f"Worker took document {doc_id_str} from Redis "
                            f"({len(data)} bytes); key {redis_key} deleted.")
            else:
                logger.warning(f"Redis key {redis_key} missing (expired or already taken); "
                               f"falling back to {file_path}.")
        except Exception as e:
            logger.warning(f"Could not read {redis_key} from Redis ({e}); falling back to {file_path}.")
            # Make sure nothing is left behind even if the read failed midway.
            doc_store.discard_document(redis_key)

    async def _do_work():
        # Recreate the connection pool to discard inherited connections from the parent process
        from app.core.database import engine
        engine.pool = engine.pool.recreate()
        
        try:
            if not source_path or not os.path.exists(source_path):
                raise FileNotFoundError(
                    "Document bytes were not found in Redis and the source file is not on this worker's disk."
                )
            # Step 1: Parse the file first without keeping a DB connection open
            progress.report(doc_id_str, "parsing")
            parsed_pages = await document_parser.parse_file(source_path, filename)
        except Exception as e:
            progress.report(doc_id_str, "failed", message=f"Could not read the document: {e}")
            # If parsing fails, open DB session briefly to mark as failed
            async with SessionLocal() as db:
                result = await db.execute(select(Document).where(Document.id == doc_id))
                doc = result.scalar_one_or_none()
                if doc:
                    doc.status = "failed"
                    doc.meta_info = {
                        **(doc.meta_info or {}),
                        "error_msg": f"Parsing failed: {str(e)}",
                        "failed_at": time.strftime("%Y-%m-%d %H:%M:%S")
                    }
                    await db.commit()
            raise e

        # Step 2: Index in Qdrant and update PostgreSQL status
        async with SessionLocal() as db:
            try:
                await document_indexer.index_document(db, doc_id, parsed_pages, chunk_size, chunk_overlap)
            except Exception as e:
                progress.report(doc_id_str, "failed", message=f"Indexing failed: {e}")
                result = await db.execute(select(Document).where(Document.id == doc_id))
                doc = result.scalar_one_or_none()
                if doc:
                    doc.status = "failed"
                    doc.meta_info = {
                        **(doc.meta_info or {}),
                        "error_msg": f"Indexing failed: {str(e)}",
                        "failed_at": time.strftime("%Y-%m-%d %H:%M:%S")
                    }
                    await db.commit()
                raise e

    try:
        run_async(_do_work)
    finally:
        # The temp copy only existed for the parser; never leave it on disk.
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
