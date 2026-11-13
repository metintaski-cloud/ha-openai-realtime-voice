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


def _client(posted):
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
    return Client


def _sunset_config():
    return {"alias": "Licht bei Sonnenuntergang",
            "triggers": [{"trigger": "sun", "event": "sunset", "offset": "-00:15:00"}],
            "actions": [
                {"action": "light.turn_on", "target": {"entity_id": ["light.wohnzimmer_lamba_1"]},
                 "data": {"color_temp_kelvin": 2700, "brightness_pct": 80}},
                {"action": "light.turn_on", "target": {"entity_id": ["light.flur"]},
                 "data": {"brightness_pct": 50}}]}


def _with_sunset(monkeypatch):
    import httpx
    states = STATES + [{"entity_id": "automation.sonnenuntergang", "state": "on",
                        "attributes": {"friendly_name": "Licht bei Sonnenuntergang",
                                       "id": "a3"}}]
    configs = dict(CONFIGS, a3=_sunset_config())
    posted = []
    monkeypatch.setattr(httpx, "AsyncClient", _client(posted))

    class W(Writer):
        async def _get(self, client, path):
            if path == "states":
                return states
            if path.startswith("config/automation/config/"):
                return configs.get(path.rsplit("/", 1)[1])
            return await super()._get(client, path)
    return W(), posted


def test_parse_color():
    assert technik.parse_color("Rot") == {"rgb_color": [255, 0, 0]}
    assert technik.parse_color("warmweiß") == {"color_temp_kelvin": 2700}
    assert technik.parse_color("255, 120, 0") == {"rgb_color": [255, 120, 0]}
    assert technik.parse_color("300,0,0") is None
    assert technik.parse_color("regenbogen") is None


async def test_automation_list_shows_current_light_settings(monkeypatch):
    w, _ = _with_sunset(monkeypatch)
    r = await w.run({"action": "automationen", "suche": "Sonnenuntergang"})
    macht = r["automationen"][0]["macht"]
    assert "color_temp_kelvin 2700" in macht[0] and "brightness_pct 80" in macht[0]


async def test_change_light_color_replaces_white_tone_and_keeps_the_rest(monkeypatch):
    w, posted = _with_sunset(monkeypatch)
    r = await w.run({"action": "licht_aendern", "suche": "Sonnenuntergang",
                     "lampe": "Wohnzimmer", "farbe": "orange", "helligkeit": None})
    assert r["geaendert"] == "Licht bei Sonnenuntergang" and r["lampen"] == 1
    cfg = posted[0][1]
    assert cfg["triggers"] == _sunset_config()["triggers"]
    assert cfg["actions"][0]["data"] == {"rgb_color": [255, 120, 0], "brightness_pct": 80}
    assert cfg["actions"][1] == _sunset_config()["actions"][1]
    assert w.pushed and "orange" in w.pushed[0][1]


async def test_change_light_brightness_only_for_all_lamps(monkeypatch):
    w, posted = _with_sunset(monkeypatch)
    r = await w.run({"action": "licht_aendern", "suche": "Sonnenuntergang",
                     "lampe": None, "farbe": None, "helligkeit": 30})
    assert r["lampen"] == 2
    acts = posted[0][1]["actions"]
    assert acts[0]["data"] == {"color_temp_kelvin": 2700, "brightness_pct": 30}
    assert acts[1]["data"] == {"brightness_pct": 30}


async def test_change_light_rejects_bad_input_and_non_light_automations(monkeypatch):
    w, posted = _with_sunset(monkeypatch)
    base = {"action": "licht_aendern", "suche": "Sonnenuntergang", "lampe": None}
    assert "error" in await w.run({**base, "farbe": "regenbogen", "helligkeit": None})
    assert "error" in await w.run({**base, "farbe": None, "helligkeit": 0})
    assert "error" in await w.run({**base, "farbe": None, "helligkeit": None})
    assert "error" in await w.run({**base, "lampe": "Keller", "farbe": "rot",
                                   "helligkeit": None})
    assert "error" in await w.run({"action": "licht_aendern", "suche": "anderes", "lampe": None,
                                   "farbe": "rot", "helligkeit": None})
    assert posted == []


