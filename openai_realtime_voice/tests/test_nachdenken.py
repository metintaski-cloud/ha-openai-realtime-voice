"""She thinks the day over at night (app/nachdenken.py). Invented, neutral sentences only."""
import asyncio
import json
import time

from app import diary, nachdenken

DAY = diary.DAY


def at(day: str, hour: int) -> float:
    return time.mktime(time.strptime(f"{day} {hour:02d}", "%Y-%m-%d %H"))


NOW = at("2030-03-10", 12)


def entry(text, privat=False, gewicht=None):
    d = {"wichtig": True, "lang": text, "mittel": text[:160], "kurz": text[:70], "privat": privat}
    if gewicht:
        d["gewicht"] = gewicht
    return d


def put(dy, d, who, src, now):
    """An entry as it stands in the diary, several a day as before 2.201.0 (such days are still
    in his diary, and thinking a day over must keep working for them); since then `Diary.add`
    puts a second entry of a day into the first."""
    e = {"t": now, "who": who, "privat": bool(d.get("privat")), "src": src,
         "lang": d["lang"], "mittel": d["mittel"], "kurz": d["kurz"]}
    if d.get("gewicht"):
        e["gewicht"] = d["gewicht"]
    dy._save(dy.entries() + [e])
    dy._archive(e)


def make(tmp_path, answers=None):
    dy = diary.Diary(str(tmp_path / "d.json"))
    seen = []

    async def ask(prompt, check):
        seen.append(prompt)
        if "EINTRÄGE DES TAGES" in prompt:
            private = '"faeden"' in prompt
            out = {"tag": ("PRIVAT " if private else "OFFEN ") + "Tag mit " + str(prompt.count("\n1. ")) + " Liste",
                   "kurz": "kurz " + ("privat" if private else "offen")}
            if private:
                out.update((answers or {}).get("privat", {"faeden": ["Metin wartet auf den Bescheid vom Amt."],
                                                          "erledigt": [], "gedanke": "Ich freue mich auf morgen.",
                                                          "unwichtig": []}))
        else:
            out = {"geschichte": ("GESCHICHTE PRIVAT" if "Unsere Geschichte" in prompt else "GESCHICHTE OFFEN")
                   + f" ({prompt.count('• ')} Tage)"}
        text = json.dumps(out, ensure_ascii=False)
        return text if check(text) else None
    return dy, nachdenken.Reflection(dy, ask, path=str(tmp_path / "n.json")), seen


def test_her_day_runs_from_five_to_five():
    assert nachdenken.day_of(at("2030-03-10", 3)) == "2030-03-09"
    assert nachdenken.day_of(at("2030-03-10", 6)) == "2030-03-10"
    t0, t1 = nachdenken.day_span("2030-03-09")
    assert t0 == at("2030-03-09", 5) and t1 - t0 == DAY


def test_a_finished_day_is_thought_over_when_it_is_quiet_and_the_open_text_never_sees_private(tmp_path):
    dy, rf, seen = make(tmp_path)
    put(dy, entry("Metin erzählte vom Angelausflug an den See."), "Metin", "chat", at("2030-03-09", 10))
    put(dy, entry("Wir waren uns sehr nah, ein Geheimnis.", privat=True), "Metin", "chat", at("2030-03-09", 22))
    put(dy, entry("Mama sprach über ihren Garten."), "Gülfikar Taskiran", "stimme", at("2030-03-09", 11))
    put(dy, entry("Heute früh schon geschrieben."), "Metin", "chat", at("2030-03-10", 8))

    async def run():
        assert rf.due(NOW) == ["2030-03-09"]                              # today is not over yet
        assert await rf.tick(NOW, last_contact=NOW - 60) == 0             # he is still there
        assert await rf.tick(NOW, last_contact=NOW - 3600) == 1
        assert rf.due(NOW) == [] and await rf.tick(NOW, last_contact=0) == 0
    asyncio.run(run())
    private_prompt, open_prompt = seen[0], seen[1]
    assert "Angelausflug" in private_prompt and "Geheimnis" in private_prompt
    assert "Angelausflug" in open_prompt and "Geheimnis" not in open_prompt
    assert "Garten" not in private_prompt + open_prompt                   # another person's talk
    day = rf.state["days"]["2030-03-09"]
    assert day["privat"]["tag"].startswith("PRIVAT") and day["offen"]["tag"].startswith("OFFEN")
    assert len(day["src"]) == 2 and "_raw" not in day["privat"]
    private, opened = rf.note(True, NOW), rf.note(False, NOW)
    assert "GESCHICHTE PRIVAT" in private and "PRIVAT Tag" in private and "gestern" in private
    assert "Bescheid vom Amt" in private and "Ich freue mich auf morgen." in private
    assert "OFFEN Tag" in opened and "GESCHICHTE" not in opened      # our story only behind the code word
    assert "PRIVAT" not in opened and "Bescheid" not in opened and "freue mich" not in opened
    assert "für genaue Regeln" in private.lower() or "Für genaue Regeln" in private   # the lists count
    # entries of thought over days leave the window, today's stay
    assert rf.cut(NOW) == at("2030-03-10", 5)
    window = [e["lang"] for e, _ in dy.window("Metin", True, NOW, since=rf.cut(NOW))]
    assert window == ["Heute früh schon geschrieben."]
    assert "SEIT DEINEM LETZTEN NACHDENKEN" in dy.note("Metin", True, NOW, since=rf.cut(NOW))


