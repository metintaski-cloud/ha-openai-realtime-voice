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


async def test_status_lists_rooms():
    r = await FakeVac().run({"action": "status", "rooms": [], "modus": None, "staerke": None})
    assert r["rooms"] == ["küche", "flur"] and r["battery_percent"] == 100
