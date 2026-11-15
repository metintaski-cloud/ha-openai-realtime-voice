import json

import pytest

from app import chat, mail, memory


def mailer(tmp_path):
    return mail.Mailer("metin@gmail.com", "abcd efgh ijkl mnop", "Ayşe: ayse@example.de; Umut Taskiran: umut@example.de",
                       path=str(tmp_path / "drafts.json"))


def test_contacts_and_names(tmp_path):
    m = mailer(tmp_path)
    assert m.available and m.password == "abcdefghijklmnop"
    assert m.resolve("ayse") == "Ayşe" and m.resolve("Umut") == "Umut Taskiran"
    assert m.resolve("jemand@fremd.de") is None and m.resolve("") is None
    assert mail.parse_contacts("kaputt; X: keine adresse; Y: y@z.de") == {"Y": "y@z.de"}


async def test_draft_waits_and_only_send_sends(tmp_path, monkeypatch):
    m = mailer(tmp_path)
    sent = []
    monkeypatch.setattr(m, "_smtp_send", lambda d: sent.append(d["addr"]))
    assert "kontakte" in m.draft("Fremder", "x", "y")
    r = m.draft("Ayşe", "Hallo", "Liebe Grüße, Metin")
    assert r["ok"] and not sent and len(m.pending()) == 1
    assert (await m.send(r["id"]))["ok"] and sent == ["ayse@example.de"] and m.pending() == []
    assert not (await m.send(r["id"]))["ok"]  # gone after sending
    r2 = m.draft("Umut", "Hi", "Text")
    assert m.discard(r2["id"]) and m.pending() == []


async def test_voice_tool_and_chat_make_only_drafts(tmp_path, monkeypatch):
    m = mailer(tmp_path)
    assert (await m.run({"an": "ayse", "betreff": "B", "text": "T"}))["ok"]
    store = memory.MemoryStore(str(tmp_path / "mem.json"))
    seen = []

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            seen.append(json["instructions"])

            class R:
                status_code = 200

                def json(self):
                    return {"output_text": '{"reply": "Liegt bereit", "proposals": [], '
                            '"email": {"to": "Umut", "subject": "Essen", "body": "Kommst du? Metin"}}'}
            return R()

    monkeypatch.setattr(chat.httpx, "AsyncClient", Client)
    out = await chat.answer("k", ["m"], "R", store, [], "Schreib Umut eine Mail", mailer=m)
    assert out["email"]["to"] == "Umut Taskiran" and out["email"]["addr"] == "umut@example.de"
    assert "E-MAIL" in seen[-1] and "Umut Taskiran" in seen[-1]
    assert len(m.pending()) == 2
