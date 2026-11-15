"""Per-user daily usage: how much each user has asked today, and whether a
new question fits under their limit.

Usage comes from the query log, the record already kept for every answered
question, so there is no separate counter to drift. Days run on UTC.
"""
from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import asdict, dataclass
from typing import Dict, Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.auth import User
from app.models.metrics import QueryLog


def day_start(now: Optional[dt.datetime] = None) -> dt.datetime:
    now = now or dt.datetime.now(dt.timezone.utc)
    return now.astimezone(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def resets_at(now: Optional[dt.datetime] = None) -> dt.datetime:
    return day_start(now) + dt.timedelta(days=1)


def limits_for(user: User) -> tuple[int, int]:
    """(question limit, token limit) for this user; 0 means unlimited."""
    if user.role == "admin" and settings.ADMINS_UNLIMITED and user.daily_question_limit is None and user.daily_token_limit is None:
        return 0, 0
    q = settings.DAILY_QUESTION_LIMIT if user.daily_question_limit is None else user.daily_question_limit
    t = settings.DAILY_TOKEN_LIMIT if user.daily_token_limit is None else user.daily_token_limit
    return max(0, int(q)), max(0, int(t))


@dataclass
class UsageToday:
    questions: int
    tokens: int
    cost_usd: float
    question_limit: int       # 0 = unlimited
    token_limit: int          # 0 = unlimited
    resets_at: str
    custom_limits: bool

    @property
    def blocked_reason(self) -> Optional[str]:
        if self.question_limit and self.questions >= self.question_limit:
            return f"You have used all {self.question_limit} questions for today."
        if self.token_limit and self.tokens >= self.token_limit:
            return f"You have used today's AI allowance ({self.token_limit:,} tokens)."
        return None

    def as_dict(self) -> dict:
        return {**asdict(self), "blocked": self.blocked_reason is not None}


async def usage_by_user(db: AsyncSession, user_ids: Optional[Iterable[uuid.UUID]] = None) -> Dict[uuid.UUID, tuple]:
    """{user_id: (questions, tokens, cost)} for today."""
    q = (select(QueryLog.user_id, func.count(QueryLog.id),
                func.coalesce(func.sum(func.coalesce(QueryLog.prompt_tokens, 0) + func.coalesce(QueryLog.completion_tokens, 0)), 0),
                func.coalesce(func.sum(QueryLog.cost_usd), 0.0))
         .where(QueryLog.created_at >= day_start(), QueryLog.user_id.is_not(None))
         .group_by(QueryLog.user_id))
    if user_ids is not None:
        ids = list(user_ids)
        if not ids:
            return {}
        q = q.where(QueryLog.user_id.in_(ids))
    return {uid: (int(n or 0), int(t or 0), float(c or 0.0)) for uid, n, t, c in (await db.execute(q)).all()}


async def usage_today(db: AsyncSession, user: User) -> UsageToday:
    n, tokens, cost = (await usage_by_user(db, [user.id])).get(user.id, (0, 0, 0.0))
    ql, tl = limits_for(user)
    return UsageToday(questions=n, tokens=tokens, cost_usd=round(cost, 4), question_limit=ql, token_limit=tl,
                      resets_at=resets_at().isoformat(),
                      custom_limits=user.daily_question_limit is not None or user.daily_token_limit is not None)


def friendly_wait(now: Optional[dt.datetime] = None) -> str:
    left = resets_at(now) - (now or dt.datetime.now(dt.timezone.utc))
    h, m = divmod(int(left.total_seconds()) // 60, 60)
    return f"{h} h {m} min" if h else f"{m} min"
