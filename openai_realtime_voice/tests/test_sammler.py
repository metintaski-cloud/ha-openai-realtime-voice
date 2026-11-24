"""Near wakes: the sound that almost woke her, collected for training the wake word (2.158.0)."""
import asyncio
import io
import json
import wave

import pytest

from app import falsewakes, memory_web, sammler


def clip(seconds=4.0, rate=16000):
    return b"\x10\x00" * int(rate * seconds)


def collector(tmp_path, monkeypatch, named=False):
    c = sammler.Collector(str(tmp_path / "near"))
    c.api_key = "key"

    async def hears(item):
        return named
    monkeypatch.setattr(c, "hears_her_name", hears)
    return c


def test_a_clip_is_taken_and_filed_as_clean_when_nothing_else_happened(tmp_path, monkeypatch):
    c = collector(tmp_path, monkeypatch)
    assert c.take(clip(), "rate=16000") == {"ok": True} and len(c.pending) == 1
    name = asyncio.run(c.settle(c.pending[0]))
    assert name.startswith("beinahe_") and name.endswith("_n0_f0.wav")
    with wave.open(str(tmp_path / "near" / name)) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()) == (16000, 1, 2, 64000)
    assert c.stats()["gesammelt"] == 1 and c.stats()["sauber"] == 1 and c.stats()["pruefen"] == 0


def test_what_is_no_clip_is_refused(tmp_path, monkeypatch):
    c = collector(tmp_path, monkeypatch)
    assert c.take(clip(0.2), "rate=16000") == {"ok": False}          # too short
    assert c.take(clip(6.0), "rate=16000") == {"ok": False}          # too long
    assert c.take(clip(), "rate=abc") == {"ok": False} and c.take(clip(), "rate=100") == {"ok": False}
    assert c.take(clip(), "") == {"ok": True}                        # the rate defaults to 16 kHz
    assert c.take(clip(), "rate=16000") == {"ok": False}             # a second one right away
    assert c.refused == 5 and len(c.pending) == 1


def test_a_talk_by_the_wake_word_at_the_same_moment_covers_the_clip(tmp_path, monkeypatch):
    c = collector(tmp_path, monkeypatch)
    c.take(clip(), "rate=16000")
    c.wake()                                                         # the strict model fired too
    assert asyncio.run(c.settle(c.pending[0])) is None and c.covered == 1
    assert not (tmp_path / "near").exists()


def test_a_call_that_may_have_been_missed_is_never_filed_as_clean(tmp_path, monkeypatch):
    c = collector(tmp_path, monkeypatch, named=True)                  # the recogniser heard her name
    c.take(clip(), "rate=16000")
    assert asyncio.run(c.settle(c.pending[0])).endswith("_n1_f0.wav")
    c = collector(tmp_path, monkeypatch)                              # somebody tried again soon after
    c.take(clip(), "rate=16000")
    item = c.pending[0]
    c.wakes.append(item["t"] + 8.0)
    assert asyncio.run(c.settle(item)).endswith("_n0_f1.wav")
    c = collector(tmp_path, monkeypatch)                              # two near wakes close together
    c.take(clip(), "rate=16000")
    item = c.pending[0]
    c.nears.append(item["t"] - 6.0)
    assert asyncio.run(c.settle(item)).endswith("_n0_f1.wav")
    c = collector(tmp_path, monkeypatch, named=None)                  # the recogniser did not answer
    c.take(clip(), "rate=16000")
    assert asyncio.run(c.settle(c.pending[0])).endswith("_nx_f0.wav")
    stats = c.stats()
    assert stats["gesammelt"] >= 3 and stats["sauber"] == 0 and stats["pruefen"] == stats["gesammelt"]


def test_only_the_newest_clips_are_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(sammler, "MAX_FILES", 2)
    c = collector(tmp_path, monkeypatch)
    for name in ("beinahe_20261124_100000_n0_f0.wav", "beinahe_20261124_110000_n0_f0.wav",
                 "beinahe_20261124_120000_n1_f0.wav"):
        c._write(name, b"RIFF")
    left = sorted(p.name for p in (tmp_path / "near").iterdir())
    assert left == ["beinahe_20261124_110000_n0_f0.wav", "beinahe_20261124_120000_n1_f0.wav"]
    assert c.stats()["tage"] == [{"tag": "2026-11-24", "sauber": 1, "pruefen": 1}]


def test_the_probe_takes_a_near_wake_whole(tmp_path):
    path = tmp_path / "beinahe_20261124_120000_n0_f0.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(clip(4.0))
    pcm, rate = falsewakes.clip(str(path))
    assert rate == 16000 and len(pcm) == 128000


class Writer:
    def __init__(self):
        self.data = b""

    def write(self, b):
        self.data += b

    async def drain(self):
        pass

    def close(self):
        pass

    async def wait_closed(self):
        pass


def test_the_device_posts_raw_samples_to_the_page_port(tmp_path, monkeypatch):
    c = collector(tmp_path, monkeypatch)
    monkeypatch.setattr(sammler, "_COLLECTOR", c)
    monkeypatch.setattr(sammler, "SETTLE_S", 0.05)
    body = clip(1.0)

    async def run():
        reader = asyncio.StreamReader()
        reader.feed_data(b"POST /api/weckton?rate=16000 HTTP/1.1\r\nHost: x\r\n"
                         b"Content-Type: application/octet-stream\r\nContent-Length: %d\r\n"
                         b"Connection: close\r\n\r\n" % len(body) + body)
        reader.feed_eof()
        writer = Writer()
        await memory_web._handle(None, None, reader, writer)
        await asyncio.sleep(0.3)                                       # it settles by itself
        return writer.data
    reply = asyncio.run(run())
    assert b"200 OK" in reply and json.loads(reply.split(b"\r\n\r\n", 1)[1]) == {"ok": True}
    kept = [p.name for p in (tmp_path / "near").iterdir()]
    assert len(kept) == 1 and kept[0].endswith("_n0_f0.wav") and not c.pending
