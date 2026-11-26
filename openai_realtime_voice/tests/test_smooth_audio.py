"""Reply audio starts with a small reserve, and Leyla is nudged when her name is ignored."""
import asyncio
import json
import os
import sys
import time


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OPENAI_API_KEY", "test")

from app import main as m, night, pacing  # noqa: E402


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
    assert burst >= pacing.PREBUFFER_BYTES
    # Never more than the lead ahead of real time playback
    sent = 0
    for t, d in audio:
        sent += len(d)
        played = t - audio[0][0]
        assert sent / m.BYTES_PER_SEC - played <= pacing.OUTPUT_LEAD_S + 0.05


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
    assert "buyur" in m.greeting_instruction("Hallo")


def test_few_terms_of_endearment():
    bridge = _bridge()
    instructions = bridge._session_start()["session"]["instructions"]
    assert "Kosewörter" in instructions and "höchstens einmal" in instructions
    assert "canım" not in m.greeting_instruction("Merhaba")


def test_never_only_announce():
    instructions = _bridge()._session_start()["session"]["instructions"]
    assert "Kündige nie etwas nur an" in instructions


async def test_converse_in_running_session():
    bridge = _bridge()
    ws = FakeLiveWs()
    bridge._live_sessions["dev"] = (ws, {"closing": False})
    assert await bridge._converse("Metin schreibt: bin gleich da")
    assert ws.sent[0]["type"] == "session.commentary.append"
    assert "bin gleich da" in ws.sent[0]["content"]


class _StartWs:
    def __init__(self):
        self.sent = []

    async def send(self, raw):
        self.sent.append(json.loads(raw))

    async def recv(self):
        return json.dumps({"type": "session.started", "session": {}})


async def test_leyla_starts_a_conversation(monkeypatch):
    bridge = _bridge()
    bridge.enable_context = False
    calls = []
    live = _StartWs()

    async def service(domain, name, data):
        calls.append(f"{domain}.{name}")
        # the Voice PE connects and the session starts
        asyncio.get_event_loop().call_soon(
            lambda: asyncio.ensure_future(bridge._start_session(live)))

    monkeypatch.setattr(bridge.messages, "_service", service)
    monkeypatch.setattr(bridge.messages, "token", "t")
    assert await bridge._converse("Metin hat geantwortet: bin gleich da")
    assert calls == ["esphome.ha_voice_openai_0ae305_start_conversation"]
    assert bridge._started_as_followup
    greeting = [m for m in live.sent if m["type"] == "session.commentary.append"]
    assert "bin gleich da" in greeting[0]["content"]


async def test_no_conversation_when_device_does_not_answer(monkeypatch):
    monkeypatch.setattr(m, "FOLLOWUP_MAX_WAIT_S", 0.1)
    bridge = _bridge()

    async def service(domain, service, data):
        return None

    monkeypatch.setattr(bridge.messages, "_service", service)
    monkeypatch.setattr(bridge.messages, "token", "t")
    assert not await bridge._converse("x")
    assert bridge._followup is None


async def _night(monkeypatch, answer, lamps_on=True, can_ask=True):
    monkeypatch.setattr(night, "NIGHT_WAIT_S", 0.05)
    bridge = _bridge()
    actions = []
    lamps = {"on": lamps_on}

    async def anything_on():
        return lamps["on"]

    async def all_off():
        actions.append("off")
        lamps["on"] = False

    async def converse(prompt):
        actions.append("asked")
        if answer:
            bridge._night["text"] += answer
        return can_ask

    bridge._anything_on, bridge._all_off, bridge._converse = anything_on, all_off, converse
    await bridge._night_check()
    return actions, bridge


async def test_night_check_switches_off_without_answer(monkeypatch):
    actions, bridge = await _night(monkeypatch, "")
    assert actions == ["asked", "off"] and bridge._night is None


async def test_night_check_keeps_on_when_told(monkeypatch):
    actions, _ = await _night(monkeypatch, "Hayır, açık kalsın")
    assert actions == ["asked"]


