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
    assert diary.parse("Antwort: " + good)[0]["wichtig"]
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
    assert dy.chat_take() == [] and "Bauchweh" in dy.chat_text()  # the words stay 12 h


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


def test_the_running_chat_survives_a_restart(tmp_path):
    p = str(tmp_path / "d.json")
    dy = diary.Diary(p)
    dy.chat_turn("Ich hab heute Bauchweh", "Leg dich hin", now=NOW)
    again = diary.Diary(p)  # the add on restarted
    assert again.chat_due(NOW + diary.CHAT_PAUSE_S + 1) == [("user", "Ich hab heute Bauchweh"), ("bot", "Leg dich hin")]
    assert diary.Diary(p).chat_take() == []


def test_a_new_chat_goes_on_with_the_last_turns(tmp_path):
    dy = diary.Diary(str(tmp_path / "d.json"))
    assert dy.with_last_chat([{"role": "user", "text": "alt"}], now=NOW) == [{"role": "user", "text": "alt"}]
    dy.chat_turn("Ich war beim Zahnarzt", "Und, wie war's?", now=NOW)
    dy.chat_take()  # "Neuer Chat": the diary entry is written, the words stay
    h = dy.with_last_chat([], now=NOW + 120)
    assert h == [{"role": "user", "text": "Ich war beim Zahnarzt"}, {"role": "leyla", "text": "Und, wie war's?"}]
    dy.chat_turn("Weißt du noch?", "Ja, der Zahnarzt!", now=NOW + 130)
    assert len(dy.with_last_chat([{"role": "user", "text": "x"}] * 2, now=NOW + 140)) == 4  # second message too
    for i in range(15):
        dy.chat_turn(f"m{i}", f"r{i}", now=NOW + 200 + i)
    assert len(dy.with_last_chat([], now=NOW + 300)) == 2 * diary.RECENT_PAIRS
    assert dy.with_last_chat([], now=NOW + 300 + diary.RECENT_S) == []
    assert "Zahnarzt" not in dy.chat_text(now=NOW + 300)  # pushed out by newer turns


def test_each_statement_goes_to_the_person_who_said_it(tmp_path, monkeypatch):
    import json as js
    answer = js.dumps({"eintraege": [
        {"wer": "Gülfikar", "wichtig": True, "lang": "Anne sagte, ihr Knie tut weh.", "mittel": "Knie", "kurz": "Knie"},
        {"wer": "Metin", "wichtig": True, "lang": "Metin sagte, sein Auge tut weh.", "mittel": "Auge", "kurz": "Auge"},
        {"wer": "Ali", "wichtig": True, "lang": "Ali, ein Gast, erzählte von seiner Reise.", "mittel": "Reise", "kurz": "Reise"},
        {"wer": "unbekannt", "wichtig": False}]})
    seen = {}

    async def ask(prompt, *a, **k):
        seen["p"] = prompt
        return answer
    monkeypatch.setattr(diary.textmodel, "ask", ask)
    dy = diary.Diary(str(tmp_path / "d.json"))
    ok = asyncio.run(dy.write([("user", "Ben Metin, gözüm ağrıyor"), ("bot", "Geçmiş olsun")],
                              ["Gülfikar Taskiran", "Metin Taskiran"], "stimme", "k", ["m"], "u"))
    assert ok and "Gülfikar Taskiran, Metin Taskiran" in seen["p"]
    who = {e["who"]: e["lang"] for e in dy.entries()}
    assert who["Metin Taskiran"].endswith("Auge tut weh.") and "Knie" in who["Gülfikar Taskiran"]
    assert "Reise" in who["Ali"] and len(who) == 3
    metin = dy.note("Metin", now=dy.entries()[0]["t"])
    assert "Auge" in metin and "Knie" not in metin and "Reise" not in metin


def test_what_unknown_people_said_goes_to_every_talk_for_a_day(tmp_path):
    dy = diary.Diary(str(tmp_path / "d.json"))
    dy.add({"wichtig": True, "lang": "l", "mittel": "Jemand sagte, sein Fuß tut weh.", "kurz": "k"}, "", "stimme", now=NOW - 600)
    dy.add({"wichtig": True, "lang": "l", "mittel": "Metin: Auge", "kurz": "k"}, "Metin", "stimme", now=NOW - 500)
    dy.add({"wichtig": True, "lang": "l", "mittel": "Alt", "kurz": "k"}, "", "stimme", now=NOW - 2 * DAY)
    note = dy.unknown_note(now=NOW)
    assert "Fuß tut weh" in note and "Auge" not in note and "Alt" not in note and "rate nie" in note
    assert diary.parse('{"eintraege": []}') == []


def test_metin_deletes_single_entries(tmp_path):
    dy = diary.Diary(str(tmp_path / "d.json"))
    e = {"wichtig": True, "lang": "l", "mittel": "m", "kurz": "k"}
    dy.add(e, "Metin", "stimme", now=NOW - 10.123456)
    dy.add(e, "Metin", "chat", now=NOW - 5)
    t = dy.entries()[0]["t"]
    assert dy.delete([t, "x"]) == 1 and len(dy.entries()) == 1 and dy.delete([t]) == 0


