"""Tests for the long term memory."""
import asyncio
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import memory, textmodel  # noqa: E402
from tests.test_live_bridge import FakeLive, CHUNK, _run, _collect  # noqa: E402


def test_parse_facts_json():
    assert memory.parse_facts_json('Hier: {"facts": ["A", "A", " B "]}') == ["A", "B"]
    assert memory.parse_facts_json("kein json") is None
    assert memory.parse_facts_json('{"other": 1}') is None


def test_wants_to_remember():
    assert memory.wants_to_remember("Leyla, merk dir bitte, dass ich Tee mag")
    assert memory.wants_to_remember("Bunu aklında tut")
    assert not memory.wants_to_remember("Wie spät ist es?")


def test_store_roundtrip(tmp_path):
    store = memory.MemoryStore(str(tmp_path / "m" / "memory.json"))
    assert store.load() == []
    assert store.instructions_block() == ""
    store.save(["Metin mag Tee."])
    assert store.load() == ["Metin mag Tee."]
    assert "Metin mag Tee." in store.instructions_block()


class _Handler(BaseHTTPRequestHandler):
    requests: list = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _Handler.requests.append(body)
        if body["model"] == "bad-model":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"error": "model not found"}')
            return
        out = {"output": [{"type": "message", "content": [
            {"type": "output_text",
             "text": '{"family": ["Metin trinkt gern Tee."], "private": ["X"]}'}]}]}
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


