"""Her mouth on the TV (app/mund.py): the output queue with its hold, and the line to the PC."""
import asyncio
import json
import struct
import time

import pytest

from app import mund, tvshow

AUDIO = bytes(4800)  # 0.1 s of 24 kHz 16 bit mono


class FakeMund:
    """Stands in for MundLink: records what the queue tells the PC."""

    def __init__(self, active=True, delay_s=0.2, fein_ms=100.0):
        self.is_active, self.delay_s, self.fein_ms = active, delay_s, fein_ms
        self.calls = []

    def active(self):
        return self.is_active

    def start(self, in_ms):
        self.calls.append(("S", in_ms))

    def audio(self, pcm):
        self.calls.append(("A", len(pcm)))

    def end(self):
        self.calls.append(("E",))

    def abort(self):
        self.calls.append(("X",))

    def kinds(self):
        return [c[0] for c in self.calls]


async def take(q, timeout=1.0):
    return await asyncio.wait_for(q.get(), timeout=timeout)


# ---------------------------------------------------------------------- without a mouth: a plain queue
@pytest.mark.parametrize("m", [None, FakeMund(active=False)])
async def test_without_an_active_mouth_it_is_a_plain_queue(m):
    q = mund.Ausgang(m)
    assert q.empty() and q.qsize() == 0
    items = [("phase", "thinking"), ("phase", "replying"), AUDIO, AUDIO, ("scene", "tanz"), ("error", "x")]
    t0 = time.monotonic()
    for it in items:
        await q.put(it)
    assert not q.empty() and q.qsize() == len(items)
    got = [await take(q, 0.05) for _ in items]
    assert got == items                       # same order, nothing held
    assert time.monotonic() - t0 < 0.05
    assert q.empty()
    if m is not None:
        assert m.calls == []                  # the PC hears nothing while nobody watches
    with pytest.raises(asyncio.QueueEmpty):
        q.get_nowait()


async def test_get_waits_for_an_item_like_a_queue():
    q = mund.Ausgang(None)
    with pytest.raises(asyncio.TimeoutError):
        await take(q, 0.05)
    asyncio.get_running_loop().call_later(0.05, q.put_nowait, AUDIO)
    assert await take(q, 0.5) == AUDIO


# ---------------------------------------------------------------------- with the mouth: the reply waits, then flows
async def test_a_reply_is_held_for_the_delay_and_then_let_through_at_once():
    m = FakeMund(delay_s=0.2)
    q = mund.Ausgang(m)
    t0 = time.monotonic()
    await q.put(("phase", "replying"))
    for _ in range(3):
        await q.put(AUDIO)
    with pytest.raises(asyncio.TimeoutError):  # nothing comes out before the gate
        await take(q, 0.1)
    assert q.qsize() == 4                      # and nothing was lost by the cancelled wait
    assert await take(q) == ("phase", "replying")
    first = time.monotonic() - t0
    assert 0.18 <= first < 0.3
    assert [await take(q, 0.02) for _ in range(3)] == [AUDIO] * 3   # the rest at once
    await q.put(AUDIO)                         # audio that comes while the reply runs is not held again
    assert await take(q, 0.02) == AUDIO
    # the PC got the start with the promise, and every piece of audio the moment it came
    assert m.kinds() == ["S", "A", "A", "A", "A"]
    assert m.calls[0][1] == pytest.approx(200 + 100, abs=15)


async def test_the_end_of_a_reply_is_told_to_the_pc_and_the_next_reply_is_held_again():
    m = FakeMund(delay_s=0.1)
    q = mund.Ausgang(m)
    await q.put(AUDIO)
    assert await take(q) == AUDIO
    with pytest.raises(asyncio.TimeoutError):  # the sender keeps asking; after the gap the reply counts as over
        await take(q, mund.GAP_S + 0.2)
    assert m.kinds() == ["S", "A", "E"]
    t0 = time.monotonic()
    await q.put(AUDIO)
    assert await take(q) == AUDIO
    assert time.monotonic() - t0 >= 0.09
    assert m.kinds() == ["S", "A", "E", "S", "A"]


