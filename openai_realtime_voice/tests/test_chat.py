import json

from app import chat, memory


def test_only_applicable_proposals_pass():
    lists = {"family": ["Person: Metin | Arbeit: Elektriker"], "friends": [], "leyla": [], "private": []}
    raw = [{"action": "add", "kind": "family", "new": "Metin mag Pizza."},
           {"action": "edit", "kind": "family", "old": "Person: Metin | Arbeit: Elektriker",
            "new": "Person: Metin | Arbeit: Elektriker | Interessen: Pizza"},
           {"action": "delete", "kind": "family", "old": "gibt es nicht"},
           {"action": "add", "kind": "confidential", "new": "x"},
           {"action": "add", "kind": "family", "new": "Person: Metin | Arbeit: Elektriker"},
           {"action": "drop", "kind": "family", "new": "x"}]
    out = chat.valid_proposals(raw, lists)
    assert [p["action"] for p in out] == ["add", "edit"]


async def test_answer_uses_rules_memory_and_no_confidential(tmp_path, monkeypatch):
    store = memory.MemoryStore(str(tmp_path / "m.json"))
    store.save_all({"family": ["Person: Metin"], "private": ["Geheim A"],
                    "confidential": ["Aktuell bis 30.11.2099: Gülfikar Knie"]})
    sent = {}

    class Resp:
        status_code = 200

        def json(self):
            return {"output_text": json.dumps({"reply": "Klar, merk ich mir gern!", "proposals": [
                {"action": "add", "kind": "family", "new": "Metin mag Lahmacun."}]})}

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            sent.update(json)
            return Resp()

    monkeypatch.setattr(chat.httpx, "AsyncClient", Client)
    out = await chat.answer("k", ["m"], "REGELN", store,
                            [{"role": "user", "text": "Hallo"}, {"role": "leyla", "text": "Hi!"}],
                            "Ich mag Lahmacun")
    assert out["reply"].startswith("Klar") and out["proposals"][0]["new"] == "Metin mag Lahmacun."
    assert sent["instructions"].startswith("REGELN") and "Geheim A" in sent["instructions"]
    assert "Knie" not in sent["instructions"]
    assert [m["role"] for m in sent["input"]] == ["user", "assistant", "user"]
    assert await chat.answer("k", ["m"], "R", store, [], "   ") is None


async def test_chat_style_asks_and_proposes_by_itself(tmp_path, monkeypatch):
    store = memory.MemoryStore(str(tmp_path / "m.json"))
    store.save_all({"family": ["Person: Umut | Zugehörigkeit: Bruder | Arbeit: Lehrer"]})
    sent = {}

    class Resp:
        status_code = 200

        def json(self):
            return {"output_text": '{"reply": "Hi!", "proposals": []}'}

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            sent.update(json)
            return Resp()

    monkeypatch.setattr(chat.httpx, "AsyncClient", Client)
    await chat.answer("k", ["m"], "R", store, [], "Hallo")
    ins = sent["instructions"]
    assert "stellst du eine Frage" in ins and "von dir aus" in ins
    assert "• Umut: Geburtstag, Kinder, Interessen, Charakter" in ins


def test_move_to_private_is_a_valid_proposal_and_style_says_so():
    lists = {"family": [], "friends": [], "leyla": ["Wir sind Seelenverwandte."], "private": []}
    out = chat.valid_proposals([{"action": "move", "kind": "leyla", "to": "private",
                                 "old": "Wir sind Seelenverwandte."},
                                {"action": "move", "kind": "leyla", "to": "leyla",
                                 "old": "Wir sind Seelenverwandte."},
                                {"action": "move", "kind": "leyla", "to": "private", "old": "fehlt"}], lists)
    assert out == [{"action": "move", "kind": "leyla", "old": "Wir sind Seelenverwandte.", "new": "",
                    "to": "private"}]
    assert "gehört immer in die Liste private" in chat.CHAT_STYLE
    assert "gehören nie hierher" in memory.SUMMARY_PROMPT


