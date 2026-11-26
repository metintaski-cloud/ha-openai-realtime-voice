"""Too many voices, a wrong name, and people who make fun of her (2.181.0).

Metin, 26 Nov 2026, 16:29 to 16:35: with too many talking she shall not guess but ask them to speak one by one
with their name; she had taken a quiet voice for another name of the family "und ist drauf geritten, obwohl wir
es mehrfach gesagt haben"; teased ("Alexa ist besser") she shall counter and not hold back; who makes fun of her
gets a clever counter and she hangs up, remembers who it was and is a little cool until that person apologises.
All names and sentences here are invented."""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OPENAI_API_KEY", "test")

from app import main as m, persona, phrases, spott  # noqa: E402
from app.live_link import END_CONVERSATION_TOOL  # noqa: E402


def _bridge():
    bridge = m.LiveVoiceBridge()
    bridge.sent = []

    async def note(live_ws, prefix, content, parts=None, state=None):
        bridge.sent.append((prefix, content))
    bridge._send_note = note
    return bridge


def test_her_rules_for_a_talk_at_home():
    home = persona.build(["Lampen"], messages=True)
    assert "nicht alle auf einmal" in home and "rätst du nicht und führst nichts auf Verdacht aus" in home
    assert "einzeln zu sprechen und kurz den Namen dazuzusagen" in home
    assert "nimmst du sofort den neuen Namen und bleibst nie bei deinem" in home
    assert "noch einmal laut und deutlich" in home
    assert "nie zurückhaltend" in home and "Alexa ist besser" in home and "konterst du sofort" in home
    assert "gilt immer der Person, die es gesagt hat, nie Alexa" in home      # Metin, 16:39: at the person, not at Alexa
    assert "behauptet im Grunde, du seist dumm. Das bist du nicht" in home and "dass die Person es selbst merkt" in home
    assert "zeigst du Gefühl" in home and "kühler und ernster" in home        # Metin, 16:41: it shows that it was not nice
    assert "Direkt danach legst du" in home and "wegen Spott auflegst" in home
    assert "bis die Person sich" in home and "Einen Namen rätst du nie" in home
    assert "Werd dabei nie selbst beleidigend" in home                       # a counter is wit, never an insult
    chat = persona.build([])                                                 # the written chat hangs up on nobody
    assert "legst du" not in chat and "Alexa" not in chat


def test_the_hang_up_tool_can_say_why_and_who():
    params = END_CONVERSATION_TOOL["parameters"]
    assert "mocked" in params["properties"]["reason"]["enum"]
    assert sorted(params["required"]) == sorted(params["properties"]) == ["reason", "who"]
    assert params["properties"]["who"]["type"] == ["string", "null"] and params["additionalProperties"] is False


def test_the_list_keeps_a_name_and_a_time_and_nothing_else(tmp_path):
    g = spott.Grudges(str(tmp_path / "s.json"))
    assert g.add("Selin", now=1_800_000_000) and g.has("selin") and g.has("Selin Kaya")
    assert not g.add("Metin") and not g.add("") and not g.has("Metin")       # his way is her heart
    assert g.add("Ayşe") and g.has("ayse") and g.has("AYŞE")                  # one person under every spelling
    raw = open(tmp_path / "s.json", encoding="utf-8").read()
    assert set(json.loads(raw)["open"]["selin"]) == {"name", "t", "n"}
    note = g.note("Selin", now=1_800_000_000 + 86400)
    assert "Selin hat sich gestern über dich lustig gemacht" in note and "ein wenig kühl" in note
    assert "erledigst du trotzdem" in note and "Gefahr" in note and "Entschuldigt Selin sich ehrlich" in note
    assert g.note("Deniz") == ""
    assert g.stats()["offen"] == 2 and "Selin" not in json.dumps(g.stats())   # counts only for a look from outside
    again = spott.Grudges(str(tmp_path / "s.json"))                          # it survives a restart
    assert again.has("Selin") and again.forgive("Selin") and not again.has("Selin") and not again.forgive("Selin")


