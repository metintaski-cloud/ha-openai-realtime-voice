"""The planner: a plan is checked when it is made, runs once at its time and never twice.
Invented neutral examples only."""
import asyncio
import json
from datetime import datetime

import pytest

from app import fan, lights, planer, purifier
from app.agenda import _tz


def ts(text: str) -> float:
    """'2026-11-24 22:00' in the home time zone as seconds."""
    return datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=_tz()).timestamp()


class Clock:
    def __init__(self, text: str):
        self.now = ts(text)

    def __call__(self) -> float:
        return self.now

    def set(self, text: str):
        self.now = ts(text)


class Home:
    """Stands in for the bridge: records every step that really runs."""

    def __init__(self):
        self.calls, self.said, self.pushed = [], [], []
        self.fail = {}  # tool name -> result or exception

    def schemas(self):
        return {lights.LIGHTS_TOOL["name"]: lights.LIGHTS_TOOL["parameters"],
                fan.FAN_TOOL["name"]: fan.FAN_TOOL["parameters"],
                purifier.PURIFIER_TOOL["name"]: purifier.PURIFIER_TOOL["parameters"]}

    async def run(self, name, args):
        self.calls.append((name, args))
        bad = self.fail.get(name)
        if isinstance(bad, Exception):
            raise bad
        return bad or {"done": "ok"}

    async def say(self, text):
        self.said.append(text)

    async def notify(self, title, message):
        self.pushed.append(message)

    def check(self, name, args):
        if name == "licht_steuern" and any(n > 4 for n in args.get("lamps") or []):
            return "Es gibt nur Stehlampe 1 bis 4."


def make(tmp_path, start="2026-11-24 22:00"):
    home, clock = Home(), Clock(start)
    p = planer.Planner(schemas=home.schemas, run=home.run, say=home.say, notify=home.notify,
                       check=home.check, path=str(tmp_path / "planer.json"), clock=clock)
    return p, home, clock


def lamp(action="off", lamps=(1, 2), **more):
    return {"geraet": "licht_steuern",
            "argumente": json.dumps({"lamps": list(lamps), "action": action, **more})}


def plan(**over):
    base = {"aktion": "anlegen", "titel": None, "datum": None, "uhrzeit": "23:00",
            "in_minuten": None, "wiederholung": None, "tage": None, "schritte": [lamp()],
            "nummer": None}
    return dict(base, **over)


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


# ---- making a plan ----
def test_a_plan_says_when_and_what_and_switches_nothing_now(tmp_path):
    p, home, _ = make(tmp_path)
    r = p.add(plan(titel="Licht aus am Abend"))
    assert r["ok"] and r["wann"] == "heute 23:00" and r["was"] == "Stehlampe 1 und 2 aus"
    assert home.calls == []
    assert p.stats()["offen"] == 1 and p.stats()["in_s"] == 3600


def test_a_time_that_has_passed_today_means_tomorrow(tmp_path):
    p, _, _ = make(tmp_path)
    assert p.add(plan(uhrzeit="07:00"))["wann"] == "morgen 07:00"


def test_today_with_a_passed_time_is_refused_not_moved(tmp_path):
    p, _, _ = make(tmp_path)
    r = p.add(plan(datum="heute", uhrzeit="21:00"))
    assert "Vergangenheit" in r["error"] and p.plans == []


def test_weekday_today_with_time_ahead_is_today(tmp_path):
    p, _, _ = make(tmp_path)  # 24 Nov 2026 is a Tuesday
    assert p.add(plan(datum="Dienstag", uhrzeit="23:30"))["wann"] == "heute 23:30"
    assert p.add(plan(datum="dienstag", uhrzeit="08:00"))["wann"] == "Di 1.12. 08:00"
    assert p.add(plan(datum="2026-11-27", uhrzeit="08:00"))["wann"] == "Fr 27.11. 08:00"


def test_in_minutes(tmp_path):
    p, _, _ = make(tmp_path)
    assert p.add(plan(uhrzeit=None, in_minuten=20))["wann"] == "heute 22:20"
    assert "nicht beides" in p.add(plan(in_minuten=20))["error"]
    assert "error" in p.add(plan(uhrzeit=None, in_minuten=0))
    assert "error" in p.add(plan(uhrzeit=None, in_minuten=20, wiederholung="taeglich"))


def test_no_time_is_refused(tmp_path):
    p, _, _ = make(tmp_path)
    assert "Uhrzeit" in p.add(plan(uhrzeit=None))["error"]
    assert "Uhrzeit" in p.add(plan(uhrzeit="25:00"))["error"]
    assert "verstehe ich nicht" in p.add(plan(datum="irgendwann"))["error"]


