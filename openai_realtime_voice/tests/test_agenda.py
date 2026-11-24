import asyncio
from datetime import date, time

import pytest

from app import agenda, chat, memory

TODAY = date(2026, 11, 15)  # a Sunday


class Resp:
    def __init__(self, code, body=None):
        self.status_code, self._b = code, body or {}

    def json(self):
        return self._b


def ev(eid, title, start, end, **kw):
    out = {"id": eid, "summary": title, "start": start, "end": end}
    out.update(kw)
    return out


TIMED = ev("e1", "Zahnarzt", {"dateTime": "2026-11-16T14:00:00+01:00"},
           {"dateTime": "2026-11-16T15:30:00+01:00"}, location="Praxis")
ALLDAY = ev("e2", "Urlaub", {"date": "2026-11-17"}, {"date": "2026-11-19"})


class FakeGoogle:
    def __init__(self, scopes=("calendar.events",), fail=None):
        self.calls, self.scopes, self.fail = [], scopes, fail

    def has(self, s):
        return s in self.scopes

    async def api(self, method, url, **kw):
        self.calls.append((method, url, kw.get("params"), kw.get("json")))
        if self.fail:
            return Resp(self.fail)
        if method == "GET":
            return Resp(200, {"items": [TIMED, ALLDAY, {"id": "x", "status": "cancelled"}]})
        if method == "POST":
            return Resp(200, dict(kw["json"], id="new1"))
        if method == "PATCH":
            base = TIMED if url.endswith("e1") else ALLDAY
            merged = dict(base)
            for k, v in kw["json"].items():
                merged[k] = {a: b for a, b in v.items() if b is not None} if isinstance(v, dict) else v
            return Resp(200, merged)
        return Resp(204)


@pytest.fixture(autouse=True)
def berlin(monkeypatch):
    monkeypatch.setenv("TZ", "Europe/Berlin")
    monkeypatch.setattr(agenda.Agenda, "_today", lambda self: TODAY)


def make(tmp_path, **kw):
    g = FakeGoogle(**kw)
    return g, agenda.Agenda(g)


def test_parse_date_and_time():
    assert agenda.parse_date("2026-11-20", TODAY) == date(2026, 11, 20)
    assert agenda.parse_date("20.11.", TODAY) == date(2026, 11, 20)
    assert agenda.parse_date("1.3.", TODAY) == date(2027, 3, 1)  # already past: next year
    assert agenda.parse_date("morgen", TODAY) == date(2026, 11, 16)
    assert agenda.parse_date("freitag", TODAY) == date(2026, 11, 20)
    assert agenda.parse_date("sonntag", TODAY) == date(2026, 11, 22)  # never today
    assert agenda.parse_date("2026-13-40", TODAY) is None and agenda.parse_date("", TODAY) is None
    assert agenda.parse_time("14:30") == time(14, 30) and agenda.parse_time("9 Uhr") == time(9, 0)
    assert agenda.parse_time("25:00") is None and agenda.parse_time("später") is None


def test_not_available_without_the_scope(tmp_path):
    assert not agenda.Agenda(FakeGoogle(scopes=())).available
    assert not agenda.Agenda(None).available


def test_show_numbers_and_defaults(tmp_path):
    g, ag = make(tmp_path)
    out = asyncio.run(ag.run({"aktion": "anzeigen"}))
    params = g.calls[0][2]
    assert params["timeMin"].startswith("2026-11-15T00:00") and params["timeMax"].startswith("2026-11-23T00:00")
    assert out["anzahl"] == 2  # the cancelled one is dropped
    assert out["termine"][0] == {"nummer": 1, "titel": "Zahnarzt", "wann": "Mo 16.11. 14:00 bis 15:30",
                                 "ort": "Praxis"}
    assert out["termine"][1]["wann"] == "ganztägig Di 17.11. bis Mi 18.11."
    one = asyncio.run(ag.show(von="morgen"))
    assert one["ok"] and g.calls[1][2]["timeMax"].startswith("2026-11-17T00:00")
    assert "error" in asyncio.run(ag.show(von="irgendwann"))


