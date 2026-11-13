import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.freshness import age_minutes  # noqa: E402

NOW = dt.datetime(2026, 11, 13, 15, 0, tzinfo=dt.timezone.utc)


def test_age_from_last_reported_then_updated():
    assert age_minutes({"last_reported": "2026-11-13T14:30:00+00:00"}, NOW) == 30
    assert age_minutes({"last_updated": "2026-11-13T14:59:30Z"}, NOW) == 0
    assert age_minutes({"last_reported": "2026-11-13T14:00:00.123456+00:00",
                        "last_updated": "2026-11-13T10:00:00+00:00"}, NOW) == 59


def test_unusable_time_gives_none_and_the_future_is_zero():
    assert age_minutes({}, NOW) is None
    assert age_minutes({"last_updated": "kaputt"}, NOW) is None
    assert age_minutes({"last_updated": "2026-11-13T16:00:00+00:00"}, NOW) == 0
