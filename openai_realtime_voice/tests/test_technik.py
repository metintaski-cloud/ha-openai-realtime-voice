"""Read only technology check."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import technik  # noqa: E402

STATES = [
    {"entity_id": "automation.lampen_aus", "state": "on",
     "attributes": {"friendly_name": "Lampen nachts aus", "id": "a1",
                    "last_triggered": "2026-11-11T22:30:00+00:00"}},
    {"entity_id": "automation.sonst", "state": "off",
     "attributes": {"friendly_name": "Etwas anderes", "id": "a2"}},
    {"entity_id": "light.wohnzimmer_lamba_1", "state": "on",
     "attributes": {"friendly_name": "Wohnzimmer Lamba 1"}},
    {"entity_id": "person.metin", "state": "home", "attributes": {"friendly_name": "Metin"}},
]
CONFIGS = {
    "a1": {"alias": "Lampen nachts aus", "triggers": [{"trigger": "time", "at": "23:30:00"}],
           "conditions": [], "actions": [{"action": "light.turn_off",
                                          "target": {"entity_id": ["light.wohnzimmer_lamba_1"]}}]},
    "a2": {"triggers": [{"trigger": "sun", "event": "sunset"}], "actions": []},
}


class Fake(technik.TechnikChecker):
    def __init__(self):
        super().__init__(token="t")

    async def _get(self, client, path):
        if path == "states":
            return STATES
        if path == "config":
            return {"time_zone": "Europe/Berlin"}
        if path.startswith("config/automation/config/"):
            return CONFIGS.get(path.rsplit("/", 1)[1])
        return None


async def test_finds_automation_by_time_and_shows_what_it_does():
    r = await Fake().run({"action": "automationen", "suche": "23:30"})
    assert r["treffer"] == 1
    a = r["automationen"][0]
    assert a["eingeschaltet"] and a["ausloeser"] == ["täglich um 23:30:00"]
    assert a["macht"] == ["light.turn_off auf light.wohnzimmer_lamba_1"]
    assert a["zuletzt_gelaufen"] == "11.11.2026 23:30"


async def test_no_match_says_so():
    r = await Fake().run({"action": "automationen", "suche": "Rolladen"})
    assert r["treffer"] == 0


async def test_devices_only_listed_domains():
    r = await Fake().run({"action": "geraete", "suche": "wohnzimmer"})
    assert r["geraete"] == [{"name": "Wohnzimmer Lamba 1", "zustand": "on"}]
    assert (await Fake().run({"action": "geraete", "suche": "metin"}))["treffer"] == 0


class Writer(Fake):
    def __init__(self):
        super().__init__()
        self.posted = []
        self.pushed = []

        async def notify(title, message):
            self.pushed.append((title, message))
        self.notify = notify


async def test_change_time_writes_only_the_time_and_tells_metin(monkeypatch):
    import httpx

    posted = []

    class Resp:
        status_code = 200

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            posted.append((url, json))
            return Resp()

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    w = Writer()
    r = await w.run({"action": "zeit_aendern", "suche": "Lampen", "alt": None, "neu": "23:45"})
    assert r == {"geaendert": "Lampen nachts aus", "von": "23:30", "auf": "23:45"}
    url, cfg = posted[0]
    assert url.endswith("config/automation/config/a1")
    assert cfg["triggers"] == [{"trigger": "time", "at": "23:45:00"}]
    assert cfg["actions"] == CONFIGS["a1"]["actions"]
    assert w.pushed and "23:30" in w.pushed[0][1] and "23:45" in w.pushed[0][1]


async def test_change_time_rejects_bad_input():
    w = Writer()
    assert "error" in await w.run({"action": "zeit_aendern", "suche": "Lampen", "alt": None,
                                   "neu": "25:99"})
    assert "error" in await w.run({"action": "zeit_aendern", "suche": "Rolladen", "alt": None,
                                   "neu": "23:45"})
    sun = await w.run({"action": "zeit_aendern", "suche": "anderes", "alt": None, "neu": "23:45"})
    assert "keine feste Uhrzeit" in sun["error"]