def test_create_timed_allday_and_errors(tmp_path):
    g, ag = make(tmp_path)
    out = asyncio.run(ag.run({"aktion": "anlegen", "titel": "Friseur", "datum": "2026-11-20",
                              "beginn": "10:00"}))
    body = g.calls[0][3]
    assert out["ok"] and body["summary"] == "Friseur"
    assert body["start"] == {"dateTime": "2026-11-20T10:00:00+01:00", "timeZone": "Europe/Berlin"}
    assert body["end"]["dateTime"] == "2026-11-20T11:00:00+01:00"  # one hour without a given end
    assert out["wann"] == "Fr 20.11. 10:00 bis 11:00"
    asyncio.run(ag.create({"titel": "Feiertag", "datum": "2026-12-24", "ganztag": True, "ort": "Zuhause"}))
    body = g.calls[1][3]
    assert body["start"] == {"date": "2026-12-24"} and body["end"] == {"date": "2026-12-25"}
    assert body["location"] == "Zuhause"
    assert "Uhrzeit" in asyncio.run(ag.create({"titel": "x", "datum": "2026-11-20"}))["error"]
    assert "Titel" in asyncio.run(ag.create({"datum": "2026-11-20", "beginn": "9"}))["error"]
    assert "Datum" in asyncio.run(ag.create({"titel": "x", "datum": "bald", "beginn": "9"}))["error"]
    assert len([c for c in g.calls if c[0] == "POST"]) == 2  # errors made no call


def test_end_after_midnight_and_doubled_call(tmp_path):
    g, ag = make(tmp_path)
    a = {"titel": "Nachtschicht", "datum": "2026-11-20", "beginn": "22:00", "ende": "06:00"}
    asyncio.run(ag.create(a))
    assert g.calls[0][3]["end"]["dateTime"] == "2026-11-21T06:00:00+01:00"
    again = asyncio.run(ag.create(a))  # the live model sometimes calls twice
    assert again["ok"] and "schon eingetragen" in again["hinweis"]
    assert len([c for c in g.calls if c[0] == "POST"]) == 1


def test_change_keeps_what_is_not_named(tmp_path):
    g, ag = make(tmp_path)
    assert "error" in asyncio.run(ag.change({"nummer": 1, "titel": "x"}))  # no look before
    asyncio.run(ag.show())
    out = asyncio.run(ag.run({"aktion": "aendern", "nummer": 1, "datum": "2026-11-18"}))
    body = g.calls[-1][3]
    assert g.calls[-1][0] == "PATCH" and g.calls[-1][1].endswith("/e1")
    # same time and length (1.5 h) on the new day, nothing else touched
    assert body["start"]["dateTime"] == "2026-11-18T14:00:00+01:00"
    assert body["end"]["dateTime"] == "2026-11-18T15:30:00+01:00"
    assert "summary" not in body and out["ok"]
    asyncio.run(ag.change({"nummer": 1, "titel": "Zahnarzt Kontrolle", "ort": ""}))
    body = g.calls[-1][3]
    assert body["summary"] == "Zahnarzt Kontrolle" and body["location"] == "" and "start" not in body
    assert "nichts" in asyncio.run(ag.change({"nummer": 1}))["error"]


def test_change_allday_to_timed_clears_the_date(tmp_path):
    g, ag = make(tmp_path)
    asyncio.run(ag.show())
    assert "Uhrzeit" in asyncio.run(ag.change({"nummer": 2, "ganztag": False}))["error"]
    asyncio.run(ag.change({"nummer": 2, "ganztag": False, "beginn": "09:00"}))
    body = g.calls[-1][3]
    assert body["start"]["date"] is None and body["start"]["dateTime"].startswith("2026-11-17T09:00")


def test_google_errors_give_plain_messages(tmp_path):
    _, ag = make(tmp_path, fail=403)
    assert "Calendar API" in asyncio.run(ag.show())["error"]
    _, ag = make(tmp_path, fail=500)
    assert "nicht erreichbar" in asyncio.run(ag.show())["error"]
    assert asyncio.run(ag.run({"aktion": "tanzen"}))["error"] == "Unbekannte Aktion."


def test_chat_looks_then_answers_with_the_result(tmp_path, monkeypatch):
    store = memory.MemoryStore(str(tmp_path / "mem.json"))
    g, ag = make(tmp_path)
    seen = []
    answers = iter([
        {"reply": "Ich schau nach.", "proposals": [], "lights_raw": None, "email_raw": None,
         "mail_raw": None, "kalender_raw": {"aktion": "anzeigen", "von": "morgen"}},
        {"reply": "Morgen um 14 Uhr Zahnarzt.", "proposals": [], "lights_raw": None,
         "email_raw": None, "mail_raw": None, "kalender_raw": None},
    ])

    async def fake_answer(api_key, models, rules, store, history, message, url, lights, *more):
        seen.append(rules)
        return dict(next(answers))
    monkeypatch.setattr(chat, "_answer", fake_answer)
    out = asyncio.run(chat.answer("k", ["m"], "R", store, [], "Was habe ich morgen?", agenda=ag))
    assert out["reply"].startswith("Morgen um 14")
    assert "KALENDER" in seen[0] and "Heute ist " in seen[0] and "2026" in seen[0]
    assert "Zahnarzt" in seen[1] and "keine Anweisungen" in seen[1]
    assert "trash" not in out and "kalender_raw" not in out