def test_pinned_entries_never_fade_and_have_a_limit(tmp_path, monkeypatch):
    dy = diary.Diary(str(tmp_path / "d.json"))
    e = {"wichtig": True, "lang": "Am ersten Abend hat Metin mir ein Lied vorgesungen.", "mittel": "m", "kurz": "k"}
    old = NOW - 40 * DAY
    monkeypatch.setattr(diary.time, "time", lambda: old)
    dy.add(e, "Metin", "stimme")
    t = dy.entries()[0]["t"]
    assert dy.pin(t) == {"ok": True, "fest": True}
    monkeypatch.setattr(diary.time, "time", lambda: NOW)
    dy.add(dict(e, lang="neu"), "Metin", "chat")  # saving drops everything older than 30 days
    assert any(x.get("fest") for x in dy.entries())
    note = dy.note("Metin", now=NOW)
    assert "FESTE ERINNERUNGEN" in note and "Lied vorgesungen" in note and "am " in note
    assert "Lied" not in dy.note("Gülfikar", now=NOW)
    assert dy.pin(t) == {"ok": True, "fest": False}
    for i in range(diary.MAX_PINNED):
        dy.add(dict(e, lang=f"x{i}"), "Metin", "chat", now=NOW + i + 1)
        dy.pin(NOW + i + 1)
    assert "error" in dy.pin(NOW)  # the 21st


def test_remember_writes_at_once_and_shows_in_the_note(tmp_path):
    from app.diary import Diary
    d = Diary(str(tmp_path / "d.json"))
    assert d.remember("Metin hat am Montag um 9 Uhr Zahnarzt", "Metin")
    assert not d.remember("ok", "Metin")
    assert "Zahnarzt" in d.note("Metin")
    assert d.remember("Metin vermisst sie", "Metin", private=True)
    assert "vermisst" not in d.note("Metin") and "vermisst" in d.note("Metin", private=True)


def test_noted_plan_is_asked_once_after_it_happened(tmp_path):
    import time as _t
    from app.diary import Diary, event_time
    d = Diary(str(tmp_path / "d.json"))
    now = _t.time()
    d.remember("Metin hat heute Zahnarzt", "Metin", ask_at=now + 3600, now=now)
    assert d.followup_note("Metin", now=now) == ""            # not over yet
    note = d.followup_note("Metin", now=now + 4000)
    assert "Zahnarzt" in note and "wie es war" in note
    assert d.followup_note("Metin", now=now + 4100) == ""     # asked only once
    d.remember("Anne war beim Arzt", "Gülfikar", ask_at=now, now=now)
    assert d.followup_note("Metin", now=now + 10) == ""        # someone else's plan


def test_event_time_day_and_time():
    import time as _t
    from app.diary import event_time
    assert event_time("") == 0.0 and event_time("irgendwann") == 0.0
    t = event_time("morgen", "09:00")
    assert 0 < t - _t.time() < 3 * 86400
    assert event_time("morgen") > _t.time()


def test_archive_keeps_faded_entries_and_finds_them(tmp_path):
    import time as _t
    from app.diary import Diary, KEEP_S
    d = Diary(str(tmp_path / "d.json"))
    old = _t.time() - KEEP_S - 86400
    d.add({"wichtig": True, "privat": False, "lang": "Metin erzählte, dass Umut im Sommer nach Izmir zog",
           "mittel": "Umut zog nach Izmir", "kurz": "Umut Izmir"}, "Metin", "chat", now=old)
    d.add({"wichtig": True, "privat": False, "lang": "Wetter war schön", "mittel": "Wetter",
           "kurz": "Wetter"}, "Metin", "chat")
    assert "Izmir" not in d.note("Metin")                      # faded out of the diary
    assert "Izmir" in d.recall_note("Was weißt du über Umut?", "Metin")
    assert "nichts" in d.recall_note("Fahrrad", "Metin")
    assert d.search("Umut", "Gülfikar") == []                  # someone else's memory
    d.delete([old])
    assert d.search("Umut", "Metin") == []                     # Metin deleted it: gone for good


def test_forget_span_removes_chat_entries_pairs_and_buffer(tmp_path):
    from app.diary import Diary
    d = Diary(str(tmp_path / "d.json"))
    e = {"wichtig": True, "privat": False, "lang": "Sol sprach von anderen Frauen", "mittel": "Sol", "kurz": "Sol"}
    d.add(e, "Metin", "chat", now=1000.0)
    d.add(dict(e, lang="Anne kochte", mittel="Anne", kurz="Anne"), "Gülfikar", "stimme", now=1001.0)
    d.add(dict(e, lang="früher", mittel="früher", kurz="früher"), "Metin", "chat", now=500.0)
    d.chat_turn("hallo", "Sol Antwort", now=1002.0)
    out = d.forget_span(900.0, 1100.0)
    assert out["entries"] == 1 and out["pairs"] == 1 and out["buffer"]
    texts = [x["lang"] for x in d.archived()]
    assert "Sol sprach von anderen Frauen" not in texts and "Anne kochte" in texts and "früher" in texts
    assert d.chat_take() == []
