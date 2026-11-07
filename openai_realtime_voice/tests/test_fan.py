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
    """Fake fan: light 18 W, fan speed 3 (10.7 W), the licht button toggles the light."""

    def __init__(self, light=False, fan=False):
        self.light, self.fan = light, fan

    @property
    def watts(self):
        return (18.0 if self.light else 0.0) + (10.7 if self.fan else 0.0)


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
    assert m.light and r["done"] == "Das Licht ist schon an." or r["done"] == "Licht an"
    assert m.light
    r = await ctl.run({"action": "licht_an"})  # known now: no press
    assert m.light and "schon an" in r["done"]


async def test_light_on_corrects_wrong_toggle(tmp_path, monkeypatch):
    m = _Meter(light=True, fan=True)  # 28.7 W: light 18 + fan 3, or fan 6 alone
    ctl = _metered(tmp_path, monkeypatch, m)
    assert ctl.describe(m.watts)["licht"] == "unklar"
    r = await ctl.run({"action": "licht_an"})
    assert m.light and "jetzt stimmt es" in r["note"]


async def test_light_off_and_status(tmp_path, monkeypatch):
    m = _Meter(light=True, fan=True)
    ctl = _metered(tmp_path, monkeypatch, m)
    r = await ctl.run({"action": "licht_aus"})
    assert not m.light and r["done"] == "Licht aus"
    r = await ctl.run({"action": "status"})
    assert r == {"watt": 10.7, "licht": "aus", "ventilator": "an, ungefähr Stufe 3"}
    r = await ctl.run({"action": "licht_aus"})
    assert not m.light and "schon aus" in r["done"]


async def test_light_without_meter(tmp_path):
    dev = FakeDevice("h")
    remote = rf.RfRemote("h", 433.87, str(tmp_path / "c.json"), device_factory=lambda h: dev)
    for i in (1, 2, 3):
        remote.save_code(f"licht_{i}", f"licht{i}".encode())
    ctl = fan.FanController(remote, power_sensor="sensor.x", token="")
    r = await ctl.run({"action": "licht_an"})
    assert r["pressed"] == "licht" and dev.sent[-1].startswith(b"licht")


def test_watts_alone():
    ctl = fan.FanController(None, power_sensor="s", token="")
    assert ctl.describe(0.0) == {"watt": 0.0, "licht": "aus", "ventilator": "aus"}
    ctl.light_on = ctl.speed = None
    assert ctl.describe(10.6)["ventilator"] == "an, ungefähr Stufe 3"  # only the fan fits
    ctl.light_on = ctl.speed = None
    r = ctl.describe(42.0)  # only light plus a fast fan fits
    assert r["licht"] == "an" and r["ventilator"].startswith("an")
    ctl.light_on = ctl.speed = None
    r = ctl.describe(14.5)  # light alone or fan speed 4 alone
    assert r["licht"] == "unklar" and "nur das Licht" in r["moeglich"]
    assert "nur der Ventilator auf Stufe 4" in r["moeglich"]


# Power readings recorded on 7 Nov 2026 (seconds, watts) while switching through
HISTORY = [
    (0, 13.5),                                  # light on, fan off
    (27, 2.5), (28, 0.0), (30, 0.0),            # light off
    (34, 5.3), (35, 12.1), (36, 5.2),           # fan speed 1, with its start kick
    (44, 6.3), (51, 7.6), (53, 9.2), (55, 10.9),  # speeds 2 and 3
    (62, 12.7), (63, 14.4),                     # speed 4
    (70, 15.5), (71, 17.3), (73, 19.1),         # speed 5
    (79, 20.8), (80, 22.0), (81, 23.1), (83, 26.4), (85, 28.5),  # speed 6
    (87, 37.7), (88, 46.6),                     # light on
    (96, 43.4), (99, 39.2), (101, 36.9), (103, 33.4), (105, 31.4), (107, 28.2),
    (109, 26.1), (111, 22.5),                   # down to speed 1
    (112, 18.5),                                # fan off, light stays
    (179, 0.0),                                 # light off
]


def test_follows_recorded_history():
    ctl = fan.FanController(None, power_sensor="s", token="")
    import time
    base = time.monotonic() - 1000
    seen = {}
    for t, w in HISTORY:
        ctl.on_power(w, base + t)
        seen[t] = ctl.describe(w)
    assert seen[0]["licht"] == "unklar"          # 13.5 W alone: light or fan 4
    assert seen[36] == {"watt": 5.2, "licht": "aus", "ventilator": "an, ungefähr Stufe 1"}
    assert seen[63]["licht"] == "aus" and seen[63]["ventilator"] == "an, ungefähr Stufe 4"
    assert seen[85]["licht"] == "aus" and seen[85]["ventilator"] == "an, ungefähr Stufe 6"
    assert seen[88]["licht"] == "an" and seen[88]["ventilator"] == "an, ungefähr Stufe 6"
    assert seen[112] == {"watt": 18.5, "licht": "an", "ventilator": "aus"}
    assert seen[179] == {"watt": 0.0, "licht": "aus", "ventilator": "aus"}


def test_fan_stop_versus_light_off():
    import time
    base = time.monotonic() - 1000
    ctl = fan.FanController(None, power_sensor="s", token="")
    ramp = [(20 + i, 18.2 + 1.5 * i) for i in range(11)]  # fan ramps up to speed 4
    for t, w in [(0, 0.0), (5, 9.0), (6, 18.2)] + ramp:   # light on, then the fan
        ctl.on_power(w, base + t)
    assert ctl.describe(33.2) == {"watt": 33.2, "licht": "an", "ventilator": "an, ungefähr Stufe 4"}
    ctl.on_power(18.2, base + 41)   # quick drop of 15 W, the light alone is left
    assert ctl.describe(18.2) == {"watt": 18.2, "licht": "an", "ventilator": "aus"}
    for t, w in [(60 + i, 18.2 + 1.5 * i) for i in range(11)]:  # fan up again
        ctl.on_power(w, base + t)
    ctl.on_power(14.8, base + 71)   # quick drop of 18 W: what is left looks like the fan
    assert ctl.describe(14.8) == {"watt": 14.8, "licht": "aus", "ventilator": "an, ungefähr Stufe 4"}


def test_state_survives_restart(tmp_path):
    import time
    path = str(tmp_path / "fan_state.json")
    base = time.monotonic() - 1000
    a = fan.FanController(None, power_sensor="s", token="", state_path=path)
    for t, w in [(0, 0.0), (5, 9.0), (6, 18.2)]:
        a.on_power(w, base + t)
    assert a.describe(18.2)["licht"] == "an"
    b = fan.FanController(None, power_sensor="s", token="", state_path=path)
    assert b.describe(18.0) == {"watt": 18.0, "licht": "an", "ventilator": "aus"}
    c = fan.FanController(None, power_sensor="s", token="", state_path=path)
    assert c.describe(14.8)["licht"] == "unklar"  # power changed meanwhile: not trusted
