"""Tests for the ceiling fan control."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import fan, rf  # noqa: E402
from tests.test_rf import FakeDevice  # noqa: E402


def test_button_mapping():
    assert fan.button_for({"action": "stufe", "speed": 4}) == ("stufe4", None)
    assert fan.button_for({"action": "stufe", "speed": 9})[0] is None
    assert fan.button_for({"action": "timer", "hours": 2}) == ("timer2", None)
    assert fan.button_for({"action": "timer", "hours": 3})[0] is None
    assert fan.button_for({"action": "aus"}) == ("stop", None)
    assert fan.button_for({"action": "links"}) == ("vorwaerts", None)
    assert fan.button_for({"action": "rechts"}) == ("rueckwaerts", None)
    assert fan.button_for({"action": "licht"}) == ("licht", None)


async def test_controller_sends_rotating(tmp_path):
    dev = FakeDevice("h")
    remote = rf.RfRemote("h", 433.87, str(tmp_path / "c.json"), device_factory=lambda h: dev)
    ctl = fan.FanController(remote)
    assert not ctl.available
    for name in ("stop", "licht", "stufe3"):
        for i in (1, 2, 3):
            remote.save_code(f"{name}_{i}", f"{name}{i}".encode())
    assert ctl.available
    r = await ctl.run({"action": "stufe", "speed": 3, "hours": None})
    assert r["speed"] == 3 and dev.sent[-1] == b"stufe32"
    await ctl.run({"action": "licht", "speed": None, "hours": None})
    await ctl.run({"action": "licht", "speed": None, "hours": None})
    assert dev.sent[-2:] == [b"licht2", b"licht3"]
    r = await ctl.run({"action": "naturwind", "speed": None, "hours": None})
    assert "error" in r
    r = await ctl.run({"action": "stufe", "speed": None, "hours": None})
    assert "error" in r
