"""The code phrase unlocks Leyla's memory for one conversation."""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.test_live_bridge import FakeLive, _run  # noqa: E402


class CodeLive(FakeLive):
    commentary: list = []

    async def __call__(self, ws):
        try:
            async for raw in ws:
                msg = json.loads(raw)
                if msg["type"] == "session.start":
                    self.start_msg = msg
                    await ws.send(json.dumps({"type": "session.started", "session": {"id": "s"}}))
                elif msg["type"] == "session.commentary.append":
                    CodeLive.commentary.append(msg["content"])
                elif msg["type"] == "session.input_audio.append" and not self.responded:
                    self.responded = True
                    for d in [" Ley", "la", " Hab", "ibi"]:
                        await ws.send(json.dumps({"type": "session.input_transcript.delta",
                                                  "delta": d}))
                        await asyncio.sleep(0.01)
        except Exception:
            pass


async def test_code_phrase_unlocks(tmp_path):
    os.environ["CODE_PHRASE"] = "Leyla habibi"
    os.environ["MEMORY_PATH"] = str(tmp_path / "m.json")
    os.environ["ENABLE_CONTEXT"] = "false"
    (tmp_path / "m.json").write_text(json.dumps({"facts": ["Metin wohnt in Ranzel."]}))
    CodeLive.commentary = []
    fake = CodeLive()
    try:
        async def scenario(client):
            assert json.loads(await client.recv())["type"] == "ready"
            for _ in range(3):
                await client.send(b"\x00\x00" * 480)
            await asyncio.sleep(1.0)
            return True

        await _run(fake, scenario)
        assert "Ranzel" not in fake.start_msg["session"]["instructions"]
        assert any("Ranzel" in c for c in CodeLive.commentary)
    finally:
        for k in ("CODE_PHRASE", "MEMORY_PATH", "ENABLE_CONTEXT"):
            os.environ.pop(k, None)


async def test_private_list_only_after_code(tmp_path, monkeypatch):
    import json as _json
    from app import main as m
    monkeypatch.setenv("CODE_PHRASE", "Leyla habibi")
    monkeypatch.setenv("MEMORY_PATH", str(tmp_path / "memory.json"))
    bridge = m.LiveVoiceBridge()
    bridge.memory.save_all({"family": ["Person: Ayşe (Metins Schwester)."],
                            "private": ["Metins Geburtsdatum ist der 16. Juli 1981."]})
    text = bridge._instructions_with_memory()
    assert "Ayşe" in text and "16. Juli" not in text
    sent = []

    class WS:
        async def send(self, raw):
            sent.append(_json.loads(raw))

    await bridge._unlock(WS(), {})
    assert "16. Juli" in sent[0]["content"] and "privat bleiben" in sent[0]["content"]
