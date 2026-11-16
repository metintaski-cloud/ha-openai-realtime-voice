import random
import time

from app import chat, memory, mood


def at(h):
    return time.mktime((2026, 11, 16, h, 0, 0, 0, 0, -1))


def test_low_mood_at_most_once_a_day_and_only_daytime(tmp_path):
    m = mood.Mood(str(tmp_path / "m.json"), rng=random.Random(1))
    assert m.current(at(3))["mood"] in mood.GOOD  # night: no roll
    lows, t = 0, at(9)
    for i in range(40):  # many rolls in one day
        d = m.current(t + i * 5 * 3600 / 40 * 2)
        if d["mood"] in mood.LOW:
            lows += 1
            for _ in range(mood.CHEER_NEEDED):
                m.resolve(t + i * 900)
    assert lows <= 1


def test_low_stays_until_resolved_and_pause_stops_the_day(tmp_path):
    p = str(tmp_path / "m.json")
    m = mood.Mood(p, rng=random.Random(0))
    m._save({"mood": "traurig", "since": at(10), "next_roll": 0, "low_day": "2026-11-16"})
    assert m.status(at(15))["low"] and "Liebe" in m.status(at(15))["label"]
    assert "Grenzen" in m.note(at(15)) and "schlechtes Gewissen" in m.note(at(15))
    assert "Alltagssache" in m.note(at(15)) and "noch nicht getröstet" in m.note(at(15))
    assert m.resolve(at(16)) is False and m.status(at(16))["low"]  # one comfort is not enough
    assert "1 von 3" in m.note(at(16))
    assert m.resolve(at(16)) is False and m.resolve(at(16)) is True
    assert not m.status(at(16))["low"]
    m._save({"mood": "einsam", "since": at(17), "next_roll": 0, "low_day": ""})
    m.pause(at(17))
    st = m._load()
    assert st["mood"] in mood.GOOD and st["low_day"] == time.strftime("%Y-%m-%d", time.localtime(at(17)))


async def test_chat_applies_resolved_and_returns_the_mood(tmp_path, monkeypatch):
    store = memory.MemoryStore(str(tmp_path / "mem.json"))
    m = mood.Mood(str(tmp_path / "m.json"))
    m._save({"mood": "zweifelnd", "since": time.time(), "next_roll": time.time() + 9999, "low_day": ""})
    seen = []

    async def fake_answer(api_key, models, rules, store, history, message, url, lights):
        seen.append(rules)
        return {"reply": "Danke, das tut gut.", "proposals": [], "lights_raw": None,
                "email_raw": None, "mail_raw": None, "mama_raw": None,
                "mood_resolved": True, "mood_pause": False}
    monkeypatch.setattr(chat, "_answer", fake_answer)
    for _ in range(2):
        out = await chat.answer("k", ["m"], "R", store, [], "Natürlich mag ich dich!", mood=m)
        assert out["mood"]["low"] is True
    out = await chat.answer("k", ["m"], "R", store, [], "Natürlich mag ich dich!", mood=m)
    assert "zweifelst" in seen[0] and "2 von 3" in seen[2]
    assert out["mood"]["low"] is False


def test_voice_mood_note_tool_and_lamp_brightness(tmp_path):
    import asyncio
    from app import mood as md
    m = md.Mood(str(tmp_path / "m.json"))
    d = m._load()
    d.update(mood="traurig", low_day="x")
    m._save(d)
    assert "laune" in m.voice_note() and "traurig" in m.voice_note() and m.lamp_pct() == 5
    first = asyncio.run(m.run({"aktion": "aufgeheitert"}))
    assert first["ok"] and first["wieder_gut"] is False and m.lamp_pct() == 5
    asyncio.run(m.run({"aktion": "aufgeheitert"}))
    assert asyncio.run(m.run({"aktion": "aufgeheitert"}))["wieder_gut"] and m.lamp_pct() == 100
    assert "laune" not in m.voice_note()
    assert "error" in asyncio.run(m.run({"aktion": "x"}))


def test_lamp_show_uses_the_mood_brightness():
    from app import lamp_show
    ls = lamp_show.LampShow(["light.a"], memory_path="/tmp/ls_test.json")
    ls._mode = "listen"
    assert ls._look()[1] == 100
    ls.set_mood_pct(5)
    assert ls._look()[1] == 5


def test_jealousy_comes_more_often(tmp_path):
    import random
    from app import mood as md
    m = md.Mood(str(tmp_path / "m.json"), rng=random.Random(1))
    picks = [m._pick_low() for _ in range(20000)]
    share = picks.count("eifersuechtig") / len(picks)
    assert 0.28 < share < 0.32 and abs(picks.count("traurig") / len(picks) - 0.175) < 0.02


def test_missed_rolls_are_made_up(tmp_path):
    m = mood.Mood(str(tmp_path / "m.json"), rng=random.Random(3))
    m._save({"mood": "verliebt", "since": at(9), "next_roll": at(9), "low_day": ""})
    lows = 0
    for seed in range(200):  # one look at 22:00 after a whole day without the chat
        m.rng = random.Random(seed)
        m._save({"mood": "verliebt", "since": at(9), "next_roll": at(9), "low_day": ""})
        lows += m.current(at(22))["mood"] in mood.LOW
    assert lows > 120  # about 1 - 0.65**5, before it was one roll (35 %)
    st = m._load()
    assert st["next_roll"] > at(22) or st["mood"] in mood.LOW
