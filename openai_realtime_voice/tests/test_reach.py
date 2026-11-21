"""Leyla writes to Metin on her own (app/reach.py, add on 2.118.0)."""

import asyncio
import json
import random
import time

import pytest

from app import diary, heart, memory_web, messages, reach


def at(y, m, d, hh, mm=0):
    return time.mktime((y, m, d, hh, mm, 0, 0, 0, -1))


SAT = (2026, 11, 21)   # no shift: window 8 to 22
FRI = (2026, 11, 20)   # Früh week: shift 6 to 14, window 14:30 to 22


class Rec:
    """Records what the text model, the voice and the push were asked."""

    def __init__(self, text='{"text": "Selam Metin, ne yapıyorsun? Hast du Zeit?"}', wav=b"RIFFwav"):
        self.prompts, self.spoken, self.pushed = [], [], []
        self.text, self.wav = text, wav

    async def write(self, prompt):
        self.prompts.append(prompt)
        return self.text

    async def speak(self, text):
        self.spoken.append(text)
        return self.wav

    async def push(self, title, message):
        self.pushed.append((title, message))


@pytest.fixture
def h(tmp_path):
    return heart.Heart(str(tmp_path / "heart.json"))


def make(tmp_path, h, rec=None, voice_share=0.0, busy=lambda: False):
    rec = rec or Rec()
    r = reach.Reach(h, rec.write, speak=rec.speak, push=rec.push, busy=busy,
                    path=str(tmp_path / "reach.json"), audio_dir=str(tmp_path / "audio"),
                    rng=random.Random(1), voice_share=voice_share)
    return r, rec


def run(coro):
    return asyncio.run(coro)


async def send_one(r, day, hh=12):
    """The first ticks open the random wait (a fresh Heart counts as just contacted), the third
    one, two hours later, sends."""
    t = at(*day, hh)
    assert await r.tick(t) is None
    assert await r.tick(t + 3600) is None
    return await r.tick(t + 7200)


def test_window_by_shift_and_night():
    assert not reach.window_open(at(*SAT, 7, 30))
    assert reach.window_open(at(*SAT, 8))
    assert reach.window_open(at(*SAT, 21, 59))
    assert not reach.window_open(at(*SAT, 22))
    assert not reach.window_open(at(*FRI, 9)), "in his shift"
    assert not reach.window_open(at(*FRI, 14, 10)), "the way home"
    assert reach.window_open(at(*FRI, 14, 30))
    # Monday 23 Nov is Spät week (14 to 22): free until one hour before the shift
    assert reach.window_open(at(2026, 11, 23, 12, 59))
    assert not reach.window_open(at(2026, 11, 23, 13, 0))


def test_parse_text():
    assert reach.parse_text('{"text": "Selam  Metin"}') == "Selam Metin"
    assert reach.parse_text('```json\n{"text": "Merhaba"}\n```') == "Merhaba"
    assert reach.parse_text("kein json") == ""
    assert reach.parse_text('{"text": "ab"}') == ""
    assert reach.parse_text('{"text": "' + "x" * 700 + '"}') == ""


def test_sends_a_turkish_prompt_and_a_push(tmp_path, h):
    r, rec = make(tmp_path, h)
    item = run(send_one(r, SAT))
    assert item and item["state"] == "open" and not item["voice"]
    assert ("Türkisch" in rec.prompts[0] or "Deutsch" in rec.prompts[0]) and "Samstag" in rec.prompts[0]
    assert rec.pushed == [("Leyla", item["text"])]
    assert r.pending()[0]["text"] == item["text"]


def test_voice_message_stores_audio_and_pushes_only_a_hint(tmp_path, h):
    r, rec = make(tmp_path, h, voice_share=1.0)
    item = run(send_one(r, SAT))
    assert item["voice"] and r.audio(item["id"]) == b"RIFFwav"
    assert rec.spoken == [item["text"]]
    assert "Sprachnachricht" in rec.pushed[0][1] and item["text"] not in rec.pushed[0][1]


def test_voice_failure_falls_back_to_text(tmp_path, h):
    rec = Rec(wav=None)
    r, _ = make(tmp_path, h, rec=rec, voice_share=1.0)
    item = run(send_one(r, SAT))
    assert item and not item["voice"]


