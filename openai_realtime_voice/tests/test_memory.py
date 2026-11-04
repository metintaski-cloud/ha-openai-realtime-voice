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
            {"type": "output_text", "text": '{"facts": ["Metin trinkt gern Tee."]}'}]}]}
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
        assert saved["facts"] == ["Metin trinkt gern Tee."]
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
    store.save(["A"])
    assert store.add("B; A; null") == ["B"]
    assert store.load() == ["A", "B"]
