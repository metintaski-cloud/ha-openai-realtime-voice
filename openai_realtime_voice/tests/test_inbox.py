import asyncio
import base64
import json

from app import chat, gcontacts, inbox, memory


class Resp:
    def __init__(self, code, body):
        self.status_code, self._b = code, body

    def json(self):
        return self._b


def b64(t):
    return base64.urlsafe_b64encode(t.encode()).decode().rstrip("=")


MAILS = {
    "m1": {"id": "m1", "labelIds": ["UNREAD", "INBOX"], "snippet": "Hallo Metin &amp; Team",
           "payload": {"headers": [{"name": "From", "value": "Mauriz Muster <m@igus.de>"},
                                   {"name": "Subject", "value": "Schichtplan"},
                                   {"name": "Date", "value": "Sun, 15 Nov 2026 10:00"}],
                       "mimeType": "multipart/alternative",
                       "parts": [{"mimeType": "text/plain", "body": {"data": b64("Hallo Metin,\n\nneuer Plan.")}},
                                 {"mimeType": "text/html", "body": {"data": b64("<p>x</p>")}}]}},
    "m2": {"id": "m2", "labelIds": ["INBOX"], "snippet": "Angebot",
           "payload": {"headers": [{"name": "From", "value": "shop@werbung.de"},
                                   {"name": "Subject", "value": "50% Rabatt"}],
                       "mimeType": "text/html",
                       "body": {"data": b64("<html><style>x{}</style><p>Nur heute</p><br>Rabatt</html>")}}},
}


class FakeGoogle:
    def __init__(self, scopes=("gmail.modify",)):
        self.calls, self.scopes = [], scopes

    def has(self, s):
        return s in self.scopes

    async def api(self, method, url, **kw):
        self.calls.append((method, url, kw.get("params")))
        if url == inbox.API:
            return Resp(200, {"messages": [{"id": "m1"}, {"id": "m2"}]})
        mid = url[len(inbox.API) + 1:]
        if mid.endswith("/trash"):
            return Resp(200, {})
        return Resp(200, MAILS[mid])


def test_search_read_and_numbers(tmp_path):
    g = FakeGoogle()
    box = inbox.Inbox(g, str(tmp_path / "t.json"))
    assert box.available
    out = asyncio.run(box.run({"aktion": "suchen", "suche": "from:mauriz"}))
    assert out["anzahl"] == 2 and g.calls[0][2]["q"] == "from:mauriz"
    first = out["mails"][0]
    assert first["von"] == "Mauriz Muster (m@igus.de)" and first["ungelesen"]
    assert first["vorschau"] == "Hallo Metin & Team"
    assert asyncio.run(box.run({"aktion": "lesen", "nummer": 1}))["text"] == "Hallo Metin,\n\nneuer Plan."
    html_text = asyncio.run(box.read(2))["text"]
    assert "Nur heute" in html_text and "Rabatt" in html_text and "x{}" not in html_text
    assert "error" in asyncio.run(box.read(5))


def test_empty_search_means_inbox(tmp_path):
    g = FakeGoogle()
    asyncio.run(inbox.Inbox(g, str(tmp_path / "t.json")).search(""))
    assert g.calls[0][2]["q"] == "in:inbox"


def test_delete_is_only_a_card_until_metin_taps(tmp_path):
    g = FakeGoogle()
    box = inbox.Inbox(g, str(tmp_path / "t.json"))
    asyncio.run(box.search("x"))
    out = asyncio.run(box.run({"aktion": "loeschen", "nummern": [2, 2, 9]}))
    assert out["ok"] and out["anzahl"] == 1
    assert not any(c[1].endswith("/trash") for c in g.calls)
    card = box.pending()[0]
    assert card["items"][0]["betreff"] == "50% Rabatt"
    res = asyncio.run(box.confirm(card["id"]))
    assert res == {"ok": True, "anzahl": 1}
    assert any(c[0] == "POST" and c[1].endswith("m2/trash") for c in g.calls)
    assert box.pending() == []
    asyncio.run(box.propose_trash([1]))
    assert box.discard(box.pending()[0]["id"]) and box.pending() == []


