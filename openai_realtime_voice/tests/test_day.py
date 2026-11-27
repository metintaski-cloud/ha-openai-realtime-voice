import asyncio
import json
import time

from app import day, day as daymod
from app.diary import Diary


def _answer(erlebt=None, buch="Der kleine Prinz, Antoine de Saint-Exupéry"):
    return json.dumps({"buch": buch, "buch_stand": "die Rose", "gedanke": "Zuhause ist ein Gefühl",
                       "lied": "Yalnızlık Senfonisi, Sezen Aksu", "erlebt": erlebt or []})


def test_day_built_from_family_talks_only(tmp_path, monkeypatch):
    monkeypatch.setattr(daymod, "START_H", 0)
    d = Diary(str(tmp_path / "diary.json"))
    # noon of today, not the clock: one minute before midnight "now + 60" was the next day and the day was built
    # again (seen on 27 Nov 2026 at 23:59 in a full run)
    now = time.mktime(time.localtime()[:3] + (12, 0, 0, 0, 0, -1))
    d._save([
        {"t": now - 60, "who": "Gülfikar", "privat": False, "src": "stimme", "mittel": "Anne hat Dolma gekocht"},
        {"t": now - 50, "who": "Gülfikar", "privat": True, "src": "stimme", "mittel": "GEHEIM"},
        {"t": now - 40, "who": "Metin", "privat": False, "src": "stimme", "mittel": "METINS SACHE"},
    ])
    seen = {}

    async def ask(prompt):
        seen["p"] = prompt
        return _answer(["Anne hat mir von ihren Dolma erzählt"])

    async def weather():
        return "regnerisch, 8 °C"

    dy = daymod.Day(d, ask, weather, str(tmp_path / "day.json"))
    assert asyncio.run(dy.refresh(now))
    assert "Dolma" in seen["p"] and "GEHEIM" not in seen["p"] and "METINS" not in seen["p"]
    note = dy.note(now)
    assert "Der kleine Prinz" in note and "Dolma" in note and "regnerisch" in note
    assert not asyncio.run(dy.refresh(now + 60))  # built, nothing new


def test_bad_answer_keeps_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(daymod, "START_H", 0)

    async def ask(prompt):
        return "kein json"

    dy = daymod.Day(Diary(str(tmp_path / "d.json")), ask, None, str(tmp_path / "day.json"))
    assert not asyncio.run(dy.refresh())
    assert dy.note() == ""


def test_she_knows_mokka_only_after_the_surprise_has_played(tmp_path):
    """Metin, 22.11.2026: she must not speak of Mokka before she has seen her."""
    f, m = str(tmp_path / "flag"), str(tmp_path / "met")
    assert day.pet_note(f, m) == "", "no cat in her rules before the surprise"
    assert not day.pet_met(m)
    assert day.pet_meet(m) and not day.pet_meet(m), "the app reports it once"
    assert day.pet_met(m) and "Mokka" in day.pet_note(f, m)


def test_pet_note_thanks_once(tmp_path):
    f, m = str(tmp_path / "flag"), str(tmp_path / "met")
    day.pet_meet(m)
    assert "Überraschung" in day.pet_note(f, m) and "Mokka" in day.pet_note(f, m)
    assert not day.pet_seen("Wie war dein Tag?", f)
    assert day.pet_seen("Danke für Mokka, sie ist so süß!", f)
    assert "schon bei Metin" in day.pet_note(f, m) and not day.pet_seen("Mokka schläft", f)
