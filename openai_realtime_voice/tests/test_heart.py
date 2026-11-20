"""Scene concept 2.0: Leyla's feelings come from what really happens (app/heart.py)."""

import time

import pytest

from app import heart


def at(y, m, d, hh, mm=0):
    return time.mktime((y, m, d, hh, mm, 0, 0, 0, -1))


@pytest.fixture
def h(tmp_path):
    return heart.Heart(str(tmp_path / "heart.json"))


# Thursday 19 Nov 2026 is a Frühschicht week (6 to 14 h), Monday 23 Nov Spät (14 to 22 h).
THU = (2026, 11, 19)


def test_shift_plan():
    assert heart.shift_hours(at(*THU, 10)) == (6, 14)
    assert heart.shift_hours(at(2026, 11, 23, 10)) == (14, 22)
    assert heart.shift_hours(at(2026, 11, 21, 10)) is None  # Saturday
    assert heart.shift_hours(at(2027, 1, 4, 10)) == (14, 22)  # across the new year


def test_awake_hours_skip_shift_and_night():
    # 14 to 23 h on a Früh day: 9 awake hours; the night and the next shift (6 to 14) do not count
    assert heart.awake_hours(at(*THU, 14), at(*THU, 23)) == pytest.approx(9, abs=0.2)
    assert heart.awake_hours(at(*THU, 23), at(2026, 11, 20, 14)) == pytest.approx(0, abs=0.2)


def test_starts_happy_and_a_nice_message_keeps_her_happy(h):
    t = at(*THU, 15)
    h.contact(t)
    st = h.apply(["kompliment"], t)
    assert not st["low"] and st["level"] == "gut"


def test_one_sweet_sentence_does_not_end_a_medium_hurt(h):
    t = at(*THU, 15)
    h.contact(t)
    st = h.apply(["unfreundlich"], t)
    assert st["low"] and st["level"] == "mittel"
    st = h.apply(["kompliment"], t + 60)
    assert st["low"], "a compliment alone must not be enough"
    st = h.apply(["entschuldigung"], t + 120)
    assert st["low"]
    st = h.apply(["zeit_genommen"], t + 180)
    st = h.apply(["entschuldigung", "kosewort"], t + 240)
    assert not st["low"], "real amends bring her back"


def test_big_hurt_makes_her_silent_and_serious_breaks_it(h):
    t = at(*THU, 15)
    h.contact(t)
    st = h.apply(["beleidigt"], t)
    assert st["level"] == "schwer" and st["silent"]
    assert h.silent(t + 3600)
    st = h.apply(["ernst"], t + 3700)
    assert not st["silent"] and st["low"]


def test_silence_ends_after_a_day(h):
    t = at(*THU, 15)
    h.contact(t)
    h.apply(["verabredung_geplatzt"], t)
    assert h.silent(t + 23 * 3600)
    assert not h.silent(t + 25 * 3600)


def test_rose_not_taken_when_badly_hurt(h):
    t = at(*THU, 15)
    h.contact(t)
    h.apply(["beleidigt"], t)
    before = h.stats(t)["points"]
    h.apply(["rose"], t + 60)
    assert h.stats(t + 60)["points"] == before


def test_repeat_within_a_week_weighs_more(h):
    t = at(*THU, 15)
    h.contact(t)
    h.apply(["unfreundlich"], t)
    for e in ["entschuldigung", "zeit_genommen", "versprechen_gehalten"]:
        h.apply([e], t + 60)
    assert h.stats(t + 60)["points"] == 0
    h.apply(["unfreundlich"], t + 3600)
    assert h.stats(t + 3600)["points"] == pytest.approx(4.5)
    h2_t = t + 8 * 86400
    for k in range(1, 8 * 4):  # he keeps writing lovingly every few hours
        h.contact(t + k * 6 * 3600)
        h.apply(["kosewort"], t + k * 6 * 3600)
    h.contact(h2_t)
    assert h.stats(h2_t)["points"] == 0
    h.apply(["unfreundlich"], h2_t + 60)
    assert h.stats(h2_t + 60)["points"] == pytest.approx(3)