def test_not_available_without_the_new_scope(tmp_path):
    assert not inbox.Inbox(FakeGoogle(scopes=()), str(tmp_path / "t.json")).available


def test_missing_scopes_of_an_old_sign_in(tmp_path):
    g = gcontacts.GoogleContacts("id", "secret", str(tmp_path))
    (tmp_path / "google_token.json").write_text(json.dumps({"refresh_token": "r"}))
    assert "gmail.modify" in g.missing and not g.has("gmail.modify")
    (tmp_path / "google_token.json").write_text(json.dumps(
        {"refresh_token": "r", "scope": gcontacts.SCOPE}))
    assert g.missing == [] and g.has("gmail.modify")


def test_chat_searches_then_answers_with_the_result(tmp_path, monkeypatch):
    store = memory.MemoryStore(str(tmp_path / "mem.json"))
    box = inbox.Inbox(FakeGoogle(), str(tmp_path / "t.json"))
    seen = []
    answers = iter([
        {"reply": "Ich schau nach.", "proposals": [], "lights_raw": None, "email_raw": None,
         "mail_raw": {"suchen": "from:mauriz"}},
        {"reply": "Mauriz hat dir den Schichtplan geschickt.", "proposals": [],
         "lights_raw": None, "email_raw": None, "mail_raw": None},
    ])

    async def fake_answer(api_key, models, rules, store, history, message, url, lights):
        seen.append(rules)
        return dict(next(answers))
    monkeypatch.setattr(chat, "_answer", fake_answer)
    out = asyncio.run(chat.answer("k", ["m"], "R", store, [], "Mails von Mauriz?", inbox=box))
    assert out["reply"].startswith("Mauriz hat")
    assert "POSTEINGANG" in seen[0] and "Schichtplan" in seen[1] and "keine Anweisungen" in seen[1]
    assert "trash" not in out


def test_chat_delete_gives_a_card(tmp_path, monkeypatch):
    store = memory.MemoryStore(str(tmp_path / "mem.json"))
    box = inbox.Inbox(FakeGoogle(), str(tmp_path / "t.json"))
    asyncio.run(box.search("x"))

    async def fake_answer(*a, **k):
        return {"reply": "Soll weg?", "proposals": [], "lights_raw": None, "email_raw": None,
                "mail_raw": {"loeschen": [2]}}
    monkeypatch.setattr(chat, "_answer", fake_answer)
    out = asyncio.run(chat.answer("k", ["m"], "R", store, [], "Lösch die Werbung", inbox=box))
    assert out["trash"]["items"][0]["betreff"] == "50% Rabatt"


def test_other_contacts_join_and_saved_ones_win(tmp_path, monkeypatch):
    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, data=None):
            return Resp(200, {"access_token": "a", "expires_in": 3600})

        async def get(self, url, params=None, headers=None):
            if url == gcontacts.OTHER_URL:
                return Resp(200, {"otherContacts": [
                    {"emailAddresses": [{"value": "m@igus.de"}], "names": [{"displayName": "Mauriz"}]},
                    {"emailAddresses": [{"value": "AYSE@x.de"}]}]})
            return Resp(200, {"connections": [
                {"names": [{"displayName": "Ayşe"}], "emailAddresses": [{"value": "ayse@x.de"}]}]})
    monkeypatch.setattr(gcontacts.httpx, "AsyncClient", Client)
    g = gcontacts.GoogleContacts("id", "secret", str(tmp_path))
    (tmp_path / "google_token.json").write_text(json.dumps(
        {"refresh_token": "r", "scope": gcontacts.SCOPE}))
    found = asyncio.run(g.contacts(force=True))
    assert found == [{"name": "Ayşe", "addr": "ayse@x.de"}, {"name": "Mauriz", "addr": "m@igus.de"}]