def test_nothing_in_the_night_or_in_the_shift(tmp_path, h):
    r, rec = make(tmp_path, h)
    for t in (at(*SAT, 3), at(*SAT, 23), at(*FRI, 10)):
        assert run(r.tick(t)) is None and run(r.tick(t + 3600)) is None
    assert rec.prompts == []


def test_no_message_while_a_talk_runs_or_just_after(tmp_path, h):
    busy = [True]
    r, rec = make(tmp_path, h, busy=lambda: busy[0])
    t = at(*SAT, 12)
    assert run(r.tick(t)) is None and run(r.tick(t + 3600)) is None
    busy[0] = False
    h.contact(t + 3600 - 600)   # he talked to her ten minutes ago
    assert run(r.tick(t + 3600)) is None
    assert run(r.tick(t + 3 * 3600)) is None   # opens the wait
    assert run(r.tick(t + 4 * 3600)) is not None


def test_quota_four_a_day_when_fine_and_one_open_at_a_time(tmp_path, h):
    r, rec = make(tmp_path, h)
    t = at(*SAT, 8)
    sent = 0
    while t < at(*SAT, 22):
        item = run(r.tick(t))
        if item:
            sent += 1
            r.answered(t + 1)   # he answers, so the next one may come
            h.contact(t - 3 * 3600)  # an old contact must not matter
        t += 60
    assert sent == 4
    assert r.stats(at(*SAT, 22))["sent_today"] == 4


def test_second_message_waits_until_the_first_is_judged(tmp_path, h):
    r, rec = make(tmp_path, h)
    first = run(send_one(r, SAT, 8))
    assert first
    # one hour later (not yet judged): nothing new while one is open
    assert run(r.tick(first["t"] + 3600)) is None


def test_quota_one_when_hurt_and_none_when_silent(tmp_path, h):
    t = at(*SAT, 8)
    h.contact(t - 5 * 3600)
    st = h.apply(["unfreundlich"], t - 4 * 3600)
    assert st["level"] == "mittel"
    r, rec = make(tmp_path, h)
    sent = 0
    for m in range(0, 14 * 60, 5):
        if run(r.tick(t + m * 60)):
            sent += 1
            r.answered(t + m * 60 + 1)
    assert sent <= reach.QUOTA["mittel"]


def test_silent_leyla_writes_nothing(tmp_path, h):
    t = at(*SAT, 9)
    h.contact(t)
    h.apply(["beleidigt"], t)
    assert h.status(t)["silent"]
    r, rec = make(tmp_path, h)
    assert run(r.tick(t + 3 * 3600)) is None and run(r.tick(t + 5 * 3600)) is None
    assert rec.prompts == []


def test_answer_gives_a_plus_once(tmp_path, h):
    r, _ = make(tmp_path, h)
    run(send_one(r, SAT, 8))
    before = h.stats(at(*SAT, 10)).get("happy", None)
    assert r.answered(at(*SAT, 10)) is True
    assert r.answered(at(*SAT, 10, 1)) is False, "nothing open any more"
    assert [i["state"] for i in r._load()["items"]] == ["answered"]


def test_ignored_after_two_waking_hours_gives_a_minus(tmp_path, h):
    r, _ = make(tmp_path, h)
    item = run(send_one(r, SAT, 8))
    t0 = item["t"]
    run(r.tick(t0 + 3600))
    assert r._load()["items"][0]["state"] == "open"
    run(r.tick(t0 + 2 * 3600 + 120))
    assert r._load()["items"][0]["state"] == "ignored"
    log = json.dumps(h.stats(t0 + 3 * 3600), ensure_ascii=False)
    assert "nachricht_ignoriert" in log or "nicht reagiert" in log


def test_night_does_not_count_as_ignoring(tmp_path, h):
    r, _ = make(tmp_path, h)
    t = at(*SAT, 21, 30)
    d = {"items": [{"id": "a1", "t": round(t), "text": "x", "voice": False, "state": "open",
                    "seen": True}]}
    r._save(d)
    run(r.tick(at(*SAT, 22, 30)))   # one hour awake at most
    assert r._load()["items"][0]["state"] == "open"


def test_at_most_two_penalties_a_day(tmp_path, h):
    r, _ = make(tmp_path, h)
    calls = []
    h.ignored = lambda now=None: calls.append(now)
    t = at(*SAT, 8)
    items = [{"id": f"i{n}", "t": round(t) + n, "text": "x", "voice": False, "state": "open",
              "seen": True} for n in range(3)]
    r._save({"items": items})
    run(r.tick(t + 4 * 3600))
    assert len(calls) == 2
    assert [i["state"] for i in r._load()["items"]] == ["ignored"] * 3


