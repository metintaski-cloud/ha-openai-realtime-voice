"""Called again within a minute after a talk ended, Leyla goes on instead of greeting (2.180.0).

Metin, 26 Nov 2026, 15:55: "Wenn sie innerhalb 1 min nach dem Beenden nochmal aktiviert wird, soll sie nicht neu
beginnen mit Hallo, sondern da, wo das letzte Gespräch beendet wurde. Quasi: ah, war noch was?"
All sentences here are invented."""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OPENAI_API_KEY", "test")

import pytest  # noqa: E402

from app import main as m, phrases  # noqa: E402


@pytest.fixture(autouse=True)
def _always_hallo(monkeypatch):
    """In the morning and in the evening the greeting is drawn from a larger pool ("Guten Abend"); these tests ask
    for "Hallo" (they failed by chance on 26 Nov 2026 at 19:31 and had passed at 16:00)."""
    monkeypatch.setattr(m, "pick_greeting", lambda words, hour: words[0])


class _StartWs:
    def __init__(self):
        self.sent = []

    async def send(self, raw):
        self.sent.append(json.loads(raw))

    async def recv(self):
        return json.dumps({"type": "session.started", "session": {}})


def _bridge():
    bridge = m.LiveVoiceBridge()
    bridge.enable_context = False
    bridge.greeting_words = ["Hallo"]
    return bridge


TALK = [["bot", "Hallo, was kann ich für dich tun?"], ["user", "Wie wird das Wetter morgen?"],
        ["bot", "Morgen bleibt es trocken."], ["user", "Danke, tschüss."], ["bot", "Bis später."]]


async def _start(bridge, start=None):
    live = _StartWs()
    await bridge._start_session(live, start=start)
    first = live.sent[0]["session"]
    spoken = [x["content"] for x in live.sent if x["type"] == "session.commentary.append"]
    return first.get("input", []), spoken


def _texts(messages):
    return [(x["role"], x["content"][0]["text"]) for x in messages]


async def test_a_first_call_greets_as_before():
    bridge = _bridge()
    messages, spoken = await _start(bridge)
    assert bridge._resumed is None
    assert len(spoken) == 1 and "Hallo" in spoken[0] and spoken[0] == phrases.greeting_instruction("Hallo")
    assert _texts(messages) == [("developer", spoken[0])]


async def test_called_again_within_a_minute_she_goes_on_without_a_hello():
    bridge = _bridge()
    bridge._keep_for_resume({"dialog": TALK}, "goodbye")
    messages, spoken = await _start(bridge)
    assert spoken == [phrases.RESUME_OPEN]                                    # this is what makes her speak first
    assert "kein Hallo" in spoken[0] and "war noch was" in spoken[0] and "Grußwort" in spoken[0]
    texts = _texts(messages)
    assert texts[:5] == [("assistant" if sp == "bot" else "user", t) for sp, t in TALK]   # she still knows the talk
    assert texts[5] == ("developer", phrases.RESUME_OPEN) and len(texts) == 6
    assert messages[1]["content"][0]["type"] == "input_text" and messages[0]["content"][0]["type"] == "output_text"


async def test_after_a_minute_she_greets_again(monkeypatch):
    bridge = _bridge()
    bridge._keep_for_resume({"dialog": TALK}, "goodbye")
    bridge._last_talk["at"] = time.monotonic() - 59
    assert (await _start(bridge))[1] == [phrases.RESUME_OPEN]
    bridge._last_talk["at"] = time.monotonic() - 61
    messages, spoken = await _start(bridge)
    assert bridge._resumed is None and "Hallo" in spoken[0] and len(messages) == 1


async def test_a_private_talk_is_not_carried_over_until_the_code_word():
    """The code word is not taken along: somebody may have come into the room in that minute."""
    bridge = _bridge()
    bridge._keep_for_resume({"dialog": TALK, "unlocked": True}, "auto_stop")
    messages, spoken = await _start(bridge)
    assert spoken == [phrases.RESUME_PRIVATE] and "Codewort gilt für dieses Gespräch noch nicht" in spoken[0]
    assert _texts(messages) == [("developer", phrases.RESUME_PRIVATE)]         # not one turn of the private talk
    assert "Wetter" not in json.dumps(messages, ensure_ascii=False)
    # the talk that now runs: the turns wait apart and are hers again with the code word
    state = {"resume_private": list(bridge._resumed["dialog"]), "dialog": [["user", "Noch eine Frage."]]}
    bridge._unlock_effects(state, app=True)
    assert "resume_private" not in state and state["resume_dialog"][1][1] == "Wie wird das Wetter morgen?"
    history = bridge._history(list(state.get("resume_dialog") or []) + state["dialog"])
    assert history[-1]["content"][0]["text"] == "Noch eine Frage." and len(history) == 6


async def test_what_is_kept_and_what_is_not():
    bridge = _bridge()
    bridge._keep_for_resume({"dialog": TALK, "from_app": True}, "goodbye")       # the app has its own chat
    assert bridge._last_talk is None
    bridge._keep_for_resume({"dialog": [["bot", "Hallo?"]]}, "auto_stop")          # nobody spoke
    assert bridge._last_talk is None
    bridge._keep_for_resume({"dialog": TALK}, "goodbye")
    kept = bridge._last_talk
    bridge._keep_for_resume({"dialog": [["bot", "Ah, war noch was?"]]}, "no_speech")   # a false wake in between
    assert bridge._last_talk is kept and not kept["private"]
    # a talk that itself went on from one before keeps both, newest last, and never more than the limit
    bridge._keep_for_resume({"dialog": [["user", "Und übermorgen?"], ["bot", "Regen."]],
                             "resume_dialog": kept["dialog"]}, "goodbye")
    assert [t for _, t in bridge._last_talk["dialog"]][-3:] == ["Bis später.", "Und übermorgen?", "Regen."]
    bridge._keep_for_resume({"dialog": [["user", str(i)] for i in range(60)]}, "goodbye")
    assert len(bridge._last_talk["dialog"]) == m.RESUME_MAX_TURNS


async def test_the_app_and_her_own_calls_are_not_resumed():
    bridge = _bridge()
    bridge._keep_for_resume({"dialog": TALK}, "goodbye")
    # she starts a talk herself (a message for Metin): her own first sentence, not "war noch was"
    import asyncio
    bridge._followup = {"at": time.monotonic(), "prompt": "Sag ihm die Nachricht.", "taken": asyncio.Event()}
    messages, spoken = await _start(bridge)
    assert spoken == ["Sag ihm die Nachricht."] and bridge._resumed is None and len(messages) == 1


def test_nothing_of_the_talk_goes_into_the_log_or_a_file():
    import inspect
    src = inspect.getsource(m.LiveVoiceBridge._keep_for_resume)
    assert "logger" not in src and "open(" not in src and "json.dump" not in src
    assert m.RESUME_WITHIN_S == 60.0