@pytest.mark.parametrize("steps, word", [
    (None, "mindestens einen Schritt"),
    ([], "mindestens einen Schritt"),
    ([lamp()] * 7, "höchstens"),
    ([{"geraet": "kalender", "argumente": "{}"}], "kann ich nicht planen"),
    ([{"geraet": "licht_steuern", "argumente": "{nicht json"}], "kein gültiges JSON"),
    ([{"geraet": "licht_steuern", "argumente": "[1]"}], "JSON Objekt"),
    ([{"geraet": "licht_steuern", "argumente": json.dumps({"lamps": [1]})}], "Es fehlt: action"),
    ([lamp(action="aus")], "gibt es nicht"),
    ([lamp(lamps=["1"])], "integer"),
    ([lamp(helligkeit=50)], "Unbekannte Angabe"),
    ([lamp(color="grau")], "gibt es nicht"),
    ([lamp(brightness_percent="50")], "falsche Art"),
    ([lamp(action="status")], "liest nur"),
    ([lamp(lamps=(1, 9))], "nur Stehlampe 1 bis 4"),
    ([{"geraet": "ansage", "argumente": json.dumps({"text": "  "})}], "braucht einen Text"),
    ([{"geraet": "ansage", "argumente": json.dumps({"text": "a" * 301})}], "zu lang"),
])
def test_a_wrong_step_is_refused_when_the_plan_is_made(tmp_path, steps, word):
    p, _, _ = make(tmp_path)
    r = p.add(plan(schritte=steps))
    assert word in r["error"] and p.plans == []


def test_missing_optional_values_become_none_as_the_tool_expects(tmp_path):
    p, _, _ = make(tmp_path)
    p.add(plan())
    assert p.plans[0]["schritte"][0]["argumente"] == {
        "lamps": [1, 2], "action": "off", "brightness_percent": None, "white": None, "color": None}


def test_the_same_plan_twice_counts_once(tmp_path):
    p, _, _ = make(tmp_path)
    assert "schon_geplant" not in p.add(plan())
    assert p.add(plan())["schon_geplant"] is True
    assert len(p.plans) == 1
    p.add(plan(uhrzeit="23:30"))
    assert len(p.plans) == 2


def test_no_announcements_without_a_speaker(tmp_path):
    home = Home()
    p = planer.Planner(schemas=home.schemas, run=home.run, path=str(tmp_path / "p.json"))
    assert "ansage" not in p.devices
    assert "kann ich nicht planen" in p.add(plan(
        schritte=[{"geraet": "ansage", "argumente": '{"text": "Die Wäsche ist fertig"}'}]))["error"]
    assert "ansage" not in p.tool()["parameters"]["properties"]["schritte"]["items"][
        "properties"]["geraet"]["enum"]


def test_limit_of_open_plans(tmp_path):
    p, _, _ = make(tmp_path)
    for i in range(planer.MAX_PLANS):
        assert p.add(plan(uhrzeit=None, in_minuten=10 + 3 * i))["ok"]
    assert "lösch zuerst" in p.add(plan(uhrzeit=None, in_minuten=5000))["error"]


# ---- running ----
def test_runs_at_its_time_once_and_in_order(tmp_path):
    p, home, clock = make(tmp_path)
    p.add(plan(schritte=[lamp(), {"geraet": "ventilator_steuern",
                                 "argumente": '{"action": "licht_aus"}'},
                         {"geraet": "ansage", "argumente": '{"text": "Gute Nacht"}'}]))
    clock.set("2026-11-24 22:59")
    assert run(p.tick()) == 0 and home.calls == []
    clock.set("2026-11-24 23:00")
    assert run(p.tick()) == 1
    assert [c[0] for c in home.calls] == ["licht_steuern", "ventilator_steuern"]
    assert home.calls[1][1] == {"action": "licht_aus", "speed": None, "hours": None}
    assert home.said == ["Gute Nacht"] and home.pushed == []
    clock.set("2026-11-24 23:01")
    assert run(p.tick()) == 0 and len(home.calls) == 2  # never twice
    assert p.stats()["erledigt"] == 1 and p.stats()["offen"] == 0
    assert p.listing()["zuletzt"][0]["letztes_mal"] == "24.11. 23:00 erledigt"


def test_a_failed_step_does_not_stop_the_rest_and_metin_is_told(tmp_path):
    p, home, clock = make(tmp_path)
    home.fail["licht_steuern"] = {"error": "Die Lampen sind nicht erreichbar."}
    p.add(plan(titel="Abend", schritte=[lamp(), {"geraet": "ventilator_steuern",
                                                "argumente": '{"action": "aus"}'}]))
    clock.set("2026-11-24 23:00")
    run(p.tick())
    assert [c[0] for c in home.calls] == ["licht_steuern", "ventilator_steuern"]
    assert p.stats()["fehler"] == 1
    assert len(home.pushed) == 1 and "nicht ganz geklappt" in home.pushed[0] and "Abend" in home.pushed[0]
    assert "nicht erreichbar" in p.listing()["zuletzt"][0]["probleme"][0]


def test_an_exception_and_a_timeout_count_as_failed(tmp_path):
    p, home, clock = make(tmp_path)
    home.fail["licht_steuern"] = asyncio.TimeoutError()
    home.fail["ventilator_steuern"] = RuntimeError("boom")
    p.add(plan(schritte=[lamp(), {"geraet": "ventilator_steuern", "argumente": '{"action": "aus"}'}]))
    clock.set("2026-11-24 23:00")
    run(p.tick())
    last = p.listing()["zuletzt"][0]
    assert "zu lange" in last["probleme"][0] and "ging nicht" in last["probleme"][1]


