"""Robot vacuum control."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import vacuum  # noqa: E402

ROOMS = {"Karte1": [{"id": 1, "name": "Küche"}, {"id": 2, "name": "Flur"}]}


def test_rooms_and_turkish_names():
    rooms = vacuum.map_rooms(ROOMS)
    assert rooms == {"küche": 1, "flur": 2}
    assert vacuum.match_rooms(["Küche"], rooms) == ([1], [])
    assert vacuum.match_rooms(["mutfağı", "koridor"], rooms) == ([1, 2], [])
    assert vacuum.match_rooms(["die Küche", "Bad"], rooms) == ([1], ["Bad"])


def test_pick_option():
    opts = ["Sweeping", "Mopping", "Sweeping and mopping", "Mopping after sweeping"]
    assert vacuum.pick_option(opts, vacuum.MODES["saugen_und_wischen"]) == "Sweeping and mopping"
    assert vacuum.pick_option(["Quiet", "Standard"], vacuum.SUCTION["leise"]) == "Quiet"
    assert vacuum.pick_option(["quiet"], "turbo") is None


class FakeVac(vacuum.VacuumController):
    def __init__(self):
        super().__init__("vacuum.x60", token="t")
        self.calls = []

    async def _state(self, client, eid):
        if eid == "vacuum.x60":
            return {"state": "docked", "attributes": {"rooms": ROOMS, "battery_level": 100}}
        if eid.startswith("select."):
            return {"attributes": {"options": ["Sweeping", "Mopping"]}}
        return {"state": "installed"}

    async def _service(self, client, domain, service, data):
        self.calls.append((domain, service, data))


async def test_clean_kitchen_mopping():
    v = FakeVac()
    r = await v.run({"action": "raeume", "rooms": ["mutfak"], "modus": "wischen", "staerke": None})
    assert ("select", "select_option", {"entity_id": "select.x60_cleaning_mode",
                                        "option": "Mopping"}) in v.calls
    assert ("dreame_vacuum", "vacuum_clean_segment",
            {"entity_id": "vacuum.x60", "segments": [1]}) in v.calls
    assert r["rooms"] == ["küche"]


async def test_suction_is_always_turbo():
    class Turbo(FakeVac):
        async def _state(self, client, eid):
            if eid.startswith("select.") and eid.endswith("suction_level"):
                return {"attributes": {"options": ["Quiet", "Standard", "Strong", "Turbo"]}}
            return await super()._state(client, eid)

    for asked in ("leise", "standard", None):
        v = Turbo()
        await v.run({"action": "starten", "rooms": [], "modus": None, "staerke": asked})
        assert ("select", "select_option", {"entity_id": "select.x60_suction_level",
                                            "option": "Turbo"}) in v.calls


async def test_status_lists_rooms():
    r = await FakeVac().run({"action": "status", "rooms": [], "modus": None, "staerke": None})
    assert r["rooms"] == ["küche", "flur"] and r["battery_percent"] == 100


async def test_status_refreshes_first_and_reports_how_old_the_data_is():
    class Old(FakeVac):
        async def _state(self, client, eid):
            st = await super()._state(client, eid)
            if eid == "vacuum.x60":
                st = dict(st, last_reported="2026-11-13T10:00:00+00:00")
            return st

    v = Old()
    r = await v.run({"action": "status", "rooms": [], "modus": None, "staerke": None})
    assert v.calls[0][:2] == ("homeassistant", "update_entity")
    assert "vacuum.x60" in v.calls[0][2]["entity_id"]
    assert r["refreshed"] is True and r["data_age_minutes"] > 15 and "warning" in r


async def test_fresh_data_has_no_warning():
    import datetime as dt

    class Fresh(FakeVac):
        async def _state(self, client, eid):
            st = await super()._state(client, eid)
            if eid == "vacuum.x60":
                st = dict(st, last_reported=dt.datetime.now(dt.timezone.utc).isoformat())
            return st

    r = await Fresh().run({"action": "status", "rooms": [], "modus": None, "staerke": None})
    assert r["data_age_minutes"] == 0 and "warning" not in r


async def test_unreachable_robot_is_said_plainly_not_answered_with_old_values():
    class Gone(FakeVac):
        async def _state(self, client, eid):
            if eid == "vacuum.x60":
                return {"state": "unavailable", "attributes": {}}
            return await super()._state(client, eid)

    r = await Gone().run({"action": "status", "rooms": [], "modus": None, "staerke": None})
    assert r["reachable"] is False and "nicht erreichbar" in r["error"]
    assert "battery_percent" not in r


async def test_a_failing_refresh_does_not_break_the_status():
    class NoRefresh(FakeVac):
        async def _service(self, client, domain, service, data):
            if service == "update_entity":
                raise RuntimeError("HA HTTP 500")
            await super()._service(client, domain, service, data)

    r = await NoRefresh().run({"action": "status", "rooms": [], "modus": None, "staerke": None})
    assert r["refreshed"] is False and r["battery_percent"] == 100
