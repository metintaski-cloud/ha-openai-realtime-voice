import asyncio

from app import lamp_show as ls


def test_looks():
    quiet, qb = ls.speak_look(0.0)
    loud, lb = ls.speak_look(1.0)
    assert quiet == ls.BLUE and loud == ls.MAGENTA and qb < lb <= ls.SPEAK_MAX_PCT
    assert ls.speak_look(5.0)[1] == ls.SPEAK_MAX_PCT and ls.speak_look(-1)[1] == ls.SPEAK_MIN_PCT
    assert ls.level_from_rms(0) == 0 and ls.level_from_rms(100000) == 1.0


def test_restore_data():
    assert ls.restore_data("light.a", {"state": "off"})[0] == "turn_off"
    svc, d = ls.restore_data("light.a", {"state": "on", "brightness": 200, "color_mode": "color_temp",
                                          "color_temp_kelvin": 6500, "hs_color": [10, 5]})
    assert svc == "turn_on" and d["color_temp_kelvin"] == 6500 and "hs_color" not in d and d["brightness"] == 200
    svc, d = ls.restore_data("light.a", {"state": "on", "color_mode": "hs", "hs_color": [120, 50]})
    assert d["hs_color"] == [120, 50] and "color_temp_kelvin" not in d


def test_from_env(monkeypatch):
    monkeypatch.setenv("SUPERVISOR_TOKEN", "t")
    monkeypatch.setenv("LAMP_SHOW", "null")
    monkeypatch.setenv("LAMP_SHOW_LIGHTS", "null")
    show = ls.from_env()
    assert show.entities == ["light.wohnzimmer_lamba_1", "light.wohnzimmer_lamba_2"]
    monkeypatch.setenv("LAMP_SHOW", "false")
    assert ls.from_env().entities == []


def _show(monkeypatch):
    calls = []
    show = ls.LampShow(["light.a", "light.b"], token="t")

    async def service(name, data):
        calls.append((name, data))

    async def snapshot():
        show._before = {"light.a": {"state": "off"},
                        "light.b": {"state": "on", "brightness": 180, "color_mode": "color_temp",
                                    "color_temp_kelvin": 6000}}

    monkeypatch.setattr(show, "_service", service)
    monkeypatch.setattr(show, "_snapshot", snapshot)
    monkeypatch.setattr(ls, "MIN_INTERVAL_S", 0.02)
    monkeypatch.setattr(ls, "AUDIO_LEAD_S", 0.0)
    return show, calls


async def test_show_follows_phases_and_restores(monkeypatch):
    show, calls = _show(monkeypatch)
    await show.begin()
    await asyncio.sleep(0.05)
    assert calls[0][0] == "turn_on" and calls[0][1]["rgb_color"] == list(ls.CYAN)  # listening, also from off
    show.phase("thinking")
    await asyncio.sleep(0.05)
    assert calls[-1][1]["rgb_color"] == list(ls.VIOLET)
    show.phase("replying")
    show.audio(5000)
    await asyncio.sleep(0.05)
    assert calls[-1][1]["rgb_color"] == list(ls.MAGENTA) and calls[-1][1]["brightness_pct"] == ls.SPEAK_MAX_PCT
    show.audio(0)
    await asyncio.sleep(0.05)
    assert calls[-1][1]["rgb_color"] == list(ls.BLUE)
    n = len(calls)
    await show.end()
    names = [c[0] for c in calls[n:]]
    assert sorted(names) == ["turn_off", "turn_on"]  # a off again, b back to its white
    restored = {c[1]["entity_id"]: c for c in calls[n:]}
    assert restored["light.a"][0] == "turn_off"
    assert restored["light.b"][1]["color_temp_kelvin"] == 6000 and restored["light.b"][1]["brightness"] == 180
    await asyncio.sleep(0.05)
    assert len(calls) == n + 2  # the show has stopped


async def test_speech_ends_back_to_listening(monkeypatch):
    show, calls = _show(monkeypatch)
    monkeypatch.setattr(ls, "SPEECH_HOLD_S", 0.05)
    await show.begin()
    show.audio(4000)
    await asyncio.sleep(0.2)
    assert calls[-1][1]["rgb_color"] == list(ls.CYAN)
    await show.end()


async def test_end_before_begin_finished_leaves_nothing(monkeypatch):
    show, calls = _show(monkeypatch)
    async def slow_snapshot():
        await asyncio.sleep(0.05)
        show._before = {}

    monkeypatch.setattr(show, "_snapshot", slow_snapshot)
    started = asyncio.create_task(show.begin())
    await asyncio.sleep(0.01)  # begin is waiting for the lamps when the conversation ends
    await show.end()
    await started
    await asyncio.sleep(0.05)
    assert show._worker is None and not any(c[0] == "turn_on" for c in calls)


async def test_unavailable_does_nothing():
    show = ls.LampShow([], token="t")
    await show.begin()
    show.phase("replying")
    show.audio(3000)
    await show.end()
    assert show._worker is None
