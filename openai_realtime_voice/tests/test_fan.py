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


class _Meter:
    """Fake fan: light 14 W, fan 10 W, the licht button toggles the light."""

    def __init__(self, light=False, fan=False):
        self.light, self.fan = light, fan

    @property
    def watts(self):
        return (14.0 if self.light else 0.0) + (10.0 if self.fan else 0.0)


def _metered(tmp_path, monkeypatch, meter):
    import asyncio as _a
    _orig = _a.sleep
    monkeypatch.setattr(fan.asyncio, "sleep", lambda s: _orig(0))
    dev = FakeDevice("h")
    remote = rf.RfRemote("h", 433.87, str(tmp_path / "c.json"), device_factory=lambda h: dev)
    for name in ("stop", "licht"):
        for i in (1, 2, 3):
            remote.save_code(f"{name}_{i}", f"{name}{i}".encode())
    ctl = fan.FanController(remote, power_sensor="sensor.x", token="t")

    async def power():
        return meter.watts

    async def send_rotating(name):
        if name == "licht":
            meter.light = not meter.light
        return {"sent": name}

    ctl.power = power
    remote.send_rotating = send_rotating
    return ctl


async def test_light_on_from_off(tmp_path, monkeypatch):
    m = _Meter()
    ctl = _metered(tmp_path, monkeypatch, m)
    r = await ctl.run({"action": "licht_an"})
    assert m.light and r["done"] == "Licht an"
    r = await ctl.run({"action": "licht_an"})  # already on: no press
    assert m.light and "schon an" in r["done"]


async def test_light_on_corrects_wrong_toggle(tmp_path, monkeypatch):
    m = _Meter(light=True, fan=True)  # light already on, fan turning: 24 W
    ctl = _metered(tmp_path, monkeypatch, m)
    r = await ctl.run({"action": "licht_an"})
    assert m.light and "jetzt stimmt es" in r["note"]


async def test_light_off_and_status(tmp_path, monkeypatch):
    m = _Meter(light=True, fan=True)
    ctl = _metered(tmp_path, monkeypatch, m)
    r = await ctl.run({"action": "status"})
    assert r["light"] == "unbekannt"
    r = await ctl.run({"action": "licht_aus"})
    assert not m.light and r["done"] == "Licht aus"
    r = await ctl.run({"action": "status"})
    assert r == {"watt": 10.0, "light": "aus", "fan": "dreht sich"}
    r = await ctl.run({"action": "licht_aus"})
    assert not m.light and "schon aus" in r["done"]
    m.fan = False
    r = await ctl.run({"action": "status"})
    assert r["light"] == "aus" and r["fan"] == "steht"


async def test_light_without_meter(tmp_path):
    dev = FakeDevice("h")
    remote = rf.RfRemote("h", 433.87, str(tmp_path / "c.json"), device_factory=lambda h: dev)
    for i in (1, 2, 3):
        remote.save_code(f"licht_{i}", f"licht{i}".encode())
    ctl = fan.FanController(remote, power_sensor="sensor.x", token="")
    r = await ctl.run({"action": "licht_an"})
    assert r["pressed"] == "licht" and dev.sent[-1].startswith(b"licht")
