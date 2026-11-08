"""Tests for the long term memory."""
import asyncio
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import memory  # noqa: E402
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
    assert data["version"] == 2 and len(data["private"]) == 1


def test_states_expire(tmp_path):
    import datetime as dt
    store = memory.MemoryStore(str(tmp_path / "m.json"))
    store.save(["Person: Ayşe (Metins Schwester).",
                "Aktuell bis 10.11.2026: Ayşe ist erkältet.",
                "Aktuell bis 30.11.2026: Umut hat bald eine Prüfung."])
    assert store.expire(dt.date(2026, 11, 15)) == ["Aktuell bis 10.11.2026: Ayşe ist erkältet."]
    assert len(store.load()) == 2


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

    monkeypatch.setattr(memory.httpx, "AsyncClient", Client)
    old = {"family": [], "private": ["Geheimnis"]}
    r = await memory.summarize("k", ["m"], old, [["user", "Ben Ayşe, Metin'in ablası"]])
    assert r["private"] == ["Geheimnis"] and "Geheimnis" not in Client.prompt
    assert r["family"][0].startswith("Person: Ayşe")
    r = await memory.summarize("k", ["m"], old, [["user", "Leyla habibi, vergiss das"]],
                               unlocked=True)
    assert r["private"] == [] and "Geheimnis" in Client.prompt


def test_profiles_and_open_questions(tmp_path):
    store = memory.MemoryStore(str(tmp_path / "m.json"))
    store.save(["Person: Ayşe | Zugehörigkeit: Metins Schwester | Interessen: Kochen",
                "Person: Metin | Zugehörigkeit: wohnt hier | Geburtstag: 16.07.1981 | Kinder: keine"
                " | Arbeit: Elektroniker | Interessen: Technik",
                "Im Wohnzimmer stehen vier SwitchBot Stehlampen."])
    assert memory.parse_profile(store.load()[0]) == (
        "Ayşe", {"Zugehörigkeit": "Metins Schwester", "Interessen": "Kochen"})
    assert memory.missing_fields(store.load()[0]) == ["Geburtstag", "Kinder", "Arbeit"]
    block = store.instructions_block()
    assert "Noch offen" in block and "- Ayşe: Geburtstag, Kinder, Arbeit" in block
    assert "- Metin:" not in block.split("Noch offen")[1]
