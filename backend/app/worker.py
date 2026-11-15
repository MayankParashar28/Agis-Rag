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
                          redis_key: str = None, storage_key: str = None):
    from app.services.ingest import process_document
    run_async(process_document, doc_id_str, file_path, filename, chunk_size, chunk_overlap,
              redis_key=redis_key, storage_key=storage_key, in_worker=True)
