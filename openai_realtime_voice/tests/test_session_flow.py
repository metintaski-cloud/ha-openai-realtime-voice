"""The real session flow against a fake GPT Live server: ready, audio both ways, phases,
tools (and who may use them), quota error, hang up reasons."""
import asyncio
import base64
import json
import os
import socket
import sys

import pytest
import websockets

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OPENAI_API_KEY", "test")

from app import main as m  # noqa: E402

LOUD = (b"\x10\x27" * 480)  # 20 ms of a loud signal (peak 10000)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def b64(pcm: bytes) -> str:
    return base64.standard_b64encode(pcm).decode("ascii")


@pytest.fixture
def env(tmp_path, monkeypatch):
    for k, v in {"ENABLE_MEMORY": "false", "ENABLE_CONTEXT": "false", "GREETING_WORDS": "",
                 "MEMORY_PATH": str(tmp_path / "memory.json"), "CODE_PHRASE": "sesam",
                 "ENABLE_WEB_SEARCH": "false", "RECORD_FALSE_WAKES": "false"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    return tmp_path


class FakeLive:
    """Plays the GPT Live side: answers session.start, then runs a script of events."""

    def __init__(self, script=None):
        self.script = script
        self.received = []
        self.port = free_port()
        self.server = None

    async def handler(self, ws):
        async for raw in ws:
            event = json.loads(raw)
            self.received.append(event)
            if event["type"] == "session.start":
                await ws.send(json.dumps({"type": "session.started",
                                          "session": {"id": "s1", "model": "fake"}}))
                if self.script:
                    asyncio.create_task(self.script(ws, self))
            elif event["type"] == "session.close":
                await ws.send(json.dumps({"type": "session.closed", "reason": "client"}))
                await ws.close()

    async def __aenter__(self):
        self.server = await websockets.serve(self.handler, "127.0.0.1", self.port)
        os.environ["OPENAI_LIVE_URL"] = f"ws://127.0.0.1:{self.port}"
        return self

    async def __aexit__(self, *a):
        self.server.close()
        await self.server.wait_closed()


class Bridge:
    def __init__(self):
        self.bridge = m.LiveVoiceBridge()
        self.port = free_port()

    async def __aenter__(self):
        self.server = await websockets.serve(self.bridge.handle_client, "127.0.0.1", self.port)
        return self

    async def __aexit__(self, *a):
        self.server.close()
        await self.server.wait_closed()

    def connect(self):
        return websockets.connect(f"ws://127.0.0.1:{self.port}")


async def collect(ws, until, timeout=6.0):
    """Read client messages until until(msg) is true; return everything received."""
    got = []
    async def read():
        async for msg in ws:
            got.append(msg)
            if until(msg):
                return
    try:
        await asyncio.wait_for(read(), timeout)
    except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed):
        pass
    return got


def phases(got):
    return [json.loads(g)["phase"] for g in got if isinstance(g, str) and '"phase"' in g]


async def test_ready_then_audio_both_ways_with_replying_phase(env):
    async def script(ws, fake):
        await asyncio.sleep(0.2)
        await ws.send(json.dumps({"type": "session.input_transcript.delta", "delta": "Hallo"}))
        for _ in range(10):
            await ws.send(json.dumps({"type": "session.output_audio.delta", "delta": b64(LOUD)}))
            await asyncio.sleep(0.02)

    async with FakeLive(script) as fake, Bridge() as b:
        async with b.connect() as client:
            first = json.loads(await asyncio.wait_for(client.recv(), 5))
            assert first == {"type": "ready"}
            await client.send(b"\x01\x02" * 480)  # mic audio goes to GPT Live
            got = await collect(client, lambda g: isinstance(g, bytes) and len(g) > 0)
            assert "replying" in phases(got)
            audio = b"".join(g for g in got if isinstance(g, bytes))
            assert audio and set(audio) <= set(LOUD)
        appended = [e for e in fake.received if e["type"] == "session.input_audio.append"]
        assert any(base64.b64decode(e["audio"]) == b"\x01\x02" * 480 for e in appended)


