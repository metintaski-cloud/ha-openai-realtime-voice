"""Tests for the GPT Live bridge, using a scripted fake GPT Live server."""
import asyncio
import base64
import json
import os
import sys

import pytest
import websockets
from websockets.asyncio.server import serve as ws_serve

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

LIVE_PORT = 19991
BRIDGE_PORT = 19992
CHUNK = base64.standard_b64encode(b"\x10\x27" * 480).decode("ascii")  # 20 ms, loud
QUIET = base64.standard_b64encode(b"\x05\x00" * 2400).decode("ascii")  # 100 ms, near silent


def _env():
    os.environ["OPENAI_API_KEY"] = "test"
    os.environ["OPENAI_LIVE_URL"] = f"ws://127.0.0.1:{LIVE_PORT}"
    os.environ["WEBSOCKET_PORT"] = str(BRIDGE_PORT)
    os.environ["WEBSOCKET_HOST"] = "127.0.0.1"


class FakeLive:
    def __init__(self, goodbye=False, respond_after=2, chunks=10, quiet_first=0):
        self.quiet_first = quiet_first
        self.goodbye = goodbye
        self.respond_after = respond_after
        self.chunks = chunks
        self.start_msg = None
        self.appends = 0
        self.responded = False
        self.received = []

    async def __call__(self, ws):
        try:
            async for raw in ws:
                msg = json.loads(raw)
                self.received.append(msg["type"])
                t = msg["type"]
                if t == "session.start":
                    self.start_msg = msg
                    await ws.send(json.dumps({
                        "type": "session.started",
                        "session": {"id": "s1", "model": msg["session"]["model"]},
                    }))
                elif t == "session.input_audio.append":
                    self.appends += 1
                    if not self.responded and self.appends >= self.respond_after:
                        self.responded = True
                        asyncio.create_task(self._reply(ws))
                elif t == "session.close":
                    await ws.send(json.dumps({"type": "session.closed", "reason": "close_requested",
                                              "usage": {"seconds": 3}}))
                    await ws.close()
                    return
                elif t == "response.item.create":
                    pass
        except Exception:
            pass

    async def _reply(self, ws):
        for _ in range(self.quiet_first):
            await ws.send(json.dumps({"type": "session.output_audio.delta", "delta": QUIET}))
            await asyncio.sleep(0.005)
        await ws.send(json.dumps({"type": "session.delegation.created",
                                  "delegation": {"id": "d1", "target": "responses"}}))
        if self.goodbye:
            await ws.send(json.dumps({"type": "response.event", "delegation_id": "d1", "event": {
                "type": "response.output_item.done",
                "item": {"type": "function_call", "name": "end_conversation",
                         "call_id": "call_1", "arguments": "{\"reason\":\"user_requested_stop\"}"}}}))
        for _ in range(self.chunks):
            await ws.send(json.dumps({"type": "session.output_audio.delta", "delta": CHUNK,
                                      "start_ms": 0, "end_ms": 20}))
            await asyncio.sleep(0.005)


async def _run(fake, scenario, **overrides):
    _env()
    import importlib
    import app.main as m
    importlib.reload(m)
    for k, v in overrides.items():
        setattr(m, k, v)
    bridge = m.LiveVoiceBridge()
    live = ws_serve(fake, "127.0.0.1", LIVE_PORT)
    async with live:
        bridge_server = websockets.serve(bridge.handle_client, "127.0.0.1", BRIDGE_PORT)
        async with bridge_server:
            async with websockets.connect(f"ws://127.0.0.1:{BRIDGE_PORT}") as client:
                return await scenario(client)


async def _collect(client, until_type=None, timeout=8.0):
    texts, audio = [], 0
    loop = asyncio.get_event_loop()
    end = loop.time() + timeout
    try:
        while loop.time() < end:
            msg = await asyncio.wait_for(client.recv(), timeout=end - loop.time())
            if isinstance(msg, bytes):
                audio += len(msg)
            else:
                texts.append(json.loads(msg))
                if until_type and texts[-1].get("type") == until_type:
                    break
    except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed):
        pass
    return texts, audio


