"""What is on the false wake recordings: length, loudness, when, and from where."""
import asyncio
import math
import struct
import wave

from app import falsewakes, metrics


def write(path, seconds, loud_from=None, rate=24000):
    n = int(rate * seconds)
    start = n if loud_from is None else int(rate * loud_from)
    samples = [int(6000 * math.sin(2 * math.pi * 300 * i / rate)) if i >= start else 0 for i in range(n)]
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<%dh" % n, *samples))


def test_a_recording_is_measured_without_its_content(tmp_path):
    write(tmp_path / "a.wav", 4.0, loud_from=1.0)
    m = falsewakes.measure(str(tmp_path / "a.wav"))
    assert m["sekunden"] == 4.0 and m["erster_ton_s"] == 1.0 and 0.7 <= m["ton_anteil"] <= 0.8
    assert m["spitze"] > 5000
    write(tmp_path / "still.wav", 2.0)
    still = falsewakes.measure(str(tmp_path / "still.wav"))
    assert still["ton_anteil"] == 0 and still["erster_ton_s"] is None


def test_the_name_tells_when_and_whether_it_came_from_the_app():
    assert falsewakes.describe("falsewake_192_168_2_241_20261124_092934.wav") == {
        "tag": "2026-11-24", "uhrzeit": "09:29", "app": False, "vorher": False}
    assert falsewakes.describe("falsewake_192_168_2_241_20261124_092934_vorher.wav")["vorher"] is True
    assert falsewakes.describe("falsewake_app_100_112_116_21_20261124_062611.wav")["app"] is True
    assert falsewakes.describe("other.wav") == {"datei": "other.wav"}


def test_a_batch_is_analysed_and_silence_is_not_sent_to_the_recogniser(tmp_path, monkeypatch):
    write(tmp_path / "falsewake_192_168_2_241_20261124_092934.wav", 2.0, loud_from=0.5)
    write(tmp_path / "falsewake_192_168_2_241_20261124_101347.wav", 2.0)
    asked = []

    async def heard(path, api_key, client):
        asked.append(path)
        return "etwas aus dem Fernseher"
    monkeypatch.setattr(falsewakes, "heard", heard)
    out = asyncio.run(falsewakes.analyse(str(tmp_path), "key"))
    assert out["anzahl"] == 2 and len(asked) == 1
    assert out["items"][0]["gehoert"] == "etwas aus dem Fernseher" and "gehoert" not in out["items"][1]
    assert asyncio.run(falsewakes.analyse(str(tmp_path / "none")))["anzahl"] == 0


def test_a_live_talk_from_the_app_is_not_counted_as_woken():
    now = 1795500000
    entries = [{"event": "session_end", "ts": now, "reason": "no_speech"},
               {"event": "session_end", "ts": now, "reason": "no_speech", "app": True},
               {"event": "session_end", "ts": now, "reason": "end_conversation"}]
    assert metrics.wake_stats(entries)[0]["geweckt"] == 2 and metrics.wake_stats(entries)[0]["fehlstarts"] == 1


def test_the_probe_runs_every_way_of_listening_over_the_kept_recordings(tmp_path, monkeypatch):
    write(tmp_path / "falsewake_192_168_2_241_20261124_115753_vorher_w840.wav", 2.5, loud_from=2.0)
    write(tmp_path / "falsewake_192_168_2_241_20261124_092934.wav", 6.0)
    seen = []

    async def hear(pcm, rate, api_key, client, wake_ms=None, timeout=0):
        seen.append((len(pcm) / (rate * 2), wake_ms))
        return {"ganz": "televizyon", "ganz_kw": "Hallo Leyla", "ruf": None, "ruf_kw": ""}
    monkeypatch.setattr(falsewakes.wakecheck, "hear", hear)
    out = asyncio.run(falsewakes.probe(str(tmp_path), "key"))
    assert out["anzahl"] == 2 and out["name_gehoert"] == {"ganz": 0, "ganz_kw": 2, "ruf": 0, "ruf_kw": 0}
    first = out["items"][1]
    assert first["v"] == {"ganz": False, "ganz_kw": True, "ruf": None, "ruf_kw": False} and first["weck_ms"] == 840
    assert "gehoert" not in first                               # the texts only when asked for
    assert first["pegel"][0] == 0 and first["pegel"][-1] > 3000 and len(first["pegel"]) == 10
    assert sorted(seen, key=str) == [(2.5, 840), (2.5, None)]            # a long recording is cut to the same length
    only = asyncio.run(falsewakes.probe(str(tmp_path), "key", pre=True, text=True))
    assert only["anzahl"] == 1 and only["items"][0]["vorher"] and only["items"][0]["gehoert"]["ganz_kw"] == "Hallo Leyla"
    assert falsewakes.describe("falsewake_192_168_2_241_20261124_092934_vorher.wav")["vorher"] is True
