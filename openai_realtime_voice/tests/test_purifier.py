"""Air purifier control."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import purifier  # noqa: E402


class Fake(purifier.PurifierController):
    def __init__(self):
        super().__init__("fan.luftreiniger", token="t")
        self.calls = []

    async def _state(self, client, eid):
        if eid == "fan.luftreiniger":
            return {"state": "on", "attributes": {"preset_mode": "auto", "percentage": 50}}
        return {"state": "13"}

    async def _service(self, client, domain, service, data):
        self.calls.append((domain, service, data))


async def test_sleep_mode_and_status():
    f = Fake()
    r = await f.run({"action": "modus", "modus": "schlaf", "stufe": None, "minuten": None})
    assert ("fan", "set_preset_mode", {"entity_id": "fan.luftreiniger",
                                       "preset_mode": "sleep"}) in f.calls
    assert r["level"] == 2 and r["air_quality"] == "mäßig"


async def test_timer():
    f = Fake()
    await f.run({"action": "timer", "modus": None, "stufe": None, "minuten": 60})
    assert ("number", "set_value", {"entity_id": "number.luftreiniger_timer_aus",
                                    "value": 60}) in f.calls


async def test_status_refreshes_first_and_warns_about_old_data():
    class Old(Fake):
        async def _state(self, client, eid):
            st = await super()._state(client, eid)
            if eid == "fan.luftreiniger":
                st = dict(st, last_reported="2026-11-13T10:00:00+00:00")
            return st

    p = Old()
    r = await p.run({"action": "status"})
    assert p.calls[0][:2] == ("homeassistant", "update_entity")
    assert r["data_age_minutes"] > 15 and "warning" in r


async def test_unreachable_purifier_is_said_plainly():
    class Gone(Fake):
        async def _state(self, client, eid):
            if eid == "fan.luftreiniger":
                return {"state": "unavailable", "attributes": {}}
            return await super()._state(client, eid)

    r = await Gone().run({"action": "status"})
    assert r["reachable"] is False and "nicht erreichbar" in r["error"]
