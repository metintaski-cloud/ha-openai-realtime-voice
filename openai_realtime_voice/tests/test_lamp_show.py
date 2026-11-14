import asyncio
import json

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


def _show(monkeypatch, tmp_path, fail=None):
    """A show over two fake lamps: a is off, b is white. `fail(name, data)` makes a call fail."""
    calls = []
    lamps = {"light.a": {"state": "off"},
             "light.b": {"state": "on", "brightness": 180, "color_mode": "color_temp",
                         "color_temp_kelvin": 6000}}
    show = ls.LampShow(["light.a", "light.b"], token="t", memory_path=str(tmp_path / "lamps.json"))
    show._last_on["light.a"] = {"state": "on", "brightness": 90, "color_mode": "color_temp",
                                "color_temp_kelvin": 2700}

    async def service(name, data, timeout=None):
        calls.append((name, data))
        if fail and fail(name, data):
            raise RuntimeError("")  # like an httpx timeout: no message
        ents = data["entity_id"] if isinstance(data["entity_id"], list) else [data["entity_id"]]
        for e in ents:
            lamps[e] = {"state": "on" if name == "turn_on" else "off"}
            if name == "turn_on" and "rgb_color" in data:
                lamps[e].update(brightness=255, color_mode="hs", hs_color=[230.0, 80.0])

    async def read_state(client, entity):
        return dict(lamps[entity])

    monkeypatch.setattr(show, "_service", service)
    monkeypatch.setattr(show, "_read_state", read_state)
    monkeypatch.setattr(ls, "MIN_INTERVAL_S", 0.02)
    monkeypatch.setattr(ls, "AUDIO_LEAD_S", 0.0)
    monkeypatch.setattr(ls, "RESTORE_WAIT_S", 0.01)
    monkeypatch.setattr(ls, "VERIFY_WAIT_S", 0.0)
    monkeypatch.setattr(ls, "LEVEL_TAU_S", 0.0001)
    monkeypatch.setattr(ls, "RETRY_DELAYS_S", (0.05, 0.05))
    show.lamps = lamps
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


async def test_failed_restore_is_kept_and_the_stuck_colour_is_never_learned(monkeypatch, tmp_path):
    # 14 Nov 2026: Lamba 1 did not answer at the end of a talk, stayed blue, and the next talk took
    # the blue for its normal state, so it never went off again.
    broken = {"on": True}
    show, calls = _show(monkeypatch, tmp_path,
                        fail=lambda n, d: broken["on"] and d["entity_id"] == "light.a"
                        and "rgb_color" not in d)
    monkeypatch.setattr(ls, "RETRY_DELAYS_S", (60.0,))  # no background retry in this test
    await show.begin()
    await asyncio.sleep(0.05)
    assert show.lamps["light.a"]["state"] == "on"  # the show lit it
    await show.end()
    assert show.lamps["light.a"]["state"] == "on" and "light.a" in show._pending
    assert "light.b" not in show._pending  # b answered and is back to white
    saved = json.load(open(tmp_path / "lamps.json"))
    assert saved["pending"]["light.a"]["state"] == "off"
    # the next talk starts from the pending state, not from the stuck blue
    broken["on"] = False
    await show.begin()
    assert show._before["light.a"]["state"] == "off"
    assert show._last_on["light.a"]["color_temp_kelvin"] == 2700  # blue was not learned
    await show.end()
    assert show.lamps["light.a"]["state"] == "off" and show._pending == {}
    assert json.load(open(tmp_path / "lamps.json"))["pending"] == {}


async def test_failed_restore_is_tried_again_in_the_background(monkeypatch, tmp_path):
    broken = {"on": True}
    show, calls = _show(monkeypatch, tmp_path,
                        fail=lambda n, d: broken["on"] and n == "turn_off")
    await show.begin()
    await asyncio.sleep(0.03)
    await show.end()
    assert "light.a" in show._pending and show._retry is not None
    broken["on"] = False
    await asyncio.sleep(0.2)
    assert show._pending == {} and show.lamps["light.a"]["state"] == "off" and show._retry is None


