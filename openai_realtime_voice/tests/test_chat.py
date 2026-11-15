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
    assert "stellst du meist eine Frage" in ins and "von dir aus" in ins
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
    assert "fast immer aus" in chat.CHAT_STYLE


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
    assert "Wort für Wort" in chat.speak_prompt("Hallo du") and "Hallo du" in chat.speak_prompt("Hallo du")


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

    async def fake_answer(api_key, models, rules, store, history, message, url, lights):
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