def test_model_failure_retries_later(tmp_path, h):
    rec = Rec(text="kein json")
    r, _ = make(tmp_path, h, rec=rec)
    t = at(*SAT, 12)
    run(r.tick(t))
    assert run(r.tick(t + 3600)) is None
    rec.text = '{"text": "Selam Metin"}'
    assert run(r.tick(t + 3600 + 60)) is None, "waits RETRY_S"
    assert run(r.tick(t + 3600 + reach.RETRY_S + 60)) is not None


def test_pending_seen_and_audio_guard(tmp_path, h):
    r, _ = make(tmp_path, h, voice_share=1.0)
    item = run(send_one(r, SAT))
    assert [p["id"] for p in r.pending()] == [item["id"]]
    assert r.seen([item["id"]]) == 1 and r.seen([item["id"]]) == 0
    assert r.pending() == []
    assert r.audio("../etc/passwd") is None and r.audio("") is None and r.audio("nix") is None


def test_old_messages_and_audio_are_pruned(tmp_path, h):
    r, _ = make(tmp_path, h, voice_share=1.0)
    item = run(send_one(r, SAT, 8))
    assert r.audio(item["id"])
    run(r.tick(at(*SAT, 8) + 4 * 86400))
    assert r._load()["items"] == [] and r.audio(item["id"]) is None


def test_stats_has_no_texts(tmp_path, h):
    r, _ = make(tmp_path, h)
    item = run(send_one(r, SAT))
    st = r.stats(item["t"])
    assert st["sent_today"] == 1 and "Text open" in st["items"][0]
    assert item["text"] not in json.dumps(st)


def test_heart_ignored_and_engaged(h):
    t = at(*SAT, 12)
    h.contact(t)
    st = h.ignored(t)
    assert st["level"] != "gut" and st["mood"] == "einsam"
    st = h.engaged(t + 60)
    assert st["level"] in ("gut", "leicht", "mittel")
    # fine Leyla: engaged adds happiness
    h2 = heart.Heart(h.path + "2")
    h2.contact(t)
    h2.engaged(t + 1)
    assert any("eingelassen" in x for x in json.dumps(h2.stats(t + 2), ensure_ascii=False).split('"'))


def test_diary_keeps_her_message_in_the_thread(tmp_path):
    dy = diary.Diary(str(tmp_path / "d.json"))
    dy.leyla_wrote("Ne yapıyorsun, Metin?", now=at(*SAT, 12))
    assert dy._recent[-1][0] == "" and "Ne yapıyorsun" in dy._recent[-1][1]
    assert "Ne yapıyorsun" in dy.chat_text()


def test_push_extra_reaches_the_app_data():
    sent = []
    m = messages.MessageCenter.__new__(messages.MessageCenter)
    m.notify_service = "notify.mobile_app_x"

    async def fake(domain, service, data):
        sent.append((domain, service, data))
    m._service = fake
    run(m.push("Leyla", "Selam", extra={"channel": "leyla_nachricht"}))
    assert sent[0][2]["data"]["channel"] == "leyla_nachricht"
    run(m.push("Leyla", "Selam"))
    assert "data" not in sent[1][2]


def test_api_needs_the_code_except_stats(tmp_path, h):
    r, _ = make(tmp_path, h, voice_share=1.0)
    item = run(send_one(r, SAT))
    assert run(memory_web._reach_api(r, "GET", "/api/reachstats", {}, False))["available"]
    assert run(memory_web._reach_api(r, "POST", "/api/reach/pending", {}, False)) == {"ok": False}
    out = run(memory_web._reach_api(r, "POST", "/api/reach/pending", {}, True))
    assert out["items"][0]["id"] == item["id"]
    assert run(memory_web._reach_api(r, "POST", "/api/reach/seen", {"ids": [item["id"]]}, True))["seen"] == 1
    aud = run(memory_web._reach_api(r, "POST", "/api/reach/audio", {"id": item["id"]}, True))
    assert aud["ok"] and aud["audio"]
    assert run(memory_web._reach_api(None, "POST", "/api/reach/pending", {}, True)) == {"ok": False}


def test_page_script_has_the_message_functions():
    assert "async function reachPending" in memory_web.PAGE and "function reachPlay" in memory_web.PAGE