async def test_no_speech_ends_the_session_quietly(env, monkeypatch):
    monkeypatch.setattr(m, "NO_SPEECH_TIMEOUT_S", 0.5)
    async with FakeLive() as fake, Bridge() as b:
        async with b.connect() as client:
            assert json.loads(await asyncio.wait_for(client.recv(), 5))["type"] == "ready"
            got = await collect(client, lambda g: isinstance(g, str) and "disconnect" in g)
    last = json.loads([g for g in got if isinstance(g, str)][-1])
    assert last["type"] == "disconnect" and last["reason"] == "no_speech"
    assert any(e["type"] == "session.close" for e in fake.received)


async def test_speaking_keeps_the_session_open_past_the_no_speech_time(env, monkeypatch):
    monkeypatch.setattr(m, "NO_SPEECH_TIMEOUT_S", 0.6)

    async def script(ws, fake):
        await asyncio.sleep(0.2)
        await ws.send(json.dumps({"type": "session.input_transcript.delta", "delta": "Wie spät"}))

    async with FakeLive(script) as fake, Bridge() as b:
        async with b.connect() as client:
            assert json.loads(await asyncio.wait_for(client.recv(), 5))["type"] == "ready"
            got = await collect(client, lambda g: isinstance(g, str) and "disconnect" in g,
                                timeout=1.5)
    assert not any(isinstance(g, str) and "disconnect" in g for g in got)


async def test_quota_error_reaches_the_client_and_the_phone(env):
    async def script(ws, fake):
        await asyncio.sleep(0.2)
        await ws.send(json.dumps({"type": "error", "error": {"code": "insufficient_quota"}}))

    async with FakeLive(script) as fake, Bridge() as b:
        sent = []

        async def notify(title, message):
            sent.append(message)
        b.bridge.health.notify = notify
        async with b.connect() as client:
            assert json.loads(await asyncio.wait_for(client.recv(), 5))["type"] == "ready"
            got = await collect(client, lambda g: isinstance(g, str) and "insufficient_quota" in g)
        await asyncio.sleep(0.2)
    assert any('"insufficient_quota"' in g for g in got if isinstance(g, str))
    assert len(sent) == 1 and "Guthaben" in sent[0]


async def test_goodbye_from_the_backend_function_hangs_up_after_the_farewell(env, monkeypatch):
    monkeypatch.setattr(m, "GOODBYE_MAX_WAIT_S", 1.0)

    async def script(ws, fake):
        await asyncio.sleep(0.2)
        await ws.send(json.dumps({"type": "session.input_transcript.delta", "delta": "Tschüss"}))
        await ws.send(json.dumps({"type": "response.event", "event": {
            "type": "response.output_item.done",
            "item": {"type": "function_call", "name": "end_conversation", "call_id": "c1",
                     "arguments": "{}"}}}))

    async with FakeLive(script) as fake, Bridge() as b:
        async with b.connect() as client:
            assert json.loads(await asyncio.wait_for(client.recv(), 5))["type"] == "ready"
            got = await collect(client, lambda g: isinstance(g, str) and "disconnect" in g,
                                timeout=10)
    last = json.loads([g for g in got if isinstance(g, str)][-1])
    assert last["type"] == "disconnect" and last["reason"] == "user_requested_stop"
    outputs = [e for e in fake.received if e["type"] == "response.item.create"]
    assert outputs and outputs[0]["item"]["call_id"] == "c1"


async def test_failed_connection_to_openai_is_counted_for_the_phone(env, monkeypatch):
    monkeypatch.setenv("OPENAI_LIVE_URL", f"ws://127.0.0.1:{free_port()}")  # nobody listens
    async with Bridge() as b:
        counted = []

        async def failed(error=""):
            counted.append(error)
        b.bridge.health.openai_failed = failed
        async with b.connect() as client:
            got = await collect(client, lambda g: False, timeout=2.0)
        await asyncio.sleep(0.2)
    assert counted and not any(isinstance(g, str) and "ready" in g for g in got)


# ---- tools: who may use them, errors and timeouts ----------------------------------------

class Sink:
    def __init__(self):
        self.sent = []

    async def send(self, data):
        self.sent.append(json.loads(data))

    def result(self):
        out = [e for e in self.sent if e["type"] == "response.item.create"]
        return json.loads(out[-1]["item"]["output"]) if out else None


