import asyncio

from app import gcontacts, mail


class Resp:
    def __init__(self, code, body):
        self.status_code, self._b = code, body

    def json(self):
        return self._b


def fake(calls, people):
    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, data=None):
            calls.append(("post", data.get("grant_type")))
            if data.get("grant_type") == "authorization_code" and data.get("code") != "abc":
                return Resp(400, {})
            return Resp(200, {"refresh_token": "r1", "access_token": "a1", "expires_in": 3600})

        async def get(self, url, params=None, headers=None):
            calls.append(("get", headers["Authorization"]))
            return Resp(200, {"connections": people})
    return Client


PEOPLE = [{"names": [{"displayName": "Ayşe Taskiran"}], "emailAddresses": [{"value": "ayse@x.de"}]},
          {"names": [{"displayName": "Firma Bau"}], "emailAddresses": [{"value": "info@bau.de"}]},
          {"names": [{"displayName": "Ohne Mail"}]}]


def test_code_from_the_pasted_address():
    assert gcontacts.code_from("http://127.0.0.1/?code=4/0Ab-cd&scope=x") == "4/0Ab-cd"
    assert gcontacts.code_from("4/0Abcd") == "4/0Abcd"
    assert gcontacts.code_from("kein code hier") == ""


def test_connect_read_and_only_ticked_contacts_reach_leyla(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(gcontacts.httpx, "AsyncClient", fake(calls, PEOPLE))
    g = gcontacts.GoogleContacts("id", "secret", str(tmp_path))
    assert g.configured and not g.connected
    assert "contacts.readonly" in g.auth_url() and "127.0.0.1" in g.auth_url()
    assert not asyncio.run(g.connect("http://127.0.0.1/?code=falsch"))["ok"]
    assert asyncio.run(g.connect("http://127.0.0.1/?code=abc"))["ok"] and g.connected
    found = asyncio.run(g.contacts())
    assert [c["addr"] for c in found] == ["ayse@x.de", "info@bau.de"]
    assert g.allowed_contacts() == {}
    g.set_allowed("AYSE@x.de", True)
    assert g.allowed_contacts() == {"Ayşe Taskiran": "ayse@x.de"}
    m = mail.Mailer("me@gmail.com", "pw", "", path=str(tmp_path / "d.json"), google=g)
    assert m.available and m.draft("Ayşe", "Hallo", "Hi")["ok"]
    assert "error" in m.draft("Firma Bau", "Hallo", "Hi")  # not ticked
    g.set_allowed("ayse@x.de", False)
    assert "error" in m.draft("Ayşe", "Hallo", "Hi")


def test_web_address_draft_is_marked(tmp_path):
    m = mail.Mailer("me@gmail.com", "pw", "Umut: u@y.de", path=str(tmp_path / "d.json"))
    r = m.draft("Stadtwerke", "Frage", "Hallo", web_addr="kundenservice@stadtwerke.de")
    assert r["ok"]
    d = m.pending()[-1]
    assert d["web"] and d["addr"] == "kundenservice@stadtwerke.de"
    assert not m.pending()[0]["web"] if len(m.pending()) > 1 else True
    assert "error" in m.draft("Stadtwerke", "Frage", "Hallo", web_addr="kein adresse")
    assert m.pending()[-1]["web"] is True
    assert m.draft("Umut", "x", "y")["ok"] and m.pending()[-1]["web"] is False