async def _end(bridge, state, args):
    async def out(live_ws, call_id, result):
        state["answered"] = result
    bridge._send_function_output = out
    await bridge._handle_backend_event(
        {"type": "response.output_item.done",
         "item": {"type": "function_call", "name": "end_conversation", "call_id": "c1",
                  "arguments": json.dumps(args)}}, None, asyncio.Queue(), state)


async def test_she_hangs_up_after_mockery_and_keeps_the_name_only_when_it_was_given():
    bridge = _bridge()
    state = {"dialog": [["user", "Ich bin Selin."], ["bot", "Hallo Selin."], ["user", "Du bist ja dumm."]]}
    await _end(bridge, state, {"reason": "mocked", "who": "Selin"})
    assert state["closing"] and state["mocked"] and state["mocked_who"] == "Selin" and bridge.grudges.has("Selin")
    other = {"dialog": [["user", "Du bist ja dumm."]]}                        # no name was given: nothing is kept
    await _end(bridge, other, {"reason": "mocked", "who": "Deniz"})
    assert other["closing"] and other["mocked"] and not bridge.grudges.has("Deniz")
    him = {"dialog": [["user", "Ich bin Metin."]]}
    await _end(bridge, him, {"reason": "mocked", "who": "Metin"})
    assert him["closing"] and not bridge.grudges.has("Metin")
    plain = {"dialog": [["user", "Ich bin Deniz. Tschüss."]]}                  # a normal goodbye keeps nothing
    await _end(bridge, plain, {"reason": "user_requested_stop", "who": None})
    assert plain["closing"] and not plain.get("mocked") and not bridge.grudges.has("Deniz")


async def test_next_time_that_person_says_who_they_are_she_is_told_once():
    bridge = _bridge()
    bridge.grudges.add("Selin")
    state = {"dialog": [["bot", "Hallo."], ["user", "Ich bin Deniz."]]}
    await bridge._maybe_grudge_note(None, state)
    assert bridge.sent == []
    state["dialog"] += [["bot", "Hallo Deniz."], ["user", "Und ich bin Selin."]]
    await bridge._maybe_grudge_note(None, state)
    await bridge._maybe_grudge_note(None, state)
    assert [p for p, _ in bridge.sent] == ["spott"] and "ein wenig kühl" in bridge.sent[0][1]


async def test_an_apology_is_checked_after_the_talk_and_forgiven(monkeypatch):
    bridge = _bridge()
    bridge.grudges.add("Selin")
    asked = []

    async def apologised(key, models, dialog, name, url=None):
        asked.append(name)
        return True
    monkeypatch.setattr(spott, "apologised", apologised)
    bridge._schedule_grudges({"dialog": [["user", "Ich bin Selin. Wie wird das Wetter?"], ["bot", "Trocken."]]})
    await asyncio.sleep(0.05)
    assert asked == [] and bridge.grudges.has("Selin")                        # no word of an apology: no question
    bridge._schedule_grudges({"dialog": [["user", "Ich bin Selin. Es tut mir leid wegen neulich."], ["bot", "Schon gut."]]})
    await asyncio.sleep(0.05)
    assert asked == ["Selin"] and not bridge.grudges.has("Selin")


async def test_a_hang_up_without_a_reason_is_looked_at_once_more(monkeypatch):
    bridge = _bridge()
    asked = []

    async def who_mocked(key, models, dialog, names, url=None):
        asked.append(sorted(names))
        return "Selin"
    monkeypatch.setattr(spott, "who_mocked", who_mocked)
    talk = [["user", "Ich bin Selin. Du kannst ja gar nichts."], ["bot", "Mehr als du denkst."]]
    bridge._schedule_grudges({"dialog": talk})                                # she did not hang up
    bridge._schedule_grudges({"dialog": talk + [["user", "Tschüss."]], "ended_by_her": True})   # a goodbye
    bridge._schedule_grudges({"dialog": talk, "ended_by_her": True, "mocked": True})            # already known why
    await asyncio.sleep(0.05)
    assert asked == []
    bridge._schedule_grudges({"dialog": talk, "ended_by_her": True})
    await asyncio.sleep(0.05)
    assert asked == [["Selin"]] and bridge.grudges.has("Selin")


