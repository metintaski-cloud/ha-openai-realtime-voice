"""Was she really called? The microphone history from before the wake word (2.157.0)."""
import asyncio
import json

import pytest

from app import wakecheck


class Ws:
    def __init__(self, frames, gap=0.0):
        self.frames, self.gap = list(frames), gap

    async def recv(self):
        if not self.frames:
            await asyncio.sleep(3600)
        await asyncio.sleep(self.gap)
        return self.frames.pop(0)


def head(n, rate=16000, wake_ms=None):
    return json.dumps({"type": "preroll", "rate": rate, "bytes": n,
                       **({} if wake_ms is None else {"wake_ms": wake_ms})})


@pytest.mark.parametrize("text", ["Hallo Leyla", "hallo leila, mach das licht an", "Halo Layla", "Alo Laila!",
                                  "Leyla'yı çağır", "LEYLA", "Hallo Leylaaa"])
def test_her_name_is_found_however_the_recogniser_writes_it(text):
    assert wakecheck.named(text)


@pytest.mark.parametrize("text", ["", "Biz dinleyicilerimiz de merak etti", "Hallo, schön dass du da bist",
                                  "Lale geldi", "alle Lichter aus", "Leyl"])
def test_television_talk_without_her_name_is_not(text):
    assert not wakecheck.named(text)


def test_the_header_says_how_many_bytes_follow():
    assert wakecheck.header(head(80000)) == 80000
    assert wakecheck.header('{"type":"interrupt"}') == 0 and wakecheck.header(b"\x00\x01") == 0
    assert wakecheck.header(head(10 ** 9)) == wakecheck.MAX_BYTES and wakecheck.header("preroll") == 0


def test_the_history_is_taken_off_the_line_and_nothing_else():
    state = {}
    pcm, rate = asyncio.run(wakecheck.read(Ws([head(8), b"\x01\x00\x02\x00", b"\x03\x00\x04\x00"]), state))
    assert pcm == b"\x01\x00\x02\x00\x03\x00\x04\x00" and rate == 16000 and state["pre_left"] == 0


def test_old_firmware_sends_nothing_and_costs_only_the_short_wait(monkeypatch):
    monkeypatch.setattr(wakecheck, "HEADER_WAIT_S", 0.1)
    state = {}
    assert asyncio.run(wakecheck.read(Ws([]), state)) == (b"", 0) and "pre_left" not in state
    state = {}   # something else came first: it is handed on, not lost
    assert asyncio.run(wakecheck.read(Ws(['{"type":"interrupt"}']), state)) == (b"", 0)
    assert state["early"] == ['{"type":"interrupt"}']


def test_what_is_still_missing_when_time_is_up_is_remembered(monkeypatch):
    monkeypatch.setattr(wakecheck, "BODY_WAIT_S", 0.2)
    state = {}
    pcm, _ = asyncio.run(wakecheck.read(Ws([head(8), b"\x01\x00\x02\x00"]), state))
    assert pcm == b"\x01\x00\x02\x00" and state["pre_left"] == 4


def run_check(monkeypatch, mode, tv, heard, frames=None, use="ganz"):
    """`heard`: one text for every way of listening, or {(only the call, keyword): text}.
    The default frames are a talk the wake word started (wake_ms in the header)."""
    asked = []

    async def transcribe(audio, api_key, client, keywords=()):
        asked.append(len(audio))
        if isinstance(heard, Exception):
            raise heard
        if isinstance(heard, dict):
            return heard[(len(audio) < 75000, bool(keywords))]
        return heard

    async def playing():
        return tv
    monkeypatch.setattr(wakecheck, "transcribe", transcribe)
    monkeypatch.setattr(wakecheck, "HEADER_WAIT_S", 0.1)
    state = {}
    frames = [head(128000, wake_ms=600), b"\x01\x00" * 64000] if frames is None else frames
    out = asyncio.run(wakecheck.check(Ws(frames), state, mode, playing, "key", use))
    return out, state, asked


def test_with_the_tv_off_nobody_is_asked_and_she_is_taken_as_called(monkeypatch):
    out, state, asked = run_check(monkeypatch, 2, tv=False, heard="television")
    assert out["named"] is None and not out["reject"] and not asked and out["pre"] == 4.0
    assert state["preroll"][1] == 16000        # the history is there for a later false wake


def test_watching_never_ends_a_talk_and_acting_does_when_her_name_is_missing(monkeypatch):
    out, _, asked = run_check(monkeypatch, 1, tv=True, heard="Biz dinleyicilerimiz")
    assert out["named"] is False and not out["reject"] and asked
    out, _, _ = run_check(monkeypatch, 2, tv=True, heard="Biz dinleyicilerimiz")
    assert out["named"] is False and out["reject"]
    out, _, _ = run_check(monkeypatch, 2, tv=True, heard="... Hallo Leyla")
    assert out["named"] is True and not out["reject"]
    out, _, asked = run_check(monkeypatch, 0, tv=True, heard="x")      # switched off: only taken off the line
    assert not asked and not out["reject"] and out["pre"] == 4.0


def test_in_doubt_she_is_taken_as_called(monkeypatch):
    out, _, _ = run_check(monkeypatch, 2, tv=True, heard=RuntimeError("down"))
    assert out["named"] is None and not out["reject"]
    out, _, asked = run_check(monkeypatch, 2, tv=True, heard="x", frames=[])    # no history at all
    assert not out["reject"] and not asked and out["pre"] == 0.0


