"""Fixed commands: set once by saying it, valid at once, run by the code exactly as set.
Invented example rules only."""
import asyncio

from app import befehle


class Lights:
    available = True
    entities = ["l1", "l2", "l3", "l4"]

    def __init__(self):
        self.calls = []

    async def run(self, args):
        self.calls.append((tuple(args["lamps"]), args["action"]))
        return {"lamps": [{"lamp": n, "state": "on" if args["action"] == "on" else "off"} for n in args["lamps"]]}


class Fan:
    available = True

    def __init__(self):
        self.calls = []

    async def run(self, args):
        self.calls.append(args["action"])
        return {"licht": "aus" if args["action"] == "licht_aus" else "an"}


def store(tmp_path):
    lights, fan = Lights(), Fan()
    return befehle.Commands(lights, fan, path=str(tmp_path / "befehle.json")), lights, fan


def new(**over):
    base = {"name": "lichter aus", "saetze": ["Lambaları kapat", "alle Lichter aus"], "lampen_an": [],
            "lampen_aus": [3, 4], "ventilatorlicht": "nichts", "ventilator": None, "loeschen": False}
    return dict(base, **over)


def test_set_once_and_it_runs_exactly_that(tmp_path):
    c, lights, fan = store(tmp_path)
    out = c.define(new())
    assert out["ok"] and out["gilt_jetzt"] == "Stehlampe 3 und 4 aus"
    done = asyncio.run(c.run({"name": "lichter aus"}))
    assert done["ok"] and lights.calls == [((3, 4), "off")] and fan.calls == []


def test_a_change_by_saying_it_applies_at_once_and_keeps_the_rest(tmp_path):
    c, lights, fan = store(tmp_path)
    c.define(new())
    out = c.define({"name": "Lichter aus", "saetze": ["ışıkları kapat"], "lampen_an": None, "lampen_aus": None,
                    "ventilatorlicht": "aus", "ventilator": None, "loeschen": False})
    assert out["gilt_jetzt"] == "Stehlampe 3 und 4 aus, Ventilatorlicht aus"
    assert out["saetze"] == ["Lambaları kapat", "alle Lichter aus", "ışıkları kapat"]
    assert len(c.load()) == 1                                    # changed, not a second one
    done = asyncio.run(c.run({"name": "LAMBALARI KAPAT"}))       # found by a sentence too, any spelling
    assert done["ok"] and lights.calls == [((3, 4), "off")] and fan.calls == ["licht_aus"]
    assert done["getan"] == "Stehlampe 3 und 4 aus, Ventilatorlicht aus"


def test_on_and_off_in_one_command_and_the_fan(tmp_path):
    c, lights, fan = store(tmp_path)
    c.define(new(name="gemütlich", saetze=["mach es gemütlich"], lampen_an=[1, 2], lampen_aus=[3],
                 ventilatorlicht="aus", ventilator="aus"))
    asyncio.run(c.run({"name": "gemütlich"}))
    assert sorted(lights.calls) == [((1, 2), "on"), ((3,), "off")] and fan.calls == ["licht_aus", "aus"]


def test_what_cannot_be_right_is_refused(tmp_path):
    c, _, _ = store(tmp_path)
    assert "Namen" in c.define(new(name=" "))["error"]
    assert "1 bis 4" in c.define(new(lampen_aus=[3, 7]))["error"]
    assert "zugleich" in c.define(new(lampen_an=[3]))["error"]
    assert "muss etwas schalten" in c.define(new(lampen_aus=[]))["error"]
    assert "mindestens einen Satz" in c.define(new(saetze=[]))["error"]
    assert c.load() == []
    c.define(new())
    assert "gibt es schon" in c.define(new(name="anders", saetze=["LAMBALARI KAPAT"]))["error"]
    assert "gibt es nicht" in asyncio.run(c.run({"name": "unbekannt"}))["error"]


def test_delete_and_the_hint_she_gets(tmp_path):
    c, _, _ = store(tmp_path)
    assert befehle.HINT_HEAD not in c.hint() and "befehl_festlegen" in c.hint()   # none yet: only how to set one
    c.define(new(ventilatorlicht="aus"))
    hint = c.hint()
    assert "'lichter aus': «Lambaları kapat», «alle Lichter aus» -> Stehlampe 3 und 4 aus, Ventilatorlicht aus" in hint
    assert c.define(new(loeschen=True)) == {"ok": True, "geloescht": "lichter aus"} and c.load() == []


def test_a_lamp_that_is_not_reachable_is_reported_not_hidden(tmp_path):
    c, lights, fan = store(tmp_path)

    async def run(args):
        return {"lamps": [], "unavailable": [4]}
    lights.run = run
    c.define(new())
    out = asyncio.run(c.run({"name": "lichter aus"}))
    assert out["ok"] is False and "Stehlampe 4" in out["probleme"][0]
    fan.available = False
    c.define(new(name="lichter aus", saetze=None, lampen_an=None, lampen_aus=None, ventilatorlicht="aus"))
    assert any("Ventilator" in p for p in asyncio.run(c.run({"name": "lichter aus"}))["probleme"])


def test_only_metin_sets_a_command_and_anyone_uses_one(tmp_path, monkeypatch):
    from app import main as m
    monkeypatch.setenv("CODE_PHRASE", "Leyla habibi")
    monkeypatch.setenv("MEMORY_PATH", str(tmp_path / "memory.json"))
    bridge = m.LiveVoiceBridge()
    bridge.commands.path = str(tmp_path / "befehle.json")
    tools = bridge._build_tools()
    setter, runner = tools["befehl_festlegen"], tools["fester_befehl"]
    assert "nur Metin" in setter["gate"](new(), {})["error"]                 # his mother, a guest
    assert setter["gate"](new(), {"metin_known": True}) is None              # known by his words
    assert setter["gate"](new(), {"unlocked": True}) is None                 # the code word
    assert "gate" not in runner
    bridge.commands.lights = Lights()
    assert asyncio.run(setter["run"](new()))["ok"] and len(bridge.commands.load()) == 1
