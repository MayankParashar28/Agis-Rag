"""Timestamps for one chat turn."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple


def turn_stamps(started_at: float, now: Optional[datetime] = None) -> Tuple[datetime, datetime]:
    """(question time, answer time) for a turn.

    The question and answer are saved in one transaction, and Postgres now()
    returns the transaction's start time - so with the column's server default
    both got the identical timestamp and a refresh could list the answer above
    its question. The question is stamped when it was asked and the answer
    when it was saved, always at least 1 ms later.
    """
    asked = datetime.fromtimestamp(started_at, tz=timezone.utc)
    answered = max(now or datetime.now(timezone.utc), asked + timedelta(milliseconds=1))
    return asked, answered
