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


async def test_controller(tmp_path):
    _HA.calls.clear()
    server = _server(19995)
    dev = FakeDevice("h")
    remote = rf.RfRemote("h", 433.87, str(tmp_path / "c.json"), device_factory=lambda h: dev)
    for name in ("rx_eins", "rx_zwei", "rx_sechs", "rx_power"):
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
        await ctl.run({"action": "an", "channel": None, "steps": None})
        assert _HA.calls[-1][1] == "turn_on"
        await ctl.run({"action": "lauter", "channel": None, "steps": None})
        assert _HA.calls[-1][2] == {"entity_id": "remote.android_tv", "command": "VOLUME_UP",
                                    "num_repeats": 3, "delay_secs": 0.25}
        await ctl.run({"action": "stumm", "channel": None, "steps": None})
        assert _HA.calls[-1][2]["command"] == "VOLUME_MUTE"
    finally:
        server.shutdown()