def test_fan_light_the_meter_did_not_confirm_is_a_problem(tmp_path):
    assert planer.problems({"pressed": True, "done": False}) != []
    assert planer.problems({"done": "Licht aus"}) == []
    assert planer.problems({"lamps": [], "unavailable": [3]}) == ["Nicht erreichbar: 3"]
    assert planer.problems({"ok": False, "probleme": ["x"]}) == ["x"]


def test_too_late_is_missed_not_run(tmp_path):
    p, home, clock = make(tmp_path)
    p.add(plan(titel="Abend"))
    clock.set("2026-11-24 23:31")  # more than half an hour late: the add on was down
    assert run(p.tick()) == 0 and home.calls == []
    assert p.stats()["verpasst"] == 1 and "nicht nachgeholt" in home.pushed[0]
    assert "verpasst" in p.listing()["zuletzt"][0]["letztes_mal"]


def test_a_little_late_still_runs(tmp_path):
    p, home, clock = make(tmp_path)
    p.add(plan())
    clock.set("2026-11-24 23:29")
    assert run(p.tick()) == 1 and len(home.calls) == 1


def test_daily_plan_moves_to_the_next_day_before_it_runs(tmp_path):
    p, home, clock = make(tmp_path)
    r = p.add(plan(uhrzeit="07:00", wiederholung="taeglich"))
    assert r["wann"] == "täglich 07:00, das nächste Mal morgen 07:00"
    seen = []

    async def spy(name, args):
        seen.append(p.plans[0]["faellig"])  # what is on record while the step runs
        return {"done": "ok"}
    p._run = spy
    clock.set("2026-11-25 07:00")
    assert run(p.tick()) == 1
    assert seen == [ts("2026-11-26 07:00")]
    assert run(p.tick()) == 0
    clock.set("2026-11-26 07:00")
    assert run(p.tick()) == 1 and p.stats()["offen"] == 1 and p.stats()["wiederholt"] == 1


def test_daily_plan_missed_for_days_runs_once_at_the_next_time_only(tmp_path):
    p, home, clock = make(tmp_path)
    p.add(plan(uhrzeit="07:00", wiederholung="taeglich"))
    clock.set("2026-11-28 12:00")  # three mornings missed
    assert run(p.tick()) == 0 and home.calls == [] and len(home.pushed) == 1
    assert p.plans[0]["faellig"] == ts("2026-11-29 07:00")
    clock.set("2026-11-29 07:00")
    assert run(p.tick()) == 1 and len(home.calls) == 1


def test_weekly_plan_only_on_its_days(tmp_path):
    p, home, clock = make(tmp_path)  # Tuesday 22:00
    r = p.add(plan(uhrzeit="06:30", wiederholung="woechentlich", tage=["mo", "fr"]))
    assert r["wann"] == "jede Woche Mo, Fr 06:30, das nächste Mal Fr 27.11. 06:30"
    clock.set("2026-11-27 06:30")
    assert run(p.tick()) == 1
    assert p.plans[0]["faellig"] == ts("2026-11-30 06:30")  # Monday
    assert "Wochentage" in p.add(plan(wiederholung="woechentlich"))["error"]
    assert "tage sind" in p.add(plan(wiederholung="woechentlich", tage=["montag"]))["error"]


def test_weekly_from_a_date_takes_its_weekday(tmp_path):
    p, _, _ = make(tmp_path)
    r = p.add(plan(uhrzeit="09:00", wiederholung="woechentlich", datum="2026-11-28"))
    assert r["wann"].startswith("jede Woche Sa 09:00") and r["wann"].endswith("Sa 28.11. 09:00")


def test_summer_time_keeps_the_clock_time(tmp_path):
    p, _, clock = make(tmp_path, "2027-03-27 12:00")  # the clocks change on 28 Mar 2027
    p.add(plan(uhrzeit="07:00", wiederholung="taeglich"))
    clock.set("2027-03-28 07:00")
    run(p.tick())
    assert p.plans[0]["faellig"] == ts("2027-03-29 07:00")
    assert ts("2027-03-29 07:00") - ts("2027-03-28 07:00") == 24 * 3600
    assert ts("2027-03-28 07:00") - ts("2027-03-27 07:00") == 23 * 3600


# ---- restart ----
def test_plans_survive_a_restart(tmp_path):
    p, home, clock = make(tmp_path)
    p.add(plan())
    again = planer.Planner(schemas=home.schemas, run=home.run, path=p.path, clock=clock)
    assert again.stats()["offen"] == 1
    clock.set("2026-11-24 23:00")
    assert run(again.tick()) == 1 and len(home.calls) == 1


def test_a_restart_in_the_middle_never_runs_the_plan_again(tmp_path):
    p, home, clock = make(tmp_path)
    p.add(plan(titel="Abend"))
    clock.set("2026-11-24 23:00")
    p._claim(p.plans[0], clock())  # as tick does before the first step ...
    p._save()                      # ... and then the add on stops
    again = planer.Planner(schemas=home.schemas, run=home.run, notify=home.notify,
                           path=p.path, clock=clock)
    assert run(again.tick()) == 0 and home.calls == []
    assert again.stats()["fehler"] == 1 and "Neustart" in home.pushed[0]


