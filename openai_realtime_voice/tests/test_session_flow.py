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

from app import main as m, session_end  # noqa: E402

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
                 "ENABLE_WEB_SEARCH": "false", "RECORD_FALSE_WAKES": "false",
                 "WARM_CONNECTION": "false"}.items():
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
        self.connections = 0
        self.session_conns = []  # which connection (1, 2, ...) each session.start arrived on
        self.mute_first = False  # the first connection never answers session.start
        self.delay = 0.0         # seconds before session.start is answered

    async def handler(self, ws):
        self.connections += 1
        mine = self.connections
        async for raw in ws:
            event = json.loads(raw)
            self.received.append(event)
            if event["type"] == "session.start":
                self.session_conns.append(mine)
                if self.mute_first and mine == 1:
                    continue
                await asyncio.sleep(self.delay)
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
    monkeypatch.setattr(session_end, "NO_SPEECH_TIMEOUT_S", 0.5)
    async with FakeLive() as fake, Bridge() as b:
        async with b.connect() as client:
            assert json.loads(await asyncio.wait_for(client.recv(), 5))["type"] == "ready"
            got = await collect(client, lambda g: isinstance(g, str) and "disconnect" in g)
    last = json.loads([g for g in got if isinstance(g, str)][-1])
    assert last["type"] == "disconnect" and last["reason"] == "no_speech"
    assert any(e["type"] == "session.close" for e in fake.received)


async def test_speaking_keeps_the_session_open_past_the_no_speech_time(env, monkeypatch):
    monkeypatch.setattr(session_end, "NO_SPEECH_TIMEOUT_S", 0.6)

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


async def test_empty_credit_error_of_today_is_treated_as_quota(env):
    async def script(ws, fake):
        await asyncio.sleep(0.2)
        await ws.send(json.dumps({"type": "error", "error": {"type": "invalid_request_error", "code": "credit_balance_exhausted"}}))

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
    monkeypatch.setattr(session_end, "GOODBYE_MAX_WAIT_S", 1.0)

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


async def test_a_client_that_leaves_before_ready_is_no_session_error(env, caplog):
    """2.182.5. Seen 26 Nov 2026, 20:14: a live talk from the app was ended there 2.4 s after it connected, while the
    session was still being opened. The ready signal then met a closed socket, and that was logged as "Session error"
    with a traceback and counted as session_error, as if something of ours had failed."""
    import logging
    async with FakeLive() as fake, Bridge() as b:
        fake.delay = 0.6
        counted, ended = [], []

        async def failed(error=""):
            counted.append(error)
        b.bridge.health.openai_failed = failed
        real_end = b.bridge._end_session

        async def end(client_id, client_ws, state, end_reason, start_time):
            ended.append(dict(end_reason))
            return await real_end(client_id, client_ws, state, end_reason, start_time)
        b.bridge._end_session = end
        with caplog.at_level(logging.INFO):
            async with b.connect() as client:
                await asyncio.sleep(0.15)                      # she is still opening the session
            for _ in range(40):
                if ended:
                    break
                await asyncio.sleep(0.1)
    assert ended and ended[0]["reason"] == "client_disconnected" and ended[0].get("early"), ended
    assert not counted
    texts = [r.getMessage() for r in caplog.records]
    assert any("Client left before the session was ready" in t for t in texts)
    assert not any(r.levelno >= logging.ERROR for r in caplog.records), [t for t in texts if "rror" in t]


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
    assert "Nicht erlaubt" in (await call(bridge, "technik_pruefen",
                                          {"action": "licht_aendern"}, stranger))[0].result()["error"]
    assert "Nicht erlaubt" in (await call(bridge, "technik_pruefen",
                                          {"action": "ventilator_aendern"}, stranger))[0].result()["error"]
    assert "Nicht erlaubt" in (await call(bridge, "technik_pruefen",
                                          {"action": "nacht_aendern"}, stranger))[0].result()["error"]
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
                 m.messages.TO_METIN_TOOL, m.costs.COSTS_TOOL, bridge.planer.tool()):
        assert tool["name"] in bridge._tools


# ---- the pre opened (warm) connection -----------------------------------------------------

async def test_a_warm_connection_is_used_for_the_session(env, monkeypatch):
    monkeypatch.setenv("WARM_CONNECTION", "true")
    async with FakeLive() as fake, Bridge() as b:
        await b.bridge._open_warm()
        assert fake.connections == 1  # opened before anybody said the wake word
        async with b.connect() as client:
            assert json.loads(await asyncio.wait_for(client.recv(), 5))["type"] == "ready"
        assert fake.session_conns == [1]  # the session started on the warm connection
        await asyncio.sleep(0.2)
        assert fake.connections == 2  # and the next warm one is already on its way