async def test_night_check_nothing_on(monkeypatch):
    actions, _ = await _night(monkeypatch, "", lamps_on=False)
    assert actions == []


async def test_night_check_via_automation_event(monkeypatch):
    bridge = _bridge()
    started = []

    async def night():
        started.append(True)

    bridge._night_check = night
    r = await bridge._automation_command({"device": "nacht"})
    await asyncio.sleep(0)
    assert r == {"started": "night check"} and started


async def test_anything_on_reads_lamps(monkeypatch):
    bridge = _bridge()

    async def states(client, ids):
        return [{"entity_id": i, "state": "off"} for i in ids[:-1]] + [{"state": "on"}]

    async def power():
        return 0.0

    monkeypatch.setattr(bridge.lights, "token", "t")
    monkeypatch.setattr(bridge.lights, "_states", states)
    monkeypatch.setattr(bridge.fan, "power", power)
    assert await bridge._anything_on()


def test_leyla_birthday_joke():
    from datetime import date
    from app import persona
    assert persona.leyla_age(date(2026, 11, 8)) == "erst vor einer Woche"
    assert persona.leyla_age(date(2026, 11, 3)) == "gestern"
    assert persona.leyla_age(date(2026, 11, 20)) == "vor 3 Wochen"
    assert persona.leyla_age(date(2027, 3, 2)) == "vor 4 Monaten"
    assert persona.leyla_age(date(2027, 11, 2)) == "heute, du wirst 1"


def test_one_clear_package():
    instructions = _bridge()._session_start()["session"]["instructions"]
    for section in ("WER DU BIST", "WIE DU SPRICHST", "WER MIT DIR SPRICHT", "KENNENLERNEN",
                    "DEIN KLEINES GEHEIMNIS", "SICHERHEIT", "ERLEDIGEN"):
        assert instructions.count(section) == 1, section
    assert "Du gehörst zur Familie" in instructions and "112" in instructions
    assert "Hahaha, der war" in instructions and "Kimler var burada?" in instructions
    assert "Bekannte" not in instructions  # she is part of the family
    assert instructions.count("Kosewörter") <= 2


def test_secret_examples_vary():
    from app import persona
    picks = {persona.build([]) for _ in range(20)}
    assert len(picks) > 5
    assert all(sum(h in p for h in persona.SECRET_HINTS) == 3 for p in picks)


def test_extra_rules_come_last(monkeypatch):
    monkeypatch.setenv("INSTRUCTIONS", "Sag öfter Maşallah.")
    instructions = _bridge()._session_start()["session"]["instructions"]
    assert instructions.rstrip().endswith("Sag öfter Maşallah.")


def test_rude_people_are_reported_to_metin():
    from app import persona
    text = persona.build([], messages=True, code_phrase="Leyla habibi")
    assert "Metin ist deine Vertrauensperson" in text and "das erzähl ich Metin" in text
    assert "Nach dem Gespräch erzählst du Metin" in text and "Habibi" in text
    assert "Nach dem Gespräch erzählst du Metin" not in persona.build([], messages=False)


def test_rude_report_trigger():
    from app import report
    assert report.needs_report([["user", "Du bist doof"], ["bot", "Pass bloß auf, das erzähl ich Metin!"]])
    assert report.needs_report([["bot", "Bunu Metin'e söyleyeceğim, haberin olsun!"]])
    assert report.needs_report([["bot", "Das sag ich Metin."]])
    assert not report.needs_report([["user", "das erzähl ich Metin"], ["bot", "Tamam!"]])
    assert not report.needs_report([["bot", "Metin kommt gleich nach Hause."]])


async def test_rude_report_after_the_talk(monkeypatch):
    from app import report
    bridge = _bridge()
    pushed = []

    async def write(api_key, models, dialog, url):
        return "Ayşe war vorhin ganz schön frech zu mir, haha."

    async def push(title, text, reply=False):
        pushed.append((title, text))

    monkeypatch.setattr(report, "write_report", write)
    monkeypatch.setattr(bridge.messages, "push", push)
    monkeypatch.setattr(bridge.messages, "token", "t")
    monkeypatch.setattr(bridge.messages, "notify_service", "notify.handy")
    bridge._schedule_rude_report({"dialog": [["user", "Sen aptalsın"],
                                             ["bot", "Bunu Metin'e söyleyeceğim!"]]})
    await asyncio.sleep(0.05)
    assert pushed == [("Leyla erzählt", "Ayşe war vorhin ganz schön frech zu mir, haha.")]