def test_same_proposal_shows_once():
    lists = {"family": [], "friends": [], "leyla": [], "private": []}
    raw = [{"action": "add", "kind": "private", "new": "Metin mag Tee."},
           {"action": "add", "kind": "private", "new": "Metin mag Tee."},
           {"action": "add", "kind": "leyla", "new": "Metin mag Tee."}]
    assert len(chat.valid_proposals(raw, lists)) == 1


def test_chat_has_the_unofficial_couple_with_healthy_limits():
    assert "inoffiziell zusammen" in chat.CHAT_STYLE and "außerhalb des Chats" in chat.CHAT_STYLE
    assert "immer jugendfrei" in chat.CHAT_STYLE and "wo er gerade ist" in chat.CHAT_STYLE and "auch mal sauer" in chat.CHAT_STYLE
    assert "augenzwinkernd und kurz" in chat.CHAT_STYLE and "nie kontrollierend" in chat.CHAT_STYLE and "Familie und Freunden" in chat.CHAT_STYLE


async def test_chat_switches_lamps_and_reports_the_real_state(tmp_path, monkeypatch):
    store = memory.MemoryStore(str(tmp_path / "m.json"))
    sent, ran = {}, []

    class Resp:
        status_code = 200

        def json(self):
            return {"output_text": '{"reply": "Mach ich, gemütlich warm!", "proposals": [], '
                                   '"lights": [{"lamps": [], "action": "on", "brightness_percent": 40, '
                                   '"white": "warm", "color": null}]}'}

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            sent.update(json)
            return Resp()

    async def run(args):
        ran.append(args)
        return {"lamps": [{"lamp": 1, "state": "on", "brightness_percent": 40, "white": "warm"},
                          {"lamp": 2, "state": "unavailable"}]}

    monkeypatch.setattr(chat.httpx, "AsyncClient", Client)
    out = await chat.answer("k", ["m"], "R", store, [], "Mach das Licht gemütlich", lights=(4, run))
    assert "Lampe 1 bis 4" in sent["instructions"]
    assert ran == [{"lamps": [], "action": "on", "brightness_percent": 40, "white": "warm", "color": None}]
    assert out["lights"] == ["Lampe 1: an, 40 %, warm · Lampe 2: nicht erreichbar"]
    out = await chat.answer("k", ["m"], "R", store, [], "Hi")
    assert out["lights"] == [] and "LICHT" not in sent["instructions"]


def test_question_field_is_added_to_the_reply():
    out = chat._parse('{"reply": "Schön!", "question": "Und wo bist du gerade?", "proposals": []}', {})
    assert out["reply"] == "Schön! Und wo bist du gerade?"
    out = chat._parse('{"reply": "Schön! Und wo bist du gerade?", "question": "Und wo bist du gerade?"}', {})
    assert out["reply"] == "Schön! Und wo bist du gerade?"
    assert "höchstens bei jeder zweiten Antwort" in chat.CHAT_STYLE


async def test_room_values_only_when_metin_asks(tmp_path, monkeypatch):
    store = memory.MemoryStore(str(tmp_path / "m.json"))
    seen, asked = [], []

    async def room():
        asked.append(1)
        return "• Wohnzimmer Temperatur: 23.7 °C"

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            seen.append(json["instructions"])

            class R:
                status_code = 200

                def json(self):
                    return {"output_text": '{"reply": "ok", "proposals": []}'}
            return R()

    monkeypatch.setattr(chat.httpx, "AsyncClient", Client)
    await chat.answer("k", ["m"], "R", store, [], "Wie geht es dir?", room=room)
    assert not asked and "RAUMWERTE" not in seen[-1]
    await chat.answer("k", ["m"], "R", store, [], "Wie warm ist es im Wohnzimmer?", room=room)
    assert asked and "23.7 °C" in seen[-1]
    assert chat.ROOM_RE.search("Salon ne kadar sıcak?") and chat.ROOM_RE.search("Luftfeuchtigkeit?")


