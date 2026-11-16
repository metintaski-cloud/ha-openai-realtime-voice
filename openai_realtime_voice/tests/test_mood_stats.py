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
