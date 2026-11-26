"""Tests for the TV control."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import rf, tv  # noqa: E402
from tests.test_rf import FakeDevice  # noqa: E402
from tests.test_lights import _HA, _server  # noqa: E402


OLD = "atv Avrupa=1; A Haber=2; Euro D=6"   # the places on the satellite receiver


def test_channels():
    assert tv.parse_channels(None) == {"atv": 2, "Euro D": 3, "A Haber": 12}   # his waipu.tv places
    ch = tv.parse_channels(OLD)
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
    ctl = tv.TvController(remote, tv.parse_channels(OLD), api_url="http://127.0.0.1:19995/api",
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
                                    "num_repeats": 3, "delay_secs": 0.1}
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


async def test_duck_while_leyla_listens(tmp_path, monkeypatch):
    import asyncio as _a
    _orig = _a.sleep
    monkeypatch.setattr(tv.asyncio, "sleep", lambda s: _orig(0))
    monkeypatch.delenv("TV_DUCK", raising=False)
    _HA.calls.clear()
    player = {"entity_id": "media_player.android_tv_2", "state": "on",
              "attributes": {"volume_level": 0.5, "is_volume_muted": False}}
    _HA.states["media_player.android_tv_2"] = player
    _HA.states["remote.android_tv"] = {"entity_id": "remote.android_tv", "state": "on",
                                       "attributes": {}}
    server = _server(19993)
    remote = rf.RfRemote("", 433.87, str(tmp_path / "c.json"))
    ctl = tv.TvController(remote, tv.parse_channels(None), api_url="http://127.0.0.1:19993/api",
                          token="tok")
    try:
        await ctl.duck()
        assert _HA.calls[-1][2] == {"entity_id": "remote.android_tv", "command": "VOLUME_DOWN",
                                    "num_repeats": 42, "delay_secs": 0.1}  # 50 -> 8
        # Asked for the volume, Leyla tells the normal one
        r = await ctl.run({"action": "status"})
        assert r["volume_percent"] == 50
        # Ducking twice does nothing
        n = len(_HA.calls)
        await ctl.duck()
        assert len(_HA.calls) == n
        # After the conversation it goes back up
        player["attributes"]["volume_level"] = 0.15
        await ctl.unduck()
        assert _HA.calls[-1][2]["command"] == "VOLUME_UP"
        assert _HA.calls[-1][2]["num_repeats"] == 35
        # A volume request during the conversation starts from the normal volume
        player["attributes"]["volume_level"] = 0.5
        await ctl.duck()
        player["attributes"]["volume_level"] = 0.15
        await ctl.run({"action": "lauter", "steps": 3})
        cmds = [c[2]["command"] for c in _HA.calls[-2:]]
        assert cmds == ["VOLUME_UP", "VOLUME_UP"] and _HA.calls[-1][2]["num_repeats"] == 3
        # A moment later the TV goes down again, and the new volume is the one to restore
        for _ in range(30):
            await _orig(0.05)
            if ctl._ducked_from is not None and not ctl._lock.locked():
                break
        assert _HA.calls[-1][2]["command"] == "VOLUME_DOWN" and ctl._ducked_from == 15
        n = len(_HA.calls)
        await ctl.unduck()  # fake TV still reports 15: nothing to press
        assert len(_HA.calls) == n and not ctl.listening
        # Quiet or muted TV: left alone
        player["attributes"]["volume_level"] = 0.06
        await ctl.duck()
        player["attributes"].update(volume_level=0.5, is_volume_muted=True)
        await ctl.duck()
        assert len(_HA.calls) == n
        # Switched off with TV_DUCK=false
        player["attributes"]["is_volume_muted"] = False
        monkeypatch.setenv("TV_DUCK", "false")
        off = tv.TvController(remote, {}, api_url="http://127.0.0.1:19993/api", token="tok")
        await off.duck()
        assert len(_HA.calls) == n
    finally:
        _HA.states.pop("media_player.android_tv_2", None)
        _HA.states.pop("remote.android_tv", None)
        server.shutdown()


async def test_no_duck_when_tv_is_off(tmp_path, monkeypatch):
    _HA.calls.clear()
    server = _server(19994)
    remote = rf.RfRemote("", 433.87, str(tmp_path / "c.json"))
    ctl = tv.TvController(remote, {}, api_url="http://127.0.0.1:19994/api", token="tok")
    try:
        await ctl.duck()  # remote.android_tv unknown -> not on
        await ctl.unduck()
        assert _HA.calls == []
    finally:
        server.shutdown()


def _fake_tv(ctl, rules):
    """Let the fake TV react to what Leyla sends: `rules` maps a key or a start value to the
    app that is in front afterwards (None: nothing happens, as measured on his TV)."""
    real = ctl._service

    async def service(domain, name, data):
        await real(domain, name, data)
        what = data.get("activity") or data.get("command")
        if isinstance(what, str) and rules.get(what):
            _HA.states["remote.android_tv"] = {"entity_id": "remote.android_tv", "state": "on",
                                               "attributes": {"current_activity": rules[what]}}
    ctl._service = service


def _tv_calls():
    return [(c[1], c[2].get("activity") or c[2].get("command")) for c in _HA.calls]


TUNER, HOME, WAIPU = "com.mediatek.wwtv.tvcenter", "com.google.android.tvlauncher", "de.exaring.waipu"


async def _app_ctl(tmp_path, monkeypatch, port, activity, state="on", tv_app=tv.DEFAULT_TV_APP):
    import asyncio as _a
    _orig = _a.sleep
    monkeypatch.setattr(tv.asyncio, "sleep", lambda s: _orig(0))
    _HA.calls.clear()
    _HA.states["remote.android_tv"] = {"entity_id": "remote.android_tv", "state": state,
                                       "attributes": {"current_activity": activity}}
    server = _server(port)
    dev = FakeDevice("h")
    remote = rf.RfRemote("h", 433.87, str(tmp_path / "c.json"), device_factory=lambda h: dev)
    ctl = tv.TvController(remote, tv.parse_channels(None), api_url=f"http://127.0.0.1:{port}/api", token="tok",
                          tv_app=tv_app)
    return ctl, server, dev


async def test_channels_through_the_tv_app(tmp_path, monkeypatch):
    """2.182.0 (Metin, 26 Nov 2026: the receiver is broken, he watches with waipu.tv) and 2.182.2 ("Ich möchte ins
    Home-Button und dann das App öffnen und dann das Kanal"): from the dark screen of the TV's tuner app she presses
    Home, starts the app and types the channel number with the digit keys of the TV; nothing goes out by infrared."""
    ctl, server, dev = await _app_ctl(tmp_path, monkeypatch, 19996, TUNER)
    _fake_tv(ctl, {"HOME": HOME, "waipu://tv": WAIPU})
    try:
        r = await ctl.run({"action": "kanal", "channel": "A Haber", "steps": None, "volume_percent": None})
        assert r["done"].startswith("A Haber (Programm 12)") and "geöffnet" in r["done"], r
        assert _tv_calls() == [("send_command", "HOME"), ("turn_on", "waipu://tv"), ("send_command", ["1", "2"])]
        assert _HA.calls[-1][2]["delay_secs"] == tv.DIGIT_DELAY_S
        # the app is in front now: only the digit, no Home and no new start
        _HA.calls.clear()
        r = await ctl.run({"action": "kanal", "channel": "atv", "steps": None, "volume_percent": None})
        assert r["done"] == "atv (Programm 2)", r
        assert _tv_calls() == [("send_command", "2")]
        r = await ctl.run({"action": "kanal", "channel": "Kanal 7", "steps": None, "volume_percent": None})
        assert "kenne ich nicht" in r["error"] and dev.sent == []                # nothing by infrared at all
    finally:
        server.shutdown()
        _HA.states.pop("remote.android_tv", None)


async def test_the_other_start_is_tried_when_the_first_does_nothing(tmp_path, monkeypatch):
    """Measured on his TV on 26 Nov 2026: at 19:08 the address did nothing and the package name started the app, from
    19:18 on it was the other way round. So the starts are tried in turn until the TV reports the app in front."""
    ctl, server, _ = await _app_ctl(tmp_path, monkeypatch, 19998, HOME)
    _fake_tv(ctl, {"HOME": HOME, "waipu://tv": None, "de.exaring.waipu": WAIPU})
    try:
        r = await ctl.run({"action": "kanal", "channel": "Euro D", "steps": None, "volume_percent": None})
        assert r["done"].startswith("Euro D (Programm 3)"), r
        # already on the home screen: no Home key
        assert _tv_calls() == [("turn_on", "waipu://tv"), ("turn_on", "de.exaring.waipu"), ("send_command", "3")]
    finally:
        server.shutdown()
        _HA.states.pop("remote.android_tv", None)


async def test_no_channel_is_claimed_when_the_app_does_not_come(tmp_path, monkeypatch):
    """Metin, 26 Nov 2026, 19:20: "Sie macht zwar Fernseher an und sagt zum Beispiel, dieser Kanal ist jetzt da, aber
    dabei ist es nicht da. Da steht immer noch, bitte Kanäle suchen." No digit goes into another app and the answer
    is an error."""
    ctl, server, _ = await _app_ctl(tmp_path, monkeypatch, 19999, TUNER)
    _fake_tv(ctl, {"HOME": HOME})                       # no start brings the app
    try:
        r = await ctl.run({"action": "kanal", "channel": "atv", "steps": None, "volume_percent": None})
        assert "nicht öffnen" in r["error"] and "done" not in r, r
        calls = _tv_calls()
        assert [c[1] for c in calls if c[0] == "turn_on"] == ["waipu://tv", "de.exaring.waipu", "waipu://tv"]
        assert not [c for c in calls if c[0] == "send_command" and c[1] != "HOME"]   # no digit typed
    finally:
        server.shutdown()
        _HA.states.pop("remote.android_tv", None)


async def test_the_tv_is_switched_on_first_for_a_channel(tmp_path, monkeypatch):
    ctl, server, _ = await _app_ctl(tmp_path, monkeypatch, 20001, WAIPU[:0], state="off")
    _fake_tv(ctl, {"HOME": HOME, "waipu://tv": WAIPU})
    try:
        r = await ctl.run({"action": "kanal", "channel": "atv", "steps": None, "volume_percent": None})
        assert r["done"].startswith("atv (Programm 2)"), r
        calls = _tv_calls()
        assert calls[0] == ("turn_on", None) and calls[-1] == ("send_command", "2"), calls
    finally:
        server.shutdown()
        _HA.states.pop("remote.android_tv", None)


def test_the_starts_of_an_app():
    ctl = tv.TvController(None, {}, tv_app="de.exaring.waipu")
    assert ctl._app_starts() == ("de.exaring.waipu", ["waipu://tv", "de.exaring.waipu"])
    ctl = tv.TvController(None, {}, tv_app="waipu://tv")         # the address in the option means the same app
    assert ctl._app_starts() == ("de.exaring.waipu", ["waipu://tv", "de.exaring.waipu"])
    assert tv.TvController(None, {}, tv_app="zattoo://zattoo.com")._app_starts() == ("zattoo", ["zattoo://zattoo.com"])
    assert tv.TvController(None, {}, tv_app="ar.tvplayer.tv")._app_starts() == ("ar.tvplayer.tv", ["ar.tvplayer.tv"])


def test_the_tv_app_is_the_default_and_the_receiver_can_be_chosen(monkeypatch):
    monkeypatch.delenv("TV_APP", raising=False)
    assert tv.from_env(None).tv_app == "de.exaring.waipu"     # the package name, as the TV reports the app in front
    monkeypatch.setenv("TV_APP", "null")          # the add on option is not set
    assert tv.from_env(None).tv_app == "de.exaring.waipu"
    monkeypatch.setenv("TV_APP", "receiver")
    assert tv.from_env(None).tv_app == ""
    tool = tv.build_tool(tv.parse_channels(None))
    assert "atv (2)" in tool["description"] and "A Haber (12)" in tool["description"]
    assert sorted(tool["parameters"]["required"]) == sorted(tool["parameters"]["properties"])


async def test_an_address_still_works_as_the_app(tmp_path, monkeypatch):
    """An address like waipu://tv in the option: the app counts as in front when the TV reports its package name, so
    it is not started again for every channel (that was the fault of 2.182.0 on his TV)."""
    import asyncio as _a
    _orig = _a.sleep
    monkeypatch.setattr(tv.asyncio, "sleep", lambda s: _orig(0))
    _HA.calls.clear()
    _HA.states["remote.android_tv"] = {"entity_id": "remote.android_tv", "state": "on",
                                       "attributes": {"current_activity": "de.exaring.waipu"}}
    server = _server(19997)
    remote = rf.RfRemote("h", 433.87, str(tmp_path / "c.json"), device_factory=lambda h: FakeDevice("h"))
    ctl = tv.TvController(remote, tv.parse_channels(None), api_url="http://127.0.0.1:19997/api", token="tok",
                          tv_app="waipu://tv")
    try:
        r = await ctl.run({"action": "kanal", "channel": "Euro D", "steps": None, "volume_percent": None})
        assert r["done"] == "Euro D (Programm 3)" and [c[1] for c in _HA.calls] == ["send_command"], (r, _HA.calls)
    finally:
        server.shutdown()
        _HA.states.pop("remote.android_tv", None)
