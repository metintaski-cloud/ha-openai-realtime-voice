import asyncio

from app import lamp_show as ls


def test_looks():
    quiet, qb = ls.speak_look(0.0)
    loud, lb = ls.speak_look(1.0)
    assert quiet == ls.BLUE and loud == ls.MAGENTA and qb == lb == 100  # full strength, the colour breathes
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


def _show(monkeypatch, tmp_path):
    calls = []
    show = ls.LampShow(["light.a", "light.b"], token="t", memory_path=str(tmp_path / "lamps.json"))
    show._last_on["light.a"] = {"state": "on", "brightness": 90, "color_mode": "color_temp",
                                "color_temp_kelvin": 2700}

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
    monkeypatch.setattr(ls, "RESTORE_WAIT_S", 0.01)
    return show, calls


async def test_show_follows_phases_and_restores(monkeypatch, tmp_path):
    show, calls = _show(monkeypatch, tmp_path)
    await show.begin()
    await asyncio.sleep(0.05)
    assert calls[0][0] == "turn_on" and calls[0][1]["rgb_color"] == list(ls.CYAN)  # listening, also from off
    show.phase("thinking")
    await asyncio.sleep(0.05)
    assert calls[-1][1]["rgb_color"] == list(ls.VIOLET)
    show.phase("replying")
    show.audio(5000)
    await asyncio.sleep(0.05)
    assert calls[-1][1]["rgb_color"] == list(ls.MAGENTA) and calls[-1][1]["brightness_pct"] == 100
    show.audio(0)
    await asyncio.sleep(0.05)
    assert calls[-1][1]["rgb_color"] == list(ls.BLUE)
    n = len(calls)
    await show.end()
    names = [c[0] for c in calls[n:]]
    # a was off: its old strength is set first, then it goes off; b is back to its white
    after = calls[n:]
    assert [c[0] for c in after].count("turn_off") == 1 and len(after) == 3
    a_on = [c for c in after if c[0] == "turn_on" and c[1]["entity_id"] == "light.a"][0]
    assert a_on[1]["brightness"] == 90 and a_on[1]["color_temp_kelvin"] == 2700
    assert after.index(a_on) < [i for i, c in enumerate(after) if c[0] == "turn_off"][0]
    b_on = [c for c in after if c[0] == "turn_on" and c[1]["entity_id"] == "light.b"][0]
    assert b_on[1]["color_temp_kelvin"] == 6000 and b_on[1]["brightness"] == 180
    await asyncio.sleep(0.05)
    assert len(calls) == n + 3  # the show has stopped


async def test_speech_ends_back_to_listening(monkeypatch, tmp_path):
    show, calls = _show(monkeypatch, tmp_path)
    monkeypatch.setattr(ls, "SPEECH_HOLD_S", 0.05)
    await show.begin()
    show.audio(4000)
    await asyncio.sleep(0.2)
    assert calls[-1][1]["rgb_color"] == list(ls.CYAN)
    await show.end()


async def test_end_before_begin_finished_leaves_nothing(monkeypatch, tmp_path):
    show, calls = _show(monkeypatch, tmp_path)
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