async def test_session_updates_memory_and_next_session_uses_it(tmp_path):
    server = HTTPServer(("127.0.0.1", 19993), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    os.environ["OPENAI_RESPONSES_URL"] = "http://127.0.0.1:19993/v1/responses"
    os.environ["MEMORY_PATH"] = str(tmp_path / "memory.json")
    os.environ["MEMORY_MODEL"] = "bad-model"  # falls back to the backend model
    try:
        class TalkLive(FakeLive):
            async def _reply(self, ws):
                await ws.send(json.dumps({"type": "session.input_transcript.delta",
                                          "delta": "Merk dir, ich trinke gern Tee."}))
                await ws.send(json.dumps({"type": "session.output_transcript.delta",
                                          "delta": "Alles klar!"}))
                for _ in range(3):
                    await ws.send(json.dumps({"type": "session.output_audio.delta", "delta": CHUNK}))

        fake = TalkLive()

        async def scenario(client):
            assert json.loads(await client.recv())["type"] == "ready"
            for _ in range(3):
                await client.send(b"\x00\x00" * 480)
            await _collect(client, timeout=1.0)
            return True

        await _run(fake, scenario)
        for _ in range(50):
            if os.path.exists(tmp_path / "memory.json"):
                break
            await asyncio.sleep(0.1)
        saved = json.loads((tmp_path / "memory.json").read_text(encoding="utf-8"))
        assert saved["family"] == ["Metin trinkt gern Tee."]
        assert saved["private"] == ["X"]  # no code phrase configured: nothing is locked
        assert [r["model"] for r in _Handler.requests][:2] == ["bad-model", "gpt-5.6-luna"]

        fake2 = FakeLive(respond_after=10**6)

        async def scenario2(client):
            assert json.loads(await client.recv())["type"] == "ready"
            return True

        await _run(fake2, scenario2)
        assert "Metin trinkt gern Tee." in fake2.start_msg["session"]["instructions"]
    finally:
        server.shutdown()
        for k in ("OPENAI_RESPONSES_URL", "MEMORY_PATH", "MEMORY_MODEL"):
            os.environ.pop(k, None)


def test_forget_removes_matching_facts(tmp_path):
    store = memory.MemoryStore(str(tmp_path / "m.json"))
    store.save(["Metin mag warmes Licht", "Lichtbefehle immer zweimal senden", "Mama heißt Gülfikar"])
    removed = store.forget("ZWEIMAL; gibt es nicht")
    assert removed == ["Lichtbefehle immer zweimal senden"]
    assert store.load() == ["Metin mag warmes Licht", "Mama heißt Gülfikar"]
    assert store.forget("") == [] and store.forget("null") == []


def test_add_facts(tmp_path):
    store = memory.MemoryStore(str(tmp_path / "m.json"))
    store.save(["A"], memory.PRIVATE)
    assert store.add("B; A; null") == ["B"]
    assert store.load(memory.PRIVATE) == ["A", "B"]


def test_wants_to_forget():
    assert memory.wants_to_forget("Vergiss bitte das mit dem Licht")
    assert memory.wants_to_forget("bunu unut")
    assert not memory.wants_to_forget("Mach das Licht an")


def test_no_memory_update_without_request(monkeypatch):
    os.environ["OPENAI_API_KEY"] = os.environ.get("OPENAI_API_KEY", "test")
    from app.main import LiveVoiceBridge
    bridge = LiveVoiceBridge()
    bridge.enable_memory = True
    called = []
    monkeypatch.setattr(asyncio, "create_task", lambda c: called.append(c) or c.close())
    bridge._schedule_memory_update({"dialog": [["user", "Mach das Licht an"]]})
    assert called == []


def test_code_phrase_detection():
    from app import memory as m
    assert m.code_words("Leyla habibi") == ["habibi"]
    assert m.has_code("Leila, habibi, was weißt du?", "Leyla habibi")
    assert m.has_code("ok Habibi", "Leyla habibi")
    assert not m.has_code("Leyla, ich bin Metin", "Leyla habibi")


def test_old_file_becomes_private(tmp_path):
    p = tmp_path / "m.json"
    p.write_text(json.dumps({"facts": ["Metins Geburtsdatum ist der 16. Juli 1981."]}),
                 encoding="utf-8")
    store = memory.MemoryStore(str(p))
    assert store.load(memory.FAMILY) == []
    assert store.load(memory.PRIVATE) == ["Metins Geburtsdatum ist der 16. Juli 1981."]
    assert "16. Juli" not in store.instructions_block()
    assert "16. Juli" in store.private_listing()
    store.save(["Person: Ayşe (Metins Schwester)."], memory.FAMILY)
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["version"] == 3 and len(data["private"]) == 1


def test_past_states_stay_stored_but_are_hidden_from_leyla(tmp_path):
    store = memory.MemoryStore(str(tmp_path / "m.json"))
    store.save(["Person: Ayşe (Metins Schwester).",
                "Aktuell bis 10.11.2020: Ayşe ist erkältet.",
                "Aktuell bis 30.11.2099: Umut hat bald eine Prüfung."])
    assert not hasattr(store, "expire") and len(store.load()) == 3
    block = store.instructions_block()
    assert "Ayşe ist erkältet" not in block and "Umut hat bald" not in block  # personal


def test_personal_part_only_after_the_person_is_known(tmp_path):
    store = memory.MemoryStore(str(tmp_path / "m.json"))
    store.save_all({"family": [
        "Person: Umut | Zugehörigkeit: Bruder | Stimmung: müde | Zuletzt: 14.11.: Prüfung",
        "Person: Gülfikar | Zugehörigkeit: Metins Mutter | Offen: Arzttermin",
        "Aktuell bis 30.11.2099: Umut hat bald eine Prüfung.",
        "Aktuell bis 01.01.2020: Umut war erkältet."],
        "confidential": ["Aktuell bis 30.11.2099: Gülfikar sorgt sich um ihr Knie"]})
    block = store.instructions_block()
    assert "Person: Umut | Zugehörigkeit: Bruder" in block
    assert "müde" not in block and "Prüfung" not in block and "Arzttermin" not in block
    assert "Knie" not in block
    umut = store.personal_for("Umut")
    assert "Stimmung: müde" in umut and "bald eine Prüfung" in umut and "erkältet" not in umut
    assert "Knie" not in umut
    mama = store.personal_for("Gülfikar")
    assert "Offen: Arzttermin" in mama and "Knie" in mama and "allein" in mama
    assert store.personal_for("Niemand") == ""
    assert store.profile_words()["Gülfikar"] >= {"gulfikar", "anne", "annen"}


async def test_summary_keeps_private_without_code(monkeypatch):
    class Resp:
        status_code = 200

        def __init__(self, text):
            self._t = text

        def json(self):
            return {"output_text": self._t}

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            Client.prompt = json["input"]
            return Resp('{"family": ["Person: Ayşe (Metins Schwester). Charakter: lustig."],'
                        ' "private": []}')

    monkeypatch.setattr(textmodel.httpx, "AsyncClient", Client)
    old = {"family": [], "private": ["Geheimnis"]}
    r = await memory.summarize("k", ["m"], old, [["user", "Ben Ayşe, Metin'in ablası"]])
    assert r["private"] == ["Geheimnis"] and "Geheimnis" not in Client.prompt
    assert r["family"][0].startswith("Person: Ayşe")
    r = await memory.summarize("k", ["m"], old, [["user", "Leyla habibi, vergiss das"]],
                               unlocked=True)
    assert r["private"] == [] and "Geheimnis" in Client.prompt


def test_profiles_and_open_questions(tmp_path):
    store = memory.MemoryStore(str(tmp_path / "m.json"))
    store.save(["Person: Ayşe | Zugehörigkeit: Metins Schwester | Spricht: Türkisch | Interessen: Kochen",
                "Person: Ali | Zugehörigkeit: Nachbar",
                "Person: Metin | Zugehörigkeit: wohnt hier | Geburtstag: 16.07.1981 | Kinder: keine"
                " | Arbeit: Elektroniker | Interessen: Technik",
                "Im Wohnzimmer stehen vier SwitchBot Stehlampen."])
    assert memory.parse_profile(store.load()[0]) == (
        "Ayşe", {"Zugehörigkeit": "Metins Schwester", "Spricht": "Türkisch", "Interessen": "Kochen"})
    assert memory.missing_fields(store.load()[0]) == ["Geburtstag", "Kinder", "Arbeit"]
    block = store.instructions_block()
    assert "NOCH OFFEN" in block and "• Ayşe: Geburtstag, Kinder, Arbeit" in block
    assert "• Metin:" not in block.split("NOCH OFFEN")[1]
    # Ali was only mentioned and never talked with Leyla: nothing to ask yet (Metin, 14 Nov 2026)
    assert memory.missing_fields(store.load()[1]) == [] and "• Ali:" not in block


def test_friends_and_relatives_list(tmp_path):
    store = memory.MemoryStore(str(tmp_path / "m.json"))
    store.save_all({"family": ["Person: Ayşe | Zugehörigkeit: Metins Schwester"],
                    "friends": ["Person: Ali | Zugehörigkeit: Freund von Umut | Spricht: Deutsch"]})
    assert store.load(memory.FRIENDS) == ["Person: Ali | Zugehörigkeit: Freund von Umut | Spricht: Deutsch"]
    block = store.instructions_block()
    assert "FAMILIE UND HAUSHALT\n• Person: Ayşe" in block
    assert "FREUNDE UND VERWANDTE\n• Person: Ali" in block
    assert "• Ali: Geburtstag" in block.split("NOCH OFFEN")[1]
    # an old file without the friends list still loads
    (tmp_path / "old.json").write_text('{"version": 2, "family": ["x"], "private": []}')
    assert memory.MemoryStore(str(tmp_path / "old.json")).load(memory.FRIENDS) == []


async def test_summary_keeps_friends_the_model_left_out(monkeypatch):
    class Resp:
        status_code = 200

        def json(self):
            return {"output_text": '{"family": ["Person: Metin"], "private": []}'}

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            return Resp()

    monkeypatch.setattr(textmodel.httpx, "AsyncClient", Client)
    old = {"family": ["Person: Metin"], "friends": ["Person: Ali | Zugehörigkeit: Nachbar"],
           "private": ["geheim"]}
    lists = await memory.summarize("k", ["m"], old, [["user", "hallo"]])
    assert lists["friends"] == ["Person: Ali | Zugehörigkeit: Nachbar"]
    assert lists["private"] == ["geheim"]


def test_profile_with_memory_fields_parses():
    fact = ("Person: Gülfikar | Zugehörigkeit: Metins Mutter | Stimmung: gut gelaunt | "
            "Humor: lacht über Leylas Sprüche | Zuletzt: 12.11.: Arzttermin am Montag | "
            "Offen: nachfragen, wie der Arzttermin war | Eindruck: erzählt gern von früher")
    name, fields = memory.parse_profile(fact)
    assert name == "Gülfikar"
    assert fields["Zuletzt"].startswith("12.11.") and fields["Offen"].startswith("nachfragen")
    assert len(memory._clean_facts([fact])[0]) == len(fact)
    assert "Zuletzt" in memory.PROFILE_FIELDS and "Eindruck" in memory.PROFILE_FIELDS


def test_leyla_own_list_is_stored_and_shown(tmp_path):
    store = memory.MemoryStore(str(tmp_path / "m.json"))
    store.save_all({"leyla": ["Ich necke Metin gern wegen seiner Lampen"]})
    assert store.load(memory.LEYLA) == ["Ich necke Metin gern wegen seiner Lampen"]
    assert "DEINE EIGENE GESCHICHTE" in store.instructions_block()
    assert store.load(memory.FAMILY) == []


async def test_summarize_keeps_leyla_list_when_model_wipes_it(monkeypatch):
    import httpx

    class Resp:
        status_code = 200

        def json(self):
            return {"output_text": '{"family": [], "friends": [], "private": [], "leyla": []}'}

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            return Resp()

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    old = {"family": [], "friends": [], "private": [],
           "leyla": ["a", "b", "c", "d", "e"]}
    out = await memory.summarize("k", ["m"], old, [["user", "hi"]], unlocked=True)
    assert out["leyla"] == old["leyla"]


SECRET = "Aktuell bis 20.11.2026: Gülfikar macht sich Sorgen um ihre Knie"


def test_confidential_list_is_hidden_but_given_to_leyla(tmp_path):
    from app import memory_web, todo_sync
    store = memory.MemoryStore(str(tmp_path / "m.json"))
    store.save_all({"family": ["Person: Metin"], "confidential": [SECRET]})
    assert store.load(memory.CONFIDENTIAL) == [SECRET]
    assert SECRET not in store.instructions_block()  # only once Mama is known
    store.save_all({"family": ["Person: Metin", "Person: Gülfikar | Zugehörigkeit: Metins Mutter"]})
    part = store.personal_for("Gülfikar")
    assert SECRET in part and "allein" in part and "Metin nicht" in part and "nie geraten" in part
    page = json.dumps(memory_web.snapshot(store), ensure_ascii=False)
    assert "Knie" not in page
    assert memory.CONFIDENTIAL not in todo_sync.DEFAULT_LISTS
    assert memory.CONFIDENTIAL not in memory.OPEN_KINDS
    # moving open entries on the page keeps the hidden list untouched
    assert memory_web.move_items(store, {"family": ["Person: Metin", "Person: Gülfikar | Zugehörigkeit: Metins Mutter"], "friends": [], "leyla": []})
    assert store.load(memory.CONFIDENTIAL) == [SECRET]


def test_past_confidential_entry_stays_stored_and_hidden(tmp_path):
    store = memory.MemoryStore(str(tmp_path / "m.json"))
    store.save_all({"confidential": ["Aktuell bis 01.01.2020: Gülfikar war traurig", SECRET]})
    assert len(store.load(memory.CONFIDENTIAL)) == 2
    assert "war traurig" not in store.instructions_block()


def test_forget_never_touches_confidential(tmp_path):
    store = memory.MemoryStore(str(tmp_path / "m.json"))
    store.save_all({"family": ["Gülfikar mag Knie Übungen"], "confidential": [SECRET]})
    assert store.forget("Knie") == ["Gülfikar mag Knie Übungen"]
    assert store.load(memory.CONFIDENTIAL) == [SECRET]


async def test_summarize_updates_confidential_and_keeps_it_when_left_out(monkeypatch):
    replies = ['{"family": [], "confidential": []}', '{"family": []}']
    prompts = []

    class Resp:
        status_code = 200

        def __init__(self, text):
            self.text_ = text

        def json(self):
            return {"output_text": self.text_}

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, json=None, **k):
            prompts.append(json["input"])
            return Resp(replies.pop(0))

    monkeypatch.setattr(textmodel.httpx, "AsyncClient", Client)
    old = {"family": [], "friends": [], "private": [], "leyla": [], "confidential": [SECRET]}
    out = await memory.summarize("k", ["m"], old, [["user", "dizim artık iyi"]])
    assert out["confidential"] == [SECRET]  # Leyla never deletes, not even when resolved
    assert "Knie" in prompts[0] and '"confidential"' in prompts[0]
    out = await memory.summarize("k", ["m"], old, [["user", "hallo"]])
    assert out["confidential"] == [SECRET]