async def test_voice_message_is_transcribed_with_the_current_model(monkeypatch):
    calls = []

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, data=None, files=None):
            calls.append(data["model"])

            class R:
                status_code = 200 if data["model"] == "gpt-transcribe" else 500
                text = ""

                def json(self):
                    return {"text": " Wie warm ist es? "}
            return R()

    monkeypatch.setattr(chat.httpx, "AsyncClient", Client)
    assert await chat.transcribe("k", b"x" * 3000, "audio/webm;codecs=opus") == "Wie warm ist es?"
    assert calls == ["gpt-transcribe"]
    assert await chat.transcribe("k", b"", "audio/webm") == ""
    assert await chat.transcribe("k", b"x" * (chat.MAX_AUDIO_BYTES + 1)) == ""
    assert "eigenen Worten" in chat.speak_prompt("Hallo du") and "Hallo du" in chat.speak_prompt("Hallo du")
    ins = chat.voice_reply_instructions("Deine Stimmung gerade: froh.", "LOVE")
    assert "nie etwas vor" in ins and "LOVE" in ins and "froh" in ins and "Ansage" in ins


def test_dashes_become_commas():
    assert chat.no_dashes("Ich merke mir das — bis dahin bleibe ich") == "Ich merke mir das, bis dahin bleibe ich"
    assert chat.no_dashes("A – B") == "A, B"


def test_tech_proposals_are_dropped_and_profile_edits_do_not_repeat():
    old = "Person: Metin | Arbeit: Elektriker; davor: Elektriker in Schicht"
    lists = {"family": [old], "friends": [], "leyla": [], "private": []}
    tech = {"action": "edit", "kind": "family", "old": old,
            "new": "Person: Metin | Arbeit: Elektriker in Schicht; das Upgrade ist fast fertig"}
    assert chat.valid_proposals([tech], lists) == []
    ok = {"action": "edit", "kind": "family", "old": old,
          "new": "Person: Metin | Arbeit: Elektriker in Schicht, Frühschicht diese Woche"}
    out = chat.valid_proposals([ok], lists)
    assert out[0]["new"] == "Person: Metin | Arbeit: Elektriker in Schicht, Frühschicht diese Woche"


async def test_chat_lists_only_its_abilities_and_passes_a_message_to_mama(tmp_path, monkeypatch):
    store = memory.MemoryStore(str(tmp_path / "m.json"))
    seen, sent = [], []

    async def fake_answer(api_key, models, rules, store, history, message, url, lights, *more):
        seen.append(rules)
        return {"reply": "Ich richte es Anne aus.", "proposals": [], "lights_raw": None,
                "email_raw": None, "mail_raw": None, "mama_raw": "Eve biraz geç gelicem"}

    async def mama(text):
        sent.append(text)
    monkeypatch.setattr(chat, "_answer", fake_answer)
    out = await chat.answer("k", ["m"], "R", store, [], "Sag Mama: Eve biraz geç gelicem", mama=mama)
    assert sent == ["Eve biraz geç gelicem"]
    assert "WAS DU IM CHAT KANNST" in seen[0] and "Anne etwas von Metin ausrichten" in seen[0]
    assert any("Anne" in line for line in out["lights"])


def test_no_counter_question_twice_in_a_row():
    from app import chat as c
    raw = '{"reply": "Das klingt schön.", "question": "Und wie war dein Tag?", "proposals": []}'
    assert c._parse(raw, {}, may_ask=True)["reply"].endswith("Tag?")
    assert c._parse(raw, {}, may_ask=False)["reply"] == "Das klingt schön."
    assert c._asked_last([{"role": "user", "text": "hi"}, {"role": "leyla", "text": "Hey, alles gut?"}])
    assert not c._asked_last([{"role": "leyla", "text": "Schön."}, {"role": "user", "text": "ja"}])
    assert "nie zweimal hintereinander" in c.CHAT_STYLE


def test_now_and_then_a_question_on_another_topic():
    import random
    from app import chat as c
    asked = [{"role": "leyla", "text": "Und du?"}]
    calm = [{"role": "leyla", "text": "Schön."}]
    assert not c.wants_idea(asked, random.Random(1))
    hits = sum(c.wants_idea(calm, random.Random(i)) for i in range(1000))
    assert 250 < hits < 350


