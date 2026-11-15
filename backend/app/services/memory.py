"""Short-term conversation memory, read from Postgres.

This was backed by Redis, which duplicated what `chat.py` already writes to the
`messages` table on every turn. The duplication was not free: `get_history`
swallowed any Redis error and returned `[]`, so an unreachable Redis silently
cost the model its conversation context and follow-up questions were answered
as if they were the first. Postgres is the system of record for messages, so
read from it and keep one copy of the truth.
"""
import uuid
from typing import Any, Dict, List

from sqlalchemy import case, select

from app.core.database import SessionLocal
from app.core.logging import logger
from app.models.metrics import Message


class ChatMemory:
    """Recent turns of a conversation, oldest first."""

    async def get_history(self, session_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        try:
            conv_id = uuid.UUID(str(session_id))
        except (ValueError, AttributeError, TypeError):
            return []
        try:
            async with SessionLocal() as db:
                rows = list((await db.execute(
                    select(Message)
                    .where(Message.conversation_id == conv_id)
                    # Newest first, answer before its question on a tied
                    # timestamp (older rows); reversed below.
                    .order_by(Message.created_at.desc(), case((Message.sender == "user", 0), else_=1).desc())
                    .limit(limit)
                )).scalars().all())
        except Exception as e:
            logger.error(f"Could not read conversation history for {session_id}: {e}")
            return []
        rows.reverse()
        return [{"sender": m.sender, "content": m.content, "citations": m.citations or []} for m in rows]

    async def add_message(self, session_id: str, message: Dict[str, Any]) -> None:
        """No-op: `chat.py` inserts the Message row inside the request's own
        transaction, which is what get_history reads."""
        return None

    async def clear_history(self, session_id: str) -> None:
        """No-op: deleting the conversation deletes its messages."""
        return None


chat_memory = ChatMemory()
