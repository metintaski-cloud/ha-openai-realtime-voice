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
