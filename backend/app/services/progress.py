"""Live indexing progress, kept in Redis while a document is being processed.

The worker reports each stage (queued -> receiving -> parsing -> chunking ->
embedding -> saving -> done/failed) with a percentage. The API reads it back
so the UI can show a live progress bar.

Redis stays clean on its own: every progress key has a TTL, and once a
document finishes (or fails) the key is shortened to a brief grace period -
long enough for the UI's next poll to see the final state, then it expires.
Postgres `documents.status` remains the source of truth after that.
"""
from __future__ import annotations

import json
import time
from typing import Dict, Iterable, Optional

from app.core.logging import logger
from app.services import doc_store

KEY_PREFIX = "doc:progress:"
ACTIVE_TTL_SECONDS = 3600      # while work is in flight
FINAL_TTL_SECONDS = 120        # after done/failed: just long enough for the UI to see it

# Stage -> where the bar sits when that stage starts. "embedding" fills the
# range up to "saving" batch by batch.
STAGES = {
    "queued": 2,
    "receiving": 5,
    "parsing": 10,
    "summarizing": 25,
    "chunking": 35,
    "embedding": 40,
    "saving": 90,
    "done": 100,
    "failed": 100,
}

STAGE_LABELS = {
    "queued": "Waiting for a worker",
    "receiving": "Receiving document",
    "parsing": "Reading document",
    "summarizing": "Writing summary",
    "chunking": "Splitting into chunks",
    "embedding": "Creating embeddings",
    "saving": "Saving to the index",
    "done": "Indexed",
    "failed": "Failed",
}


def _key(doc_id: str) -> str:
    return f"{KEY_PREFIX}{doc_id}"


# In-process indexing (INDEXING_MODE=inprocess) runs in the API's own process,
# so progress can live in memory: no Redis round trip, and it works even when
# Redis is unreachable. doc_id -> (expires_at, payload)
_local: Dict[str, tuple] = {}


def _use_redis() -> bool:
    from app.core.config import settings
    return settings.INDEXING_MODE != "inprocess"


def _local_put(doc_id: str, payload: dict, ttl: int) -> None:
    now = time.time()
    for k in [k for k, (exp, _) in _local.items() if exp < now]:
        _local.pop(k, None)
    _local[doc_id] = (now + ttl, payload)


def report(doc_id: str, stage: str, percent: Optional[float] = None,
           message: Optional[str] = None, eta_seconds: Optional[float] = None) -> None:
    """Record a document's current stage. Never raises: progress is cosmetic,
    and a Redis hiccup must not fail an indexing job."""
    if percent is None:
        percent = STAGES.get(stage, 0)
    payload = {
        "doc_id": str(doc_id),
        "stage": stage,
        "label": STAGE_LABELS.get(stage, stage),
        "percent": round(max(0.0, min(100.0, float(percent))), 1),
        "message": message,
        "updated_at": time.time(),
    }
    if eta_seconds is not None:
        payload["eta_seconds"] = int(max(0, eta_seconds))
    ttl = FINAL_TTL_SECONDS if stage in ("done", "failed") else ACTIVE_TTL_SECONDS
    if not _use_redis():
        _local_put(str(doc_id), payload, ttl)
        return
    try:
        doc_store.get_client().set(_key(str(doc_id)), json.dumps(payload), ex=ttl)
    except Exception as e:
        # Visible on purpose: without it a stuck progress bar has no explanation.
        logger.warning(f"Could not record indexing progress for {doc_id} ({stage}): {e}")


def embedding_progress(doc_id: str, done: int, total: int, started_at: Optional[float] = None) -> None:
    """Map embedded-batch progress onto the 40-90% band of the bar, with an
    estimate of the time left from the speed so far."""
    if total <= 0:
        return
    start, end = STAGES["embedding"], STAGES["saving"]
    pct = start + (end - start) * (done / total)
    eta = None
    if started_at and 0 < done < total:
        eta = (time.time() - started_at) / done * (total - done)
    report(doc_id, "embedding", pct, f"{done}/{total} chunks embedded", eta_seconds=eta)


def get_many(doc_ids: Iterable[str]) -> Dict[str, dict]:
    """Return {doc_id: progress} for the ids that currently have progress."""
    ids = [str(d) for d in doc_ids]
    if not ids:
        return {}
    if not _use_redis():
        now = time.time()
        return {d: _local[d][1] for d in ids if d in _local and _local[d][0] >= now}
    try:
        values = doc_store.get_client().mget([_key(d) for d in ids])
    except Exception as e:
        logger.debug(f"progress.get_many skipped: {e}")
        return {}
    out = {}
    for doc_id, raw in zip(ids, values):
        if raw:
            try:
                out[doc_id] = json.loads(raw)
            except ValueError:
                pass
    return out


def clear(doc_id: str) -> None:
    _local.pop(str(doc_id), None)
    if not _use_redis():
        return
    try:
        doc_store.get_client().delete(_key(str(doc_id)))
    except Exception:
        pass