def test_a_broken_file_is_an_empty_planner(tmp_path):
    path = tmp_path / "planer.json"
    path.write_text("{kaputt")
    assert planer.Planner(path=str(path)).plans == []
    path.write_text(json.dumps([{"id": "x"}, "y", {"id": "z", "schritte": [1], "faellig": "bald"}]))
    assert planer.Planner(path=str(path)).plans == []


def test_finished_plans_leave_the_list_after_two_days(tmp_path):
    p, _, clock = make(tmp_path)
    p.add(plan())
    clock.set("2026-11-24 23:00")
    run(p.tick())
    clock.set("2026-11-26 22:59")
    p._save()
    assert len(p.plans) == 1
    clock.set("2026-11-26 23:01")
    p._save()
    assert p.plans == []


# ---- listing and deleting ----
def test_listing_is_numbered_by_time(tmp_path):
    p, _, _ = make(tmp_path)
    p.add(plan(titel="spät", uhrzeit="23:30"))
    p.add(plan(titel="früh", uhrzeit="22:30"))
    out = run(p.run_tool({"aktion": "anzeigen"}))
    assert [(x["nummer"], x["titel"]) for x in out["geplant"]] == [(1, "früh"), (2, "spät")]
    assert run(planer.Planner(path=str(tmp_path / "leer.json")).run_tool({}))["hinweis"]


def test_delete_by_the_number_of_the_last_list(tmp_path):
    p, home, clock = make(tmp_path)
    p.add(plan(titel="spät", uhrzeit="23:30"))
    p.add(plan(titel="früh", uhrzeit="22:30"))
    assert "letzten Liste nicht" in p.remove({"nummer": 1})["error"]  # nothing was listed yet
    p.add(plan(titel="Nacht", uhrzeit="23:45"))
    p.listing()  # 1 früh, 2 spät, 3 Nacht
    assert p.remove({"nummer": 2})["geloescht"] == "spät"
    assert "schon weg" in p.remove({"nummer": 2})["error"]
    assert p.remove({"nummer": 3})["geloescht"] == "Nacht"  # numbers mean what she read out
    assert "error" in p.remove({"nummer": 4}) and "error" in p.remove({"nummer": 0})
    clock.set("2026-11-24 22:30")
    assert run(p.tick()) == 1 and len(home.calls) == 1
    clock.set("2026-11-24 23:59")
    assert run(p.tick()) == 0 and len(home.calls) == 1  # the deleted ones never run


def test_delete_by_a_word_only_when_it_is_clear(tmp_path):
    p, _, _ = make(tmp_path)
    p.add(plan(titel="Licht aus am Abend"))
    p.add(plan(titel="Licht an am Morgen", uhrzeit="07:00", schritte=[lamp("on")]))
    r = p.remove({"titel": "Licht"})
    assert "mehrere" in r["error"] and len(r["geplant"]) == 2 and len(p.plans) == 2
    assert p.remove({"nummer": 1})["geloescht"] == "Licht aus am Abend"
    assert p.remove({"titel": "morgen"})["ok"] and p.plans == []
    assert "keinen Plan" in p.remove({"titel": "Licht"})["error"]
    assert "Welchen Plan" in p.remove({})["error"]


# ---- words ----
@pytest.mark.parametrize("step, text", [
    ({"geraet": "licht_steuern", "argumente": {"lamps": [], "action": "on", "brightness_percent": 40,
                                               "white": "warm", "color": None}},
     "alle Stehlampen an 40 % warm"),
    ({"geraet": "ventilator_steuern", "argumente": {"action": "stufe", "speed": 3}}, "Ventilator Stufe 3"),
    ({"geraet": "luftreiniger", "argumente": {"action": "modus", "modus": "schlaf"}},
     "Luftreiniger Modus schlaf"),
    ({"geraet": "saugroboter", "argumente": {"action": "raeume", "rooms": ["Küche"],
                                             "modus": "saugen_und_wischen", "staerke": None}},
     "Saugroboter: Küche (saugen und wischen)"),
    ({"geraet": "fernseher_steuern", "argumente": {"action": "aus"}}, "Fernseher aus"),
    ({"geraet": "fester_befehl", "argumente": {"name": "lichter aus"}}, "fester Befehl „lichter aus“"),
    ({"geraet": "ansage", "argumente": {"text": "Der Tee ist fertig"}}, "Ansage: „Der Tee ist fertig“"),
])
def test_steps_in_words(step, text):
    assert planer.describe_step(step) == text


def test_the_tool_lists_only_what_this_home_has(tmp_path):
    p, _, _ = make(tmp_path)
    tool = p.tool()
    assert tool["name"] == "planer"
    assert tool["parameters"]["properties"]["schritte"]["items"]["properties"]["geraet"]["enum"] == [
        "licht_steuern", "ventilator_steuern", "luftreiniger", "ansage"]
    assert set(tool["parameters"]["required"]) == set(tool["parameters"]["properties"])


