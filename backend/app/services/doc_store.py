"""Redis hand-off store for uploaded documents.

The API stages an uploaded file's bytes in Redis and hands the key to the
Celery worker. The worker takes the bytes out with a single atomic
read-and-delete, so once the hand-off is complete nothing of the document is
left in Redis. A TTL is set on every staged key as a safety net: if a worker
never picks the job up, the bytes still expire on their own instead of
piling up.

This uses a synchronous, binary-safe client on purpose:
- the shared async client in ``app.core.redis_client`` decodes responses to
  ``str``, which would corrupt PDF/DOCX bytes;
- the Celery task runs each job in its own event loop, and a sync client has
  no event-loop affinity, so it works the same in the API and the worker.
The API calls it through ``asyncio.to_thread`` so the event loop never blocks.
"""
from __future__ import annotations

import os
import tempfile
from typing import Optional

import redis

from app.core.config import settings
from app.core.logging import logger

KEY_PREFIX = "doc:handover:"

_client: Optional[redis.Redis] = None


def _redis_url() -> str:
    url = settings.REDIS_URL
    # Managed Redis (e.g. Upstash) uses rediss:// - mirror the Celery config,
    # which also skips certificate verification for these URLs.
    if url.startswith("rediss://") and "ssl_cert_reqs" not in url:
        url += ("&" if "?" in url else "?") + "ssl_cert_reqs=none"
    return url


def get_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(
            _redis_url(),
            decode_responses=False,  # raw bytes: documents are binary
            socket_timeout=30,
            socket_connect_timeout=30,
            health_check_interval=30,
        )
    return _client


def reset_client() -> None:
    """Drop the cached client (used after a process fork in the worker)."""
    global _client
    _client = None


def handover_key(doc_id: str) -> str:
    return f"{KEY_PREFIX}{doc_id}"


def stage_document(doc_id: str, file_path: str) -> Optional[str]:
    """Copy a file's bytes into Redis for the worker. Returns the key, or None.

    Returning None (instead of raising) lets the caller fall back to handing
    the worker the file path, so an unreachable or size-limited Redis never
    blocks an upload.
    """
    key = handover_key(doc_id)
    try:
        with open(file_path, "rb") as f:
            data = f.read()
        get_client().set(key, data, ex=settings.DOC_HANDOVER_TTL_SECONDS)
        logger.info(f"Staged document {doc_id} in Redis ({len(data)} bytes, key={key}).")
        return key
    except Exception as e:
        logger.warning(f"Could not stage document {doc_id} in Redis, worker will use the file path: {e}")
        return None


def take_document(key: str) -> Optional[bytes]:
    """Atomically read and delete a staged document. None if it is gone.

    GET and DEL run in one MULTI/EXEC transaction, so two workers can never
    both receive the same document and the key is removed in the same step it
    is handed over. (Equivalent to GETDEL, but also works on Redis < 6.2.)
    """
    pipe = get_client().pipeline(transaction=True)
    pipe.get(key)
    pipe.delete(key)
    data, _ = pipe.execute()
    return data


def discard_document(key: str) -> None:
    """Remove a staged document without reading it (cleanup on any path)."""
    try:
        get_client().delete(key)
    except Exception as e:
        logger.warning(f"Failed to delete Redis hand-off key {key}: {e}")


def count_staged() -> int:
    """How many documents are currently waiting in Redis for a worker."""
    count = 0
    for _ in get_client().scan_iter(match=f"{KEY_PREFIX}*", count=500):
        count += 1
    return count


def write_temp_file(data: bytes, filename: str) -> str:
    """Write handed-over bytes to a temp file the parsers can open by path.

    Keeps the original extension, since the parser picks its strategy from it.
    """
    ext = os.path.splitext(filename)[1].lower()
    fd, path = tempfile.mkstemp(prefix="aegis_doc_", suffix=ext)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return path
