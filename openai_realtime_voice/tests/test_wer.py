"""The ears of the bridge: the text model reads who talks (2.183.0, app/wer.py).

Metin, 27 Nov 2026: "Ich glaube, jetzt, wo die Brücke da ist und an Bedeutung gewonnen hat, sollte sie so oder so
bessere Ohren haben." All names and sentences here are invented."""
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OPENAI_API_KEY", "test")

from app import main as m, phrases, wer  # noqa: E402

FAMILY = {"family": ["Person: Selin | Zugehörigkeit: wohnt hier", "Person: Selin Beispiel | Zugehörigkeit: Gast",
                     "Person: Deniz | Zugehörigkeit: Gast"]}


def _bridge(tmp_path, monkeypatch, answers):
    monkeypatch.setenv("MEMORY_PATH", str(tmp_path / "memory.json"))
    bridge = m.LiveVoiceBridge()
    bridge.memory.save_all(FAMILY)
    handed, sent, prompts = [], [], []

    async def hand(ws, state, name):
        handed.append(name)
        state.setdefault("identified", set()).add(name)

    async def note(ws, prefix, content):
        sent.append(content)

    async def ask(prompt):
        prompts.append(prompt)
        await asyncio.sleep(0.01)
        return answers.pop(0) if answers else None
    bridge._hand_over_personal, bridge._send_note, bridge._who_ask = hand, note, ask
    return bridge, handed, sent, prompts


async def _settle(bridge):
    while bridge._background:
        await asyncio.gather(*list(bridge._background))


async def test_the_question_and_the_answer():
    asked = []

    async def ask(prompt):
        asked.append(prompt)
        return " selin.\n"
    dialog = [["bot", "Hallo!"], ["user", "Selin am Apparat, wie wird das Wetter"]]
    assert await wer.who(ask, dialog, ["Selin", "Selin Beispiel", "Deniz"]) == "selin"
    assert "Diese Personen kennt Leyla: Selin, Deniz" in asked[0]          # one first name once
    assert "Nutzer: Selin am Apparat, wie wird das Wetter" in asked[0] and "sonst mit NIEMAND" in asked[0]

    async def other(prompt):
        return "NIEMAND"
    assert await wer.who(other, dialog, ["Selin"]) is None

    async def chatty(prompt):
        return "Das ist vermutlich Selin"
    assert await wer.who(chatty, dialog, ["Selin"]) is None               # only a clean name counts

    async def dead(prompt):
        return None
    assert await wer.who(dead, dialog, ["Selin"]) is None
    assert await wer.who(ask, [["bot", "Hallo!"]], ["Selin"]) is None and len(asked) == 1   # nobody spoke: not asked
    assert await wer.who(ask, dialog, []) is None and len(asked) == 1                         # nobody known: not asked


async def test_when_his_turn_is_over_the_model_reads_who_it_is(tmp_path, monkeypatch, caplog):
    """The talk of 26 Nov 2026, 23:42: his first words held his name in a way no list knew. Now the model is asked
    when his turn is over, and while it reads, the bridge does not tell her to ask who is there."""
    bridge, handed, sent, prompts = _bridge(tmp_path, monkeypatch, ["Selin"])
    state = {"dialog": [["bot", "Hallo!"], ["user", "Selin am Apparat, wie wird das Wetter"]]}
    with caplog.at_level(logging.INFO):
        bridge._on_bot_text(state, "Sonnig", live_ws=object())
        await asyncio.sleep(0)
        assert state["who_checking"] is True
        state["dialog"].append(["bot", " und warm."])
        await bridge._maybe_ask_who(None, state)                           # his next turn would begin now
        assert sent == []                                                  # no reminder while the model reads
        await _settle(bridge)
    assert sorted(handed) == ["Selin", "Selin Beispiel"] and state["weak_id"] == {"Selin", "Selin Beispiel"}
    assert state["who_checking"] is False and len(prompts) == 1
    assert "Who check 1: the person gave a known name after" in caplog.text
    assert "Apparat" not in caplog.text and "Wetter" not in caplog.text    # no word of the talk in the log
    bridge._on_bot_text(state, " Noch etwas?", live_ws=object())           # known now: not asked again
    await _settle(bridge)
    assert len(prompts) == 1


async def test_no_name_given_she_is_reminded_as_before_and_the_model_is_asked_again_next_turn(tmp_path, monkeypatch):
    bridge, handed, sent, prompts = _bridge(tmp_path, monkeypatch, ["NIEMAND", "NIEMAND", "Deniz"])
    state = {"dialog": [["bot", "Hallo!"], ["user", "wie wird das Wetter"]]}
    bridge._on_bot_text(state, "Sonnig.", live_ws=object())
    await _settle(bridge)
    assert handed == [] and state["who_checks"] == 1
    await bridge._maybe_ask_who(None, state)
    assert sent == [phrases.WHO_NUDGE]                                     # nobody said a name: she asks
    # a turn ends while the model still reads: it is asked once more on the newer talk, not twice at once
    state["dialog"].append(["user", "und morgen"])
    bridge._on_bot_text(state, "Regen.", live_ws=object())
    await asyncio.sleep(0)
    state["dialog"].append(["user", "ach so, hier ist übrigens der Besuch, Deniz"])
    bridge._on_bot_text(state, "Schön!", live_ws=object())
    await _settle(bridge)
    assert handed == ["Deniz"] and state["who_checks"] == 3 and len(prompts) == 3
    assert "Besuch, Deniz" in prompts[2] and "Besuch, Deniz" not in prompts[1]


async def test_not_in_the_app_not_after_the_code_word_and_not_without_end(tmp_path, monkeypatch):
    bridge, handed, sent, prompts = _bridge(tmp_path, monkeypatch, [])
    talk = [["bot", "Hallo!"], ["user", "wie wird das Wetter"]]
    for state in ({"dialog": [list(x) for x in talk], "from_app": True},
                  {"dialog": [list(x) for x in talk], "unlocked": True},
                  {"dialog": [list(x) for x in talk], "identified": {"Deniz"}},
                  {"dialog": [list(x) for x in talk], "closing": True},
                  {"dialog": [list(x) for x in talk], "who_checks": wer.MAX_CHECKS}):
        bridge._on_bot_text(state, "Sonnig.", live_ws=object())
        await _settle(bridge)
    assert prompts == [] and handed == []
    # a taken back name is not handed over again, and a model that fails changes nothing
    state = {"dialog": [list(x) for x in talk], "not_them": {"Deniz"}}
    bridge._who_ask = None

    async def says_deniz(prompt):
        return "Deniz"
    bridge._who_ask = says_deniz
    bridge._on_bot_text(state, "Sonnig.", live_ws=object())
    await _settle(bridge)
    assert handed == []

    async def broken(prompt):
        raise RuntimeError("down")
    bridge._who_ask = broken
    state = {"dialog": [list(x) for x in talk]}
    bridge._on_bot_text(state, "Sonnig.", live_ws=object())
    await _settle(bridge)
    assert handed == [] and state["who_checking"] is False