async def test_a_stale_warm_connection_is_replaced_not_used(env, monkeypatch):
    monkeypatch.setenv("WARM_CONNECTION", "true")
    async with FakeLive() as fake, Bridge() as b:
        await b.bridge._open_warm()
        ws, _ = b.bridge._warm
        b.bridge._warm = (ws, m.time.monotonic() - 1000)
        async with b.connect() as client:
            assert json.loads(await asyncio.wait_for(client.recv(), 5))["type"] == "ready"
        assert 1 not in fake.session_conns


async def test_a_warm_connection_that_does_not_answer_falls_back_quickly(env, monkeypatch):
    monkeypatch.setenv("WARM_CONNECTION", "true")
    monkeypatch.setattr(m, "WARM_START_TIMEOUT_S", 0.5)
    async with FakeLive() as fake, Bridge() as b:
        fake.mute_first = True
        await b.bridge._open_warm()
        loop = asyncio.get_event_loop()
        t0 = loop.time()
        async with b.connect() as client:
            assert json.loads(await asyncio.wait_for(client.recv(), 5))["type"] == "ready"
        assert loop.time() - t0 < 3.0
        assert fake.session_conns[0] == 1 and len(fake.session_conns) == 2


async def test_without_a_warm_connection_everything_still_works(env, monkeypatch):
    monkeypatch.setenv("WARM_CONNECTION", "true")
    async with FakeLive() as fake, Bridge() as b:
        async with b.connect() as client:
            assert json.loads(await asyncio.wait_for(client.recv(), 5))["type"] == "ready"
        assert len(fake.session_conns) == 1


async def test_live_talk_from_the_app_needs_the_code_word_and_unlocks(env):
    async with FakeLive() as fake, Bridge() as b:
        async with websockets.connect(f"ws://127.0.0.1:{b.port}/app") as client:
            await client.send(json.dumps({"type": "hello", "code": "falsch"}))
            with pytest.raises(websockets.exceptions.ConnectionClosed):
                await asyncio.wait_for(client.recv(), 5)
        assert not any(e["type"] == "session.start" for e in fake.received)
        async with websockets.connect(f"ws://127.0.0.1:{b.port}/app") as client:
            await client.send(json.dumps({"type": "hello", "code": "sesam"}))
            assert json.loads(await asyncio.wait_for(client.recv(), 5)) == {"type": "ready"}
            await asyncio.sleep(0.3)
            assert getattr(client, "close", None)
        # 2.153.0: she knows it is Metin from the first moment (inside the session start), and
        # nothing about it is appended afterwards, because she does not hear while she takes notes
        start = [e for e in fake.received if e["type"] == "session.start"][-1]["session"]
        assert "Codewort dort schon eingegeben" in start["instructions"]
        assert "FÜR DIESES GESPRÄCH MIT METIN ALLEIN" in start["instructions"]
        notes = [e for e in fake.received if e["type"] == "session.commentary.append"]
        assert not any("Codewort" in e["content"] for e in notes)


async def test_mail_draft_is_only_for_metin(env):
    bridge = m.LiveVoiceBridge()
    ran = []

    async def run(args):
        ran.append(args)
        return {"ok": True}
    bridge._tools["email_entwurf"]["run"] = run
    assert "Nicht erlaubt" in (await call(bridge, "email_entwurf", {"an": "Ayşe"}, {}))[0].result()["error"]
    assert ran == []
    assert (await call(bridge, "email_entwurf", {"an": "Ayşe"}, {"unlocked": True}))[0].result() == {"ok": True}


async def test_reading_mails_is_only_for_metin(env):
    bridge = m.LiveVoiceBridge()
    ran = []

    async def run(args):
        ran.append(args)
        return {"ok": True, "anzahl": 0}
    bridge._tools["email_lesen"]["run"] = run
    blocked = (await call(bridge, "email_lesen", {"aktion": "suchen"}, {}))[0].result()
    assert "Nicht erlaubt" in blocked["error"] and ran == []
    assert (await call(bridge, "email_lesen", {"aktion": "suchen"}, {"unlocked": True}))[0].result()["ok"]


