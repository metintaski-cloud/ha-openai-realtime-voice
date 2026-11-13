"""The 23:30 night check follows the options in the automation event."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import night, technik  # noqa: E402
from tests.test_smooth_audio import _bridge  # noqa: E402
import app.main as m  # noqa: E402


def test_parse_defaults_and_values():
    o = night.parse({"device": "nacht"})
    assert (o.lamps, o.fan, o.fan_light, o.ask, o.wait_s) == (None, True, True, True, None)
    o = night.parse({"lampen": [2, 1, 2, "x", True], "ventilator": False, "fragen": False,
                     "warten": 120})
    assert (o.lamps, o.fan, o.fan_light, o.ask, o.wait_s) == ([1, 2], False, True, False, 120.0)
    assert night.parse({"lampen": []}).lamps == []
    assert night.parse({"warten": 9999}).wait_s is None
    assert night.parse({"lampen": [], "ventilator": False, "ventilatorlicht": False}).nothing


def test_things_and_wait_texts():
    assert night.things(night.NightOptions()) == (
        "die Lampen, den Ventilator und das Ventilatorlicht",
        "Lambaları, vantilatörü ve vantilatör ışığını")
    o = night.NightOptions(lamps=[1, 2], fan=False, fan_light=False)
    assert night.things(o) == ("Lampe 1 und 2", "1 ve 2 numaralı lambaları")
    assert night.wait_phrase(70) == ("in einer Minute", "bir dakika sonra")
    assert night.wait_phrase(180) == ("in 3 Minuten", "3 dakika sonra")


async def _run_night(monkeypatch, data):
    monkeypatch.setattr(night, "NIGHT_WAIT_S", 0.05)
    bridge = _bridge()
    seen = {"prompt": None, "lamp_calls": [], "fan_calls": []}

    async def converse(prompt):
        seen["prompt"] = prompt
        return True

    async def power():
        return 30.0  # fan 6 plus light

    async def lamp_run(args):
        seen["lamp_calls"].append(args["lamps"])
        return {}

    async def fan_run(args):
        seen["fan_calls"].append(args["action"])
        return {}

    async def states(client, ids):
        return [{"entity_id": i, "state": "on"} for i in ids]

    monkeypatch.setattr(bridge, "_converse", converse)
    monkeypatch.setattr(bridge.fan, "power", power)
    monkeypatch.setattr(bridge.fan, "describe", lambda w: {"ventilator": "an", "licht": "an"})
    monkeypatch.setattr(bridge.fan, "run", fan_run)
    monkeypatch.setattr(bridge.lights, "run", lambda a: lamp_run(a))
    monkeypatch.setattr(bridge.lights, "_states", states)
    monkeypatch.setattr(bridge.lights, "token", "t")
    bridge.lights.entities = ["light.a", "light.b", "light.c", "light.d"]
    bridge._night_opts = night.parse(data)
    monkeypatch.setattr(m.asyncio, "sleep", lambda s: _noop())
    await bridge._night_check()
    return seen


async def _noop():
    return None


async def test_default_switches_everything_off_and_asks(monkeypatch):
    seen = await _run_night(monkeypatch, {"device": "nacht"})
    assert "die Lampen, den Ventilator und das Ventilatorlicht" in seen["prompt"]
    assert seen["lamp_calls"] == [[1, 2, 3, 4]] and seen["fan_calls"] == ["aus", "licht_aus"]


async def test_options_limit_what_is_switched_off(monkeypatch):
    seen = await _run_night(monkeypatch, {"lampen": [3], "ventilator": False,
                                          "ventilatorlicht": False, "warten": 180})
    assert "Lampe 3" in seen["prompt"] and "in 3 Minuten" in seen["prompt"]
    assert "Ventilator" not in seen["prompt"].split("ausschalten sollst")[0]
    assert seen["lamp_calls"] == [[3]] and seen["fan_calls"] == []


async def test_without_asking_switches_off_directly(monkeypatch):
    seen = await _run_night(monkeypatch, {"fragen": False, "ventilator": False})
    assert seen["prompt"] is None
    assert seen["lamp_calls"] == [[1, 2, 3, 4]] and seen["fan_calls"] == ["licht_aus"]


async def test_nothing_selected_does_nothing(monkeypatch):
    seen = await _run_night(monkeypatch, {"lampen": [], "ventilator": False,
                                          "ventilatorlicht": False})
    assert seen["prompt"] is None and seen["lamp_calls"] == [] and seen["fan_calls"] == []


# ---- changing the options through technik ------------------------------------------------
def _night_cfg():
    return {"alias": "Leyla 23:30 Uhr: alles aus?", "triggers": [{"trigger": "time",
                                                                  "at": "23:30:00"}],
            "actions": [{"event": "leyla_command", "event_data": {"device": "nacht"}}]}


def _writer(monkeypatch):
    import httpx
    from tests.test_technik import Writer, _client
    posted = []
    monkeypatch.setattr(httpx, "AsyncClient", _client(posted))

    class W(Writer):
        async def _get(self, client, path):
            if path == "states":
                return [{"entity_id": "automation.nacht", "state": "on",
                         "attributes": {"friendly_name": "Leyla 23:30 Uhr: alles aus?",
                                        "id": "n1"}}]
            if path == "config/automation/config/n1":
                return _night_cfg()
            return None
    w = W()
    w.lamp_count = 4
    return w, posted


def _args(**kw):
    base = {"action": "nacht_aendern", "suche": "alles aus", "nacht_lampen": None,
            "nacht_ventilator": None, "nacht_ventilatorlicht": None, "nacht_fragen": None,
            "nacht_warten": None}
    return {**base, **kw}


async def test_change_night_writes_options_and_defaults_as_no_key(monkeypatch):
    w, posted = _writer(monkeypatch)
    r = await w.run(_args(nacht_lampen=[2, 1], nacht_ventilator=False, nacht_warten=120))
    data = posted[0][1]["actions"][0]["event_data"]
    assert data == {"device": "nacht", "lampen": [1, 2], "ventilator": False, "warten": 120}
    assert r["jetzt"]["lampen"] == [1, 2] and r["jetzt"]["ventilator"] is False
    assert w.pushed
    r = await w.run(_args(nacht_lampen=[1, 2, 3, 4], nacht_ventilator=True))
    assert posted[1][1]["actions"][0]["event_data"] == {"device": "nacht"}


async def test_change_night_rejects_bad_input(monkeypatch):
    w, posted = _writer(monkeypatch)
    assert "error" in await w.run(_args(nacht_lampen=[5]))
    assert "error" in await w.run(_args(nacht_warten=9999))
    assert "error" in await w.run(_args())
    assert "error" in await w.run(_args(suche="Rolladen", nacht_fragen=False))
    assert posted == []