async def test_happy_flow_audio_and_phases():
    fake = FakeLive()

    async def scenario(client):
        first = json.loads(await client.recv())
        assert first == {"type": "ready"}
        for _ in range(3):
            await client.send(b"\x00\x00" * 480)
        texts, audio = await _collect(client, timeout=2.5)
        return texts, audio

    texts, audio = await _run(fake, scenario)
    phases = [t["phase"] for t in texts if t.get("type") == "phase"]
    assert "thinking" in phases and "replying" in phases
    assert phases.index("thinking") < phases.index("replying")
    assert audio >= 9 * 960
    start = fake.start_msg["session"]
    assert start["model"] == "gpt-live-1"
    assert start["audio"]["format"] == {"type": "audio/pcm", "rate": 24000}
    assert start["delegation"]["type"] == "responses"
    tool_names = [t.get("name") or t.get("type") for t in start["delegation"]["responses"]["tools"]]
    assert "end_conversation" in tool_names and "web_search" in tool_names
    assert fake.appends >= 3


async def test_end_conversation_sends_disconnect_and_closes_session():
    fake = FakeLive(goodbye=True)

    async def scenario(client):
        assert json.loads(await client.recv())["type"] == "ready"
        for _ in range(3):
            await client.send(b"\x00\x00" * 480)
        return await _collect(client, until_type="disconnect", timeout=10)

    texts, audio = await _run(fake, scenario)
    assert any(t.get("type") == "disconnect" for t in texts)
    assert audio >= 9 * 960  # farewell audio played before the disconnect
    await asyncio.sleep(0.2)
    assert "response.item.create" in fake.received
    assert "session.close" in fake.received


async def test_interrupt_message_is_accepted():
    fake = FakeLive(respond_after=10**6)

    async def scenario(client):
        assert json.loads(await client.recv())["type"] == "ready"
        await client.send(json.dumps({"type": "interrupt"}))
        await client.send(b"\x00\x00" * 480)
        await asyncio.sleep(0.3)
        return True

    assert await _run(fake, scenario)
    assert fake.appends >= 1


async def test_setup_error_closes_client_without_ready():
    class Broken:
        async def __call__(self, ws):
            await ws.recv()
            await ws.send(json.dumps({"type": "error", "error": {"message": "bad model"}}))
            await asyncio.sleep(0.5)

    async def scenario(client):
        texts, _ = await _collect(client, timeout=3)
        return texts

    texts = await _run(Broken(), scenario)
    assert not any(t.get("type") == "ready" for t in texts)


async def test_quiet_output_is_not_forwarded():
    fake = FakeLive(quiet_first=20, chunks=0)

    async def scenario(client):
        assert json.loads(await client.recv())["type"] == "ready"
        for _ in range(3):
            await client.send(b"\x00\x00" * 480)
        return await _collect(client, timeout=2.0)

    texts, audio = await _run(fake, scenario)
    assert audio == 0
    assert not any(t.get("phase") == "replying" for t in texts)


async def test_silence_pump_keeps_input_running():
    fake = FakeLive(respond_after=10**6)

    async def scenario(client):
        assert json.loads(await client.recv())["type"] == "ready"
        await asyncio.sleep(1.0)  # client sends nothing, like a muted mic
        return True

    assert await _run(fake, scenario)
    assert fake.appends >= 3


async def test_idle_timeout_ends_session():
    fake = FakeLive(respond_after=10**6)

    async def scenario(client):
        assert json.loads(await client.recv())["type"] == "ready"
        return await _collect(client, until_type="disconnect", timeout=5)

    texts, _ = await _run(fake, scenario, IDLE_TIMEOUT_S=1.0)
    assert any(t.get("type") == "disconnect" for t in texts)
    await asyncio.sleep(0.2)
    assert "session.close" in fake.received