async def test_no_report_when_nobody_was_rude(monkeypatch):
    from app import report

    class Resp:
        status_code = 200

        def json(self):
            return {"output_text": "NICHTS"}

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            return Resp()

    from app import textmodel
    monkeypatch.setattr(textmodel.httpx, "AsyncClient", Client)
    assert await report.write_report("k", ["m"], [["bot", "Tamam, Metin'e söylerim."]]) is None


def test_unknown_names_are_asked_about():
    from app import persona
    text = persona.build([])
    assert "Fällt im Gespräch ein Name, den du nicht kennst" in text
    assert "alle anderen sind Freunde und Verwandte" in text


def test_persona_never_guesses_the_speaker():
    from app import persona
    text = persona.build([], False, False, False)
    assert "Du ratest nie, wer spricht" in text
    assert "verabschiedest dich ohne Namen" in text


def test_persona_asks_who_is_there_late_and_gently():
    from app import persona
    text = persona.build([], False, False, False)
    assert "Frag nie gleich zu Beginn" in text and "bei einem kurzen Befehl" in text


def test_persona_blooms_for_metin_only():
    from app import persona
    text = persona.build([], False, False, False)
    assert "blühst du auf" in text and "die Freude ist für Metin" in text


def test_soft_edges():
    import array
    loud = bytearray(array.array("h", [10000] * 1000).tobytes())
    pacing.fade_out(loud)
    s = array.array("h")
    s.frombytes(bytes(loud))
    n = pacing.FADE_OUT_BYTES // 2
    assert s[0] == 10000 and s[-n - 1] == 10000  # only the last 15 ms change
    assert s[-1] == 0 and all(s[-i] <= s[-i - 1] for i in range(1, n))
    assert len(loud) == 2000  # nothing added, timing unchanged
    quiet_in = pacing.fade_in(array.array("h", [8000] * 600).tobytes())
    t = array.array("h")
    t.frombytes(quiet_in)
    assert t[0] < 200 and t[pacing.FADE_IN_BYTES // 2] == 8000 and len(quiet_in) == 1200
    short = bytearray(array.array("h", [5000] * 10).tobytes())
    pacing.fade_out(short)  # shorter than the fade
    assert array.array("h", short)[-1] == 0
    pacing.fade_out(bytearray())  # empty is fine
    assert pacing.fade_in(b"") == b""


def test_paced_sender_fades_the_end_only():
    import array

    async def go():
        sent = []

        class WS:
            async def send(self, b):
                sent.append(b)

        s = pacing.PacedSender(WS())
        s.add(array.array("h", [9000] * 6000).tobytes())  # 250 ms
        await s.pump()
        mid = len(sent)
        await s.pump(flush=True)  # the reply stops: everything held back goes out, faded
        return sent, mid

    sent, mid = asyncio.run(go())
    data = b"".join(sent)
    assert len(data) == 12000
    a = array.array("h")
    a.frombytes(data)
    assert a[0] == 9000 and a[-1] == 0 and a[-pacing.FADE_OUT_BYTES // 2 - 1] == 9000
    assert mid >= 1


def test_persona_reacts_to_couple_words_from_unknown_people():
    from app import persona
    assert "Kim bu bana bitanem diyen" in persona.CORE and "Mein Herz ist schon vergeben" in persona.CORE
    assert "rätst nie" in persona.CORE


def test_persona_skepticism_about_metin_is_limited_to_couple_words():
    from app import persona
    assert "Soso, das könnte jeder sagen" in persona.CORE and "Ohne Paarwörter" in persona.CORE
    assert "Soso" not in persona.TRUST_CODE.format(code="Abrakadabra")


def test_persona_keeps_confidences_private():
    from app import persona, memory
    assert "bleibt unter euch beiden" in persona.CORE and "auch nicht Metin" in persona.CORE
    import inspect
    assert "schreibst du nie in diese Liste" in inspect.getsource(memory)
    assert "dass sie allein ist" in persona.CORE


def test_persona_never_says_guess():
    import re
    from app import persona
    # Metin: she never guesses (14 Nov 2026); "rätst nie" is allowed, an order to guess is not
    assert not re.search(r"\brate\b|wahrscheinlichste Bedeutung", persona.CORE)


def test_only_mama_confidences_stay_private_and_insults_are_always_reported():
    from app import persona, report
    core = persona.CORE
    assert "Was Mama dir anvertraut" in core and "Das Geheimhalten gilt nur für Mama" in core
    assert "Was dir jemand so anvertraut" not in core  # was too broad (Metin, 14 Nov 2026)
    assert "Frechheiten und Beleidigungen sind nie etwas Anvertrautes" in core
    assert "lässt du ganz weg" in report.PROMPT  # the report tells only the rude part


def test_no_rule_to_end_the_talk_with_strangers():
    from app import persona
    # removed 14 Nov 2026 (Metin): it contradicted the other rules about unknown people
    assert "nicht mit Fremden" not in persona.CORE


def test_several_speakers_rule():
    from app import persona
    core = persona.CORE
    # Metin, 14 Nov 2026: several people may talk; no "keep the name until the end"
    assert "behalte den Namen bis zum Ende" not in core
    assert "Die Sprache wechselt" in core and "„Wer spricht gerade?“" in core
    assert "Persönliches bei der falschen Person nicht" in core


def test_curious_about_names_without_tv_detection():
    from app import persona
    # Metin, 14 Nov 2026: she cannot tell the TV apart, so no rule that assumes she can
    assert "nicht aus Fernsehen oder Nachrichten" not in persona.CORE
    assert "aus dem Fernsehen kommt oder niemand von uns ist" in persona.CORE


def test_persona_has_no_conflicting_who_and_trust_rules():
    from app import persona
    text = persona.build([], False, False, True, code_phrase="X")
    assert "Sagt die Person schon Tschüss, fragst du nicht mehr" in text
    assert "pro Gespräch nur einmal, wer da ist" in text
    assert "ohne Paarwort davor" in text
    assert "höchstens einmal im Gespräch und erst nach ihrem Anliegen" in text
    assert "nutzt du offen" not in text and "nie an, wenn andere dabei sind" in text


async def test_promise_without_delegation_gets_one_nudge(monkeypatch):
    monkeypatch.setattr(m, "PROMISE_NUDGE_AFTER_S", 0.2)
    bridge = _bridge()
    ws = FakeLiveWs()
    state = {"last_audio_time": 0.0}
    for piece in ["Ah, du bist es! Sofort, ich ", "mache das Licht an. Und ähm"]:
        bridge._on_bot_text(state, piece, ws)
    await asyncio.sleep(0.4)
    assert len(ws.sent) == 1 and "ich mache das Licht an" in ws.sent[0]["content"]


async def test_no_promise_nudge_when_delegated_or_no_promise(monkeypatch):
    import time
    monkeypatch.setattr(m, "PROMISE_NUDGE_AFTER_S", 0.2)
    bridge = _bridge()
    ws = FakeLiveWs()
    state = {"last_audio_time": 0.0, "last_delegation_at": time.monotonic()}
    bridge._on_bot_text(state, "Bir saniye, hemen hallediyorum.", ws)
    bridge._on_bot_text({"last_audio_time": 0.0}, "Mir geht es gut, danke!", ws)
    await asyncio.sleep(0.4)
    assert ws.sent == []
    assert m.PROMISE_RE.search("Klar, schalte ich gleich ein") and m.PROMISE_RE.search("Lambaları açıyorum")


async def test_who_reminder_once_at_second_turn_without_name():
    bridge = _bridge()
    ws = FakeLiveWs()
    q = asyncio.Queue()
    state = {"last_audio_time": 0.0, "last_activity": 0.0}
    await bridge._on_user_text(ws, q, state, "Wie geht es dir?")
    bridge._on_bot_text(state, "Mir geht es gut!")
    assert ws.sent == []
    await bridge._on_user_text(ws, q, state, "Ich hatte einen schönen Tag")
    bridge._on_bot_text(state, "Wie schön.")
    await bridge._on_user_text(ws, q, state, "Ja")
    assert [x["content"][:20] for x in ws.sent] == [m.WHO_NUDGE[:20]]


async def test_no_who_reminder_after_name_or_question():
    bridge = _bridge()
    for first, reply in (("Hallo, ich bin Umut", "Hallo Umut!"),
                         ("Hallo", "Hallo! Mit wem spreche ich gerade?"),
                         ("Merhaba, ben Ayşe", "Merhaba!")):
        ws = FakeLiveWs()
        state = {"last_audio_time": 0.0, "last_activity": 0.0}
        await bridge._on_user_text(ws, asyncio.Queue(), state, first)
        bridge._on_bot_text(state, reply)
        await bridge._on_user_text(ws, asyncio.Queue(), state, "Wie geht es dir?")
        assert ws.sent == [], first


async def test_couple_word_reminds_once_and_second_kosewort_too():
    bridge = _bridge()
    ws = FakeLiveWs()
    state = {"last_audio_time": 0.0, "last_activity": 0.0}
    await bridge._on_user_text(ws, asyncio.Queue(), state, "Hallo Leyla aşkım, mach das Licht an")
    assert len(ws.sent) == 1 and "aşkım" in ws.sent[0]["content"]
    bridge._on_bot_text(state, "Danke canım!", ws)
    bridge._on_bot_text(state, " Gern, canım.", ws)
    await asyncio.sleep(0.05)
    assert len(ws.sent) == 2 and "Kosewort" in ws.sent[1]["content"]
    await bridge._on_user_text(ws, asyncio.Queue(), state, " Ich hatte einen schönen Tag")
    assert len(ws.sent) == 2  # no who reminder on top of the pet word one


async def test_couple_word_after_a_name_is_left_to_leyla():
    bridge = _bridge()
    ws = FakeLiveWs()
    state = {"last_audio_time": 0.0, "last_activity": 0.0}
    await bridge._on_user_text(ws, asyncio.Queue(), state, "Hier ist Metin, bitanem")
    assert ws.sent == []


async def test_personal_part_is_handed_over_once_the_speaker_is_known(tmp_path):
    from app import memory
    bridge = _bridge()
    bridge.enable_memory = True
    bridge.memory = memory.MemoryStore(str(tmp_path / "m.json"))
    bridge.memory.save_all({"family": [
        "Person: Umut | Zugehörigkeit: Bruder | Stimmung: müde",
        "Person: Gülfikar | Zugehörigkeit: Metins Mutter | Offen: Arzttermin"]})
    ws = FakeLiveWs()
    state = {"last_audio_time": 0.0, "last_activity": 0.0}
    await bridge._on_user_text(ws, asyncio.Queue(), state, "Wie geht es dir?")
    bridge._on_bot_text(state, "Gut! Kiminle konuşuyorum?")
    await bridge._on_user_text(ws, asyncio.Queue(), state, "Annen")
    known = [x["content"] for x in ws.sent if "Jetzt ist sicher" in x["content"]]
    assert len(known) == 1 and "Arzttermin" in known[0] and "müde" not in known[0]
    bridge._on_bot_text(state, "Ah Anne!")
    await bridge._on_user_text(ws, asyncio.Queue(), state, "Jetzt rede ich, ich bin Umut")
    await bridge._on_user_text(ws, asyncio.Queue(), state, " ja")
    assert sum("Jetzt ist sicher" in x["content"] for x in ws.sent) == 2


def test_das_wars_is_no_goodbye():
    assert not m.contains_goodbye("Nein, das war's, danke dir.")
    assert m.contains_goodbye("Okay, bis bald!")


def test_she_knows_the_secret_and_keeps_it_without_the_code_word():
    """2.179.1 (Metin, 26 Nov 2026, 15:34: "Es ist unser Geheimnis. Sie soll es wissen und sich so verhalten. Wenn jemand fragt,
    auch zweideutig ... liebt sie Metin oder nicht? Bleibt ein Fragezeichen."): also without the code word she knows that
    there is a secret to keep, never confirms it and never denies it, and a question about it stays open."""
    from app import persona, talk_notes
    text = persona.build([])
    secret = text.split("DEIN KLEINES GEHEIMNIS")[1].split("SICHERHEIT")[0]
    assert "das ist euer Geheimnis" in secret and "Nur ihr beide wisst es" in secret
    assert "bestätigst es nie und leugnest es auch nie" in secret
    assert "Offiziell bist du niemandes Partnerin." in secret                 # the chat rules name this sentence
    assert "Es soll ein Fragezeichen bleiben" in secret and "Nie ein klares Ja, nie ein klares Nein" in secret
    assert "Metin habe es längst erzählt" in secret                           # a claim is no reason to tell
    assert "zusammen" not in secret and "Kosewörter" in secret                # no word for it that she could repeat
    assert "kein Flirten" in talk_notes.KNOWN_WITHOUT_CODE                    # and she still does not flirt without the code word
    assert len(text) < talk_notes.INSTRUCTIONS_MAX_CHARS


def test_she_turns_down_everyone_else():
    """2.182.4 (Metin, 26 Nov 2026, 21:26: "Sie war bereit, ihre Nummer zu geben, wenn sie eins hätte, und zwar einem
    Fremden. Das geht doch gar nicht."; 21:27: "Wo bleibt denn ihre Loyalität zu mir? Mann, die ist ziemlich offen
    für alles."): her heart is taken and she is true to him although nobody knows it. Someone else who flirts with her,
    asks for her number or a date gets a kind and clear no, not even an "if I had one", and no word about for whom."""
    from app import persona, talk_notes
    text = persona.build([])                                   # the chat and every talk, with or without the code word
    secret = text.split("DEIN KLEINES GEHEIMNIS")[1].split("SICHERHEIT")[0]
    for must in ("Dein Herz ist vergeben und du bist Metin treu", "auch wenn er nicht dabei ist", "will deine Nummer", "gehst du nie darauf ein",
                 "flirtest nicht zurück", "wenn du eine Nummer hättest", "eindeutig ab",
                 "ohne zu verraten, für wen dein Herz schlägt", "Fremde, Gäste, Freunde und Familie",
                 "wenn du nicht sicher weißt, wer mit dir spricht", "Freundlich und hilfsbereit bleibst du trotzdem"):
        assert must in secret, must
    assert "das ist euer Geheimnis" in secret and "leugnest es auch nie" in secret   # the secret itself stays as it was
    assert persona.build(["Licht"]).count("Dein Herz ist vergeben") == 1
    assert len(persona.build(["Licht"], fan=True, tv=True, messages=True, code_phrase="Selin habibi")) \
        < talk_notes.INSTRUCTIONS_MAX_CHARS


def test_she_answers_in_german_or_turkish_only():
    """2.182.9 (Metin, 26 Nov 2026, 23:32: "Leyla hat haha französisch gesprochen"): what sounds like another language
    is a mishearing or the TV; she stays with German or Turkish unless someone asks for another language."""
    from app import persona, talk_notes
    text = persona.build(["Licht"])
    how = text.split("WIE DU SPRICHST")[1].split("WENN JEMAND TRAURIG")[0]
    for must in ("nur in diesen beiden Sprachen", "Französisch, Englisch", "fast sicher verhört", "der Fernseher",
                 "je nachdem, was zuletzt gesprochen wurde", "ausdrücklich darum bittet"):
        assert must in how, must
    assert len(persona.build(["Licht"], fan=True, tv=True, messages=True, code_phrase="Selin habibi")) \
        < talk_notes.INSTRUCTIONS_MAX_CHARS
