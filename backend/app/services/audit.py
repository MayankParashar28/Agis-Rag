"""Audit trail: who did what, to which object, when."""
from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.models.metrics import AuditLog


async def record(db: AsyncSession, user, action: str, target_type: Optional[str] = None,
                 target_id: Optional[Any] = None, detail: Optional[Dict[str, Any]] = None,
                 commit: bool = True) -> None:
    """Append an entry. Never raises: auditing must not break the action itself."""
    try:
        entry = AuditLog(
            user_id=getattr(user, "id", None),
            user_email=getattr(user, "email", None),
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            detail=detail or {},
        )
        db.add(entry)
        if commit:
            await db.commit()
    except Exception as e:
        logger.warning(f"Audit record '{action}' not written: {e}")
        try:
            await db.rollback()
        except Exception:
            pass


def record_sync_from_worker(doc_id: uuid.UUID, action: str, detail: Optional[Dict[str, Any]] = None) -> None:
    """For the Celery worker, which has no request user."""
    from app.core.database import SessionLocal
    import asyncio

    async def _go():
        async with SessionLocal() as db:
            db.add(AuditLog(user_id=None, user_email="worker", action=action, target_type="document",
                            target_id=str(doc_id), detail=detail or {}))
            await db.commit()
    try:
        asyncio.get_event_loop().run_until_complete(_go())
    except Exception as e:
        logger.debug(f"worker audit skipped: {e}")
