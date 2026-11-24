"""A voice reply that stays silent (24 Nov 2026: three of eight came back empty and the app
showed a speaker sign without sound): give up early, send the note once more and try again."""
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


def test_silent_tries_end_without_waiting_the_whole_minute(monkeypatch):
    monkeypatch.setattr(av, "FIRST_AUDIO_S", 0.2)
    sp = Speaker([FakeLive([{"type": "session.started"}])] + [FakeLive([]) for _ in range(av.SPEAK_TRIES - 1)])
    assert asyncio.run(asyncio.wait_for(sp._speak_once("sag es", max_s=60.0), 3)) == b""
    assert not sp.lives


def test_no_word_after_the_note_sends_it_once_more_in_the_same_session(monkeypatch):
    """Measured 24 Nov 2026: a silent GPT Live confirms the note and then says nothing."""
    monkeypatch.setattr(av, "NUDGE_AFTER_S", 0.2)
    monkeypatch.setattr(av, "FIRST_AUDIO_S", 2.0)
    monkeypatch.setattr(av, "SPEECH_END_GAP_S", 0.15)

    class SecondNote(FakeLive):  # speaks only after the note came twice
        async def recv(self):
            notes = [m for m in self.sent if m.get("type") == "session.commentary.append"]
            if self.events and self.events[0]["type"] != "session.started" and len(notes) < 2:
                await asyncio.sleep(0.05)
                raise asyncio.TimeoutError
            return await super().recv()
    live = SecondNote([{"type": "session.started"},
                       {"type": "session.commentary.appended"},
                       {"type": "session.output_transcript.delta", "delta": " Hallo"},
                       {"type": "session.output_audio.delta", "delta": loud(0.5)}])
    sp = Speaker([live])
    pcm = asyncio.run(sp._speak_once("sag es", max_s=60.0))
    notes = [m for m in live.sent if m.get("type") == "session.commentary.append"]
    assert len(notes) == 2 and notes[0]["content"] == notes[1]["content"] == "sag es"
    assert len(pcm) >= 0.5 * av.BYTES_PER_SEC and not sp.lives
    assert sp._speak_seen["nudged"] and sp._speak_seen["said"] == "Hallo"


def test_she_who_speaks_at_once_gets_no_second_note(monkeypatch):
    monkeypatch.setattr(av, "NUDGE_AFTER_S", 0.2)
    monkeypatch.setattr(av, "SPEECH_END_GAP_S", 0.4)
    live = FakeLive([{"type": "session.started"},
                     {"type": "session.output_transcript.delta", "delta": " Ja"},
                     {"type": "session.output_audio.delta", "delta": loud(0.5)}])
    sp = Speaker([live])
    asyncio.run(sp._speak_once("sag es", max_s=60.0))
    assert len([m for m in live.sent if m.get("type") == "session.commentary.append"]) == 1
    assert not sp._speak_seen["nudged"]