def test_summary_prompt_creates_a_profile_after_leyla_asked_about_a_name():
    # Metin, 14 Nov 2026: name falls, Leyla asks, someone says who it is, the profile is made
    assert "Kette bei neuen Namen" in memory.SUMMARY_PROMPT
    assert "Person: Ali | Zugehörigkeit: Nachbar" in memory.SUMMARY_PROMPT
    assert "aus dem Fernsehen, dem Radio oder den Nachrichten" in memory.SUMMARY_PROMPT


def test_entries_not_talked_about_keep_their_wording():
    import datetime as dt
    old = {"family": ["Person: Gülfikar | Zugehörigkeit: Metins Mutter, wohnt hier | Spricht: Nur Türkisch",
                      "Die vier Stehlampen sind zugeordnet: 1 und 2 hinten (1 rechts, 2 links), 3 und 4 vorne.",
                      "Person: Umut | Zugehörigkeit: Metins Bruder | Sonst: Mag schnelle Antworten"],
           "friends": [], "private": [], "leyla": [], "confidential": []}
    new = {"family": ["Person: Gülfikar | Zugehörigkeit: Metins Mutter, wohnt hier | Spricht: Türkisch",
                      "Die Stehlampen 1 und 2 stehen hinten, 3 und 4 vorne."],
           "friends": [], "private": [], "leyla": [], "confidential": []}
    dialog = [["user", "Wie spät ist es? Wie wird das Wetter morgen? Erzähl mir einen Witz."],
              ["bot", "Es ist 22 Uhr. Metin gelince ev bir başka oluyor."]]
    out, undone = memory.keep_untouched(old, new, dialog, dt.date(2026, 11, 14))
    assert out["family"] == old["family"] and undone == 3


