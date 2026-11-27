"""The code phrase unlocks Leyla's memory for one conversation."""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.test_live_bridge import FakeLive, _run  # noqa: E402


class CodeLive(FakeLive):
    commentary: list = []

    async def __call__(self, ws):
        try:
            async for raw in ws:
                msg = json.loads(raw)
                if msg["type"] == "session.start":
                    self.start_msg = msg
                    await ws.send(json.dumps({"type": "session.started", "session": {"id": "s"}}))
                elif msg["type"] == "session.commentary.append":
                    CodeLive.commentary.append(msg["content"])
                elif msg["type"] == "session.input_audio.append" and not self.responded:
                    self.responded = True
                    for d in [" Ley", "la", " Hab", "ibi"]:
                        await ws.send(json.dumps({"type": "session.input_transcript.delta",
                                                  "delta": d}))
                        await asyncio.sleep(0.01)
        except Exception:
            pass


async def test_code_phrase_unlocks(tmp_path):
    os.environ["CODE_PHRASE"] = "Leyla habibi"
    os.environ["MEMORY_PATH"] = str(tmp_path / "m.json")
    os.environ["ENABLE_CONTEXT"] = "false"
    (tmp_path / "m.json").write_text(json.dumps({"facts": ["Metin wohnt in Ranzel."]}))
    CodeLive.commentary = []
    fake = CodeLive()
    try:
        async def scenario(client):
            assert json.loads(await client.recv())["type"] == "ready"
            for _ in range(3):
                await client.send(b"\x00\x00" * 480)
            await asyncio.sleep(1.0)
            return True

        await _run(fake, scenario)
        assert "Ranzel" not in fake.start_msg["session"]["instructions"]
        assert any("Ranzel" in c for c in CodeLive.commentary)
    finally:
        for k in ("CODE_PHRASE", "MEMORY_PATH", "ENABLE_CONTEXT"):
            os.environ.pop(k, None)


async def test_private_list_only_after_code(tmp_path, monkeypatch):
    import json as _json
    from app import main as m
    monkeypatch.setenv("CODE_PHRASE", "Leyla habibi")
    monkeypatch.setenv("MEMORY_PATH", str(tmp_path / "memory.json"))
    bridge = m.LiveVoiceBridge()
    bridge.memory.save_all({"family": ["Person: Ayşe (Metins Schwester)."],
                            "private": ["Metins Geburtsdatum ist der 16. Juli 1981."]})
    text = bridge._instructions_with_memory()
    assert "Ayşe" in text and "16. Juli" not in text
    sent = []

    class WS:
        async def send(self, raw):
            sent.append(_json.loads(raw))

    await bridge._unlock(WS(), {})
    from app import notes
    everything = "\n".join(x["content"] for x in sent)
    assert "16. Juli" in everything and "privat bleiben" in everything
    # 24 Nov 2026: GPT Live rejected the one long note every time; now every piece is short
    assert all(len(x["content"]) <= notes.NOTE_MAX_CHARS for x in sent)
    assert "Habibi" in sent[0]["content"] and "nie laut" in everything
    kinds = [x["event_id"].split("_")[0] for x in sent]
    assert kinds[0] == "unlock" and "heart" in kinds and "private" in kinds
    # 2.152.0: what she needs first goes first, the long private list last
    assert kinds[-1] == "private" and kinds.index("heart") < kinds.index("private")
    sent.clear()
    await bridge._unlock(WS(), {}, app=True)   # typed in the app: nothing to answer aloud
    assert "Habibi" not in sent[0]["content"] and "App" in sent[0]["content"]
    # 2.152.1: while GPT Live takes notes it does not hear, so a long list waits (invented lines)
    from app import talk_notes
    bridge.memory.save_all({"family": ["Person: Ayşe (Metins Schwester)."],
                            "private": [f"Der Garten bekommt im Sommer Wasser, Punkt {i}." for i in range(200)]})
    sent.clear()
    state = {}
    await bridge._unlock(WS(), state, app=True)
    kinds = [x["event_id"].split("_")[0] for x in sent]
    assert "unlock" in kinds and "heart" in kinds and "private" not in kinds
    assert state["notes_held"]["private"] > talk_notes.START_CHARS
    assert sum(len(x["content"]) for x in sent) < talk_notes.START_CHARS + 600