def test_nothing_of_a_plan_is_logged_but_its_devices(tmp_path, caplog):
    p, _, clock = make(tmp_path)
    with caplog.at_level("INFO"):
        p.add(plan(titel="Geheimer Titel", schritte=[
            {"geraet": "ansage", "argumente": '{"text": "Geheimer Satz"}'}]))
        clock.set("2026-11-24 23:00")
        run(p.tick())
        p.listing()
    assert "Geheim" not in caplog.text and "ansage" in caplog.text


def test_wait_is_short_before_a_plan_and_never_long(tmp_path):
    p, _, clock = make(tmp_path)
    assert p.wait_s() == planer.POLL_S
    p.add(plan(uhrzeit=None, in_minuten=1))
    clock.now += 58
    assert 1.9 < p.wait_s() < 2.1
    clock.now += 10
    assert p.wait_s() == 0.2


# ---- in the bridge: the tool, its gate and the real runners ----
@pytest.fixture
def bridge(tmp_path, monkeypatch):
    for k, v in {"ENABLE_MEMORY": "false", "ENABLE_CONTEXT": "false", "GREETING_WORDS": "",
                 "MEMORY_PATH": str(tmp_path / "memory.json"), "CODE_PHRASE": "sesam",
                 "ENABLE_WEB_SEARCH": "false", "RECORD_FALSE_WAKES": "false",
                 "WARM_CONNECTION": "false", "OPENAI_API_KEY": "test"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    from app import main as m
    b = m.LiveVoiceBridge()

    class Lamps:
        available = True
        entities = ["light.a", "light.b", "light.c"]
    b.lights = Lamps()
    b.switched = []

    async def lamps_run(args):
        b.switched.append(args)
        return {"lamps": []}
    b._tools["licht_steuern"]["run"] = lamps_run
    b.planer.clock = Clock("2026-11-24 22:00")
    return b


async def tool(bridge, args, state):
    spec = bridge._tools["planer"]
    blocked = spec["gate"](args, state)
    return blocked if blocked is not None else await spec["run"](args)


async def test_only_metin_plans_and_deletes_but_anyone_may_hear_the_plans(bridge):
    for state in ({}, {"identified": {"Ayse"}}):
        r = await tool(bridge, plan(), state)
        assert "Nicht erlaubt" in r["error"] and bridge.planer.plans == []
        assert "Nicht erlaubt" in (await tool(bridge, {"aktion": "loeschen", "nummer": 1}, state))["error"]
        assert (await tool(bridge, {"aktion": "anzeigen"}, state))["ok"]
    assert (await tool(bridge, plan(), {"metin_known": True}))["ok"]
    assert (await tool(bridge, plan(uhrzeit="23:30"), {"unlocked": True}))["ok"]
    assert len(bridge.planer.plans) == 2


async def test_a_plan_runs_through_the_same_function_as_a_spoken_request(bridge):
    r = await tool(bridge, plan(schritte=[lamp("on", lamps=(3,), brightness_percent=40)]),
                   {"unlocked": True})
    assert r["wann"] == "heute 23:00" and r["was"] == "Stehlampe 3 an 40 %"
    assert bridge.switched == []
    bridge.planer.clock.set("2026-11-24 23:00")
    assert await bridge.planer.tick() == 1
    assert bridge.switched == [{"lamps": [3], "action": "on", "brightness_percent": 40,
                                "white": None, "color": None}]


async def test_the_bridge_knows_its_lamps_and_fixed_commands(bridge):
    r = await tool(bridge, plan(schritte=[lamp(lamps=(4,))]), {"unlocked": True})
    assert "nur Stehlampe 1 bis 3" in r["error"]
    r = await tool(bridge, plan(schritte=[{"geraet": "fester_befehl",
                                          "argumente": '{"name": "gibt es nicht"}'}]),
                   {"unlocked": True})
    assert "Diesen festen Befehl gibt es nicht" in r["error"]


async def test_a_plan_never_reaches_a_tool_that_is_only_for_metin(bridge):
    assert "kalender" not in bridge.planer.devices and "technik_pruefen" not in bridge.planer.devices
    with pytest.raises(RuntimeError):
        await bridge._plan_step("gedaechtnis_aufraeumen", {})
    with pytest.raises(RuntimeError):
        await bridge._plan_step("planer", plan())  # a plan cannot make plans
    for name in bridge.planer.devices:
        assert name == "ansage" or not bridge._tools[name].get("gate"), name


async def test_she_is_offered_the_planner_only_with_something_to_switch(bridge):
    names = [t["name"] for ok, t, *_ in bridge._capabilities() if ok and t and t.get("name")]
    assert "planer" in names
    start = bridge._session_start()
    assert "PLANNER" in json.dumps(start)
    bridge.lights.available = False
    if not bridge.planer.devices:
        assert "planer" not in [t["name"] for ok, t, *_ in bridge._capabilities()
                                if ok and t and t.get("name")]


async def test_an_announcement_goes_into_the_running_talk_or_over_the_speaker(bridge):
    said, talked = [], []

    async def say(text):
        said.append(text)

    async def converse(prompt):
        talked.append(prompt)
        return True
    bridge.messages.say, bridge._converse = say, converse
    await bridge._plan_say("Der Tee ist fertig")
    assert said == ["Der Tee ist fertig"] and talked == []
    bridge._live_sessions["x"] = (object(), {})
    await bridge._plan_say("Der Tee ist fertig")
    assert len(said) == 1 and "Der Tee ist fertig" in talked[0]
    bridge._live_sessions["x"] = (object(), {"closing": True})
    await bridge._plan_say("Der Tee ist fertig")
    assert len(said) == 2


# ---- every tool a plan may use must have a schema that holds together ----
def test_tool_schemas_name_every_required_argument_as_a_property():
    """Found while building the planner: the TV tool listed volume_percent as required but
    had it outside of its properties, so an exact volume could not be asked for."""
    from app import befehle, tv, vacuum
    for t in (lights.LIGHTS_TOOL, fan.FAN_TOOL, purifier.PURIFIER_TOOL, vacuum.VACUUM_TOOL,
              befehle.RUN_TOOL, tv.build_tool({"eins": 1}), planer.build_tool(["licht_steuern"])):
        params = t["parameters"]
        assert set(params) <= {"type", "properties", "required", "additionalProperties"}, t["name"]
        assert set(params["required"]) == set(params["properties"]), t["name"]


def test_tv_volume_can_be_planned(tmp_path):
    from app import tv
    home, clock = Home(), Clock("2026-11-24 22:00")
    schema = tv.build_tool({"eins": 1})["parameters"]
    p = planer.Planner(schemas=lambda: {"fernseher_steuern": schema}, run=home.run,
                       path=str(tmp_path / "p.json"), clock=clock)
    r = p.add(plan(schritte=[{"geraet": "fernseher_steuern",
                             "argumente": '{"action": "lautstaerke", "volume_percent": 20}'}]))
    assert r["ok"] and r["was"] == "Fernseher Lautstärke 20 %"


# ---- the app chat ----
def test_the_chat_note_shows_every_device_without_the_reading_actions(tmp_path):
    p, _, _ = make(tmp_path)
    note = p.chat_note()
    assert "Heute ist Dienstag, der 24. November 2026, es ist 22:00 Uhr." in note
    assert '– licht_steuern: {"lamps": [Zahl, ...], "action": "on|off|toggle"' in note
    assert '"hours": 1|2|4 oder null' in note and "– ansage:" in note
    assert "status" not in note and "stromkosten" not in note
    assert '{"aktion": "anlegen"' in note and "{{" not in note  # formatted exactly once


def test_a_plan_from_the_chat_is_made_at_once_and_she_answers_with_the_result(tmp_path, monkeypatch):
    from app import chat, memory
    p, home, clock = make(tmp_path)
    store = memory.MemoryStore(str(tmp_path / "mem.json"))
    seen = []
    answers = iter([
        {"reply": "Ich trag es ein.", "proposals": [], "lights_raw": [{"lamps": [1], "action": "on"}],
         "planer_raw": {"aktion": "anlegen", "uhrzeit": "23:00", "schritte": [
             {"geraet": "licht_steuern", "argumente": {"lamps": [1], "action": "off"}}]}},
        {"reply": "Um 23 Uhr geht Stehlampe 1 aus.", "proposals": [], "lights_raw": None,
         "planer_raw": {"aktion": "anlegen", "uhrzeit": "23:30", "schritte": []}},
    ])

    async def fake_answer(api_key, models, rules, store, history, message, url, lights, *more):
        seen.append(rules)
        return dict(next(answers))
    monkeypatch.setattr(chat, "_answer", fake_answer)
    switched = []

    async def lamps_now(args):
        switched.append(args)
        return {"lamps": []}
    out = asyncio.run(chat.answer("k", ["m"], "R", store, [], "Lampe 1 an und um 23 Uhr aus",
                                  lights=(4, lamps_now), planer=p))
    assert "PLANER" in seen[0] and "etwas für später planen" in seen[0]
    assert "PLANER ERGEBNIS" in seen[1] and "heute 23:00" in seen[1]
    assert out["reply"].startswith("Um 23 Uhr") and "planer_raw" not in out
    assert "🗓 Geplant: heute 23:00, Stehlampe 1 aus" in out["lights"]
    assert len(p.plans) == 1                      # the second pass cannot plan again
    assert len(switched) == 1 and home.calls == []  # "jetzt an" was done, the plan not yet
    clock.set("2026-11-24 23:00")
    assert asyncio.run(p.tick()) == 1 and home.calls[0][1]["action"] == "off"


def test_a_refused_plan_from_the_chat_says_so_in_the_line(tmp_path):
    p, _, _ = make(tmp_path)
    note, line = asyncio.run(p.chat_step({"aktion": "anlegen", "datum": "heute", "uhrzeit": "21:00",
                                          "schritte": [{"geraet": "licht_steuern",
                                                        "argumente": {"lamps": [], "action": "off"}}]}))
    assert line.startswith("🗓 Nicht geplant: Das liegt in der Vergangenheit") and p.plans == []
    assert "Vergangenheit" in note
    p.add(plan(titel="Abend"))
    assert asyncio.run(p.chat_step({"aktion": "anzeigen"}))[1] == ""
    assert asyncio.run(p.chat_step({"aktion": "loeschen", "titel": "abend"}))[1] == "🗓 Gelöscht: Abend"
    assert asyncio.run(p.chat_step({"aktion": "loeschen", "titel": "abend"}))[1].startswith("🗓 Nichts gelöscht")


def test_garbage_from_a_model_never_raises(tmp_path):
    p, _, _ = make(tmp_path)
    for req in ({"aktion": "anlegen"}, {"aktion": "anlegen", "schritte": "licht aus"},
                {"aktion": "anlegen", "schritte": [None, 3]},
                {"aktion": "anlegen", "schritte": [{"geraet": ["x"], "argumente": None}]},
                plan(uhrzeit=23), plan(datum=20261125), plan(in_minuten="20", uhrzeit=None),
                plan(wiederholung=["taeglich"]), plan(wiederholung="woechentlich", tage="mo"),
                plan(titel={"a": 1}), {"aktion": "loeschen", "nummer": "1"},
                {"aktion": "loeschen", "nummer": True}, {"aktion": ["x"]}, {}):
        out = asyncio.run(p.run_tool(req))
        assert isinstance(out, dict) and ("error" in out or out.get("ok")), req
    assert asyncio.run(p.run_tool(None))["ok"]


async def test_planstats_gives_counts_without_titles_or_texts(tmp_path):
    from app import memory, memory_web
    p, _, clock = make(tmp_path)
    p.add(plan(titel="Geheimer Titel", schritte=[
        lamp(), {"geraet": "ansage", "argumente": '{"text": "Geheimer Satz"}'}]))
    clock.set("2026-11-24 23:00")
    await p.tick()
    p.add(plan(uhrzeit="07:00", wiederholung="taeglich"))
    server = await memory_web.start_http(memory.MemoryStore(str(tmp_path / "m.json")), None,
                                         host="127.0.0.1", port=0, planer=p)
    try:
        port = server.sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"GET /api/planstats HTTP/1.1\r\nHost: x\r\n\r\n")
        await writer.drain()
        raw = (await reader.read()).decode()
        writer.close()
    finally:
        server.close()
    body = json.loads(raw.split("\r\n\r\n", 1)[1])
    assert body["offen"] == 1 and body["erledigt"] == 1 and body["wiederholt"] == 1
    assert body["naechster"] == "25.11. 07:00"
    assert body["laeufe"][0] == {"t": "24.11. 23:00", "ok": True, "verpasst": False,
                                 "schritte": ["licht_steuern", "ansage"]}
    assert "Geheim" not in raw