async def test_calendar_is_only_for_metin(env):
    bridge = m.LiveVoiceBridge()
    ran = []

    async def run(args):
        ran.append(args)
        return {"ok": True, "anzahl": 0}
    bridge._tools["kalender"]["run"] = run
    blocked = (await call(bridge, "kalender", {"aktion": "anzeigen"}, {}))[0].result()
    assert "Nicht erlaubt" in blocked["error"] and ran == []
    assert (await call(bridge, "kalender", {"aktion": "anzeigen"}, {"unlocked": True}))[0].result()["ok"]


def test_after_the_code_phrase_she_may_be_tender_and_no_pet_word_reminder():
    from app import main as m
    assert "Kosewörter sind jetzt erlaubt" in m.UNLOCKED_LOVE and "zweite Stimme" in m.UNLOCKED_LOVE
    bridge = m.LiveVoiceBridge.__new__(m.LiveVoiceBridge)
    state = {"unlocked": True, "dialog": [("leyla", "Schatz, mein Schatz")]}
    bridge._note_pet_words(None, state)
    assert not state.get("pet_nudged")



async def test_mood_tool_is_only_for_metin_and_sets_the_lamps(env, tmp_path):
    bridge = m.LiveVoiceBridge()
    bridge.mood.path = str(tmp_path / "mood.json")
    blocked = (await call(bridge, "laune", {"aktion": "kompliment"}, {}))[0].result()
    assert "Nicht erlaubt" in blocked["error"]
    bridge.lamp.set_mood(True)
    done = (await call(bridge, "laune", {"aktion": "kompliment"}, {"unlocked": True}))[0].result()
    assert done["ok"] and bridge.lamp.mood_low is False


async def test_moods_without_code_only_for_known_metin_and_lamps_only_in_a_real_talk(env, tmp_path):
    bridge = m.LiveVoiceBridge()
    bridge.mood.path = str(tmp_path / "mood.json")
    assert "Nicht erlaubt" in (await call(bridge, "laune", {"aktion": "erzaehlt"}, {}))[0].result()["error"]
    assert (await call(bridge, "laune", {"aktion": "erzaehlt"}, {"metin_known": True}))[0].result()["ok"]
    state = {"metin_known": True, "dialog": [("user", "Licht an")]}
    bridge._maybe_mood_lamp(state)
    assert bridge.lamp.mood_low is None
    state["dialog"] += [("leyla", "ok"), ("user", "wie geht's"), ("leyla", "gut"), ("user", "schön")]
    bridge._maybe_mood_lamp(state)
    assert bridge.lamp.mood_low is False and state["mood_lamp"]
    # 2.158.4: the name alone is no code word, so nothing of the two of them is in his note
    assert "Codewort" in m.KNOWN_WITHOUT_CODE and "kein Flirten" in m.KNOWN_WITHOUT_CODE


def test_ending_the_talk_by_words_counts_as_goodbye():
    from app import main as m
    bridge = m.LiveVoiceBridge.__new__(m.LiveVoiceBridge)
    for said in (" Leyla, das Gespräch beenden", " einfach nur beenden, das Gespräch", " konuşmayı bitir"):
        state = {"dialog": []}
        for word in said.split(" "):
            state["recent_user_text"] = (state.get("recent_user_text", "") + " " + word)[-80:]
        assert m.contains_goodbye(state["recent_user_text"]) or m.END_TALK_RE.search(state["recent_user_text"]), said
    assert not m.END_TALK_RE.search("mach den Fernseher aus")


async def test_recall_question_from_unknown_speaker_asks_who_first():
    from app import main as m
    bridge = m.LiveVoiceBridge.__new__(m.LiveVoiceBridge)
    sent = []

    async def note(ws, prefix, content):
        sent.append(prefix)
    bridge._send_note = note
    state = {"dialog": [("user", "Leyla benim nerem ağrıyordu")]}
    await bridge._maybe_ask_who_before_recall(None, state)
    await bridge._maybe_ask_who_before_recall(None, state)
    assert sent == ["recall"]
    known = {"dialog": [("user", "was tut mir weh?")], "identified": {"Metin Taskiran"}}
    await bridge._maybe_ask_who_before_recall(None, known)
    assert sent == ["recall"]
    for q in ("Wo tut es mir weh?", "Weißt du noch, was ich gesagt habe?", "hatırlıyor musun"):
        assert m.RECALL_RE.search(q), q
    assert not m.RECALL_RE.search("Mach das Licht an")