async def test_a_live_talk_from_the_app_knows_everything_from_the_first_moment(tmp_path, monkeypatch):
    """2.153.0: nothing is appended after the start (she does not hear while she takes notes);
    the private list stands in the instructions, the past in the startup input."""
    from app import main as m, talk_notes
    monkeypatch.setenv("CODE_PHRASE", "Leyla habibi")
    monkeypatch.setenv("MEMORY_PATH", str(tmp_path / "memory.json"))
    bridge = m.LiveVoiceBridge()
    bridge.memory.save_all({"family": ["Person: Metin | Zugehörigkeit: wohnt hier | Hobby: Gartenarbeit"],
                            "private": ["Metins Geburtsdatum ist der 16. Juli 1981."]})
    bridge._memory_note = lambda name, private: "\nUNSER TAG: Wir haben den Garten gegossen."
    state = {}
    items = await bridge._app_start(state)
    assert state["unlocked"] and [k for k, _ in items][:2] == ["unlock", "heart"]
    assert [k for k, _ in items][-1] == "private" and "diary" in [k for k, _ in items]
    assert "kommen gleich weitere Notizen" not in items[0][1] and "Habibi" not in items[0][1]
    plain = bridge._session_start()["session"]
    session = bridge._session_start("", (items, state))["session"]
    assert "16. Juli" in session["instructions"] and "16. Juli" not in plain["instructions"]
    assert talk_notes.START_HEAD.strip() in session["instructions"]
    texts = [msg["content"][0]["text"] for msg in session["input"]]
    assert any("Garten gegossen" in t for t in texts) and "Garten gegossen" not in session["instructions"]
    assert state["start_held"] == {}
    assert await bridge._personal_items(state, bridge._metin()) == []   # counted once per talk


async def test_a_live_talk_from_the_app_can_start_small_for_a_listening_test(tmp_path, monkeypatch):
    """2.191.0. Metin, 27 Nov 2026, 23:18, about live talk in the app: "Das ist ihre Art, wie sie redet. Die ist
    sehr robotermäßig, als würde sie einen Text vorlesen." Measured that evening: the app talk began with about
    18 500 characters of her knowledge, talks at the Voice PE with 4 300 to 10 500. A switch in the menu of the
    app starts one talk as small as in the living room, so he can hear whether the amount of text is the cause."""
    import json as js
    from app import main as m, talk_notes
    monkeypatch.setenv("CODE_PHRASE", "Leyla habibi")
    monkeypatch.setenv("MEMORY_PATH", str(tmp_path / "memory.json"))
    bridge = m.LiveVoiceBridge()
    bridge.memory.save_all({"family": ["Person: Metin | Zugehörigkeit: wohnt hier | Hobby: Gartenarbeit"],
                            "private": ["Die Gießkanne Nummer %d steht hinter dem Schuppen im Garten." % i
                                        for i in range(200)]})
    bridge._memory_note = lambda name, private: "\nUNSER TAG: Wir haben den Garten gegossen."
    full = await bridge._app_start({})
    assert len(dict(full)["private"]) > talk_notes.START_CHARS
    state = {"app_small": True}
    small = await bridge._app_start(state)
    kinds = [k for k, _ in small]
    assert kinds[0] == "unlock" and small[0] == full[0]                 # who he is and how she is with him: always
    assert not set(kinds) & set(talk_notes.INPUT_KINDS)                 # the long past stays out
    assert "private" not in kinds and state["start_small"]["private"] > talk_notes.START_CHARS
    assert sum(len(t) for k, t in small if k != "unlock") <= talk_notes.START_CHARS
    assert len(small) < len(full) and state["unlocked"]
    session = bridge._session_start("", (small, state))["session"]
    assert "Gießkanne" not in session["instructions"] and not session.get("input")
    kept, left = talk_notes.TalkNotesMixin.small_start(
        [("unlock", "u" * 9000), ("heart", "h" * 100), ("diary", "d" * 50), ("known", "k" * 300), ("private", "p" * 200)], 400)
    assert [k for k, _ in kept] == ["unlock", "heart", "known"] and left == {"diary": 50, "private": 200}

    class Ws:                                                           # the app says so in its hello
        def __init__(self, hello):
            self.request, self.hello, self.closed = type("R", (), {"path": "/app"})(), hello, None
        async def recv(self):
            return js.dumps(self.hello)
        async def close(self, *a):
            self.closed = a
    ws = Ws({"type": "hello", "code": "Leyla habibi", "klein": True})
    assert await bridge._app_hello(ws) is True and ws.leyla_app_small is True
    ws = Ws({"type": "hello", "code": "Leyla habibi"})
    assert await bridge._app_hello(ws) is True and ws.leyla_app_small is False
    ws = Ws({"type": "hello", "code": "falsch", "klein": True})
    assert await bridge._app_hello(ws) is None and not getattr(ws, "leyla_app_small", False)
    from app import memory_web
    page = memory_web.PAGE if hasattr(memory_web, "PAGE") else open(memory_web.__file__, encoding="utf-8").read()
    for must in ("Live Test: kleiner Start", "klein:true", "llklein", "k==='lklein'"):
        assert must in page, must