# ---- waiting for a talk: the lamp show holds its lamps ----
def test_a_held_plan_waits_and_runs_as_soon_as_it_is_free(tmp_path):
    p, home, clock = make(tmp_path)
    held = {"on": True}
    p._hold = lambda plan: held["on"]
    p.add(plan())
    clock.set("2026-11-24 23:00")
    assert run(p.tick()) == 0 and home.calls == [] and p.stats()["offen"] == 1
    assert p.wait_s() == 1.0  # looks again soon, without spinning
    clock.set("2026-11-24 23:04")
    assert run(p.tick()) == 0
    held["on"] = False
    assert run(p.tick()) == 1 and len(home.calls) == 1 and p._waiting == set()
    assert p.listing()["zuletzt"][0]["letztes_mal"] == "24.11. 23:04 erledigt"


def test_a_held_plan_runs_anyway_after_the_longest_talk(tmp_path):
    p, home, clock = make(tmp_path)
    p._hold = lambda plan: True
    p.add(plan())
    clock.set("2026-11-24 23:12")
    assert run(p.tick()) == 0
    clock.set("2026-11-24 23:13")
    assert run(p.tick()) == 1 and len(home.calls) == 1


def test_a_broken_hold_check_never_blocks_a_plan(tmp_path):
    p, home, clock = make(tmp_path)

    def broken(plan):
        raise RuntimeError("boom")
    p._hold = broken
    p.add(plan())
    clock.set("2026-11-24 23:00")
    assert run(p.tick()) == 1 and len(home.calls) == 1


