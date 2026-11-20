import asyncio
import json
import time

from app import day as daymod
from app.diary import Diary


def _answer(erlebt=None, buch="Der kleine Prinz, Antoine de Saint-Exupéry"):
    return json.dumps({"buch": buch, "buch_stand": "die Rose", "gedanke": "Zuhause ist ein Gefühl",
                       "lied": "Yalnızlık Senfonisi, Sezen Aksu", "erlebt": erlebt or []})


def test_day_built_from_family_talks_only(tmp_path, monkeypatch):
    monkeypatch.setattr(daymod, "START_H", 0)
    d = Diary(str(tmp_path / "diary.json"))
    now = time.time()
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
