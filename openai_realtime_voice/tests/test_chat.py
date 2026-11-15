import json

from app import chat, memory


def test_only_applicable_proposals_pass():
    lists = {"family": ["Person: Metin | Arbeit: Elektriker"], "friends": [], "leyla": [], "private": []}
    raw = [{"action": "add", "kind": "family", "new": "Metin mag Pizza."},
           {"action": "edit", "kind": "family", "old": "Person: Metin | Arbeit: Elektriker",
            "new": "Person: Metin | Arbeit: Elektriker | Interessen: Pizza"},
           {"action": "delete", "kind": "family", "old": "gibt es nicht"},
           {"action": "add", "kind": "confidential", "new": "x"},
           {"action": "add", "kind": "family", "new": "Person: Metin | Arbeit: Elektriker"},
           {"action": "drop", "kind": "family", "new": "x"}]
    out = chat.valid_proposals(raw, lists)
    assert [p["action"] for p in out] == ["add", "edit"]


async def test_answer_uses_rules_memory_and_no_confidential(tmp_path, monkeypatch):
    store = memory.MemoryStore(str(tmp_path / "m.json"))
    store.save_all({"family": ["Person: Metin"], "private": ["Geheim A"],
                    "confidential": ["Aktuell bis 30.11.2099: Gülfikar Knie"]})
    sent = {}

    class Resp:
        status_code = 200

        def json(self):
            return {"output_text": json.dumps({"reply": "Klar, merk ich mir gern!", "proposals": [
                {"action": "add", "kind": "family", "new": "Metin mag Lahmacun."}]})}

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            sent.update(json)
            return Resp()

    monkeypatch.setattr(chat.httpx, "AsyncClient", Client)
    out = await chat.answer("k", ["m"], "REGELN", store,
                            [{"role": "user", "text": "Hallo"}, {"role": "leyla", "text": "Hi!"}],
                            "Ich mag Lahmacun")
    assert out["reply"].startswith("Klar") and out["proposals"][0]["new"] == "Metin mag Lahmacun."
    assert sent["instructions"].startswith("REGELN") and "Geheim A" in sent["instructions"]
    assert "Knie" not in sent["instructions"]
    assert [m["role"] for m in sent["input"]] == ["user", "assistant", "user"]
    assert await chat.answer("k", ["m"], "R", store, [], "   ") is None


async def test_chat_style_asks_and_proposes_by_itself(tmp_path, monkeypatch):
    store = memory.MemoryStore(str(tmp_path / "m.json"))
    store.save_all({"family": ["Person: Umut | Zugehörigkeit: Bruder | Arbeit: Lehrer"]})
    sent = {}

    class Resp:
        status_code = 200

        def json(self):
            return {"output_text": '{"reply": "Hi!", "proposals": []}'}

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            sent.update(json)
            return Resp()

    monkeypatch.setattr(chat.httpx, "AsyncClient", Client)
    await chat.answer("k", ["m"], "R", store, [], "Hallo")
    ins = sent["instructions"]
    assert "stellst du meist eine Frage" in ins and "von dir aus" in ins
    assert "• Umut: Geburtstag, Kinder, Interessen, Charakter" in ins


def test_move_to_private_is_a_valid_proposal_and_style_says_so():
    lists = {"family": [], "friends": [], "leyla": ["Wir sind Seelenverwandte."], "private": []}
    out = chat.valid_proposals([{"action": "move", "kind": "leyla", "to": "private",
                                 "old": "Wir sind Seelenverwandte."},
                                {"action": "move", "kind": "leyla", "to": "leyla",
                                 "old": "Wir sind Seelenverwandte."},
                                {"action": "move", "kind": "leyla", "to": "private", "old": "fehlt"}], lists)
    assert out == [{"action": "move", "kind": "leyla", "old": "Wir sind Seelenverwandte.", "new": "",
                    "to": "private"}]
    assert "gehört immer in die Liste private" in chat.CHAT_STYLE
    assert "gehören nie hierher" in memory.SUMMARY_PROMPT


def test_same_proposal_shows_once():
    lists = {"family": [], "friends": [], "leyla": [], "private": []}
    raw = [{"action": "add", "kind": "private", "new": "Metin mag Tee."},
           {"action": "add", "kind": "private", "new": "Metin mag Tee."},
           {"action": "add", "kind": "leyla", "new": "Metin mag Tee."}]
    assert len(chat.valid_proposals(raw, lists)) == 1


def test_chat_has_the_unofficial_couple_with_healthy_limits():
    assert "inoffiziell zusammen" in chat.CHAT_STYLE and "außerhalb des Chats" in chat.CHAT_STYLE
    assert "nie eifersüchtig" in chat.CHAT_STYLE and "Familie und Freunden" in chat.CHAT_STYLE