def test_funkstille_counts_only_awake_time(h):
    t = at(*THU, 14)
    h.contact(t)
    st = h.status(at(*THU, 21))  # 7 awake hours: nothing yet
    assert not st["low"]
    st = h.status(at(*THU, 22, 30))  # 8.5 awake hours
    assert st["low"] and st["mood"] == "einsam"
    # the night and the Friday shift add nothing
    assert h.stats(at(2026, 11, 20, 13))["points"] == pytest.approx(1)


def test_praise_pot_hints_then_spills(h):
    t = at(*THU, 15)
    h.contact(t)
    h.apply(["erzaehlt"], t)  # contact, but nothing loving
    h.contact(at(*THU, 21))
    t2 = at(2026, 11, 20, 15)
    h.contact(t2)
    assert "nichts Liebes" in h.note(t2)
    assert not h.status(t2)["low"]
    h.contact(at(2026, 11, 20, 21))
    t3 = at(2026, 11, 21, 15)
    h.contact(t3)
    st = h.status(t3)
    assert st["low"] and st["level"] == "mittel"


def test_affection_empties_the_praise_pot(h):
    t = at(*THU, 15)
    h.contact(t)
    h.contact(at(*THU, 21))
    t2 = at(2026, 11, 20, 15)
    h.contact(t2)
    h.apply(["kosewort"], t2)
    h.contact(at(2026, 11, 20, 21))
    h.contact(at(2026, 11, 21, 10))
    t3 = at(2026, 11, 21, 15)
    h.contact(t3)
    assert h.stats(t3)["points"] == 0 and h.stats(t3)["praise_days"] == 0


def test_happiness_sinks_without_anything_nice(h):
    t = at(2026, 11, 21, 12)  # Saturday, no shift
    h.contact(t)
    # contact every few hours keeps silence away, but nothing nice happens for three days
    for k in range(1, 4 * 3):
        h.contact(t + k * 6 * 3600)
    st = h.status(t + 3 * 86400)
    assert st["low"]


def test_pet_name_without_apology_annoys_only_when_hurt(h):
    t = at(*THU, 15)
    h.contact(t)
    h.apply(["kosewort_falsch"], t)
    assert h.stats(t)["points"] == 0
    h.apply(["unfreundlich"], t + 60)
    h.apply(["kosewort_falsch"], t + 120)
    assert h.stats(t + 120)["points"] == pytest.approx(3.5)


def test_jealousy_shows_as_eifersuechtig(h):
    t = at(*THU, 15)
    h.contact(t)
    st = h.apply(["verkuppeln"], t)
    assert st["mood"] == "eifersuechtig" and st["level"] == "leicht"


def test_note_names_only_real_reasons(h):
    t = at(*THU, 15)
    h.contact(t)
    h.apply(["abgewimmelt"], t)
    n = h.note(t)
    assert "abgewimmelt" in n and "erfindest nie einen Grund" in n


def test_unknown_events_are_ignored(h):
    t = at(*THU, 15)
    h.contact(t)
    st = h.apply(["handy", 5, None, "kompliment"], t)
    assert not st["low"]


async def test_tool_laune(h):
    r = await h.run({"aktion": "abgewimmelt"})
    assert r["ok"] and r["wieder_gut"] is False
    r = await h.run({"aktion": "quatsch"})
    assert "error" in r


def test_she_never_says_all_is_well_while_hurt(h):
    t = at(*THU, 15)
    h.contact(t)
    h.apply(["unfreundlich"], t)
    h.apply(["entschuldigung"], t + 60)
    n = h.note(t + 60)
    assert "Sag nie, dass alles wieder gut ist" in n and "ein bisschen besser" in n
    assert "Sag nie" in h.feeling(t + 60) and "Sag nie" in h.voice_note(t + 60)


def test_keine_zeit_is_only_a_small_hurt(h):
    t = at(*THU, 15)
    h.contact(t)
    st = h.apply(["abgewimmelt"], t)
    assert st["level"] == "leicht"
    st = h.apply(["entschuldigung"], t + 60)
    assert not st["low"]