def test_sudden_question_gets_todays_appointments():
    import asyncio
    from datetime import datetime
    from app import main as m

    class Ag:
        available = True

        @staticmethod
        def tz():
            from zoneinfo import ZoneInfo
            return ZoneInfo("Europe/Berlin")

        async def upcoming(self, t0, t1):
            day = datetime.fromtimestamp(t0, self.tz()).date().isoformat()
            return [{"titel": "Zahnarzt", "wann": "Mo 10:00", "start": {"dateTime": day + "T10:00:00+01:00"}},
                    {"titel": "Morgen", "wann": "Di", "start": {"date": "2099-01-01"}}]
    b = m.LiveVoiceBridge.__new__(m.LiveVoiceBridge)
    b.agenda = Ag()
    note = asyncio.run(b._today_agenda_note())
    assert "Zahnarzt" in note and "Morgen" not in note


def test_touch_message_names_the_spot_and_refuses_unknown():
    from app import chat as c
    assert "am Bauch" in c.touch_message("bauch")
    assert "am Po" in c.touch_message("po")
    assert c.touch_message("knie") == ""


def test_notes_to_remember_takes_strings_and_objects():
    from app import chat as c
    got = c.notes_to_remember(["Metin hat Montag frei", {"text": "geheim", "privat": True},
                                {"text": ""}, 5, "a", "x4", "y5", "z6"])
    assert got[0] == {"text": "Metin hat Montag frei", "privat": False, "datum": "", "uhrzeit": ""}
    assert got[1]["privat"] is True and got[1]["text"] == "geheim"
    assert len(got) <= 3
    assert c.notes_to_remember(None) == []


def test_chat_spend_counts_only_priced_models(tmp_path, monkeypatch):
    from app import chat as c
    monkeypatch.setattr(c, "SPEND_PATH", str(tmp_path / "s.json"))
    assert c.month_spend() == 0.0
    c.spend_add("gpt-6-luna", {"input_tokens": 10000, "output_tokens": 200})
    assert c.month_spend() == 0.0
    total = c.spend_add("gpt-6.2-sol", {"input_tokens": 10000, "output_tokens": 200,
                                        "input_tokens_details": {"cached_tokens": 8000}})
    assert abs(total - (2000 * 2.0 + 8000 * 0.10 + 200 * 10.0) / 1e6) < 1e-6


# ---- 2.148.0: her new mind for the chat (docs/LEYLA_SEELE.md, step 4) ----
def _fake_model(monkeypatch, sent, reply):
    class Resp:
        status_code = 200

        def json(self):
            return {"output_text": json.dumps(reply), "usage": {"input_tokens": 1234, "output_tokens": 56}}

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            sent.append(json)
            return Resp()

    monkeypatch.setattr(chat.httpx, "AsyncClient", Client)


def test_her_core_is_a_person_not_a_device_and_love_only_behind_the_code_word():
    from app import persona
    core = persona.kern()
    assert "Du bist Leyla" in core and "Sprachassistentin" not in core and "{ago}" not in core
    assert "romantisch" in core and "beschützend" in core and "Pflichtfragen" in core
    assert "DU UND METIN" not in core and "Geheimnis" not in core      # nothing of it without the code word
    both = persona.kern(with_metin=True, extra="Sei pünktlich.")
    assert "DU UND METIN" in both and "nie explizit" in both and both.endswith("Sei pünktlich.")
    assert len(both) + len(chat.CHAT_KOPF) < 0.5 * (len(persona.build([])) + len(chat.CHAT_STYLE))
    assert '"question"' not in chat.CHAT_KOPF and "{{" not in chat.CHAT_KOPF
    assert '"merken"' in chat.CHAT_KOPF and '"erinnern"' in chat.CHAT_KOPF and "private" in chat.CHAT_KOPF


