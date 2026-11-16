import asyncio

import pytest
from datetime import datetime
from zoneinfo import ZoneInfo

from app import reminders

TZ = ZoneInfo("Europe/Berlin")


def ts(h, m=0, day=16):
    t = datetime(2026, 11, day, h, m, tzinfo=TZ).timestamp()
    NOW[0] = t  # the module clock follows the last time a test used
    return t


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    monkeypatch.setattr(reminders.time, "time", lambda: NOW[0])


class FakeAgenda:
    available = True

    def __init__(self, events):
        self.events = events
        self.calls = 0

    @staticmethod
    def tz():
        return TZ

    async def upcoming(self, t0, t1):
        self.calls += 1
        return self.events


def ev(eid, title, h, m=0, all_day=False):
    start = {"date": "2026-11-16"} if all_day else {"dateTime": datetime(2026, 11, 16, h, m, tzinfo=TZ).isoformat()}
    return {"id": eid, "titel": title, "wann": f"heute {h:02d}:{m:02d}", "start": start}


NOW = [0.0]


def make(tmp_path, events, reachable=True):
    home = []

    async def converse(prompt):
        home.append(prompt)
        return reachable
    r = reminders.Reminders(FakeAgenda(events), converse=converse, path=str(tmp_path / "r.json"))
    return r, home


def test_home_once_an_hour_three_times_no_more(tmp_path):
    r, home = make(tmp_path, [ev("a", "Zahnarzt", 16)])
    assert asyncio.run(r.tick(ts(12, 50))) == 0          # more than 3 h before: nothing
    assert asyncio.run(r.tick(ts(13, 0))) == 1           # 3 h before
    assert "Zahnarzt" in home[0] and "in einer Stunde" in home[0]
    assert asyncio.run(r.tick(ts(13, 30))) == 0          # not within the hour
    assert asyncio.run(r.tick(ts(14, 0))) == 1
    assert asyncio.run(r.tick(ts(15, 0))) == 1
    assert asyncio.run(r.tick(ts(15, 59))) == 0          # three times are enough
    assert len(home) == 3
    assert asyncio.run(r.pending())[0]["id"].startswith("a|")  # the chat card


def test_ok_stops_it_and_a_moved_appointment_is_new(tmp_path):
    r, home = make(tmp_path, [ev("a", "Zahnarzt", 16)])
    asyncio.run(r.tick(ts(13, 0)))
    assert asyncio.run(r.run_ok({})) == {"ok": True, "anzahl": 1}
    assert asyncio.run(r.tick(ts(14, 0))) == 0 and asyncio.run(r.pending()) == []
    r.agenda.events = [ev("a", "Zahnarzt", 17)]
    r._fetched = 0
    assert asyncio.run(r.tick(ts(14, 1))) == 1
    assert asyncio.run(r.tick(ts(17, 5))) == 0           # started: no more


def test_chat_card_ok(tmp_path):
    r, home = make(tmp_path, [ev("a", "Zahnarzt", 16)])
    asyncio.run(r.tick(ts(13, 0)))
    card = asyncio.run(r.pending())[0]
    assert r.ack(card["id"]) == 1 and asyncio.run(r.pending()) == []


def test_quiet_at_night_and_retry_when_unreachable(tmp_path):
    r, home = make(tmp_path, [ev("b", "Frühschicht", 6)])
    assert asyncio.run(r.tick(ts(4, 30))) == 0 and home == []
    r2, home2 = make(tmp_path / "x", [ev("a", "Zahnarzt", 16)], reachable=False)
    assert asyncio.run(r2.tick(ts(13, 0))) == 0           # not counted
    assert r2._load()["sent"] == {}


def test_all_day_from_eight_and_voice_ok_by_word(tmp_path):
    r, home = make(tmp_path, [ev("c", "Geburtstag Ayse", 0, all_day=True), ev("d", "Zahnarzt", 10)])
    assert asyncio.run(r.tick(ts(7, 30))) == 1           # only the timed one
    assert asyncio.run(r.tick(ts(8, 30))) == 2           # all day from 8, timed again after an hour
    assert asyncio.run(r.run_ok({"titel": "zahnarzt"})) == {"ok": True, "anzahl": 1}
    assert asyncio.run(r.run_ok({}))["anzahl"] == 1
    assert asyncio.run(r.run_ok({}))["ok"] is False


def test_calendar_read_at_most_every_five_minutes(tmp_path):
    r, _ = make(tmp_path, [])
    for m in range(0, 10):
        asyncio.run(r.tick(ts(10, m)))
    assert r.agenda.calls == 2
