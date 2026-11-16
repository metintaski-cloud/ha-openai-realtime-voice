import random
import time

from app.mood import Mood, CHEER_NEEDED


def test_stats_log_rolls_and_cheer(tmp_path):
    m = Mood(path=str(tmp_path / "m.json"), rng=random.Random(1))
    noon = time.mktime(time.strptime("2026-11-16 12:00", "%Y-%m-%d %H:%M"))
    m.current(noon)  # first start sets the clock
    m.current(noon + 20 * 3600)
    st = m.stats(noon + 20 * 3600)
    assert st["log"], st
    assert any("roll" in e for e in st["log"])
    if st["low"]:
        for _ in range(CHEER_NEEDED):
            m.resolve(noon + 21 * 3600)
        assert any("good again" in e for e in m.stats(noon + 21 * 3600)["log"])


def test_low_mood_sounds_sad_not_happy(tmp_path):
    import json
    p = tmp_path / "m.json"
    p.write_text(json.dumps({"mood": "traurig", "since": 1, "next_roll": 9e12, "low_day": "x"}))
    m = Mood(path=str(p))
    for text in (m.feeling(), m.voice_note()):
        assert "ohne Lächeln" in text and "gilt das Lächeln" in text
    p.write_text(json.dumps({"mood": "froehlich", "since": 1, "next_roll": 9e12, "low_day": ""}))
    assert "Lächeln" in m.feeling() and "gilt das Lächeln" not in m.feeling()