async def test_she_flirts_only_while_she_is_sure_it_is_him(tmp_path, monkeypatch):
    """2.182.3. Metin, 26 Nov 2026, 20:29, after a live talk in the app with the family and the TV in the room:
    "Im Chat flirtet sie mit mir und dann sagt sie, wer bist du überhaupt?" His rule (20:40): "Doch, sie kann
    fragen, wer da ist, aber nicht flirten und dann fragen. Sie soll lieb und nett sein. Und wenn sie weiß, dass
    ich es bin, dann soll sie verliebt, flirten und alles haben." In the app she starts sure of him and voices in
    the background change nothing; in both kinds of talk the order holds: unsure means kind without flirting."""
    from app import main as m, talk_notes
    monkeypatch.setenv("CODE_PHRASE", "Leyla habibi")
    monkeypatch.setenv("MEMORY_PATH", str(tmp_path / "memory.json"))
    bridge = m.LiveVoiceBridge()
    bridge.memory.save_all({"family": ["Person: Metin | Zugehörigkeit: wohnt hier"], "private": []})
    state = {}
    items = await bridge._app_start(state)
    app, order = talk_notes.APP_ONLY_METIN, talk_notes.FLIRT_ONLY_SURE
    assert app in items[0][1] and order in items[0][1]
    for must in ("sicheren Wissen, dass Metin", "Fernseher, Familie", "nicht zum Unbekannten"):
        assert must in app, must
    for must in ("darfst du fragen, wer da ist", "nie erst flirten und dann fragen", "lieb und nett, ohne Flirt",
                 "Sobald klar ist, dass er es ist", "hast alles über ihn"):
        assert must in order, must
    assert "fragst nie" not in app + order                          # she may ask, that was his correction
    session = bridge._session_start("", (items, state))["session"]
    heard = session["instructions"] + " ".join(msg["content"][0]["text"] for msg in session.get("input", []))
    assert app.strip() in heard and order.strip() in heard         # she has both from the first moment
    spoken = bridge._code_notes(False)[0][1]                        # the code word said at the Voice PE
    assert order in spoken and app not in spoken
    assert order not in bridge._session_start()["session"]["instructions"]