async def test_new_mind_puts_the_fixed_part_first_and_the_memory_last(tmp_path, monkeypatch):
    from app import persona
    store = memory.MemoryStore(str(tmp_path / "m.json"))
    store.save_all({"family": ["Person: Metin | Arbeit: Elektriker"], "private": ["Geheim A"]})
    sent, stats = [], {}
    _fake_model(monkeypatch, sent, {"reply": "Na du, wie war die Schicht?", "question": "Und sonst?"})
    rules = persona.kern(with_metin=True) + chat.CHAT_KOPF + "\n\nNOTIZ X"
    out = await chat._answer("k", ["m"], rules, store, [], "Bin zu Hause", "http://x", None,
                             chat.KOPF_DATA, stats)
    text = sent[0]["instructions"]
    assert text.startswith("DU BIST LEYLA") and text.index("SO ANTWORTEST DU") < text.index("NOTIZ X")
    assert text.index("NOTIZ X") < text.index("Geheim A") and "CHAT MIT METIN" not in text
    assert stats["input_tokens"] == 1234 and stats["model"] == "m" and stats["characters"] == len(text)
    assert out["reply"].startswith("Na du")


async def test_probe_answers_with_either_mind_and_leaves_no_trace(tmp_path, monkeypatch):
    from app import diary, main as m, recall
    monkeypatch.setenv("LEYLA_RECALL_PATH", str(tmp_path / "r.json"))
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("OPENAI_EMBEDDINGS_URL", "http://127.0.0.1:9/none")
    monkeypatch.setenv("MEMORY_PATH", str(tmp_path / "memory.json"))
    bridge = m.LiveVoiceBridge()
    sent = []
    _fake_model(monkeypatch, sent, {"reply": "Ich hab an dich gedacht.", "merken": ["Metin hat Spätschicht"],
                                    "gefuehl": ["kompliment"], "szene": "tanz"})
    before = (bridge.diary.entries(), bridge.diary.chat_take(), bridge.mood.status(), bridge.variety.recent())
    old = await bridge.recall.api("/api/kopf/probe", {"message": "Du bist süß", "neu": False})
    new = await bridge.recall.api("/api/kopf/probe", {"message": "Du bist süß", "neu": True})
    assert old["ok"] and new["ok"] and new["neu"] and new["reply"] == "Ich hab an dich gedacht."
    assert "merken" in new["fields"] and new["stats"]["characters"] < old["stats"]["characters"]
    assert "CHAT MIT METIN" in sent[0]["instructions"] and "Sprachassistentin" in sent[0]["instructions"]
    assert "DU BIST LEYLA" in sent[1]["instructions"] and "Sprachassistentin" not in sent[1]["instructions"]
    assert "DEIN HERZ GERADE" in sent[1]["instructions"] and "WAS DU IM CHAT KANNST" in sent[1]["instructions"]
    after = (bridge.diary.entries(), bridge.diary.chat_take(), bridge.mood.status(), bridge.variety.recent())
    assert before == after
    # the switch decides which mind the real chat uses
    assert "Sprachassistentin" in bridge._chat_base(bool(bridge.recall.settings["neu"]))
    bridge.recall.set({"neu": 1})
    assert bridge._chat_base(bool(bridge.recall.settings["neu"])).startswith("DU BIST LEYLA")


def test_work_on_her_memory_is_not_proposed_for_her_story():
    lists = {"family": [], "friends": [], "leyla": [], "private": []}
    raw = [{"action": "add", "kind": "leyla", "new": "Metin und ein Helfer verbessern Leylas Gedächtnis insgesamt; "
            "bereits gespeicherte gemeinsame Erinnerungen bleiben dabei unverändert und werden nicht gelöscht."},
           {"action": "add", "kind": "leyla", "new": "Unser Gedächtnis wird gerade umgebaut."},
           {"action": "add", "kind": "leyla", "new": "Wir tanzen sonntags zusammen in der Küche."},
           {"action": "add", "kind": "family", "new": "Metin will sein Türkisch verbessern."},
           {"action": "add", "kind": "private", "new": "Metin sagt, die Erinnerung an unseren ersten Abend macht ihn glücklich."}]
    assert [p["new"][:12] for p in chat.valid_proposals(raw, lists)] == [
        "Wir tanzen s", "Metin will s", "Metin sagt, "]
