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
    monkeypatch.setattr(ls, "SETTLE_S", 0.0)
    monkeypatch.setattr(ls, "OFF_AGAIN_S", 0.03)
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
    assert a_on[1]["transition"] == 0 and "transition" not in [c for c in after if c[0] == "turn_off"][0][1]
    await asyncio.sleep(0.08)
    # the show has stopped; the lamp that went off was told so a second time (2.159.2), and only it
    assert len(calls) == n + 4 and calls[-1] == ("turn_off", {"entity_id": ["light.a"]})


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
    assert not ls.is_show_look({"brightness": 190, "color_mode": "hs", "hs_color": [228, 62]})
    # 2.159.0: the looks of a low are show looks too, each at its own strength (default 50 %)
    assert ls.is_show_look({"brightness": 128, "color_mode": "hs", "hs_color": [228, 62]})
    assert ls.is_show_look({"brightness": 128, "color_mode": "hs", "hs_color": [25, 91]})   # orange, listening while low
    assert not ls.is_show_look({"brightness": 128, "color_mode": "color_temp", "hs_color": [25, 91]})
    assert not ls.is_show_look({"brightness": 128, "color_mode": "hs", "hs_color": [25, 91]},
                               levels={**ls.DEFAULT_LEVELS, "sad_listen": 20})


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


async def test_a_low_has_its_own_looks_and_every_look_its_own_strength(monkeypatch, tmp_path):
    """2.159.0 (Metin, 24 Nov 2026): by day lamps at 5 percent could not be told from lamps
    that are off. A low now shows in its own set of looks; colour and strength of all six
    (listen, think, speak, normal and low) are chosen in the app and kept."""
    show, calls = _show(monkeypatch, tmp_path)
    assert show.levels == ls.DEFAULT_LEVELS and show.colors["sad_listen"] == ls.ORANGE
    show._mode = "listen"
    assert show._look() == (ls.CYAN, 100)
    show.set_mood(False)
    assert show._look() == (ls.CYAN, 100)
    show.set_mood(True)
    assert show._look() == (ls.ORANGE, 50)
    show._mode = "think"
    assert show._look() == (ls.VIOLET, 50)
    # chosen in the app: wrong values change nothing, good ones are kept across a restart
    for bad in ({"sad_listen": 0}, {"sad_listen": 101}, {"sad_listen": "50"}, {"other": 50}, {"listen": True}):
        assert not show.set_colors(None, bad)
    assert not show.set_colors({"sad_listen": "#00ff00"}, {"listen": 500}) and show.colors["sad_listen"] == ls.ORANGE
    assert show.set_colors({"sad_think": "#00ff00"}, {"sad_think": 35, "listen": 80, "sad_speak": 20})
    assert show._look() == ((0, 255, 0), 35)
    again = ls.LampShow(["light.a"], token="t", memory_path=show.memory_path)
    assert again.levels == {**ls.DEFAULT_LEVELS, "sad_think": 35, "listen": 80, "sad_speak": 20}
    assert again.colors["sad_think"] == (0, 255, 0) and again.colors["listen"] == ls.CYAN
    assert ls.speak_look(1.0, again.colors, True, again.levels) == (ls.MAGENTA, 20)
    assert again.set_colors(None, {"listen": None}) and again.levels["listen"] == 100
    # a colour file from before 2.159.0 (colours only) still loads
    with open(again.colors_path, "w") as f:
        json.dump({"listen": "#ff0000"}, f)
    old = ls.LampShow(["light.a"], token="t", memory_path=show.memory_path)
    assert old.colors["listen"] == (255, 0, 0) and old.levels == ls.DEFAULT_LEVELS
    # the test button shows a low look and leaves no mood behind
    monkeypatch.setattr(ls, "PREVIEW_S", 0.6)
    show.set_mood(None)
    calls.clear()
    assert await show.preview("sad_listen") == "ok"
    sent = [(c[1]["rgb_color"], c[1]["brightness_pct"]) for c in calls if "rgb_color" in c[1]]
    assert sent and sent[0] == (list(ls.ORANGE), 50) and show.mood_low is None
    assert await show.preview("sad_other") == "bad"
    # a talk forgets the mood at its end
    await show.begin()
    show.set_mood(True)
    await show.end()
    assert show.mood_low is None