async def test_the_promise_counts_what_the_voice_pe_still_has_to_play():
    m = FakeMund(delay_s=0.1, fein_ms=0)
    q = mund.Ausgang(m)
    for _ in range(12):                        # 1.2 s of audio arrive at once
        await q.put(AUDIO)
    await asyncio.sleep(mund.GAP_S + 0.1)      # a pause in the arrival, the Voice PE still plays
    await q.put(AUDIO)
    starts = [c[1] for c in m.calls if c[0] == "S"]
    assert len(starts) == 2
    # the first part plays from 0.1 s to 1.3 s; the second arrives at about 0.4 s and so starts in about 0.9 s
    assert starts[1] == pytest.approx(1300 - (mund.GAP_S + 0.1) * 1000, abs=60)


async def test_an_interrupt_passes_at_once_and_stops_her_mouth():
    m = FakeMund(delay_s=0.5)
    q = mund.Ausgang(m)
    await q.put(("phase", "replying"))
    await q.put(AUDIO)
    await q.put(AUDIO)
    # what the bridge does on a barge in: drop everything, then the interrupt
    while not q.empty():
        q.get_nowait()
    t0 = time.monotonic()
    await q.put(("interrupt", None))
    assert await take(q, 0.05) == ("interrupt", None)
    assert time.monotonic() - t0 < 0.05
    assert m.kinds() == ["S", "A", "A", "X"]
    await q.put(AUDIO)                         # the next reply starts a new hold
    assert m.kinds()[-2:] == ["S", "A"]


async def test_a_reply_that_began_without_a_watcher_is_not_held_halfway():
    m = FakeMund(active=False, delay_s=0.3)
    q = mund.Ausgang(m)
    await q.put(AUDIO)
    m.is_active = True                         # the TV opens the stream in the middle of her sentence
    await q.put(AUDIO)
    assert [await take(q, 0.02), await take(q, 0.02)] == [AUDIO, AUDIO]
    assert m.calls == []