async def test_only_plans_for_the_show_lamps_wait_for_the_talk(bridge):
    bridge.lamp.entities = ["light.a", "light.b"]  # the show has lamps 1 and 2
    rear = {"schritte": [{"geraet": "licht_steuern", "argumente": {"lamps": [2], "action": "off"}}]}
    front = {"schritte": [{"geraet": "licht_steuern", "argumente": {"lamps": [3], "action": "off"}}]}
    every = {"schritte": [{"geraet": "licht_steuern", "argumente": {"lamps": [], "action": "off"}}]}
    other = {"schritte": [{"geraet": "ventilator_steuern", "argumente": {"action": "aus"}},
                          {"geraet": "ansage", "argumente": {"text": "Der Tee ist fertig"}}]}
    assert not any(bridge._plan_hold(x) for x in (rear, front, every, other))  # no talk: nothing waits
    bridge.lamp._active = 1
    assert bridge._plan_hold(rear) and bridge._plan_hold(every)
    assert not bridge._plan_hold(front) and not bridge._plan_hold(other)
    bridge.commands.path = str(bridge.planer.path) + ".befehle"
    bridge.commands.define({"name": "hinten aus", "saetze": ["hinten aus"], "lampen_an": [],
                            "lampen_aus": [1], "ventilatorlicht": "nichts", "ventilator": "nichts",
                            "loeschen": False})
    bridge.commands.define({"name": "vorne aus", "saetze": ["vorne aus"], "lampen_an": [],
                            "lampen_aus": [3], "ventilatorlicht": "aus", "ventilator": "nichts",
                            "loeschen": False})
    command = lambda n: {"schritte": [{"geraet": "fester_befehl", "argumente": {"name": n}}]}  # noqa: E731
    assert bridge._plan_hold(command("hinten aus")) and not bridge._plan_hold(command("vorne aus"))
    assert not bridge._plan_hold(command("gibt es nicht"))
    bridge.lamp._active = 0
    bridge.lamp._ending = True  # the talk is over, the lamps are not back yet
    assert bridge._plan_hold(rear)
    bridge.lamp._ending = False
    assert not bridge._plan_hold(rear)


