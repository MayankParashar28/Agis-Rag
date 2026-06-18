import asyncio
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
    broker_connection_retry_on_startup=True,
    broker_connection_max_retries=None,  # Retry forever on connection loss
    broker_transport_options={
        "socket_timeout": 30,
        "socket_connect_timeout": 30,
        "socket_keepalive": True,
        "retry_on_timeout": True,
        "max_connections": 10,
    },
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
    try:
        return asyncio.run(func(*args, **kwargs))
    except RuntimeError:
        # Fallback if there is already an event loop in this thread
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(func(*args, **kwargs))

@celery_app.task(bind=True, name="process_document_task")
def process_document_task(self, doc_id_str: str, file_path: str, filename: str, chunk_size: int = 1000, chunk_overlap: int = 200):
    import uuid
    from app.core.database import SessionLocal
    from app.services.parser import document_parser
    from app.services.indexer import document_indexer
    from sqlalchemy import select
    from app.models.knowledge import Document
    import time
    
    doc_id = uuid.UUID(doc_id_str)
    
    async def _do_work():
        # Recreate the connection pool to discard inherited connections from the parent process
        from app.core.database import engine
        engine.pool = engine.pool.recreate()
        
        try:
            # Step 1: Parse the file first without keeping a DB connection open
            parsed_pages = await document_parser.parse_file(file_path, filename)
        except Exception as e:
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

    run_async(_do_work)