async def test_recover_at_start_and_old_file_format(tmp_path, monkeypatch):
    path = tmp_path / "lamps.json"
    # old format: only the last on states; a show colour in it is dropped
    path.write_text(json.dumps({"light.a": {"state": "on", "brightness": 255, "color_mode": "hs",
                                            "hs_color": [228, 62]},
                                "light.b": {"state": "on", "brightness": 153, "color_mode": "color_temp",
                                            "color_temp_kelvin": 6024}}))
    show = ls.LampShow(["light.a", "light.b"], token="t", memory_path=str(path))
    assert "light.a" not in show._last_on and show._last_on["light.b"]["brightness"] == 153
    path.write_text(json.dumps({"last_on": {}, "pending": {"light.a": {"state": "off"}}}))
    show, calls = _show(monkeypatch, tmp_path)
    show.lamps["light.a"] = {"state": "on"}
    await show.recover()
    assert show.lamps["light.a"]["state"] == "off" and show._pending == {}


def test_is_show_look():
    assert ls.is_show_look({"brightness": 255, "color_mode": "hs", "hs_color": [228, 62]})
    assert not ls.is_show_look({"brightness": 153, "color_mode": "color_temp", "hs_color": [27, 19]})
    assert not ls.is_show_look({"brightness": 255, "color_mode": "hs", "hs_color": [30, 80]})  # orange
    assert not ls.is_show_look({"brightness": 120, "color_mode": "hs", "hs_color": [228, 62]})


def test_colours_are_chosen_and_kept(tmp_path):
    show = ls.LampShow(["light.a"], token="t", memory_path=str(tmp_path / "lamps.json"))
    assert show.colors_hex()["listen"] == "#22d3ee"
    assert not show.set_colors({"listen": "rot"}) and not show.set_colors({"other": "#ffffff"})
    assert show.set_colors({"listen": "#ff0000", "speak_high": "#00ff00"})
    again = ls.LampShow(["light.a"], token="t", memory_path=str(tmp_path / "lamps.json"))
    assert again.colors["listen"] == (255, 0, 0) and again.colors["think"] == ls.VIOLET
    assert again.set_colors({"listen": None}) and again.colors["listen"] == ls.CYAN
    # a stuck red listen colour is a show colour now, the default blue is not any more
    show.set_colors({"listen": "#ff0000", "think": "#ff0000", "speak_low": "#ff0000",
                     "speak_high": "#ff0000"})
    assert ls.is_show_look({"brightness": 255, "color_mode": "hs", "hs_color": [2, 100]}, show.colors)
    assert not ls.is_show_look({"brightness": 255, "color_mode": "hs", "hs_color": [228, 62]}, show.colors)


async def test_chosen_colours_are_shown_and_preview_restores(monkeypatch, tmp_path):
    show, calls = _show(monkeypatch, tmp_path)
    monkeypatch.setattr(ls, "PREVIEW_S", 0.6)
    show.set_colors({"think": "#ff8800"})
    assert await show.preview("think") == "ok"
    sent = [c[1]["rgb_color"] for c in calls if "rgb_color" in c[1]]
    assert sent and sent[0] == [255, 136, 0]
    assert show.lamps["light.a"]["state"] == "off" and show._active == 0 and show._pending == {}
    await show.begin()
    assert await show.preview("listen") == "busy"  # never during a conversation
    await show.end()


async def test_reset_switches_off_a_lamp_left_in_a_show_colour(monkeypatch, tmp_path):
    show, calls = _show(monkeypatch, tmp_path)
    show.lamps["light.a"] = {"state": "on", "brightness": 255, "color_mode": "hs", "hs_color": [228, 62]}
    assert await show.reset() == "ok"
    assert show.lamps["light.a"]["state"] == "off" and show.lamps["light.b"]["state"] == "on"


async def test_smoothing_sends_fewer_commands(monkeypatch, tmp_path):
    import random
    async def count(tau):
        show, calls = _show(monkeypatch, tmp_path)
        monkeypatch.setattr(ls, "LEVEL_TAU_S", tau)
        monkeypatch.setattr(ls, "MIN_INTERVAL_S", 0.05)
        await show.begin()
        random.seed(3)
        for _ in range(100):
            show._set_level(ls.level_from_rms(max(0, random.gauss(2500, 1800))))
            await asyncio.sleep(0.004)
        n = len(calls)
        await show.end()
        return n
    assert await count(0.08) < await count(0.0001)