async def test_the_app_reads_and_sets_colours_and_strengths(tmp_path):
    from app import memory_web as mw
    show = ls.LampShow(["light.a"], token="t", memory_path=str(tmp_path / "lamps.json"))
    got = await mw._lamp_api(show, "GET", "/api/lamp", b"")
    assert got["levels"] == ls.DEFAULT_LEVELS and set(got["labels"]) == set(got["colors"]) == set(ls.DEFAULT_COLORS)
    body = json.dumps({"levels": {"sad_listen": 35}}).encode()
    assert (await mw._lamp_api(show, "POST", "/api/lamp/colors", body))["ok"] and show.levels["sad_listen"] == 35
    body = json.dumps({"colors": {"sad_listen": "#112233"}, "levels": {"sad_listen": 0}}).encode()
    assert not (await mw._lamp_api(show, "POST", "/api/lamp/colors", body))["ok"]
    assert show.colors["sad_listen"] == ls.ORANGE and show.levels["sad_listen"] == 35
    reset = {"colors": {k: None for k in got["colors"]}, "levels": {k: None for k in got["levels"]}}
    assert (await mw._lamp_api(show, "POST", "/api/lamp/colors", json.dumps(reset).encode()))["ok"]
    assert show.levels == ls.DEFAULT_LEVELS


async def test_lamps_that_were_on_come_back_even_when_they_report_late(monkeypatch, tmp_path):
    """24 Nov 2026, 15:11: the rear lamps were on, Metin tried looks in the app one after the
    other and changed colours and strengths in between; the lamps stayed in a test look (orange,
    15 percent) and "Lampen zurücksetzen" found nothing. Three holes: "on" alone counted as
    restored for a lamp that was on before; a look that was still reported became the state to
    go back to; and after a change in the app the old look was no longer known as one."""
    show, calls = _show(monkeypatch, tmp_path)
    white = dict(show.lamps["light.b"])
    late = {"on": True}   # the lamp keeps reporting the look of the show for a while
    orig = show._service

    async def service(name, data, timeout=None):
        before = {e: dict(v) for e, v in show.lamps.items()}
        await orig(name, data, timeout)
        ents = data["entity_id"] if isinstance(data["entity_id"], list) else [data["entity_id"]]
        for e in ents:
            if name == "turn_on" and "rgb_color" in data:   # report the look that was really sent
                hue, sat = ls._hue(tuple(data["rgb_color"]))
                show.lamps[e].update(brightness=round(data["brightness_pct"] * 2.55), hs_color=[hue, sat])
            elif name == "turn_on" and late["on"] and before[e].get("color_mode") == "hs":
                show.lamps[e] = before[e]                    # the old report still stands
            elif name == "turn_on":
                show.lamps[e] = dict(white)

    monkeypatch.setattr(show, "_service", service)
    monkeypatch.setattr(ls, "RETRY_DELAYS_S", (60.0,))
    monkeypatch.setattr(ls, "PREVIEW_S", 0.6)
    show.set_colors(None, {"sad_listen": 15})
    assert await show.preview("sad_listen") == "ok"
    assert show.lamps["light.b"]["brightness"] == 38       # still orange at 15 percent
    assert "light.b" in show._pending                       # so it is not counted as restored
    assert "light.b" not in show._last_on or show._last_on["light.b"].get("color_mode") == "color_temp"
    # he changes colour and strength in the app: the old look is still known as a leftover
    show.set_colors({"sad_listen": "#00ff00"}, {"sad_listen": 100})
    assert show._leftover(show.lamps["light.b"])
    again = ls.LampShow(["light.a", "light.b"], token="t", memory_path=show.memory_path)
    assert again._leftover(show.lamps["light.b"])           # also after a restart
    # the next test starts from the pending state and brings the white back
    late["on"] = False
    assert await show.preview("listen") == "ok"
    assert show.lamps["light.b"] == white and show._pending == {}
    # nothing pending and still a look of the show: it counts as off, never as normal
    show.lamps["light.b"] = {"state": "on", "brightness": 38, "color_mode": "hs", "hs_color": [24.6, 91.2]}
    await show.begin()
    assert show._before["light.b"] == {"state": "off"}
    await show.end()
    assert show.lamps["light.b"]["state"] == "off"