async def test_she_is_reminded_to_ask_who_is_there_and_once_more_when_no_name_comes():
    """Metin, 24 Nov 2026: asking again was only a rule of her character; now the bridge sees to it."""
    from app import main as m
    bridge = m.LiveVoiceBridge.__new__(m.LiveVoiceBridge)
    sent = []

    async def note(ws, prefix, content):
        sent.append(content)
    bridge._send_note = note
    state = {"dialog": [("user", "wie wird das Wetter"), ("bot", "Sonnig.")]}
    await bridge._maybe_ask_who(None, state)                       # second turn begins: ask
    assert sent == [m.WHO_NUDGE]
    state["dialog"] += [("user", "und morgen"), ("bot", "Regen. Wer ist denn da?")]
    await bridge._maybe_ask_who(None, state)                       # one turn after: not yet again
    assert len(sent) == 1
    state["dialog"] += [("user", "aha"), ("bot", "Ja.")]
    await bridge._maybe_ask_who(None, state)                       # two turns without a name: once more
    assert sent[-1] == m.WHO_NUDGE_AGAIN and len(sent) == 2
    state["dialog"] += [("user", "noch was"), ("bot", "Gern.")]
    await bridge._maybe_ask_who(None, state)                       # and that was it
    assert len(sent) == 2
    # she asked by herself: no first reminder, the second one two turns later
    sent.clear()
    own = {"dialog": [("user", "hallo"), ("bot", "Hallo! Mit wem spreche ich?")]}
    await bridge._maybe_ask_who(None, own)
    own["dialog"] += [("user", "mach das licht an"), ("bot", "Gemacht.")]
    await bridge._maybe_ask_who(None, own)
    assert sent == []
    own["dialog"] += [("user", "danke"), ("bot", "Gern.")]
    await bridge._maybe_ask_who(None, own)
    assert sent == [m.WHO_NUDGE_AGAIN]
    # nothing once somebody is known, by name, by the code word or by his words
    for known in ({"identified": {"Ayse"}}, {"unlocked": True}, {"metin_known": True}):
        sent.clear()
        st = dict({"dialog": [("user", "a"), ("bot", "Wer ist da?"), ("user", "b"), ("bot", "c"),
                              ("user", "d"), ("bot", "e")]}, **known)
        await bridge._maybe_ask_who(None, st)
        assert sent == []
    sent.clear()
    named = {"dialog": [("user", "ich bin Ayse"), ("bot", "Hallo"), ("user", "b"), ("bot", "c"), ("user", "d")]}
    await bridge._maybe_ask_who(None, named)
    assert sent == []


async def test_a_name_given_after_her_own_way_of_asking_counts(tmp_path, monkeypatch):
    """26 Nov 2026, 23:03. She asked with the example sentence of her character, he said his name, and two turns later
    the bridge made her ask again (Metin asked her why she asked a second time). Her question
    was not in the list of ways to ask, so the short answer did not count. All sentences here are invented."""
    from app import main as m, phrases
    for asked in ("Ich bin neugierig, wer mir da Gesellschaft leistet.", "Darf ich wissen, wer da ist?",
                  "Wie heißt du denn?", "Verrätst du mir deinen Namen?", "Sen kimsin?", "Mit wem spreche ich?"):
        assert phrases.WHO_ASKED_RE.search(asked), asked
    assert not phrases.WHO_ASKED_RE.search("Morgen wird es sonnig und warm.")
    for said, name in (("ich heiße Selin", "Selin"), ("Ich bin der Deniz", "Deniz"), ("mein Name ist Selin", "Selin")):
        assert phrases.NAME_SAID_RE.search(said).group(1) == name
    assert phrases.near("mettin", "metin") and phrases.near("medin", "metin") and phrases.near("selin", "selin")
    assert not phrases.near("martin", "metin") and not phrases.near("eli", "ela")
    monkeypatch.setenv("MEMORY_PATH", str(tmp_path / "memory.json"))
    bridge = m.LiveVoiceBridge()
    bridge.memory.save_all({"family": ["Person: Selin | Zugehörigkeit: wohnt hier", "Person: Deniz | Zugehörigkeit: Gast"]})
    handed, sent = [], []

    async def hand(ws, state, name):
        handed.append(name)
        state.setdefault("identified", set()).add(name)

    async def note(ws, prefix, content):
        sent.append(content)
    bridge._hand_over_personal, bridge._send_note = hand, note
    for answer in ("Selin", "Sellin.", "ich heiße Selin"):
        handed.clear()
        state = {"dialog": [("user", "wie wird das Wetter"), ("bot", "Sonnig. Ich bin neugierig, wer mir da Gesellschaft leistet."),
                            ("user", answer)]}
        await bridge._maybe_identify(None, state)
        assert handed == ["Selin"], (answer, handed)
        state["dialog"] += [("bot", "Schön."), ("user", "und morgen"), ("bot", "Regen."), ("user", "aha")]
        await bridge._maybe_ask_who(None, state)                    # known now: she is not made to ask again
        assert sent == []
    # two entries of the person after her question: still her question that counts
    handed.clear()
    state = {"dialog": [("bot", "Wer ist denn da?"), ("user", "äh"), ("user", "Deniz")]}
    await bridge._maybe_identify(None, state)
    assert handed == ["Deniz"]
    # without her question a single word is no name
    handed.clear()
    await bridge._maybe_identify(None, {"dialog": [("bot", "Morgen wird es sonnig."), ("user", "Selin")]})
    assert handed == []


