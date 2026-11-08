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
    "chunking": "Splitting into chunks",
    "embedding": "Creating embeddings",
    "saving": "Saving to the index",
    "done": "Indexed",
    "failed": "Failed",
}


def _key(doc_id: str) -> str:
    return f"{KEY_PREFIX}{doc_id}"


def report(doc_id: str, stage: str, percent: Optional[float] = None,
           message: Optional[str] = None) -> None:
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
    ttl = FINAL_TTL_SECONDS if stage in ("done", "failed") else ACTIVE_TTL_SECONDS
    try:
        doc_store.get_client().set(_key(str(doc_id)), json.dumps(payload), ex=ttl)
    except Exception as e:
        logger.debug(f"progress.report({doc_id}, {stage}) skipped: {e}")


def embedding_progress(doc_id: str, done: int, total: int) -> None:
    """Map embedded-batch progress onto the 40-90% band of the bar."""
    if total <= 0:
        return
    start, end = STAGES["embedding"], STAGES["saving"]
    pct = start + (end - start) * (done / total)
    report(doc_id, "embedding", pct, f"{done}/{total} chunks embedded")


def get_many(doc_ids: Iterable[str]) -> Dict[str, dict]:
    """Return {doc_id: progress} for the ids that currently have progress."""
    ids = [str(d) for d in doc_ids]
    if not ids:
        return {}
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
    try:
        doc_store.get_client().delete(_key(str(doc_id)))
    except Exception:
        pass
