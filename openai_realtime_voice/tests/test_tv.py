"""Tests for the TV control."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import rf, tv  # noqa: E402
from tests.test_rf import FakeDevice  # noqa: E402
from tests.test_lights import _HA, _server  # noqa: E402


def test_channels():
    ch = tv.parse_channels(None)
    assert ch == {"atv Avrupa": 1, "A Haber": 2, "Euro D": 6}
    assert tv.find_channel(ch, "a haber") == ("A Haber", 2)
    assert tv.find_channel(ch, "ATV") == ("atv Avrupa", 1)
    assert tv.find_channel(ch, "EuroD") == ("Euro D", 6)
    assert tv.find_channel(ch, "12") == ("Programm 12", 12)
    assert tv.find_channel(ch, "Show TV") is None


async def test_controller(tmp_path, monkeypatch):
    import asyncio as _a
    _orig = _a.sleep
    monkeypatch.setattr(tv.asyncio, "sleep", lambda s: _orig(0))
    _HA.calls.clear()
    server = _server(19995)
    dev = FakeDevice("h")
    remote = rf.RfRemote("h", 433.87, str(tmp_path / "c.json"), device_factory=lambda h: dev)
    for name in ("rx_eins", "rx_zwei", "rx_sechs", "rx_power", "tv_power"):
        remote.save_code(name, name.encode())
    ctl = tv.TvController(remote, tv.parse_channels(None), api_url="http://127.0.0.1:19995/api",
                          token="tok")
    try:
        r = await ctl.run({"action": "kanal", "channel": "A Haber", "steps": None})
        assert r["done"].startswith("A Haber") and dev.sent[-1] == b"rx_zwei"
        r = await ctl.run({"action": "kanal", "channel": "12", "steps": None})
        assert dev.sent[-2:] == [b"rx_eins", b"rx_zwei"]
        r = await ctl.run({"action": "kanal", "channel": "13", "steps": None})
        assert "drei" in r["error"]
        # remote.android_tv unknown to the fake HA -> "unavailable" -> infrared power button
        r = await ctl.run({"action": "an", "channel": None, "steps": None})
        assert dev.sent[-1] == b"rx_power" or dev.sent[-1] == b"tv_power"
        await ctl.run({"action": "lauter", "channel": None, "steps": None})
        assert _HA.calls[-1][2] == {"entity_id": "remote.android_tv", "command": "VOLUME_UP",
                                    "num_repeats": 3, "delay_secs": 0.25}
        await ctl.run({"action": "stumm", "channel": None, "steps": None})
        assert _HA.calls[-1][2]["command"] == "VOLUME_MUTE"
    finally:
        server.shutdown()


async def test_volume(tmp_path, monkeypatch):
    import asyncio as _a
    _orig = _a.sleep
    monkeypatch.setattr(tv.asyncio, "sleep", lambda s: _orig(0))
    _HA.calls.clear()
    _HA.states["media_player.android_tv_2"] = {
        "entity_id": "media_player.android_tv_2", "state": "on",
        "attributes": {"volume_level": 0.2, "is_volume_muted": False}}
    server = _server(19992)
    remote = rf.RfRemote("", 433.87, str(tmp_path / "c.json"))
    ctl = tv.TvController(remote, tv.parse_channels(None), api_url="http://127.0.0.1:19992/api",
                          token="tok")
    try:
        await ctl.run({"action": "lautstaerke", "volume_percent": 30})
        assert _HA.calls[-1][2]["command"] == "VOLUME_UP" and _HA.calls[-1][2]["num_repeats"] == 10
        r = await ctl.run({"action": "lautstaerke", "volume_percent": 0})
        assert _HA.calls[-1][2]["command"] == "VOLUME_MUTE" and r["volume_percent"] == 0
        _HA.states["remote.android_tv"] = {"entity_id": "remote.android_tv", "state": "on",
                                           "attributes": {}}
        r = await ctl.run({"action": "status"})
        assert r["tv"] == "an" and r["volume_percent"] == 20
    finally:
        _HA.states.pop("media_player.android_tv_2", None)
        _HA.states.pop("remote.android_tv", None)
        server.shutdown()
