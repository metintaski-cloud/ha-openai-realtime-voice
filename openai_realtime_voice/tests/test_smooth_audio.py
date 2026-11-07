"""Reply audio starts with a small reserve, and Leyla is nudged when her name is ignored."""
import asyncio
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OPENAI_API_KEY", "test")

from app import main as m  # noqa: E402


class FakeWs:
    def __init__(self):
        self.sent = []

    async def send(self, data):
        self.sent.append((asyncio.get_event_loop().time(), data))


def _bridge():
    return m.LiveVoiceBridge()


async def test_reply_starts_with_reserve_and_keeps_lead():
    """Audio that arrives in real time is held for 200 ms, then stays 200 ms ahead."""
    bridge = _bridge()
    ws = FakeWs()
    q: asyncio.Queue = asyncio.Queue()
    task = asyncio.create_task(bridge._output_sender(ws, q, [False], {}))
    loop = asyncio.get_event_loop()
    t0 = loop.time()
    delta = b"\x10\x27" * 2400  # 100 ms
    for _ in range(10):  # 1 s of audio, delivered in real time
        await q.put(delta)
        await asyncio.sleep(0.1)
    await asyncio.sleep(0.6)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    audio = [(t, d) for t, d in ws.sent if isinstance(d, bytes)]
    assert sum(len(d) for _, d in audio) == len(delta) * 10
    first = audio[0][0] - t0
    assert 0.08 <= first <= 0.3, first  # held until 200 ms (two deltas) were buffered
    # In the first instant at least the 200 ms reserve goes out at once
    burst = sum(len(d) for t, d in audio if t - audio[0][0] < 0.02)
    assert burst >= m.PREBUFFER_BYTES
    # Never more than the lead ahead of real time playback
    sent = 0
    for t, d in audio:
        sent += len(d)
        played = t - audio[0][0]
        assert sent / m.BYTES_PER_SEC - played <= m.OUTPUT_LEAD_S + 0.05


async def test_burst_is_paced_after_the_lead():
    """2 s of audio arriving at once takes about 1.8 s to send (2 s minus the lead)."""
    bridge = _bridge()
    ws = FakeWs()
    q: asyncio.Queue = asyncio.Queue()
    for _ in range(20):
        await q.put(b"\x10\x27" * 2400)
    task = asyncio.create_task(bridge._output_sender(ws, q, [False], {}))
    await asyncio.sleep(2.6)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    audio = [t for t, d in ws.sent if isinstance(d, bytes)]
    assert len(audio) == 100
    assert 1.6 <= audio[-1] - audio[0] <= 2.0


async def test_short_reply_is_not_lost():
    """A reply shorter than the reserve is still sent after the short wait."""
    bridge = _bridge()
    ws = FakeWs()
    q: asyncio.Queue = asyncio.Queue()
    task = asyncio.create_task(bridge._output_sender(ws, q, [False], {}))
    await q.put(b"\x10\x27" * 1200)  # 50 ms
    await asyncio.sleep(0.6)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert sum(len(d) for _, d in ws.sent if isinstance(d, bytes)) == 2400


async def test_phase_goes_out_in_order():
    bridge = _bridge()
    ws = FakeWs()
    q: asyncio.Queue = asyncio.Queue()
    task = asyncio.create_task(bridge._output_sender(ws, q, [False], {}))
    await q.put(("phase", "replying"))
    await q.put(b"\x10\x27" * 2400)
    await q.put(("phase", "thinking"))
    await asyncio.sleep(0.4)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    kinds = ["audio" if isinstance(d, bytes) else json.loads(d)["phase"] for _, d in ws.sent]
    assert kinds[0] == "replying"
    assert kinds[-1] == "thinking"
    assert "audio" in kinds[1:-1]


def test_addressed_by_name():
    assert m.addressed_by_name("Leyla, kanal 1'i açabilir misin")
    assert m.addressed_by_name("Leyla saat kaç? Bi bi dolap gibi")
    assert m.addressed_by_name("Leyla? Arkadan onu bağlayabilir misin")
    assert m.addressed_by_name("Leyla, kapatabilirsin")
    assert not m.addressed_by_name("Leyla peşinde hep. Gözün mü?")
    assert not m.addressed_by_name("Leyla çok tatlı konuşuyor.")
    assert not m.addressed_by_name("kanal bir")


class FakeLiveWs:
    def __init__(self):
        self.sent = []

    async def send(self, raw):
        self.sent.append(json.loads(raw))


async def _feed(bridge, ws, state, text):
    for i in range(0, len(text), 6):
        bridge._note_name_mention(ws, state, text[i:i + 6])
        await asyncio.sleep(0)


async def test_nudge_when_name_is_ignored(monkeypatch):
    monkeypatch.setattr(m, "NAME_NUDGE_AFTER_S", 0.2)
    bridge = _bridge()
    ws = FakeLiveWs()
    state = {"last_audio_time": 0.0}
    await _feed(bridge, ws, state, "Ne oluyor? Leyla saat kaç? Bi dolap gibi")
    await asyncio.sleep(0.4)
    assert len(ws.sent) == 1
    assert ws.sent[0]["type"] == "session.commentary.append"
    assert "Leyla saat kaç?" in ws.sent[0]["content"]


async def test_no_nudge_when_she_answers(monkeypatch):
    monkeypatch.setattr(m, "NAME_NUDGE_AFTER_S", 0.2)
    bridge = _bridge()
    ws = FakeLiveWs()
    state = {"last_audio_time": 0.0}
    await _feed(bridge, ws, state, "Leyla, kanal bir aç lütfen")
    await asyncio.sleep(0.05)
    state["last_audio_time"] = time.monotonic()  # she started talking
    await asyncio.sleep(0.4)
    assert ws.sent == []


async def test_no_nudge_when_only_talked_about(monkeypatch):
    monkeypatch.setattr(m, "NAME_NUDGE_AFTER_S", 0.2)
    bridge = _bridge()
    ws = FakeLiveWs()
    state = {"last_audio_time": 0.0}
    await _feed(bridge, ws, state, "Senin Leyla peşinde hep. Tamam")
    await asyncio.sleep(0.4)
    assert ws.sent == []


async def test_no_nudge_while_delegation_runs(monkeypatch):
    monkeypatch.setattr(m, "NAME_NUDGE_AFTER_S", 0.2)
    bridge = _bridge()
    ws = FakeLiveWs()
    state = {"last_audio_time": 0.0, "last_delegation_at": time.monotonic()}
    await _feed(bridge, ws, state, "Leyla, sesi aç biraz")
    await asyncio.sleep(0.4)
    assert ws.sent == []


def test_language_hint_in_session():
    bridge = _bridge()
    instructions = bridge._session_start()["session"]["instructions"]
    assert "bir saniye" in instructions
    assert "Leyla" in m.greeting_instruction("Hallo")
