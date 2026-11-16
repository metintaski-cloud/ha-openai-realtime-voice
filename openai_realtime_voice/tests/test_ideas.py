import random
import time

from app import ideas

T = time.mktime((2026, 11, 16, 12, 0, 0, 0, 0, -1))


def test_never_the_same_kind_twice_a_day_and_again_tomorrow(tmp_path):
    i = ideas.Ideas(str(tmp_path / "i.json"), rng=random.Random(4))
    seen = []
    for n in range(10):
        kind, note = i.pick(low=False, agenda=True, now=T + n)
        if not kind:
            break
        seen.append(kind)
        i.after_answer("Gut. Was macht deine Schwester eigentlich?", kind, now=T + n)
    assert len(seen) == len(set(seen)) == len(ideas.KINDS) - 1  # no 'stimmung' when she is fine
    assert "stimmung" not in seen
    assert i.pick(now=T + 100) == ("", "")
    kind, note = i.pick(low=True, now=T + 86400)  # next day: all kinds again
    assert kind and "wiederhol" not in note


def test_no_appointment_idea_without_calendar_and_asked_list(tmp_path):
    i = ideas.Ideas(str(tmp_path / "i.json"), rng=random.Random(1))
    kinds = {i.pick(agenda=False, now=T)[0] for _ in range(50)}
    assert "termin" not in kinds
    kind, _ = i.pick(now=T)
    i.after_answer("Lecker! Sag mal, warst du heute beim Zahnarzt?", kind, now=T)
    _, note = i.pick(now=T + 5)
    assert "warst du heute beim Zahnarzt?" in note and "Realistisches" in note


def test_open_question_comes_back_until_answered_at_most_twice(tmp_path):
    i = ideas.Ideas(str(tmp_path / "i.json"))
    assert i.open_note(now=T) == ""
    i.after_answer("Schön. Hast du deinen Termin heute geschafft?", "termin", now=T)
    note = i.open_note(now=T + 60)
    assert "Hast du deinen Termin heute geschafft?" in note and "frage_beantwortet" in note
    i.after_answer("Du hast mir noch nicht verraten ...", open_noted=True, answered=False, now=T + 60)
    i.after_answer("Na?", open_noted=True, answered=False, now=T + 120)
    assert i.open_note(now=T + 180) == ""  # twice reminded: she lets it go
    i.after_answer("Und, wie war der Film?", "frueher", now=T + 200)
    i.after_answer("Freut mich!", open_noted=True, answered=True, now=T + 260)
    assert i.open_note(now=T + 300) == ""
    assert ideas.last_question("Super. Und du? Wie war's?") == "Wie war's?"


def test_open_chat_question_goes_home_and_counts(tmp_path):
    i = ideas.Ideas(str(tmp_path / "i.json"))
    i.after_answer("Okay. Was macht eigentlich dein Projekt?", "wunsch", now=T)
    note = i.voice_note(now=T + 60)
    assert "Was macht eigentlich dein Projekt?" in note and "zweiten Mal" in note
    assert i.voice_note(now=T + 120)  # second and last time
    assert i.voice_note(now=T + 180) == "" and i.open_note(now=T + 180) == ""