def test_nothing_is_deleted_or_overwritten_and_new_entries_pass():
    import datetime as dt
    old = {"family": ["Person: Umut | Zugehörigkeit: Metins Bruder",
                      "Person: Gülfikar | Zugehörigkeit: Metins Mutter | Stimmung: ruhig",
                      "Aktuell bis 01.11.2026: Metin ist erkältet.",
                      "Unser Saugroboter heißt Robbi."],
           "friends": [], "private": [], "leyla": [], "confidential": []}
    new = {"family": ["Person: Umut | Zugehörigkeit: Metins Bruder | Arbeit: Lehrer",
                      "Person: Gülfikar | Zugehörigkeit: Metins Mutter | Stimmung: fröhlich"],
           "friends": ["Person: Ali | Zugehörigkeit: Nachbar"],
           "private": [], "leyla": [], "confidential": []}
    dialog = [["user", "Ich bin Umut, ich arbeite als Lehrer. Vergiss das mit dem Saugroboter."],
              ["bot", "Anne, ne güzel!"], ["user", "Ali ist unser Nachbar"]]
    out, fixed = memory.keep_untouched(old, new, dialog, dt.date(2026, 11, 14))
    assert out["family"] == ["Person: Umut | Zugehörigkeit: Metins Bruder | Arbeit: Lehrer",
                             "Person: Gülfikar | Zugehörigkeit: Metins Mutter | "
                             "Stimmung: fröhlich; davor: ruhig",
                             "Aktuell bis 01.11.2026: Metin ist erkältet.",
                             "Unser Saugroboter heißt Robbi."]
    assert out["friends"] == new["friends"]