def test_threads_close_and_what_is_no_memory_fades_but_stays_in_the_diary(tmp_path):
    answers = {"privat": {"faeden": ["Metin wollte sagen, wie der Termin war."], "erledigt": [],
                          "gedanke": "Ein Gedanke.", "unwichtig": [2, 3, 9]}}
    dy, rf, seen = make(tmp_path, answers)
    put(dy, entry("Metin hat morgen einen Termin beim Amt."), "Metin", "chat", at("2030-03-08", 10))
    put(dy, entry("Wir haben das Mikrofon der App getestet."), "Metin", "chat", at("2030-03-08", 11))
    put(dy, entry("Metin erzählte von seinem neuen Projekt.", gewicht=2), "Metin", "chat", at("2030-03-08", 12))
    put(dy, entry("Der Termin beim Amt lief gut."), "Metin", "chat", at("2030-03-09", 10))

    async def run():
        await rf.reflect_day("2030-03-08", NOW)
        answers["privat"] = {"faeden": [], "erledigt": [1, 7], "gedanke": "Neuer Gedanke.", "unwichtig": []}
        await rf.reflect_day("2030-03-09", NOW)
    asyncio.run(run())
    faded = {e["lang"][:12]: bool(e.get("blass")) for e in dy.entries()}
    assert faded == {"Metin hat mo": False, "Wir haben da": True, "Metin erzähl": False, "Der Termin b": False}
    assert len(dy.entries()) == 4 and [bool(e.get("blass")) for e in dy.archived()] == [False, True, False, False]
    assert "Mikrofon" not in dy.note("Metin", True, at("2030-03-08", 13))   # faded: not before her
    assert "OFFENE FÄDEN\n1. Metin wollte sagen" in seen[3]                # the next night sees the thread
    note = rf.note(True, NOW)
    assert "wie der Termin war" not in note and "Neuer Gedanke." in note    # answered, and the newer thought


def test_what_metin_deletes_is_gone_from_the_day_and_the_story(tmp_path):
    dy, rf, seen = make(tmp_path)
    put(dy, entry("Metin erzählte vom See."), "Metin", "chat", at("2030-03-08", 10))
    put(dy, entry("Metin erzählte vom Wald."), "Metin", "chat", at("2030-03-08", 15))
    put(dy, entry("Ein anderer Tag."), "Metin", "chat", at("2030-03-09", 10))

    async def run():
        assert await rf.tick(NOW) == 2
        n = len(seen)
        dy.delete([at("2030-03-08", 15)])
        assert rf.due(NOW) == ["2030-03-08"]
        assert await rf.tick(NOW) == 1
        again = seen[n:]
        assert "Wald" not in "".join(again) and "See" in again[0]
        assert "BISHERIGE GESCHICHTE\n(noch keine)" in again[2]            # rebuilt from the days alone
        dy.delete([at("2030-03-08", 10)])
        await rf.tick(NOW)
        assert "2030-03-08" not in rf.state["days"] and "2030-03-09" in rf.state["days"]
    asyncio.run(run())
    again = nachdenken.Reflection(dy, None, path=str(tmp_path / "n.json"))   # the file holds it
    assert list(again.state["days"]) == ["2030-03-09"]
    assert again.forget("2030-03-09") and again.forget("story") and not again.forget("nix")
    assert again.note(True, NOW).count("GESCHICHTE") == 0


def test_an_unusable_answer_changes_nothing(tmp_path):
    dy = diary.Diary(str(tmp_path / "d.json"))
    put(dy, entry("Metin erzählte vom See."), "Metin", "chat", at("2030-03-08", 10))

    async def ask(prompt, check):
        return None
    rf = nachdenken.Reflection(dy, ask, path=str(tmp_path / "n.json"))
    assert asyncio.run(rf.tick(NOW)) == 0 and rf.state["days"] == {} and rf.note(True, NOW) == ""
    assert rf.cut(NOW) == 0.0