def test_learned_states_of_an_older_file_are_learned_afresh(tmp_path):
    path = tmp_path / "lamps.json"
    orange = {"state": "on", "brightness": 38, "color_mode": "hs", "hs_color": [21.3, 90.9]}
    path.write_text(json.dumps({"last_on": {"light.a": orange}, "pending": {"light.a": {"state": "off"}}}))
    show = ls.LampShow(["light.a"], token="t", memory_path=str(path))
    assert show._last_on == {} and show._pending == {"light.a": {"state": "off"}}   # white ones stay, see the test above
    show._last_on = {"light.a": {"state": "on", "brightness": 200, "color_mode": "color_temp", "color_temp_kelvin": 2700}}
    show._save_memory()
    assert ls.LampShow(["light.a"], token="t", memory_path=str(path))._last_on["light.a"]["brightness"] == 200


async def test_the_end_of_a_show_never_races_its_own_last_look(monkeypatch, tmp_path):
    """24 Nov 2026, 15:22: after tests from the app Home Assistant reported the rear lamps off
    while they stood on in white. The end of a show cut the look that was on its way (Home
    Assistant still sent it), put the old white on with a fade and switched off 1.2 s later
    with another fade: commands that overtake each other in the lamp. Now the last look is
    finished first, the white comes without a fade, the off is a plain off, and it is said a
    second time, but never into a new show and never to a lamp somebody switched on."""
    show, calls = _show(monkeypatch, tmp_path)
    flying = {"n": 0, "max_while_restoring": 0}
    orig = show._service

    async def service(name, data, timeout=None):
        if "rgb_color" in data:           # a look of the show: slow, like Matter over Thread
            flying["n"] += 1
            await asyncio.sleep(0.05)
            await orig(name, data, timeout)
            flying["n"] -= 1
        else:                             # a command that puts a lamp back
            flying["max_while_restoring"] = max(flying["max_while_restoring"], flying["n"])
            await orig(name, data, timeout)

    monkeypatch.setattr(show, "_service", service)
    await show.begin()
    await asyncio.sleep(0.01)             # the first look is on its way
    await show.end()
    assert flying["max_while_restoring"] == 0
    assert show.lamps["light.a"]["state"] == "off" and show._pending == {}
    # a new show within the wait: no second off into it
    await show.begin()
    n = len([c for c in calls if c[0] == "turn_off"])
    await asyncio.sleep(0.08)
    assert len([c for c in calls if c[0] == "turn_off"]) == n
    await show.end()
    # somebody switches the lamp on right after the show: it stays on
    show.lamps["light.a"] = {"state": "on", "brightness": 200, "color_mode": "color_temp", "color_temp_kelvin": 2700}
    await asyncio.sleep(0.08)
    assert show.lamps["light.a"]["state"] == "on"


async def test_reset_also_tells_lamps_reported_off(monkeypatch, tmp_path):
    show, calls = _show(monkeypatch, tmp_path)
    show._last_on = {}
    assert await show.reset() == "ok"
    # reported off: on in a neutral white (nothing learned yet), then off; a bare off did nothing
    # on 24 Nov 2026 for lamps that stood on while Home Assistant said off
    mine = [c for c in calls if c[1]["entity_id"] == "light.a"]
    assert mine[0][0] == "turn_on" and mine[0][1]["color_temp_kelvin"] == 6000 and mine[0][1]["transition"] == 0
    assert mine[1] == ("turn_off", {"entity_id": "light.a"})
    assert not [c for c in calls if c[1]["entity_id"] == "light.b"]   # on in his white: left alone


async def test_busy_from_the_first_look_until_the_second_off_is_through(monkeypatch, tmp_path):
    """For the planner (2.161.0): a plan for these lamps waits while this is True."""
    show, calls = _show(monkeypatch, tmp_path)
    assert not show.busy
    await show.begin()
    await asyncio.sleep(0.03)
    assert show.busy
    ending = asyncio.create_task(show.end())
    await asyncio.sleep(0)  # the talk is over, the lamps are not back yet
    assert show.busy
    await ending
    assert show.busy          # lamp a went off: its second off is still to come
    await asyncio.sleep(0.08)
    assert not show.busy and calls[-1] == ("turn_off", {"entity_id": ["light.a"]})


async def test_busy_while_a_failed_restore_is_tried_again_and_free_when_it_gave_up(monkeypatch, tmp_path):
    show, _ = _show(monkeypatch, tmp_path, fail=lambda name, data: name == "turn_off")
    await show.begin()
    await asyncio.sleep(0.03)
    await show.end()
    assert show._pending and show.busy   # lamp a could not be switched off: tried again
    await asyncio.sleep(0.3)
    assert show._pending and not show.busy  # given up until the next talk: a plan need not wait