def test_last_talk_is_added_not_replaced_and_moves_keep_everything():
    old = {k: [] for k in memory.KINDS}
    old["family"] = ["Person: Metin | Arbeit: Elektriker | Zuletzt: 14.11.: über seine Schwestern",
                     "Die Stehlampen 1 und 2 stehen hinten (1 rechts, 2 links)."]
    old["friends"] = ["Person: Ali | Zugehörigkeit: unklar"]
    new = {k: [] for k in memory.KINDS}
    new["family"] = ["Person: Metin | Arbeit: Elektriker | Interessen: Pizza | "
                     "Zuletzt: 14.11.: über Pizza",
                     "Die Stehlampen 1 und 2 stehen hinten, 3 und 4 vorne.",
                     "Person: Ali | Zugehörigkeit: Cousin"]
    dialog = [["user", "Hier ist Metin. Mein Lieblingsessen ist Pizza. Ali ist mein Cousin, "
                       "die Stehlampen 3 und 4 stehen vorne."]]
    out, _ = memory.keep_untouched(old, new, dialog)
    assert out["family"][0] == ("Person: Metin | Arbeit: Elektriker | Zuletzt: 14.11.: über Pizza; "
                                "davor: 14.11.: über seine Schwestern | Interessen: Pizza")
    assert "Die Stehlampen 1 und 2 stehen hinten (1 rechts, 2 links)." in out["family"]
    assert "Die Stehlampen 1 und 2 stehen hinten, 3 und 4 vorne." in out["family"]
    assert "Person: Ali | Zugehörigkeit: Cousin; davor: unklar" in out["family"]
    assert out["friends"] == []