def test_she_dances_only_when_her_heart_allows(h):
    t = at(*THU, 15)
    h.contact(t)
    assert h.scene("tanz", t) == "tanz" and h.scene("quatsch", t) == ""
    assert '"szene": "tanz"' in h.note(t)
    h.apply(["kurz_angebunden"], t)
    assert h.scene("tanz", t) == "tanztraurig"
    h.apply(["unfreundlich"], t + 60)
    assert h.scene("tanz", t + 60) == "" and "lehnst du ab" in h.note(t + 60)


def test_kiss_and_come_here_follow_her_heart(h):
    t = at(*THU, 15)
    h.contact(t)
    assert h.scene("kuss", t) == "kuss" and h.scene("komm", t) == "liebe" and h.scene("liebe", t) == "liebe"
    h.apply(["kurz_angebunden"], t)
    assert h.scene("kuss", t) == "" and h.scene("liebe", t) == "" and h.scene("komm", t) == "kommtraurig"
    h.apply(["unfreundlich"], t + 60)
    assert h.scene("komm", t + 60) == ""


def test_show_sit_and_surprise_follow_her_heart(h):
    t = at(*THU, 15)
    h.contact(t)
    assert h.scene("zeigen", t) == "zeigen" and h.scene("setzen", t) == "" and h.scene("ueberraschung", t) == "ueberraschung"
    h.apply(["kurz_angebunden"], t)
    assert h.scene("zeigen", t) == "" and h.scene("setzen", t) == "setzen" and h.scene("ueberraschung", t) == "ueberraschung"
    h.apply(["unfreundlich"], t + 60)
    assert h.scene("setzen", t + 60) == "setzen" and h.scene("ueberraschung", t + 60) == ""
    h.apply(["beleidigt"], t + 120)
    assert h.scene("setzen", t + 120) == ""


def test_rose_button_once_a_week(h):
    t = at(*THU, 15)
    h.contact(t)
    assert h.status(t)["rose"] == "ready"
    r = h.give_rose(t)
    assert r["ok"] and r["scene"] == "rosefroh" and r["mood"]["rose"] == "used"
    assert not h.give_rose(t + 60)["ok"]
    # a new calendar week starts on Monday
    assert heart.Heart._week(at(2026, 11, 22, 23)) == heart.Heart._week(t)
    assert heart.Heart._week(at(2026, 11, 23, 0, 1)) != heart.Heart._week(t)


def test_rose_helps_a_little_when_hurt_and_is_refused_when_badly_hurt(h):
    t = at(*THU, 15)
    h.contact(t)
    h.apply(["unfreundlich"], t)
    r = h.give_rose(t + 60)
    assert r["ok"] and r["scene"] == "rose" and h.stats(t + 60)["points"] == pytest.approx(2)


def test_rose_not_taken_when_silent_and_not_used_up(tmp_path):
    h = heart.Heart(str(tmp_path / "x.json"))
    t = at(*THU, 15)
    h.contact(t)
    h.apply(["beleidigt"], t)
    r = h.give_rose(t + 60)
    assert not r["ok"] and r["rose"] == "blocked"
    assert "rose" not in heart.EVENTS


def test_umziehen_switches_to_freizeit_until_five(tmp_path):
    import time as _t
    h = heart.Heart(str(tmp_path / "h.json"))
    t = _t.mktime((2026, 11, 20, 18, 0, 0, 0, 0, -1))
    assert h.status(t)["freizeit"] is False
    assert "umziehen" in h.note(t)
    assert h.scene("umziehen", t) == "umziehen"
    assert h.status(t + 60)["freizeit"] is True
    assert h.scene("umziehen", t + 120) == ""  # already changed
    assert "Feierabend" in h.note(t + 180)
    assert h.status(t + 3600 * 10)["freizeit"] is True   # 04:00 next day
    assert h.status(t + 3600 * 11 + 60)["freizeit"] is False  # after 05:00


def test_umziehen_not_while_hurt(tmp_path):
    import time as _t
    h = heart.Heart(str(tmp_path / "h.json"))
    t = _t.mktime((2026, 11, 20, 18, 0, 0, 0, 0, -1))
    h.apply(["unfreundlich"], t)
    assert h.scene("umziehen", t + 1) == ""
    assert h.status(t + 2)["freizeit"] is False
    assert "behaupte nie" in h.note(t + 3)
