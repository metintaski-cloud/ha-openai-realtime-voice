import asyncio
import json

from app import diary

DAY = diary.DAY
NOW = 2_000_000_000.0


def entry(**kw):
    d = {"wichtig": True, "lang": "Lang " * 10, "mittel": "Mittel text", "kurz": "Kurz", "privat": False}
    d.update(kw)
    return d


def test_memory_fades_with_age_and_is_gone_after_a_month(tmp_path):
    dy = diary.Diary(str(tmp_path / "d.json"))
    dy.add(entry(lang="Heute lang erzählt"), "Metin Taskiran", "stimme", now=NOW - 3600)
    dy.add(entry(mittel="Vor zehn Tagen mittel"), "Metin", "chat", now=NOW - 10 * DAY)
    dy.add(entry(kurz="Vor drei Wochen kurz"), "Metin", "stimme", now=NOW - 21 * DAY)
    dy.add(entry(kurz="Zu alt"), "Metin", "stimme", now=NOW - 31 * DAY)
    note = dy.note("Metin", now=NOW)
    assert "heute: Heute lang erzählt" in note
    assert "vor etwa einer Woche: Vor zehn Tagen mittel" in note
    assert "Vor zehn Tagen mittel" in note and "vor etwa 3 Wochen: Vor drei Wochen kurz" in note
    assert "Zu alt" not in note
    assert note.index("Vor drei Wochen") < note.index("heute")  # in time order


def test_only_the_speakers_entries_and_private_only_with_the_code(tmp_path):
    dy = diary.Diary(str(tmp_path / "d.json"))
    dy.add(entry(lang="Mama erzählte vom Garten"), "Gülfikar Taskiran", "stimme", now=NOW)
    dy.add(entry(lang="Wir haben geflirtet", privat=True), "Metin", "chat", now=NOW)
    dy.add(entry(lang="Jemand fragte nach dem Wetter"), "", "stimme", now=NOW)
    metin = dy.note("Metin", private=False, now=NOW)
    assert "Garten" not in metin and "geflirtet" not in metin and "Wetter" in metin
    assert "geflirtet" in dy.note("Metin", private=True, now=NOW)
    mama = dy.note("Gülfikar Taskiran", private=True, now=NOW)
    assert "Garten" in mama and "geflirtet" not in mama


def test_unimportant_talks_are_not_written_and_the_note_has_a_cap(tmp_path):
    dy = diary.Diary(str(tmp_path / "d.json"))
    assert not dy.add({"wichtig": False}, "Metin", "stimme")
    for i in range(60):
        dy.add(entry(lang="x" * 390), "Metin", "stimme", now=NOW - i * 60)
    assert len(dy.note("Metin", now=NOW)) < diary.MAX_NOTE + 400


def test_parse_and_write(tmp_path, monkeypatch):
    assert diary.parse("blabla") is None
    assert diary.parse('{"wichtig": true, "lang": "a"}') is None
    good = json.dumps(entry())
    assert diary.parse("Antwort: " + good)["wichtig"]
    seen = {}

    async def ask(prompt, *a, **k):
        seen["p"] = prompt
        return good
    monkeypatch.setattr(diary.textmodel, "ask", ask)
    dy = diary.Diary(str(tmp_path / "d.json"))
    ok = asyncio.run(dy.write([("user", "Ich war heute beim Zahnarzt, es tat weh."),
                               ("bot", "Oh nein, das tut mir leid!")], "Metin", "stimme", "k", ["m"], "u"))
    assert ok and "Zahnarzt" in seen["p"] and "Gülfikar" in seen["p"] and len(dy.entries()) == 1


def test_a_chat_counts_as_one_talk_after_a_pause(tmp_path):
    dy = diary.Diary(str(tmp_path / "d.json"))
    dy.chat_turn("Hallo", "Hey du", now=NOW)
    dy.chat_turn("Wie geht's", "Gut", now=NOW + 60)
    assert dy.chat_due(NOW + 120) == []
    talk = dy.chat_due(NOW + 60 + diary.CHAT_PAUSE_S)
    assert talk[0] == ("user", "Hallo") and len(talk) == 4 and dy.chat_due(NOW + 99999) == []


def test_new_chat_takes_the_chat_at_once_and_home_sees_the_fresh_part(tmp_path):
    dy = diary.Diary(str(tmp_path / "d.json"))
    dy.chat_turn("Ich hab heute Bauchweh", "Oh nein, leg dich hin", now=NOW)
    assert "Bauchweh" in dy.chat_text() and "Leyla: Oh nein" in dy.chat_text()
    assert diary.CHAT_PAUSE_S == 300
    talk = dy.chat_take()
    assert talk == [("user", "Ich hab heute Bauchweh"), ("bot", "Oh nein, leg dich hin")]
    assert dy.chat_text() == "" and dy.chat_take() == []


def test_bridge_new_chat_writes_the_diary_before_the_next_answer(tmp_path, monkeypatch):
    from app import main as m
    bridge = m.LiveVoiceBridge.__new__(m.LiveVoiceBridge)
    bridge.diary = diary.Diary(str(tmp_path / "d.json"))
    bridge.openai_api_key, bridge.memory_model, bridge.backend_model = "k", "a", "b"
    written = []

    async def write(dialog, who, src, *a):
        await asyncio.sleep(0.05)
        written.append((who, src, len(dialog)))
        return True
    monkeypatch.setattr(bridge.diary, "write", write)
    bridge.diary.chat_turn("Hallo", "Hey")
    asyncio.run(bridge._chat_new())
    assert written == [("Metin", "chat", 2)]


def test_a_goodbye_in_the_chat_writes_the_diary_at_once(tmp_path, monkeypatch):
    from app import main as m
    for t in ("Bye", "Byeee Schatz", "ok bis später", "Ich geh jetzt schlafen", "Tschüss", "Hadi bay"):
        assert m.CHAT_BYE_RE.search(t) or m.contains_goodbye(t), t
    for t in ("maybe", "Wie war dein Tag?"):
        assert not (m.CHAT_BYE_RE.search(t) or m.contains_goodbye(t)), t


def test_the_chat_sees_a_running_talk_with_metin_at_home():
    from app import main as m
    bridge = m.LiveVoiceBridge.__new__(m.LiveVoiceBridge)
    bridge._live_sessions = {1: (None, {"dialog": [("user", "Ich bin müde"), ("bot", "Ruh dich aus")]})}
    assert bridge._live_talk_text() == ""  # nobody known: nothing
    bridge._live_sessions[1][1]["metin_known"] = True
    assert bridge._live_talk_text() == "Metin: Ich bin müde\nLeyla: Ruh dich aus"