def test_code_phrase_counts_as_metin_talking():
    import datetime as dt
    old = {k: [] for k in memory.KINDS}
    old["family"] = ["Person: Metin | Zugehörigkeit: Sohn | Stimmung: müde"]
    new = {k: [] for k in memory.KINDS}
    new["family"] = ["Person: Metin | Zugehörigkeit: Sohn | Stimmung: gut gelaunt"]
    dialog = [["user", "Mir geht es heute richtig gut"]]
    assert memory.keep_untouched(old, new, dialog, dt.date(2026, 11, 14))[0]["family"] == old["family"]
    assert memory.keep_untouched(old, new, dialog, dt.date(2026, 11, 14), metin_known=True)[0][
        "family"] == ["Person: Metin | Zugehörigkeit: Sohn | Stimmung: gut gelaunt; davor: müde"]


def test_profile_merge_does_not_repeat_what_the_new_value_says():
    old = ("Person: Metin | Arbeit: Elektriker; arbeitet in Früh- und Spätschicht; davor: "
           "Elektriker; arbeitet in Früh- und Spätschicht | Stimmung: müde")
    new = ("Person: Metin | Arbeit: Elektriker; arbeitet in Früh- und Spätschicht; hat die "
           "Gedächtnis App gebaut | Stimmung: gut gelaunt")
    merged = memory._merge_profile(old, new)
    assert merged.count("davor") == 1  # only Stimmung keeps its history
    assert "Stimmung: gut gelaunt; davor: müde" in merged
    keep = memory._merge_profile("Person: X | Arbeit: Bäcker", "Person: X | Arbeit: Maurer")
    assert "Maurer; davor: Bäcker" in keep  # real information is still never lost