async def test_with_frisch_the_code_word_puts_a_fresh_session_in_place_and_the_talk_goes_on(env, monkeypatch):
    """2.155.0: no notes are appended after the code word; a second GPT Live session starts
    with her knowledge and the talk so far, and what it says reaches the client."""
    from app import talk_notes
    monkeypatch.setattr(talk_notes, "FRESH_MIN_S", 0.1)
    monkeypatch.setattr(talk_notes, "FRESH_QUIET_S", 0.1)

    async def script(ws, fake):
        await asyncio.sleep(0.2)
        if len(fake.session_conns) == 1:      # the first session: he says the code word
            await ws.send(json.dumps({"type": "session.input_transcript.delta", "delta": " sesam "}))
        else:                                 # the fresh one speaks
            await asyncio.sleep(0.2)
            await ws.send(json.dumps({"type": "session.output_transcript.delta", "delta": "Da bin ich"}))
            await ws.send(json.dumps({"type": "session.output_audio.delta",
                                      "delta": base64.b64encode(b"\x10\x27" * 2400).decode()}))

    async with FakeLive(script) as fake, Bridge() as b:
        b.bridge.recall.settings["frisch"] = 1
        async with b.connect() as client:
            assert json.loads(await asyncio.wait_for(client.recv(), 5))["type"] == "ready"
            got = await collect(client, lambda msg: isinstance(msg, bytes), timeout=6.0)
            assert any(isinstance(g, bytes) for g in got)          # the fresh session is heard
            await client.send(b"\x00\x00" * 480)                   # and it gets his voice
            await asyncio.sleep(0.2)
        starts = [e["session"] for e in fake.received if e["type"] == "session.start"]
        assert len(starts) == 2 and fake.session_conns == [1, 2]
        assert "Codewort wurde richtig gesagt" in starts[1]["instructions"]
        assert talk_notes.START_HEAD.strip() in starts[1]["instructions"]
        assert "Codewort wurde richtig gesagt" not in starts[0]["instructions"]
        said = [(msg["role"], msg["content"][0]["text"]) for msg in starts[1]["input"] if msg["role"] != "developer"]
        assert ("user", "sesam") in said
        notes = [e for e in fake.received if e["type"] == "session.commentary.append"]
        assert not any("Codewort" in e["content"] for e in notes)   # nothing appended about it


async def _wake_talk(env, monkeypatch, mode, tv, heard, send_history=True, by_wake_word=True):
    """One wake at home with the microphone history sent first, as the firmware does; with
    `by_wake_word` it also says where the wake word was (leyla_voice 2.158.0)."""
    from app import wakecheck
    calls = {"shown": 0, "asked": 0}

    async def transcribe(audio, api_key, client, keywords=()):
        calls["asked"] += 1       # once per way of listening (wakecheck.WAYS)
        return heard

    async def script(ws, fake):
        await asyncio.sleep(0.3)
        await ws.send(json.dumps({"type": "session.output_audio.delta",
                                  "delta": base64.b64encode(b"\x10\x27" * 2400).decode()}))

    monkeypatch.setattr(wakecheck, "transcribe", transcribe)
    monkeypatch.setattr(wakecheck, "HEADER_WAIT_S", 0.3)
    monkeypatch.setenv("FALSE_WAKE_DIR", str(env / "false_wakes"))
    async with FakeLive(script) as fake, Bridge() as b:
        b.bridge.recall.settings["weckpruefung"] = mode
        b.bridge.record_false_wakes = True

        async def playing():
            return tv
        b.bridge.tv.playing = playing
        b.bridge._show_listening = lambda: calls.__setitem__("shown", calls["shown"] + 1)
        async with b.connect() as client:
            if send_history:
                await client.send(json.dumps({"type": "preroll", "rate": 16000, "bytes": 32000,
                                              **({"wake_ms": 300} if by_wake_word else {})}))
                for _ in range(10):
                    await client.send(b"\x05\x00" * 1600)
            got = await collect(client, lambda msg: isinstance(msg, bytes) or '"disconnect"' in str(msg), timeout=5.0)
            await asyncio.sleep(0.1)
        await asyncio.sleep(0.3)
        audio_in = [e for e in fake.received if e["type"] == "session.input_audio.append"]
    kept = sorted(p.name for p in (env / "false_wakes").glob("*.wav")) if (env / "false_wakes").exists() else []
    return got, calls, audio_in, kept


