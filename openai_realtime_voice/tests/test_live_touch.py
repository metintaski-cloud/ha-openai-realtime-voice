"""2.193.0. Metin, 28 Nov 2026, 00:19, after a live talk in the app in which he touched her on the stage: her
comment from the chat and her live voice overlapped ("verschnitten"). "Ist es möglich, dass wir diese
Automatisation wegmachen und dass die Leyla tatsächlich spricht und genau weiß, was ich gemacht habe?" During a
live talk the app now tells the talk itself where he touched her; the chat comment and the clip sound stay away."""
import json

from app import chat, memory_web


class Line:
    def __init__(self):
        self.sent = []

    async def send(self, text):
        self.sent.append(json.loads(text))


def _bridge(monkeypatch, tmp_path):
    from app import main as m
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("CODE_PHRASE", "Leyla habibi")
    monkeypatch.setenv("MEMORY_PATH", str(tmp_path / "memory.json"))
    monkeypatch.setenv("LEYLA_HEART_PATH", str(tmp_path / "heart.json"))
    return m, m.LiveVoiceBridge()


def test_the_note_says_where_and_asks_for_one_spoken_sentence():
    for zone, where in chat.TOUCH_WHERE.items():
        note = chat.live_touch_note(zone)
        assert where in note and "einen einzigen kurzen Satz" in note and "nie explizit" in note
        assert "nicht vorlesen" in note and "lass ihn ausreden" in note and "Gespräch normal weiter" in note
    assert chat.live_touch_note("knie") == "" and chat.live_touch_note("") == ""


async def test_a_touch_in_a_live_talk_from_the_app_is_told_to_her_once(tmp_path, monkeypatch):
    m, bridge = _bridge(monkeypatch, tmp_path)
    touched = []
    bridge.mood.touched = lambda: touched.append(1)
    line, state = Line(), {"from_app": True}
    assert await bridge._live_touch(line, state, json.dumps({"type": "touch", "zone": "bauch"})) is True
    assert len(line.sent) == 1 and line.sent[0]["type"] == "session.commentary.append"
    assert "am Bauch" in line.sent[0]["content"] and line.sent[0]["event_id"].startswith("touch_")
    assert touched == [1]
    # again at once: taken as a touch, but she is not told twice
    assert await bridge._live_touch(line, state, json.dumps({"type": "touch", "zone": "gesicht"})) is True
    assert len(line.sent) == 1 and touched == [1]
    state["touch_at"] -= m.LIVE_TOUCH_GAP_S + 1
    assert await bridge._live_touch(line, state, json.dumps({"type": "touch", "zone": "gesicht"})) is True
    assert len(line.sent) == 2 and "im Gesicht" in line.sent[1]["content"] and touched == [1, 1]


async def test_no_note_for_the_living_room_an_unknown_place_or_a_talk_that_ends(tmp_path, monkeypatch):
    m, bridge = _bridge(monkeypatch, tmp_path)
    line = Line()
    assert await bridge._live_touch(line, {"from_app": False}, json.dumps({"type": "touch", "zone": "po"})) is True
    assert await bridge._live_touch(line, {"from_app": True}, json.dumps({"type": "touch", "zone": "knie"})) is True
    assert await bridge._live_touch(line, {"from_app": True, "closing": True},
                                    json.dumps({"type": "touch", "zone": "po"})) is True
    assert line.sent == []
    # other messages are not touches: the old handling takes them
    assert await bridge._live_touch(line, {"from_app": True}, json.dumps({"type": "interrupt"})) is False
    assert await bridge._live_touch(line, {"from_app": True}, "kein json") is False
    assert line.sent == []


def test_the_app_tells_the_live_line_and_keeps_chat_comment_and_clip_sound_away():
    page = open(memory_web.__file__, encoding="utf-8").read()
    assert "const tr=onCall()?liveTouch(z):touchAsk(z);" in page
    assert "LIVE.ws.send(JSON.stringify({type:'touch',zone:z}))" in page
    assert "snd=snd&&!onCall()&&SND_RE.test(name)" in page
    assert "function onCall(){return document.getElementById('chat').classList.contains('oncall');}" in page