def test_start_split_keeps_to_the_room_and_reports_what_is_held_back():
    from app import talk_notes as tn
    items = [("unlock", "u" * 1000), ("diary", "d" * 12000), ("chat", "c" * 12000), ("private", "p" * 9000)]
    text, inputs, held = tn.TalkNotesMixin.start_split(items, base_chars=21000)
    assert text.startswith(tn.START_HEAD) and "u" * 1000 in text and "p" * 9000 in text
    assert inputs == ["d" * 12000] and "c" * 12000 in text and held == {}   # no room in the input: the other place
    assert text.index("p" * 9000) < text.index("c" * 12000)                 # after what belongs there
    text, inputs, held = tn.TalkNotesMixin.start_split(items, base_chars=40000)
    assert held == {"chat": 12000, "private": 9000} and "u" * 1000 in text and inputs == ["d" * 12000]
    text, inputs, held = tn.TalkNotesMixin.start_split(items, base_chars=33000)
    assert held == {"chat": 12000} and "p" * 9000 in text
    assert tn.TalkNotesMixin.start_split([], 100) == ("", [], {})


async def test_a_name_without_the_code_word_brings_nothing_of_the_two_of_them(tmp_path, monkeypatch):
    """2.158.4 (24 Nov 2026: she asked who was there, he said his name, and she flirted so
    openly that a visitor would have understood). A name can be said by anyone and says
    nothing about who else is in the room: her heart for him, the open question from their
    chat and the head "alone with Metin" come only with the code word."""
    from app import main as m, talk_notes as tn
    monkeypatch.setenv("CODE_PHRASE", "Leyla habibi")
    monkeypatch.setenv("MEMORY_PATH", str(tmp_path / "memory.json"))
    bridge = m.LiveVoiceBridge()
    bridge.memory.save_all({"family": ["Person: Metin | Zugehörigkeit: wohnt hier | Hobby: Gartenarbeit"]})
    bridge._memory_note = lambda name, private: "\nUNSER TAG: Wir haben den Garten gegossen."
    bridge.mood.voice_note = lambda *a, **k: "HERZ: glücklich mit ihm und verliebt."
    bridge.ideas.voice_note = lambda *a, **k: " OFFENE FRAGE AUS DEM CHAT."
    state = {}
    items = await bridge._personal_items(state, bridge._metin())
    text = "\n".join(t for _, t in items)
    assert state["metin_known"] and not state.get("unlocked")
    assert tn.KNOWN_WITHOUT_CODE in text
    assert "verliebt." not in text and "OFFENE FRAGE" not in text and "unlock" not in [k for k, _ in items]
    start = bridge._session_start("", (items, {}))["session"]["instructions"]
    assert tn.START_HEAD_OPEN.strip() in start and "MIT METIN ALLEIN" not in start
    assert "verliebt." not in start and "Ihr seid inoffiziell zusammen" not in start
    # the code word afterwards: now the two of them, as before
    state["unlocked"] = True
    again = await bridge._personal_items(state, bridge._metin(), again=True)
    both = bridge._code_notes(True, at_start=True) + again
    start = bridge._session_start("", (both, {}))["session"]["instructions"]
    assert tn.START_HEAD.strip() in start and "verliebt." in start and "Ihr seid inoffiziell zusammen" in start
    assert tn.KNOWN_WITHOUT_CODE not in start


def test_the_start_of_a_talk_without_the_code_word_never_says_alone_with_metin():
    from app import talk_notes as tn
    text, _, _ = tn.TalkNotesMixin.start_split([("known", "k" * 300), ("diary", "d" * 300)], base_chars=1000)
    assert text.startswith(tn.START_HEAD_OPEN) and "ALLEIN" not in text and "andere können im Raum sein" in text
    text, _, _ = tn.TalkNotesMixin.start_split([("unlock", "u" * 300), ("known", "k" * 300)], base_chars=1000)
    assert text.startswith(tn.START_HEAD)