# ---- 2.200.0: what somebody else switches during a show stays afterwards ----
def _reported(monkeypatch, show):
    """Like Home Assistant: every light call, also the show's own, comes back as a report."""
    fake = show._service

    async def service(name, data, timeout=None):
        show._mine(name, data)
        await fake(name, data, timeout)
        show.outside(name, json.loads(json.dumps(data)))

    monkeypatch.setattr(show, "_service", service)


async def _talk(show):
    await show.begin()
    await asyncio.sleep(0.05)
    show.phase("replying")
    show.audio(5000)
    await asyncio.sleep(0.05)


async def test_the_reports_of_the_shows_own_calls_change_nothing(monkeypatch, tmp_path):
    show, calls = _show(monkeypatch, tmp_path)
    _reported(monkeypatch, show)
    await _talk(show)
    await show.end()
    await asyncio.sleep(0.08)
    assert show.lamps["light.a"]["state"] == "off"
    b_on = [c for c in calls if c[0] == "turn_on" and c[1]["entity_id"] == "light.b"][-1]
    assert b_on[1]["color_temp_kelvin"] == 6000 and b_on[1]["brightness"] == 180
    assert not show._pending


async def test_a_lamp_switched_on_by_an_automation_during_the_talk_stays_on(monkeypatch, tmp_path):
    show, calls = _show(monkeypatch, tmp_path)
    _reported(monkeypatch, show)
    await _talk(show)
    show.outside("turn_on", {"entity_id": ["light.a"], "brightness_pct": 50, "color_temp_kelvin": 3000})
    show.audio(0)
    await asyncio.sleep(0.05)
    n = len(calls)
    await show.end()
    await asyncio.sleep(0.08)
    after = calls[n:]
    a = [c for c in after if c[1]["entity_id"] in ("light.a", ["light.a"])]
    assert [c[0] for c in a] == ["turn_on"]                       # put back to the wish, and never switched off
    assert a[0][1]["brightness"] == 128 and a[0][1]["color_temp_kelvin"] == 3000
    b_on = [c for c in after if c[0] == "turn_on" and c[1]["entity_id"] == "light.b"][0]
    assert b_on[1]["color_temp_kelvin"] == 6000 and b_on[1]["brightness"] == 180   # the other lamp as before the talk
    assert show.lamps["light.a"]["state"] == "on" and not show._pending


async def test_a_lamp_switched_off_or_toggled_during_the_talk_stays_that_way(monkeypatch, tmp_path):
    show, calls = _show(monkeypatch, tmp_path)
    _reported(monkeypatch, show)
    await _talk(show)
    show.outside("turn_off", {"entity_id": "light.b"})           # b was white before the talk
    show.outside("toggle", {"entity_id": ["light.a", "light.elsewhere"]})   # a was off before: now wished on
    await show.end()
    await asyncio.sleep(0.08)
    assert show.lamps["light.b"]["state"] == "off"
    assert show.lamps["light.a"]["state"] == "on"
    a_on = [c for c in calls if c[0] == "turn_on" and c[1]["entity_id"] == "light.a"][-1]
    assert a_on[1]["brightness"] == 90 and a_on[1]["color_temp_kelvin"] == 2700    # the way it was last on


async def test_a_look_of_the_show_is_never_taken_for_a_wish_and_nothing_counts_without_a_show(monkeypatch, tmp_path):
    show, calls = _show(monkeypatch, tmp_path)
    show.outside("turn_on", {"entity_id": ["light.a"], "brightness_pct": 50})      # no show: nothing to keep
    assert not show._pending
    _reported(monkeypatch, show)
    await _talk(show)
    look = dict([c for c in calls if c[0] == "turn_on" and "rgb_color" in c[1]][-1][1])
    look["transition"] = 99                                       # the report differs from what was sent
    show.outside("turn_on", look)
    show.outside("turn_on", {"entity_id": ["light.other"], "brightness_pct": 10})  # not a lamp of the show
    await show.end()
    await asyncio.sleep(0.08)
    assert show.lamps["light.a"]["state"] == "off"                # still back to before the talk
    b_on = [c for c in calls if c[0] == "turn_on" and c[1]["entity_id"] == "light.b"][-1]
    assert b_on[1]["color_temp_kelvin"] == 6000 and b_on[1]["brightness"] == 180