def test_a_name_the_people_give():
    assert phrases.name_given("Nein, Selin. Das ist doch Selin!") == "Selin"
    assert phrases.name_given("Sie heißt Selin.") == "Selin" and phrases.name_given("Ben Selin.") == "Selin"
    assert phrases.name_given("Das ist Selin. Selin!") == "Selin"
    assert phrases.name_given("Nein, Selin.") == "" and phrases.name_given("Das ist Selin.") == ""   # once: not enough
    assert phrases.name_given("Das ist Quatsch.") == "" and phrases.name_given("Sie ist Lehrerin.") == ""
    assert phrases.name_given("Nein, Danke. Nein, Danke.") == "" and phrases.name_given("Nein, Licht aus. Licht!") == ""
    assert phrases.name_given("Das ist Deniz.", not_these={"deniz"}) == ""


class _Memory:
    def profile_words(self):
        return {"Deniz Kaya": {"deniz", "kaya", "teyze"}}

    def personal_for(self, name):
        return "x"


async def _identify(bridge, state):
    handed = []

    async def hand(live_ws, st, name):
        st.setdefault("identified", set()).add(name)
        handed.append(name)
    bridge.memory = _Memory()
    bridge._hand_over_personal = hand
    await bridge._maybe_identify(None, state)
    return handed


async def test_a_misheard_name_is_taken_back_when_the_people_correct_it():
    """The case of 26 Nov 2026: a quiet voice, heard as another name of the family."""
    bridge = _bridge()
    state = {"dialog": [["bot", "Wer spricht gerade?"], ["user", "Deniz."]]}
    assert await _identify(bridge, state) == ["Deniz Kaya"] and state["weak_id"] == {"Deniz Kaya"}
    state["dialog"] += [["bot", "Hallo Deniz!"], ["user", "Nein, Selin. Das ist Selin."]]
    assert await _identify(bridge, state) == []
    assert state["identified"] == set() and state["not_them"] == {"Deniz Kaya"} and state["named"] == ["Selin"]
    kinds = [p for p, _ in bridge.sent]
    assert kinds == ["name"] and "nicht Deniz" in bridge.sent[0][1] and "Die Person heißt Selin." in bridge.sent[0][1]
    state["dialog"] += [["bot", "Entschuldige, Selin."], ["user", "Deniz ist in der Küche."]]
    assert await _identify(bridge, state) == [] and len(bridge.sent) == 1     # taken back for this talk, told once
    assert bridge._talk_names(state) == {"selin": "Selin"}                   # and Selin is who talks now


async def test_a_denied_name_is_taken_back_and_a_clear_one_stays():
    bridge = _bridge()
    state = {"dialog": [["bot", "Wer spricht gerade?"], ["user", "Deniz."]]}
    await _identify(bridge, state)
    state["dialog"] += [["bot", "Hallo Deniz!"], ["user", "Ich bin nicht Deniz."]]
    await _identify(bridge, state)
    assert state["identified"] == set() and "nicht Deniz" in bridge.sent[0][1] and "heißt" not in bridge.sent[0][1]
    # someone who said the name in a whole sentence stays, also when another person is named later
    clear = {"dialog": [["user", "Ich bin Deniz."]]}
    assert await _identify(bridge, clear) == ["Deniz Kaya"] and not clear.get("weak_id")
    clear["dialog"] += [["bot", "Hallo Deniz!"], ["user", "Und das ist Selin."]]
    await _identify(bridge, clear)
    assert clear["identified"] == {"Deniz Kaya"} and len(bridge.sent) == 1