def test_contains_goodbye():
    import app.main as m
    assert m.contains_goodbye("Okay, danke. Tschüss!")
    assert m.contains_goodbye("Teşekkürler, hoşça kal")
    assert m.contains_goodbye("güle  güle")
    assert not m.contains_goodbye("Wie wird das Wetter morgen?")
    assert m.contains_goodbye("Alles klar, mach\u2019s gut!")
    assert m.contains_goodbye("Tschu\u0308ss")  # decomposed umlaut
    assert m.contains_goodbye("Okay, bis dann")
    assert not m.contains_goodbye("Es regnet bis dann wieder die Sonne kommt", from_user=False)


async def test_user_goodbye_transcript_ends_session():
    class GoodbyeLive(FakeLive):
        async def _reply(self, ws):
            await ws.send(json.dumps({"type": "session.input_transcript.delta", "delta": "Danke, tschü"}))
            await ws.send(json.dumps({"type": "session.input_transcript.delta", "delta": "ss!"}))
            for _ in range(5):
                await ws.send(json.dumps({"type": "session.output_audio.delta", "delta": CHUNK}))
                await asyncio.sleep(0.005)

    fake = GoodbyeLive()

    async def scenario(client):
        assert json.loads(await client.recv())["type"] == "ready"
        for _ in range(3):
            await client.send(b"\x00\x00" * 480)
        return await _collect(client, until_type="disconnect", timeout=10)

    texts, audio = await _run(fake, scenario)
    assert any(t.get("type") == "disconnect" for t in texts)
    assert audio >= 4 * 960


async def test_barge_in_stops_queued_reply():
    class BargeLive(FakeLive):
        async def _reply(self, ws):
            for _ in range(150):  # about 3 s of audio sent at once, queued in the bridge
                await ws.send(json.dumps({"type": "session.output_audio.delta", "delta": CHUNK}))
            await asyncio.sleep(0.6)  # GPT Live stops sending, the user talks
            await ws.send(json.dumps({"type": "session.input_transcript.delta",
                                      "delta": "Moment"}))

    fake = BargeLive(respond_after=2)

    async def scenario(client):
        assert json.loads(await client.recv())["type"] == "ready"
        for _ in range(3):
            await client.send(b"\x00\x00" * 480)
        return await _collect(client, timeout=3.0)

    texts, audio = await _run(fake, scenario)
    assert any(t.get("type") == "interrupt" for t in texts)
    total = 150 * len(base64.b64decode(CHUNK))
    assert audio < total * 0.6


async def test_waits_for_speech_before_greeting():
    os.environ.pop("GREETING_WORDS", None)
    fake = FakeLive(respond_after=10**6)

    async def scenario(client):
        assert json.loads(await client.recv())["type"] == "ready"
        await asyncio.sleep(0.2)
        return True

    await _run(fake, scenario)
    assert fake.start_msg["session"]["input"][0]["role"] == "developer"
    assert "kein Kompliment" in fake.start_msg["session"]["input"][0]["content"][0]["text"]
    assert "session.commentary.append" in fake.received


async def test_greeting_can_be_disabled():
    os.environ["GREETING_WORDS"] = ""
    try:
        fake = FakeLive(respond_after=10**6)

        async def scenario(client):
            assert json.loads(await client.recv())["type"] == "ready"
            await asyncio.sleep(0.2)
            return True

        await _run(fake, scenario)
        assert "input" not in fake.start_msg["session"]
        assert "session.commentary.append" not in fake.received
    finally:
        os.environ.pop("GREETING_WORDS", None)


def test_greeting_words_and_language():
    import app.main as m
    assert m.parse_greeting_words(None)[2] == "Selamünaleyküm"
    assert m.parse_greeting_words("") == []
    assert "Selamünaleyküm" in m.greeting_instruction("Selamünaleyküm")
    assert "kein Kompliment" in m.greeting_instruction("Hallo")
    seen = {m.pick_greeting(["Hallo", "Merhaba"], 20) for _ in range(200)}
    assert {"Hallo", "Merhaba", "Guten Abend", "İyi akşamlar"} <= seen