def _lamp_states():
    return [{"entity_id": e, "state": "off", "attributes": {"friendly_name": f}}
            for e, f in [("light.wohnzimmer_lamba_1", "Wohnzimmer Lamba 1"),
                         ("light.wohnzimmer_lamba_2", "Wohnzimmer Lamba 2"),
                         ("light.flur", "Flur"), ("light.keller", "Keller")]]


def _with_lamps(monkeypatch):
    import httpx
    configs = dict(CONFIGS, a3={
        "alias": "Licht bei Sonnenuntergang",
        "triggers": [{"trigger": "sun", "event": "sunset"}],
        "actions": [{"action": "light.turn_on",
                     "target": {"entity_id": ["light.wohnzimmer_lamba_1",
                                              "light.wohnzimmer_lamba_2", "light.flur"]},
                     "data": {"brightness_pct": 80}}]})
    states = [x for x in STATES if not x['entity_id'].startswith('light.')] + _lamp_states() + [
        {"entity_id": "automation.sonnenuntergang", "state": "on",
         "attributes": {"friendly_name": "Licht bei Sonnenuntergang", "id": "a3"}}]
    posted = []
    monkeypatch.setattr(httpx, "AsyncClient", _client(posted))

    class W(Writer):
        async def _get(self, client, path):
            if path == "states":
                return states
            if path.startswith("config/automation/config/"):
                return configs.get(path.rsplit("/", 1)[1])
            return await super()._get(client, path)
    return W(), posted


def _lamps(w, mode, names):
    return w.run({"action": "lampen_aendern", "suche": "Sonnenuntergang", "modus": mode,
                  "lampen": names})


async def test_lamps_taken_out_keep_the_rest(monkeypatch):
    w, posted = _with_lamps(monkeypatch)
    r = await _lamps(w, "entfernen", ["Wohnzimmer Lamba 1", "Wohnzimmer Lamba 2"])
    assert r["schaltet_jetzt"] == ["light.flur"]
    act = posted[0][1]["actions"][0]
    assert act["target"]["entity_id"] == ["light.flur"] and act["data"] == {"brightness_pct": 80}
    assert w.pushed


async def test_lamps_added_and_only(monkeypatch):
    w, posted = _with_lamps(monkeypatch)
    r = await _lamps(w, "hinzufuegen", ["Keller"])
    assert r["schaltet_jetzt"] == ["light.flur", "light.keller", "light.wohnzimmer_lamba_1",
                                   "light.wohnzimmer_lamba_2"]
    r = await _lamps(w, "nur", ["Flur", "Keller"])
    assert posted[1][1]["actions"][0]["target"]["entity_id"] == ["light.flur", "light.keller"]


async def test_lamp_names_must_be_clear(monkeypatch):
    w, posted = _with_lamps(monkeypatch)
    amb = await _lamps(w, "entfernen", ["Wohnzimmer"])
    assert "nicht eindeutig" in amb["error"] and len(amb["lampen"]) == 2
    assert "nicht gefunden" in (await _lamps(w, "entfernen", ["Garage"]))["error"]
    assert "error" in await _lamps(w, "entfernen", [])
    assert "error" in await _lamps(w, None, ["Flur"])
    assert posted == []


async def test_cannot_remove_the_last_lamp(monkeypatch):
    w, posted = _with_lamps(monkeypatch)
    r = await _lamps(w, "entfernen", ["Flur", "Wohnzimmer Lamba 1", "Wohnzimmer Lamba 2"])
    assert "keine Lampe mehr" in r["error"] and posted == []


async def test_lamps_by_area_are_refused(monkeypatch):
    import httpx
    w, posted = _with_lamps(monkeypatch)
    orig = w._get

    async def get(client, path):
        r = await orig(client, path)
        if path.endswith("/a3"):
            r = {**r, "actions": [{"action": "light.turn_on", "target": {"area_id": "wohnzimmer"}}]}
        return r
    w._get = get
    assert "Bereich" in (await _lamps(w, "entfernen", ["Flur"]))["error"] and posted == []
