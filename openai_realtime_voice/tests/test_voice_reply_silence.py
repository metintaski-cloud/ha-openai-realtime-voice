"""A voice reply that stays silent (24 Nov 2026: three of eight came back empty and the app
showed a speaker sign without sound): give up early and try once more."""
import asyncio
import base64
import json
import struct

from app import announce_voice as av


def loud(seconds: float) -> str:
    n = int(av.SAMPLE_RATE * seconds)
    return base64.standard_b64encode(struct.pack("<%dh" % n, *([8000, -8000] * (n // 2)))).decode("ascii")


class FakeLive:
    def __init__(self, events):
        self.events, self.sent, self.closed = list(events), [], False

    async def send(self, text):
        self.sent.append(json.loads(text))

    async def recv(self):
        if self.events:
            return json.dumps(self.events.pop(0))
        await asyncio.sleep(3600)

    async def close(self):
        self.closed = True


class Speaker(av.AnnounceVoiceMixin):
    def __init__(self, lives):
        self.lives = list(lives)

    def _announce_session_start(self, instructions):
        return {"type": "session.start"}

    async def _feed_silence(self, ws):
        await asyncio.sleep(3600)

    async def _take_live(self):
        return self.lives.pop(0), False


def test_silence_gives_up_early_and_the_second_try_speaks(monkeypatch):
    monkeypatch.setattr(av, "FIRST_AUDIO_S", 0.3)
    monkeypatch.setattr(av, "SPEECH_END_GAP_S", 0.15)
    silent = FakeLive([{"type": "session.started"}])
    talks = FakeLive([{"type": "session.started"},
                      {"type": "session.output_audio.delta", "delta": loud(0.4)},
                      {"type": "session.output_audio.delta", "delta": loud(0.4)}])
    got = []
    sp = Speaker([silent, talks])
    pcm = asyncio.run(sp._speak_once("sag es", max_s=60.0, on_chunk=got.append))
    assert silent.closed and talks.closed and not sp.lives
    assert len(pcm) >= 0.7 * av.BYTES_PER_SEC and len(got) == 2
    assert any(m.get("type") == "session.commentary.append" for m in talks.sent)


def test_a_blip_before_she_speaks_is_not_the_end(monkeypatch):
    monkeypatch.setattr(av, "FIRST_AUDIO_S", 2.0)
    monkeypatch.setattr(av, "SPEECH_END_GAP_S", 0.15)

    class Slow(FakeLive):
        until = 0.0

        async def recv(self):
            loop = asyncio.get_event_loop()
            if len(self.events) == 1:       # a pause longer than the end gap after the blip
                self.until = self.until or loop.time() + 0.4
                await asyncio.sleep(max(0.0, self.until - loop.time()))
            return await super().recv()
    live = Slow([{"type": "session.started"},
                 {"type": "session.output_audio.delta", "delta": loud(0.05)},
                 {"type": "session.output_audio.delta", "delta": loud(0.6)}])
    pcm = asyncio.run(Speaker([live])._speak_once("sag es", max_s=60.0))
    assert len(pcm) >= 0.6 * av.BYTES_PER_SEC


def test_two_silent_tries_end_without_waiting_the_whole_minute(monkeypatch):
    monkeypatch.setattr(av, "FIRST_AUDIO_S", 0.2)
    sp = Speaker([FakeLive([{"type": "session.started"}]), FakeLive([])])
    assert asyncio.run(asyncio.wait_for(sp._speak_once("sag es", max_s=60.0), 3)) == b""