async def test_the_microphone_history_never_reaches_gpt_live_as_audio_of_the_talk(env, monkeypatch):
    got, calls, audio_in, kept = await _wake_talk(env, monkeypatch, mode=1, tv=True, heard="Hallo Leyla")
    texts = [json.loads(g)["type"] for g in got if isinstance(g, str)]
    assert "ready" in texts and any(isinstance(g, bytes) for g in got)     # the talk runs as always
    assert calls == {"shown": 1, "asked": 4}
    sent = sum(len(base64.b64decode(e["audio"])) for e in audio_in)
    assert sent < 32000                                                    # only silence fill, not the history


async def test_watching_changes_nothing_even_when_her_name_was_not_heard(env, monkeypatch):
    got, calls, _, _ = await _wake_talk(env, monkeypatch, mode=1, tv=True, heard="television talk")
    assert any('"ready"' in g for g in got if isinstance(g, str)) and calls["shown"] == 1


async def test_no_talk_is_turned_away_whatever_the_check_heard(env, monkeypatch):
    """24 Nov 2026: with the old setting 2 real calls were turned away; the code is gone."""
    from app import sammler
    woken = []
    monkeypatch.setattr(sammler.collector(), "wake", lambda: woken.append(1))
    got, calls, _, kept = await _wake_talk(env, monkeypatch, mode=2, tv=True, heard="television talk")
    texts = [json.loads(g)["type"] for g in got if isinstance(g, str)]
    assert "ready" in texts and any(isinstance(g, bytes) for g in got) and calls["shown"] == 1
    assert woken == [1]                                  # the collector hears of a wake word talk
    woken.clear()
    await _wake_talk(env, monkeypatch, mode=2, tv=True, heard="x", by_wake_word=False)
    assert woken == []                                   # the button is no wake word


async def test_acting_lets_a_real_call_through_and_old_firmware_too(env, monkeypatch):
    got, calls, _, kept = await _wake_talk(env, monkeypatch, mode=2, tv=True, heard="Hallo Leyla, mach das Licht an")
    assert any('"ready"' in g for g in got if isinstance(g, str)) and calls["shown"] == 1 and not kept
    got, calls, _, _ = await _wake_talk(env, monkeypatch, mode=2, tv=True, heard="x", send_history=False)
    assert any('"ready"' in g for g in got if isinstance(g, str)) and calls == {"shown": 1, "asked": 0}


async def test_the_planner_is_reached_like_every_tool_and_only_metin_plans(env):
    bridge = m.LiveVoiceBridge()

    class Lamps:
        available = True
        entities = ["light.a", "light.b"]
    bridge.lights = Lamps()
    args = {"aktion": "anlegen", "titel": "Probe", "datum": None, "uhrzeit": None, "in_minuten": 30,
            "wiederholung": None, "tage": None, "nummer": None, "schritte": [
                {"geraet": "licht_steuern", "argumente": json.dumps({"lamps": [1], "action": "off"})}]}
    blocked = (await call(bridge, "planer", args, {}))[0].result()
    assert "Nicht erlaubt" in blocked["error"] and bridge.planer.plans == []
    made = (await call(bridge, "planer", args, {"unlocked": True}))[0].result()
    assert made["ok"] and made["was"] == "Stehlampe 1 aus" and len(bridge.planer.plans) == 1
    shown = (await call(bridge, "planer", {"aktion": "anzeigen"}, {}))[0].result()
    assert shown["anzahl"] == 1 and shown["geplant"][0]["titel"] == "Probe"