def test_the_call_is_cut_out_where_the_device_says_the_wake_word_was():
    pcm = b"".join(i.to_bytes(2, "little") for i in range(64000))           # 4 s at 16 kHz, sample = index
    part = wakecheck.call(pcm, 16000, 600)                                    # wake word 0.6 s before the end
    first, last = int.from_bytes(part[:2], "little"), int.from_bytes(part[-2:], "little")
    assert first == 64000 - 9600 - 30400 and last == 64000 - 9600 + 3200 - 1  # 1.9 s before to 0.2 s after
    assert wakecheck.call(pcm, 16000, None) == b""                            # no place given
    assert wakecheck.call(pcm, 16000, 3900) == b""                            # the call lies before the history
    assert len(wakecheck.call(pcm, 16000, 0)) == 30400 * 2                    # nothing after the end to take


def test_the_header_may_say_where_the_wake_word_was():
    assert wakecheck.wake_of(head(8, wake_ms=840)) == 840 and wakecheck.wake_of(head(8)) is None
    assert wakecheck.wake_of(json.dumps({"type": "preroll", "wake_ms": "x"})) is None
    assert wakecheck.wake_of(json.dumps({"type": "preroll", "wake_ms": 99999})) is None
    state = {}
    asyncio.run(wakecheck.read(Ws([head(4, wake_ms=840), b"\x01\x00\x02\x00"]), state))
    assert state["wake_ms"] == 840


def test_the_setting_names_the_ways_that_count():
    assert wakecheck.ways("ganz+ruf_kw") == ("ganz", "ruf_kw")
    assert wakecheck.ways("ruf , unsinn") == ("ruf",)
    assert wakecheck.ways("") == ("ganz_kw",) and wakecheck.ways(None) == ("ganz_kw",)
    assert wakecheck.ways("alles") == ("ganz_kw",)


def test_one_way_that_heard_her_is_enough_and_a_missing_one_is_doubt():
    assert wakecheck.verdict({"ganz": "televizyon", "ruf": "Hallo Leyla"}, ("ganz", "ruf")) is True
    assert wakecheck.verdict({"ganz": "televizyon", "ruf": ""}, ("ganz", "ruf")) is False
    assert wakecheck.verdict({"ganz": "televizyon", "ruf": None}, ("ganz", "ruf")) is None
    assert wakecheck.verdict({"ganz": None, "ruf": "Leyla"}, ("ganz", "ruf")) is True
    # a way that could not run (no place of the wake word) does not count; then the whole with keyword
    assert wakecheck.verdict({"ganz": "x", "ganz_kw": "Hallo Leyla"}, ("ruf_kw",)) is True
    assert wakecheck.verdict({"ganz": "x", "ganz_kw": "x"}, ("ruf_kw", "ganz")) is False


def test_the_television_drowned_him_in_the_whole_but_not_in_the_call(monkeypatch):
    """24 Nov 2026, 11:57: the whole history gave only the television, he was turned away."""
    heard = {(False, False): "Hafif bir ses", (False, True): "Hafif bir ses",
             (True, False): "", (True, True): "Hallo Leyla"}
    out, _, asked = run_check(monkeypatch, 2, tv=True, heard=heard)
    assert out["reject"] and out["wake"] == 0.6
    assert out["v"] == {"ganz": False, "ganz_kw": False, "ruf": False, "ruf_kw": True}
    assert len(asked) == 4 and sorted(asked)[0] < sorted(asked)[-1]      # all four ways were heard
    out, _, _ = run_check(monkeypatch, 2, tv=True, heard=heard, use="ganz_kw+ruf_kw")
    assert out["named"] is True and not out["reject"] and "Hallo Leyla" in out["heard"]


def test_a_talk_the_wake_word_did_not_start_is_never_turned_away(monkeypatch):
    """The button, a talk she started herself, older firmware: nobody had to say her name."""
    frames = [head(80000), b"\x01\x00" * 40000]                        # no wake_ms in the header
    out, _, asked = run_check(monkeypatch, 2, tv=True, heard="Biz dinleyicilerimiz", frames=frames)
    assert out["named"] is False and not out["reject"] and out["wake"] is None
    assert len(asked) == 2 and out["v"] == {"ganz": False, "ganz_kw": False}    # only the whole history


def test_keywords_go_to_the_new_recogniser_and_as_a_prompt_to_the_old_one():
    sent = []

    class Resp:
        def __init__(self, code):
            self.status_code, self.text = code, "no"

        def json(self):
            return {"text": " Hallo Leyla "}

    class Client:
        async def post(self, url, headers, data, files):
            sent.append(data)
            return Resp(500 if data["model"] == "gpt-transcribe" else 200)

    assert asyncio.run(wakecheck.transcribe(b"x", "key", Client(), wakecheck.KEYWORDS)) == "Hallo Leyla"
    assert sent[0]["keywords[]"] == ["Hallo Leyla", "Leyla"] and "prompt" not in sent[0]
    assert sent[1]["prompt"] == "Hallo Leyla" and "keywords[]" not in sent[1]
    sent.clear()
    assert asyncio.run(wakecheck.transcribe(b"x", "key", Client())) == "Hallo Leyla"
    assert sent[0] == {"model": "gpt-transcribe"}


def test_nobody_answering_is_not_the_same_as_silence():
    class Client:
        async def post(self, url, headers, data, files):
            raise OSError("down")

    assert asyncio.run(wakecheck.transcribe(b"x", "key", Client())) is None


def test_a_wav_of_the_history_can_be_read_back():
    import io
    import wave
    data = wakecheck.wav(b"\x01\x00" * 1600 + b"\x07", 16000)       # an odd byte at the end is dropped
    with wave.open(io.BytesIO(data)) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()) == (16000, 1, 2, 1600)