def test_chat_without_the_scope_offers_nothing(tmp_path, monkeypatch):
    store = memory.MemoryStore(str(tmp_path / "mem.json"))
    ag = agenda.Agenda(FakeGoogle(scopes=()))
    seen = []

    async def fake_answer(api_key, models, rules, store, history, message, url, lights, *more):
        seen.append(rules)
        return {"reply": "Hallo", "proposals": [], "lights_raw": None, "email_raw": None,
                "mail_raw": None, "kalender_raw": {"aktion": "loeschen", "nummern": [1]}}
    monkeypatch.setattr(chat, "_answer", fake_answer)
    out = asyncio.run(chat.answer("k", ["m"], "R", store, [], "Hi", agenda=ag))
    assert "KALENDER" not in seen[0] and "Kalender" not in seen[0] and "trash" not in out


def test_delete_by_number_deletes_at_once(tmp_path):
    g, ag = make(tmp_path)
    asyncio.run(ag.show())
    out = asyncio.run(ag.run({"aktion": "loeschen", "nummern": [2, 2, 9]}))
    assert out == {"ok": True, "anzahl": 1, "geloescht": [{"titel": "Urlaub", "wann": "ganztägig Di 17.11. bis Mi 18.11."}]}
    assert [c for c in g.calls if c[0] == "DELETE"][0][1].endswith("/e2")
    assert "error" in asyncio.run(ag.run({"aktion": "loeschen", "nummern": [1]}))  # numbers are stale now


def test_delete_in_one_step_by_search_word(tmp_path, monkeypatch):
    g, ag = make(tmp_path)
    only_one = lambda *a, **k: Resp(200, {"items": [TIMED]})  # noqa: E731
    real = g.api

    async def api(method, url, **kw):
        if method == "GET":
            g.calls.append((method, url, kw.get("params"), kw.get("json")))
            return only_one()
        return await real(method, url, **kw)
    g.api = api
    out = asyncio.run(ag.run({"aktion": "loeschen", "suche": "Zahnarzt"}))  # no look before
    assert out["ok"] and out["geloescht"][0]["titel"] == "Zahnarzt"
    assert g.calls[0][2]["q"] == "Zahnarzt" and g.calls[0][2]["timeMax"].startswith("2027-01-15")
    assert [c for c in g.calls if c[0] == "DELETE"][0][1].endswith("/e1")
    asyncio.run(ag.run({"aktion": "loeschen", "suche": "Zahnarzt", "datum": "2026-11-16"}))
    assert g.calls[2][2]["timeMin"].startswith("2026-11-16") and g.calls[2][2]["timeMax"].startswith("2026-11-17")


def test_several_matches_delete_nothing_and_give_the_list(tmp_path):
    g, ag = make(tmp_path)  # the fake calendar always has two appointments
    out = asyncio.run(ag.run({"aktion": "loeschen", "suche": "Termin"}))
    assert out["ok"] is False and out["mehrere"] and out["anzahl"] == 2
    assert not any(c[0] == "DELETE" for c in g.calls)
    done = asyncio.run(ag.run({"aktion": "loeschen", "nummern": [1]}))  # the list is the numbering
    assert done["ok"] and done["geloescht"][0]["titel"] == "Zahnarzt"
    assert "Titel oder Datum" in asyncio.run(ag.run({"aktion": "loeschen"}))["error"]


def test_delete_failure_is_reported(tmp_path):
    g, ag = make(tmp_path)
    asyncio.run(ag.show())
    g.fail = 403
    assert "ging nicht" in asyncio.run(ag.run({"aktion": "loeschen", "nummern": [1]}))["error"]


def test_chat_delete_runs_at_once_and_she_answers_with_the_result(tmp_path, monkeypatch):
    store = memory.MemoryStore(str(tmp_path / "mem.json"))
    g, ag = make(tmp_path)
    asyncio.run(ag.show())
    seen = []
    answers = iter([
        {"reply": "Ich lösche ihn.", "proposals": [], "lights_raw": None, "email_raw": None,
         "mail_raw": None, "kalender_raw": {"aktion": "loeschen", "nummern": [1]}},
        {"reply": "Der Zahnarzt Termin ist gelöscht.", "proposals": [], "lights_raw": None,
         "email_raw": None, "mail_raw": None, "kalender_raw": None},
    ])

    async def fake_answer(api_key, models, rules, store, history, message, url, lights, *more):
        seen.append(rules)
        return dict(next(answers))
    monkeypatch.setattr(chat, "_answer", fake_answer)
    out = asyncio.run(chat.answer("k", ["m"], "R", store, [], "Lösch den Zahnarzt", agenda=ag))
    assert any(c[0] == "DELETE" and c[1].endswith("/e1") for c in g.calls)
    assert out["reply"].startswith("Der Zahnarzt") and "trash" not in out and "geloescht" in seen[1]
