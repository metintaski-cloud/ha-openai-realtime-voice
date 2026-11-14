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