# ---------------------------------------------------------------------- the line to the PC
async def test_the_link_frames_what_it_sends_and_reads_the_state():
    got = bytearray()
    writers = []

    async def pc(reader, writer):
        writers.append(writer)
        writer.write(b'{"bereit": true, "zuschauer": false, "strom_ms": 410}\n')
        await writer.drain()
        try:
            while True:
                d = await reader.read(65536)
                if not d:
                    break
                got.extend(d)
        except ConnectionError:
            pass

    server = await asyncio.start_server(pc, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    link = mund.MundLink("127.0.0.1", delay_s=1.2, fein_ms=80, back_url="https://x.example/?tv=1", port=port)
    assert not link.ready() and not link.active()
    link.start(1300)                           # not connected: nothing happens, nothing raises
    task = asyncio.create_task(link.run())
    try:
        for _ in range(100):
            if link.ready():
                break
            await asyncio.sleep(0.01)
        assert link.ready() and not link.active()          # the service is up, but nobody watches
        writers[0].write(b'{"bereit": true, "zuschauer": true, "strom_ms": 400}\n')
        await writers[0].drain()
        for _ in range(100):
            if link.active():
                break
            await asyncio.sleep(0.01)
        assert link.active()
        link.start(1280.4)
        link.audio(b"\x01\x02\x03\x04")
        link.end()
        link.abort()
        await asyncio.sleep(0.05)
        frames = []
        buf = bytes(got)
        while buf:
            kind, n = struct.unpack(">cI", buf[:5])
            frames.append((kind, buf[5:5 + n]))
            buf = buf[5 + n:]
        assert [f[0] for f in frames] == [b"S", b"A", b"E", b"X"]
        assert json.loads(frames[0][1]) == {"in_ms": 1280}
        assert frames[1][1] == b"\x01\x02\x03\x04"
        assert link.page() == f"http://127.0.0.1:{mund.SEITE_PORT}/?zurueck=https%3A%2F%2Fx.example%2F%3Ftv%3D1%26mundaus%3D1"
        # the PC goes away: not ready any more, and sending stays harmless
        writers[0].close()
        for _ in range(100):
            if not link.ready():
                break
            await asyncio.sleep(0.01)
        assert not link.ready() and not link.active()
        link.audio(b"\x00\x00")
    finally:
        task.cancel()
        server.close()


def test_no_host_means_no_mouth(monkeypatch):
    monkeypatch.delenv("MUND_HOST", raising=False)
    assert mund.MundLink.from_env() is None
    monkeypatch.setenv("MUND_HOST", "null")    # what bashio gives for an option that is not set
    assert mund.MundLink.from_env() is None
    monkeypatch.setenv("MUND_HOST", " 192.168.2.36 ")
    monkeypatch.setenv("MUND_DELAY_MS", "null")
    monkeypatch.setenv("MUND_FEIN_MS", "60")
    link = mund.MundLink.from_env()
    assert (link.host, link.delay_s, link.fein_ms) == ("192.168.2.36", 1.2, 60.0)


# ---------------------------------------------------------------------- the TV page learns where to go
def test_the_tv_state_names_the_pc_page_only_while_the_service_is_ready():
    class Mood:
        def status(self):
            return {"mood": "froehlich", "low": False, "outfit": "freizeit", "secret": "x"}

    class Link:
        up = False

        def ready(self):
            return self.up

        def page(self):
            return "http://pc:8090/"

    show = tvshow.TvShow(None, Mood(), url="https://x.example/?tv=1")
    before = show.page_state()
    assert "mund" not in before and "secret" not in before
    show.mund = Link()
    assert show.page_state() == before          # PC off: exactly what it was
    show.mund.up = True
    assert show.page_state() == {**before, "mund": "http://pc:8090/"}


# ---------------------------------------------------------------------- together with the real sender to the device
class FakeDevice:
    leyla_app = False

    def __init__(self):
        self.got = []  # (time, what)

    async def send(self, data):
        self.got.append((time.monotonic(), data))


class Sender(__import__("app.output_link", fromlist=["OutputMixin"]).OutputMixin):
    lamp = None


async def run_sender(q, device, seconds):
    task = asyncio.create_task(Sender()._output_sender(device, q, [False], {}))
    await asyncio.sleep(seconds)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


async def feed_reply(q, pieces=10, step=0.1):
    """A reply the way GPT Live sends it: the phase, then audio at about real time, each piece marked with its number."""
    await q.put(("phase", "replying"))
    for i in range(pieces):
        await q.put(bytes([i + 1]) * 4800)
        await asyncio.sleep(step)


@pytest.mark.parametrize("delay", [0.0, 0.6])
async def test_the_device_gets_the_same_audio_only_later(delay):
    m = FakeMund(active=delay > 0, delay_s=delay)
    q = mund.Ausgang(m)
    device = FakeDevice()
    t0 = time.monotonic()
    sender = asyncio.create_task(run_sender(q, device, 2.6 + delay))
    await feed_reply(q)
    await sender
    texts = [(t, json.loads(d)) for t, d in device.got if isinstance(d, str)]
    audio = [(t, d) for t, d in device.got if isinstance(d, bytes)]
    assert [x[1] for x in texts] == [{"type": "phase", "phase": "replying"}]
    data = b"".join(d for _, d in audio)
    assert len(data) == 10 * 4800                                   # every byte arrives
    body = data[:-720]                                              # the last 15 ms are faded out by the sender
    assert body == b"".join(bytes([i + 1]) * 4800 for i in range(10))[:len(body)]   # in order, unchanged
    first = audio[0][0] - t0
    assert texts[0][0] <= audio[0][0]                               # the phase still comes before the sound
    if delay:
        assert delay - 0.05 <= first <= delay + 0.35                # held for the delay (plus the sender's own start)
        assert texts[0][0] - t0 >= delay - 0.05                     # and the phase waits with it
        assert m.kinds()[0] == "S" and m.kinds().count("A") == 10 and m.kinds()[-1] == "E"
    else:
        assert first <= 0.4
        assert m.calls == []
    # played at playback rate either way: the last piece is sent about 0.8 s after the first (1 s of audio, 0.2 s ahead)
    assert 0.6 <= audio[-1][0] - audio[0][0] <= 1.1


async def test_an_interrupt_during_the_hold_reaches_the_device_at_once_and_no_audio_follows():
    m = FakeMund(delay_s=1.0)
    q = mund.Ausgang(m)
    device = FakeDevice()
    sender = asyncio.create_task(run_sender(q, device, 1.6))
    await q.put(("phase", "replying"))
    for i in range(4):
        await q.put(bytes([i + 1]) * 4800)
    await asyncio.sleep(0.3)
    Sender._clear_output_queue(q)
    t0 = time.monotonic()
    await q.put(("interrupt", None))
    await sender
    assert [json.loads(d) for _, d in device.got] == [{"type": "interrupt"}]
    assert device.got[0][0] - t0 < 0.15
    assert m.kinds() == ["S", "A", "A", "A", "A", "X"]