def test_a_full_disk_refuses_a_new_plan_but_a_due_plan_still_runs(tmp_path, monkeypatch):
    p, home, clock = make(tmp_path)
    assert p.add(plan())["ok"]

    def full(*a, **k):
        raise OSError("no space")
    monkeypatch.setattr(planer.os, "replace", full)
    r = p.add(plan(uhrzeit="23:30"))
    assert "nicht gespeichert" in r["error"] and len(p.plans) == 1
    p.listing()
    assert "noch da" in p.remove({"nummer": 1})["error"] and len(p.plans) == 1
    clock.set("2026-11-24 23:00")
    assert run(p.tick()) == 1 and len(home.calls) == 1
    assert run(p.tick()) == 0  # and not a second time in this run


async def test_the_loop_survives_a_fault_and_does_not_spin(tmp_path, monkeypatch):
    p, _, _ = make(tmp_path)
    ticks, sleeps = [], []

    async def tick():
        ticks.append(1)
        if len(ticks) == 1:
            raise RuntimeError("boom")
        if len(ticks) == 3:
            raise asyncio.CancelledError()

    async def sleep(s):
        sleeps.append(s)
    p.tick = tick
    monkeypatch.setattr(planer.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        await p.loop()
    assert len(ticks) == 3 and sleeps == [planer.POLL_S] * 4  # wait, fault pause, wait, wait


def test_a_file_changed_by_hand_cannot_break_the_loop(tmp_path):
    p, home, clock = make(tmp_path)
    p.add(plan())
    good = json.loads(open(p.path, encoding="utf-8").read())[0]
    bad = [dict(good, id="a1", schritte=[{"geraet": "licht_steuern"}]),
           dict(good, id="a2", status="irgendwas"), dict(good, id="a3", zeit="spät"),
           dict(good, id="a4", wdh="woechentlich"), dict(good, id="a5", faellig=True),
           dict(good, id="a6", lauf="gestern"), dict(good, id=7), dict(good, id="a8", titel=None)]
    open(p.path, "w", encoding="utf-8").write(json.dumps(bad + [good]))
    again = planer.Planner(schemas=home.schemas, run=home.run, path=p.path, clock=clock)
    assert [x["id"] for x in again.plans] == [good["id"]]
    clock.set("2026-11-24 23:00")
    assert run(again.tick()) == 1


async def test_the_real_loop_runs_a_plan_on_time_and_only_once(tmp_path):
    """With the real clock: due in 0.6 s, done within 0.3 s of its time, once."""
    import time
    home = Home()
    p = planer.Planner(schemas=home.schemas, run=home.run, path=str(tmp_path / "p.json"))
    assert p.add(plan(uhrzeit=None, in_minuten=1))["ok"]
    due = p.plans[0]["faellig"] = time.time() + 0.6
    done = []

    async def record(name, args):
        done.append(time.time() - due)
        return {"done": "ok"}
    p._run = record
    task = asyncio.create_task(p.loop())
    await asyncio.sleep(1.6)
    task.cancel()
    assert len(done) == 1 and 0 <= done[0] < 0.3, done
    assert p.stats()["erledigt"] == 1


def test_small_slips_of_a_model_in_the_arguments_are_understood(tmp_path):
    p, _, _ = make(tmp_path)
    inner = json.dumps({"lamps": [1], "action": "off"})
    # a JSON string, an object, a JSON string inside a JSON string
    for minute, given in enumerate((inner, json.loads(inner), json.dumps(inner))):
        r = p.add(plan(uhrzeit=f"22:{30 + 10 * minute}",
                       schritte=[{"geraet": "licht_steuern", "argumente": given}]))
        assert r["ok"] and r["was"] == "Stehlampe 1 aus" and "schon_geplant" not in r, given
    r = p.add(plan(uhrzeit="23:15", schritte=[{"geraet": "ansage", "argumente": "Der Tee ist fertig"}]))
    assert r["was"] == "Ansage: „Der Tee ist fertig“"
    assert "error" in p.add(plan(schritte=[{"geraet": "licht_steuern", "argumente": "Licht aus"}]))
