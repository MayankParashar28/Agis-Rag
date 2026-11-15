from datetime import datetime, timezone

from app.services.timestamps import turn_stamps


def test_answer_is_always_after_question():
    asked, answered = turn_stamps(1_700_000_000.0, now=datetime.fromtimestamp(1_700_000_005.0, tz=timezone.utc))
    assert answered > asked
    assert (answered - asked).total_seconds() == 5


def test_same_instant_still_ordered():
    t = 1_700_000_000.0
    asked, answered = turn_stamps(t, now=datetime.fromtimestamp(t, tz=timezone.utc))
    assert answered > asked