async def call(bridge, name, args, state=None, call_id="c1"):
    sink = Sink()
    q: asyncio.Queue = asyncio.Queue()
    event = {"type": "response.output_item.done", "item": {
        "type": "function_call", "name": name, "call_id": call_id,
        "arguments": json.dumps(args)}}
    await bridge._handle_backend_event(event, sink, q, state if state is not None else {})
    for t in list(bridge._background):
        await t
    return sink, q


async def test_a_tool_runs_in_the_background_and_returns_its_result(env):
    bridge = m.LiveVoiceBridge()

    async def run(args):
        return {"ok": args["x"]}
    bridge._tools["lampen"] = {"label": "T", "timeout": 1.0, "run": run, "error": "kaputt"}
    sink, _ = await call(bridge, "lampen", {"x": 5})
    assert sink.result() == {"ok": 5}
    assert sink.sent[-1] == {"type": "response.create"}


async def test_a_failing_or_slow_tool_returns_a_friendly_error(env):
    bridge = m.LiveVoiceBridge()

    async def boom(args):
        raise RuntimeError("x")

    async def slow(args):
        await asyncio.sleep(5)
    bridge._tools["a"] = {"label": "A", "timeout": 1.0, "run": boom, "error": "Fehler A"}
    bridge._tools["b"] = {"label": "B", "timeout": 0.1, "run": slow, "error": "Fehler B"}
    assert (await call(bridge, "a", {}))[0].result() == {"error": "Fehler A"}
    assert (await call(bridge, "b", {}))[0].result() == {"error": "Fehler B"}


async def test_unknown_function_gets_an_error_not_silence(env):
    bridge = m.LiveVoiceBridge()
    sink, _ = await call(bridge, "gibtsnicht", {})
    assert "Unknown function" in sink.result()["error"]


async def test_cleanup_and_time_change_are_only_for_metin(env):
    bridge = m.LiveVoiceBridge()
    ran = []

    async def run(args):
        ran.append(args)
        return {"ok": True}
    bridge._tools["gedaechtnis_aufraeumen"]["run"] = run
    bridge._tools["technik_pruefen"]["run"] = run

    stranger = {}
    assert "Nicht erlaubt" in (await call(bridge, "gedaechtnis_aufraeumen",
                                          {"action": "streichen"}, stranger))[0].result()["error"]
    assert "Nicht erlaubt" in (await call(bridge, "technik_pruefen",
                                          {"action": "zeit_aendern"}, stranger))[0].result()["error"]
    assert ran == []
    # reading the technik status is fine for everyone
    assert (await call(bridge, "technik_pruefen", {"action": "pruefen"}, stranger))[0].result() == {"ok": True}

    metin = {"unlocked": True}
    assert (await call(bridge, "gedaechtnis_aufraeumen", {"action": "vorschlaege"}, metin))[0].result() == {"ok": True}
    assert (await call(bridge, "technik_pruefen", {"action": "zeit_aendern"}, metin))[0].result() == {"ok": True}


async def test_the_costs_tool_sends_the_thinking_phase_first(env):
    bridge = m.LiveVoiceBridge()

    async def run(args):
        return {"monat": 1}
    bridge._tools[m.costs.COSTS_TOOL["name"]]["run"] = run
    sink, q = await call(bridge, m.costs.COSTS_TOOL["name"], {})
    assert q.get_nowait() == ("phase", "thinking")
    assert sink.result() == {"monat": 1}


def test_every_registered_tool_has_a_runner_and_every_runner_a_tool_name(env):
    bridge = m.LiveVoiceBridge()
    for name, spec in bridge._tools.items():
        assert callable(spec["run"]) and spec["timeout"] > 0 and spec["error"], name
    for tool in (m.lights.LIGHTS_TOOL, m.fan.FAN_TOOL, m.vacuum.VACUUM_TOOL,
                 m.purifier.PURIFIER_TOOL, m.technik.TECHNIK_TOOL, m.cleanup.CLEANUP_TOOL,
                 m.messages.TO_METIN_TOOL, m.costs.COSTS_TOOL):
        assert tool["name"] in bridge._tools