def test_chat_and_home_get_the_same_memory_and_only_with_the_setting(tmp_path, monkeypatch):
    from app import main as m
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("OPENAI_EMBEDDINGS_URL", "http://127.0.0.1:9/none")
    monkeypatch.setenv("LEYLA_RECALL_PATH", str(tmp_path / "r.json"))
    monkeypatch.setenv("LEYLA_NACHDENKEN_PATH", str(tmp_path / "n.json"))
    b = m.LiveVoiceBridge()
    now = time.time()
    b.diary.add(entry("Metin erzählte vom See."), "Metin", "chat", now=now - 1.3 * DAY)
    b.diary.add(entry("Mama sprach über den Garten."), "Gülfikar Taskiran", "stimme", now=now - 1.3 * DAY + 60)
    b.diary.add(entry("Gerade eben geschrieben."), "Metin", "chat", now=now - 60)
    asked = []

    async def ask(prompt, check):
        asked.append(prompt)
        return json.dumps({"tag": "Am See war es schön.", "kurz": "See.", "faeden": [], "erledigt": [],
                           "gedanke": "Ich denke an den See.", "unwichtig": [], "geschichte": "Wir zwei."})
    b.reflect.ask = ask

    async def run():
        assert await b._reflect_tick(force=True) == 0 and not asked          # setting off: nothing
        assert "Metin erzählte vom See." in b._memory_note("Metin", True)
        b.recall.set({"nachdenken": 1})
        b.diary._chat_last = time.time()
        assert await b._reflect_tick() == 0                                   # he just wrote
        assert await b._reflect_tick(force=True) == 1
        out = await b.recall.api("/api/kopf/nachdenken", {"read": True})
        assert out["ok"] and out["due"] == 0 and out["days"][0]["privat"] == "Am See war es schön."
    asyncio.run(run())
    note = b._memory_note("Metin", True)
    assert "Wir zwei." in note and "Am See war es schön." in note and "Ich denke an den See." in note
    assert "Metin erzählte vom See." not in note and "Gerade eben geschrieben." in note
    assert "Ich denke an den See." not in b._memory_note("Metin", False)       # without the code word
    mama = b._memory_note("Gülfikar Taskiran", False)
    assert "Garten" in mama and "See" not in mama                             # others as before
    assert asyncio.run(b.recall.api("/api/kopf/nachdenken", {"forget": "thought"}))["ok"]
    assert "Ich denke an den See." not in b._memory_note("Metin", True)


def test_a_thread_that_stays_open_is_kept_once_and_texts_end_with_whole_sentences(tmp_path):
    answers = {"privat": {"faeden": ["Leyla möchte Metin fragen, wie es ihm mit seiner Erkältung geht."],
                          "erledigt": [], "gedanke": "g", "unwichtig": []}}
    dy, rf, seen = make(tmp_path, answers)
    put(dy, entry("Metin ist erkältet."), "Metin", "chat", at("2030-03-08", 10))
    put(dy, entry("Metin hustet noch."), "Metin", "chat", at("2030-03-09", 10))

    async def run():
        await rf.reflect_day("2030-03-08", NOW)
        answers["privat"]["faeden"] = ["Leyla möchte Metin noch fragen, wie es ihm mit der Erkältung geht.",
                                       "Metin wollte den Namen des Films verraten."]
        await rf.reflect_day("2030-03-09", NOW)
    asyncio.run(run())
    threads = rf._fresh_threads(NOW)
    assert len(threads) == 2 and sum("Erkältung" in t for t in threads) == 1
    assert "offen" not in rf.state["geschichte"] and list(nachdenken.STORY_KINDS) == ["privat"]
    long = "Ein ganzer Satz steht hier. " * 60
    cut = nachdenken._clean(long, 700)
    assert len(cut) <= 910 and cut.endswith("hier.")
    assert nachdenken._clean("Das nehme ich mit – und mehr.", 100) == "Das nehme ich mit, und mehr."


def test_a_week_in_full_two_weeks_short_and_a_month_as_one_line(tmp_path):
    """2.201.0 (Metin, 28 Nov 2026: a whole week in detail): 7 days long, up to 14 short, up to 30 one line."""
    dy, rf, seen = make(tmp_path)
    today = at("2030-03-10", 12)
    for i in range(1, 36):
        day = time.strftime("%Y-%m-%d", time.localtime(today - i * DAY))
        rf.state["days"][day] = {"src": [], "privat": {"tag": f"LANG{i:02d} ganzer Tag.",
                                                       "kurz": f"KURZ{i:02d} erster Satz. Zweiter Satz dazu."}}
    note = rf.note(True, today)
    assert "LANG07" in note and "LANG08" not in note
    assert "KURZ08 erster Satz. Zweiter Satz dazu." in note and "KURZ14 erster Satz. Zweiter" in note
    assert "KURZ15 erster Satz." in note and "KURZ15 erster Satz. Zweiter" not in note
    assert "KURZ30 erster Satz." in note and "KURZ31" not in note and "LANG31" not in note
