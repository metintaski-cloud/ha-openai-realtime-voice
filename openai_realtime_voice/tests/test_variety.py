import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app import reminders, variety

TZ = ZoneInfo("Europe/Berlin")


def test_she_gets_her_last_openings_and_the_list_stays_short(tmp_path):
    v = variety.Variety(str(tmp_path / "s.json"))
    assert v.note() == ""
    v.add(["Hey Metin, schön dich zu hören! Wie geht's?", "Na klar. Ich mach das.", "Gern!", "Vierter Satz hier."])
    said = v.recent()
    assert said == ["Hey Metin, schön dich zu hören!", "Na klar.", "Vierter Satz hier."]  # "Gern!" too short
    assert "nicht wiederholen" in v.note() and "Hey Metin, schön dich zu hören!" in v.note()
    for i in range(30):
        v.add([f"Satz Nummer {i} ist da."])
    assert len(v.recent()) == variety.KEEP and v.recent()[-1] == "Satz Nummer 29 ist da."


def test_first_sentence():
    assert variety.first_sentence("Hallo du. Wie geht's?") == "Hallo du."
    assert variety.first_sentence("ohne Punkt am Ende") == "ohne Punkt am Ende"


class FakeAgenda:
    available = True

    @staticmethod
    def tz():
        return TZ

    def __init__(self, events):
        self.events = events

    async def upcoming(self, t0, t1):
        return self.events


def ev(eid, title, h0, h1):
    d = lambda h: datetime(2026, 11, 16, h, 0, tzinfo=TZ).isoformat()  # noqa: E731
    return {"id": eid, "titel": title, "wann": f"heute {h0}:00", "start": {"dateTime": d(h0)},
            "end": {"dateTime": d(h1)}}


def test_she_asks_once_how_an_appointment_went(tmp_path, monkeypatch):
    r = reminders.Reminders(FakeAgenda([ev("a", "Zahnarzt", 10, 11), ev("b", "Später", 18, 19)]),
                            path=str(tmp_path / "r.json"))
    now = datetime(2026, 11, 16, 11, 5, tzinfo=TZ).timestamp()
    assert asyncio.run(r.followup_note(now)) == ""          # only 5 minutes over
    now = datetime(2026, 11, 16, 12, 0, tzinfo=TZ).timestamp()
    note = asyncio.run(r.followup_note(now))
    assert "Zahnarzt" in note and "Später" not in note and "wie es war" in note
    assert asyncio.run(r.followup_note(now + 60)) == ""     # once
