"""
Planner: what Metin tells her to do later, she does at that time by herself (2.161.0).

Metin, 24 Nov 2026: "kann Leyla auch ein Geplant ausführen die sie vorher erstellt durch Metin
Angabe". Until now she could only change automations that already existed in Home Assistant
(technik_pruefen) and remind of calendar appointments. A plan is a time (once, every day or on
fixed days of the week) and up to MAX_STEPS steps. A step is one call of a household tool she
may use anyway (lamps, fan, purifier, vacuum, TV, a fixed command) or a spoken announcement.
The code runs the steps at the time; the model is not asked again.

What keeps it from going wrong:
- The arguments of every step are checked against the tool's own schema when the plan is made
  (check_args), so a mistake shows while Metin is still there and not at night.
- A plan is claimed before it runs: a one time plan is marked as running, a repeating one
  moves to its next time first. A restart in the middle never runs it a second time.
- A plan that is more than GRACE_S late (the add on was down) is not run late: a lamp that
  should have gone on at seven does not go on at nine. It counts as missed and Metin is told.
- A step that fails does not stop the steps after it; what failed is kept and Metin is told.
- A plan that switches the lamps of the lamp show waits while a talk at home runs (`hold`): the
  end of the show puts those lamps back to what they were before the talk and would undo it.

Only Metin makes or deletes plans (gate in tool_link); anyone may hear what is planned.
Stored in /data, not in the repo. Texts of announcements and titles are never logged.
"""
import asyncio
import json
import logging
import os
import re
import time
import unicodedata
import uuid
from datetime import date, datetime, time as dtime, timedelta
from typing import Awaitable, Callable, Optional

from app import context
from app.agenda import LONG_DAYS, SHORT_DAYS, _tz, parse_date, parse_time

logger = logging.getLogger(__name__)

PATH = os.environ.get("LEYLA_PLANER_PATH", "/data/leyla_planer.json")
MAX_PLANS = 40          # open plans
MAX_STEPS = 6           # steps of one plan
MAX_SAY_CHARS = 300     # an announcement
MAX_AHEAD_DAYS = 366
MAX_MINUTES = 7 * 24 * 60
GRACE_S = 30 * 60       # this late a plan still runs, later it is missed
KEEP_DONE_S = 2 * 24 * 3600  # finished one time plans stay listed this long
SAME_S = 120            # the same plan again within this time counts once (the model calls twice)
POLL_S = 5.0            # the loop looks at least this often
HOLD_S = 12 * 60        # a plan waits at most this long for a talk to end (a talk ends after 10 min)

DAYS = ["mo", "di", "mi", "do", "fr", "sa", "so"]
REPEATS = ("einmal", "taeglich", "woechentlich")
SAY = "ansage"
SAY_SCHEMA = {"type": "object", "properties": {"text": {"type": "string"}},
              "required": ["text"], "additionalProperties": False}
# reading something is not a plan: nobody is there to hear the answer
READ_ONLY = ("status", "stromkosten", "wartung")
OPEN, RUNNING, DONE, FAILED, MISSED = "offen", "laeuft", "erledigt", "fehler", "verpasst"

PLANER_BACKEND_HINT = (
    " PLANNER: when Metin wants something done later or again and again ('mach um 23 Uhr das "
    "Licht aus', 'in 20 Minuten Ventilator aus', 'jeden Morgen um 7 Lampe 1 an', 'sag mir um "
    "18 Uhr Bescheid wegen der Wäsche'), call planer with aktion anlegen: the time as uhrzeit "
    "(with datum when he names a day) or as in_minuten, wiederholung, and schritte. Each step "
    "is one device with argumente as a JSON string holding exactly the arguments you would "
    "give that tool to do it now, for example {\"geraet\": \"licht_steuern\", \"argumente\": "
    "\"{\\\"lamps\\\": [1], \\\"action\\\": \\\"off\\\", \\\"brightness_percent\\\": null, "
    "\\\"white\\\": null, \\\"color\\\": null}\"}; for something she shall say at that time use "
    "geraet ansage with {\"text\": \"...\"}. Do NOT switch anything now unless he also asks "
    "for now. The result says when and what (wann, was): tell him exactly that in one "
    "sentence. If the result has an error nothing is planned: say so or correct the call, "
    "never claim it is planned. If the time or the device is unclear, ask before you plan. "
    "aktion anzeigen lists what is planned and what ran lately; aktion loeschen takes the "
    "nummer from the last list or a word of the title. Only Metin may plan or delete.")


CHAT_NOTE = """

PLANER
• Du kannst für Metin etwas für später planen und es dann selbst erledigen, einmal, täglich oder an festen Wochentagen. {today} Unter "planer" trägst du genau ein Objekt ein. Anlegen: {{"aktion": "anlegen", "titel": "kurzer Titel", "datum": "JJJJ-MM-TT", "heute", "morgen", ein Wochentag oder null (null heißt: das nächste Mal, wenn diese Uhrzeit kommt), "uhrzeit": "HH:MM", "in_minuten": Zahl statt uhrzeit oder null, "wiederholung": "einmal|taeglich|woechentlich", "tage": ["mo","di","mi","do","fr","sa","so"] nur bei woechentlich, sonst null, "schritte": [{{"geraet": "...", "argumente": {{...}}}}]}}. Ansehen: {{"aktion": "anzeigen"}}. Löschen: {{"aktion": "loeschen", "nummer": 1}} mit der Nummer aus der letzten Liste, oder {{"aktion": "loeschen", "titel": "Wort aus dem Titel"}}.
• Die Geräte für "schritte" und ihre "argumente" (höchstens {steps} Schritte, sie laufen der Reihe nach):
{devices}
• Das Eintragen passiert sofort, geschaltet wird erst zur geplanten Zeit. Trag dafür nichts unter "lights" ein, außer Metin will es auch jetzt gleich. Du bekommst das Ergebnis und sagst Metin dann genau, wann und was geplant ist. Schreib vorher in "reply" nur kurz, dass du es einträgst. Steht im Ergebnis ein Fehler, ist nichts geplant: sag das ehrlich. Ist die Zeit oder das Gerät unklar, frag erst nach und trag nichts ein."""

RESULT_NOTE = """

PLANER ERGEBNIS (gerade eben wirklich ausgeführt)
{result}
Antworte Metin jetzt darauf, kurz und in deinen Worten: bei einem neuen Plan genau wann und was, wie es im Ergebnis steht; bei einem Fehler, dass es nicht geplant ist und warum. Trag kein weiteres "planer" ein."""

# what the chat model cannot see in a schema
CHAT_HINTS = {
    "licht_steuern": "lamps [] heißt alle Stehlampen",
    "ventilator_steuern": "speed 1 bis 6 nur bei stufe, hours nur bei timer",
    "luftreiniger": "modus nur bei modus, stufe 1 bis 4 nur bei stufe, minuten nur bei timer",
    "saugroboter": "rooms nur bei raeume, sonst []",
    "fernseher_steuern": "channel nur bei kanal, steps nur bei lauter und leiser, "
                         "volume_percent nur bei lautstaerke",
    "fester_befehl": "name ist der Name eines festen Befehls der Familie",
    SAY: "das sagst du dann zu Hause laut, ein oder zwei kurze Sätze",
}


def _shape(name: str, spec: dict) -> str:
    """One argument of a tool the way the chat model shall write it."""
    kinds = spec.get("type")
    kinds = kinds if isinstance(kinds, list) else [kinds]
    null = " oder null" if "null" in kinds else ""
    if "enum" in spec:
        values = [v for v in spec["enum"] if v is not None
                  and not (name == "action" and v in READ_ONLY)]
        text = "|".join(str(v) for v in values)
        return (f'"{text}"' if isinstance(values[0], str) else text) + null
    if "array" in kinds:
        item = (spec.get("items") or {}).get("type")
        return ("[Zahl, ...]" if item == "integer" else '["...", ...]') + null
    if "integer" in kinds or "number" in kinds:
        return "Zahl" + null
    if "boolean" in kinds:
        return "true|false" + null
    return '"..."' + null


def schema_line(device: str, schema: dict) -> str:
    args = ", ".join(f'"{k}": {_shape(k, v)}' for k, v in (schema.get("properties") or {}).items())
    hint = CHAT_HINTS.get(device)
    return f"– {device}: {{{args}}}" + (f" ({hint})" if hint else "")


def build_tool(devices: list) -> dict:
    """The planer tool; `devices` are the tools a step may use (only what this home has)."""
    return {
        "type": "function",
        "name": "planer",
        "description": (
            "Leyla's planner: do something later by herself, once or repeating. anlegen makes "
            "a plan, anzeigen lists the plans, loeschen removes one. Only for Metin."),
        "parameters": {
            "type": "object",
            "properties": {
                "aktion": {"type": "string", "enum": ["anlegen", "anzeigen", "loeschen"]},
                "titel": {"type": ["string", "null"],
                          "description": "Short German title of the plan, for example 'Licht "
                                         "aus am Abend'. For loeschen: a word of the title."},
                "datum": {"type": ["string", "null"],
                          "description": "JJJJ-MM-TT, heute, morgen or a weekday. null: the "
                                         "next time that clock time comes."},
                "uhrzeit": {"type": ["string", "null"], "description": "HH:MM, 24 hours."},
                "in_minuten": {"type": ["integer", "null"],
                               "description": "Instead of uhrzeit: in this many minutes."},
                "wiederholung": {"type": ["string", "null"], "enum": list(REPEATS) + [None],
                                 "description": "einmal (default), taeglich, or woechentlich "
                                                "with tage."},
                "tage": {"type": ["array", "null"], "items": {"type": "string", "enum": DAYS},
                         "description": "For woechentlich: the days, for example "
                                        "[\"mo\",\"di\",\"mi\",\"do\",\"fr\"] for work days."},
                "schritte": {
                    "type": ["array", "null"],
                    "description": "For anlegen: what to do, in order.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "geraet": {"type": "string", "enum": list(devices)},
                            "argumente": {"type": "string",
                                          "description": "JSON object with the arguments of "
                                                         "that tool, exactly as for a call "
                                                         "now. For ansage: {\"text\": ...}."},
                        },
                        "required": ["geraet", "argumente"],
                        "additionalProperties": False,
                    },
                },
                "nummer": {"type": ["integer", "null"],
                           "description": "For loeschen: the number from the last list."},
            },
            "required": ["aktion", "titel", "datum", "uhrzeit", "in_minuten", "wiederholung",
                         "tage", "schritte", "nummer"],
            "additionalProperties": False,
        },
    }


def _key(text) -> str:
    text = unicodedata.normalize("NFKD", str(text or "").replace("ı", "i")).encode(
        "ascii", "ignore").decode().lower()
    return " ".join(re.findall(r"[a-z0-9]+", text))


def _fits(value, kind: str) -> bool:
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "string":
        return isinstance(value, str)
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "array":
        return isinstance(value, list)
    if kind == "object":
        return isinstance(value, dict)
    return False


def check_args(schema: dict, raw) -> tuple:
    """`raw` (a JSON string or a dict) against a tool's parameter schema. Returns
    (arguments, None) with every missing optional value as None, or (None, what is wrong)."""
    for _ in range(2):  # a model sometimes wraps the JSON string in a second one
        if isinstance(raw, str):
            try:
                raw = json.loads(raw) if raw.strip() else {}
            except ValueError:
                return None, "argumente ist kein gültiges JSON."
    if not isinstance(raw, dict):
        return None, "argumente muss ein JSON Objekt sein."
    props = schema.get("properties") or {}
    unknown = sorted(set(raw) - set(props))
    if unknown:
        return None, ("Unbekannte Angabe: " + ", ".join(unknown) + ". Erlaubt sind: "
                      + ", ".join(props) + ".")
    out = {}
    for name, spec in props.items():
        kinds = spec.get("type")
        kinds = kinds if isinstance(kinds, list) else [kinds]
        value = raw.get(name)
        if value is None:
            if "null" in kinds:
                out[name] = None
            elif name in (schema.get("required") or []):
                return None, f"Es fehlt: {name}."
            continue
        if not any(_fits(value, k) for k in kinds if k != "null"):
            return None, f"{name} hat die falsche Art, erwartet wird {' oder '.join(k for k in kinds if k != 'null')}."
        if "enum" in spec and value not in spec["enum"]:
            allowed = ", ".join(str(v) for v in spec["enum"] if v is not None)
            return None, f"{name}: '{value}' gibt es nicht. Erlaubt: {allowed}."
        item = (spec.get("items") or {}).get("type")
        if isinstance(value, list) and item and not all(_fits(v, item) for v in value):
            return None, f"{name}: jeder Eintrag muss {item} sein."
        out[name] = value
    return out, None


def _and(numbers) -> str:
    return " und ".join(str(n) for n in numbers)


def describe_step(step: dict) -> str:
    """One step in German words, for her and for Metin."""
    device, a = step.get("geraet"), step.get("argumente") or {}
    action = a.get("action")
    if device == SAY:
        return "Ansage: „" + str(a.get("text", "")) + "“"
    if device == "licht_steuern":
        who = ("Stehlampe " + _and(a["lamps"])) if a.get("lamps") else "alle Stehlampen"
        word = {"on": "an", "off": "aus", "toggle": "umschalten"}.get(action, str(action))
        more = [f"{a['brightness_percent']} %" if a.get("brightness_percent") is not None else "",
                a.get("white") or "", a.get("color") or ""]
        return " ".join([who, word] + [m for m in more if m])
    if device == "ventilator_steuern":
        return {"aus": "Ventilator aus", "an": "Ventilator an",
                "stufe": f"Ventilator Stufe {a.get('speed')}",
                "licht_an": "Ventilatorlicht an", "licht_aus": "Ventilatorlicht aus",
                "licht": "Ventilatorlicht umschalten", "naturwind": "Ventilator Naturwind",
                "links": "Ventilator dreht links", "rechts": "Ventilator dreht rechts",
                "timer": f"Ventilator Timer {a.get('hours')} Std"}.get(action, f"Ventilator {action}")
    if device == "luftreiniger":
        return {"an": "Luftreiniger an", "aus": "Luftreiniger aus",
                "modus": f"Luftreiniger Modus {a.get('modus')}",
                "stufe": f"Luftreiniger Stufe {a.get('stufe')}",
                "timer": f"Luftreiniger Timer {a.get('minuten')} Min"}.get(action, f"Luftreiniger {action}")
    if device == "saugroboter":
        text = {"starten": "Saugroboter starten",
                "raeume": "Saugroboter: " + ", ".join(map(str, a.get("rooms") or [])),
                "pause": "Saugroboter Pause", "stopp": "Saugroboter Stopp",
                "zurueck": "Saugroboter zur Station"}.get(action, f"Saugroboter {action}")
        more = [str(a[k]).replace("_", " ") for k in ("modus", "staerke") if a.get(k)]
        return text + (" (" + ", ".join(more) + ")" if more else "")
    if device == "fernseher_steuern":
        return {"an": "Fernseher an", "aus": "Fernseher aus",
                "kanal": f"Fernseher Sender {a.get('channel')}",
                "lauter": "Fernseher lauter", "leiser": "Fernseher leiser",
                "lautstaerke": f"Fernseher Lautstärke {a.get('volume_percent')} %",
                "stumm": "Fernseher stumm", "receiver": "Receiver"}.get(action, f"Fernseher {action}")
    if device == "fester_befehl":
        return f"fester Befehl „{a.get('name')}“"
    return f"{device} {action or ''}".strip()


def describe(plan: dict) -> str:
    return ", dann ".join(describe_step(s) for s in plan.get("schritte", [])) or "nichts"


def problems(result) -> list:
    """What a tool result says went wrong, as short German lines ([] when all is well)."""
    out = []
    items = result if isinstance(result, list) else [result]
    for r in items:
        if not isinstance(r, dict):
            continue
        if r.get("error"):
            out.append(str(r["error"]))
        if r.get("unavailable"):
            out.append("Nicht erreichbar: " + ", ".join(map(str, r["unavailable"]))
                       if isinstance(r["unavailable"], list) else "Nicht erreichbar.")
        if r.get("reachable") is False and not r.get("error"):
            out.append("Nicht erreichbar.")
        if r.get("probleme"):
            out += [str(p) for p in r["probleme"]] if isinstance(r["probleme"], list) \
                else [str(r["probleme"])]
        if r.get("pressed") and not r.get("done"):
            out.append("Taste gedrückt, aber der Stromzähler hat es nicht bestätigt.")
    return out


class Planner:
    """`schemas`: function that returns {tool name: parameter schema} of the tools a step may
    use. `run(tool name, arguments)` awaits that tool and returns its result. `say(text)`
    speaks an announcement (None: no announcements here). `notify(title, message)` tells Metin
    on his phone when a plan failed or was missed. `check(tool name, arguments)` may return
    what else is wrong with a step (a lamp number that does not exist). `hold(plan)` is True
    while the plan has to wait (the lamp show holds its lamps). `clock`: seconds."""

    def __init__(self, schemas: Optional[Callable[[], dict]] = None,
                 run: Optional[Callable[[str, dict], Awaitable]] = None,
                 say: Optional[Callable[[str], Awaitable]] = None,
                 notify: Optional[Callable[[str, str], Awaitable]] = None,
                 check: Optional[Callable[[str, dict], Optional[str]]] = None,
                 hold: Optional[Callable[[dict], bool]] = None,
                 path: Optional[str] = None, clock: Callable[[], float] = time.time) -> None:
        self._schemas, self._run, self._say = schemas or (lambda: {}), run, say
        self._notify, self._check, self._hold, self.clock = notify, check, hold, clock
        self.path = path or PATH
        self._shown: list = []   # ids of the last list, so a number means what she read out
        self._tell: list = []    # (title, message) still to send to Metin
        self._waiting: set = set()  # ids of plans that wait for a talk to end
        self.plans = self._load()

    # ---- what there is ----
    @property
    def devices(self) -> list:
        return list(self._schemas()) + ([SAY] if self._say else [])

    @property
    def available(self) -> bool:
        return bool(self._run and self.devices)

    def tool(self) -> dict:
        return build_tool(self.devices)

    # ---- the app chat (always Metin, after his code word) ----
    def chat_note(self) -> str:
        lines = [schema_line(d, s) for d, s in self._schemas().items()]
        if self._say:
            lines.append(schema_line(SAY, SAY_SCHEMA))
        return CHAT_NOTE.format(today=context.format_datetime(self._local(self.clock())),
                                steps=MAX_STEPS, devices="\n".join(lines))

    async def chat_step(self, req: dict) -> tuple:
        """One "planer" request from the chat: (the note for her second pass with the result,
        the line the page shows under her answer; the line is made here, not by the model)."""
        out = await self.run_tool(req)
        line = ""
        if req.get("aktion") == "anlegen":
            line = (f"🗓 Geplant: {out['wann']}, {out['was']}" if out.get("ok")
                    else "🗓 Nicht geplant: " + str(out.get("error", "")))
        elif req.get("aktion") == "loeschen":
            line = (f"🗓 Gelöscht: {out['geloescht']}" if out.get("ok")
                    else "🗓 Nichts gelöscht: " + str(out.get("error", "")))
        return RESULT_NOTE.format(result=json.dumps(out, ensure_ascii=False)), line

    # ---- the store ----
    def _load(self) -> list:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return []
        plans = [p for p in data if self._sound(p)] if isinstance(data, list) else []
        for p in plans:
            if p.get("status") == RUNNING:  # the add on stopped in the middle of this plan
                p["status"] = FAILED
                p["lauf"] = {"t": round(self.clock()), "ok": False,
                             "probleme": ["Ich wurde mitten im Ablauf neu gestartet."]}
                self._tell.append(("Leyla Planer", "„%s“ wurde durch einen Neustart "
                                   "unterbrochen. Schau bitte, ob alles so ist, wie du es "
                                   "wolltest." % p.get("titel", "")))
        return plans

    @staticmethod
    def _sound(p) -> bool:
        """A stored plan the loop can work with; anything else in the file is left out."""
        return (isinstance(p, dict) and isinstance(p.get("id"), str)
                and isinstance(p.get("titel"), str)
                and isinstance(p.get("faellig"), (int, float)) and not isinstance(p.get("faellig"), bool)
                and p.get("status") in (OPEN, RUNNING, DONE, FAILED, MISSED)
                and p.get("wdh") in REPEATS and parse_time(p.get("zeit")) is not None
                and isinstance(p.get("schritte"), list) and bool(p["schritte"])
                and all(isinstance(x, dict) and isinstance(x.get("geraet"), str)
                        and isinstance(x.get("argumente"), dict) for x in p["schritte"])
                and (p["wdh"] != "woechentlich" or (
                    isinstance(p.get("tage"), list) and bool(p["tage"])
                    and all(d in range(7) for d in p["tage"])))
                and (p.get("lauf") is None or (isinstance(p["lauf"], dict)
                                               and isinstance(p["lauf"].get("t"), (int, float)))))

    def _save(self) -> bool:
        """Write the plans. False when the disk refused (logged, never raised: a plan that is
        due is still run, and a new plan is then refused in add)."""
        now = self.clock()
        self.plans = [p for p in self.plans if p.get("status") in (OPEN, RUNNING)
                      or now - (p.get("lauf") or {}).get("t", now) < KEEP_DONE_S]
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.plans, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
            return True
        except OSError as e:
            logger.warning("Planner: could not write the plans: %s", type(e).__name__)
            return False

    def open_plans(self) -> list:
        return sorted((p for p in self.plans if p.get("status") == OPEN),
                      key=lambda p: p["faellig"])

    # ---- times ----
    def _local(self, ts: float) -> datetime:
        return datetime.fromtimestamp(ts, _tz())

    def _at(self, day: date, t: dtime) -> float:
        return datetime.combine(day, t, tzinfo=_tz()).timestamp()

    def _next(self, plan: dict, after: float) -> Optional[float]:
        """The next time of a repeating plan that lies after `after`."""
        t = parse_time(plan.get("zeit"))
        if not t:
            return None
        first = self._local(after).date()
        for i in range(9):
            day = first + timedelta(days=i)
            if plan.get("wdh") == "woechentlich" and day.weekday() not in (plan.get("tage") or []):
                continue
            ts = self._at(day, t)
            if ts > after:
                return ts
        return None

    def when(self, plan: dict, now: Optional[float] = None) -> str:
        """'heute 23:00', 'morgen 07:00', 'Mi 25.11. 07:00', 'täglich 22:30, das nächste Mal ...'."""
        now = self.clock() if now is None else now
        due, today = self._local(plan["faellig"]), self._local(now).date()
        gap = (due.date() - today).days
        day = {0: "heute", 1: "morgen"}.get(gap) or f"{SHORT_DAYS[due.weekday()]} {due.day}.{due.month}."
        once = f"{day} {due:%H:%M}"
        if plan.get("wdh") == "taeglich":
            return f"täglich {plan['zeit']}, das nächste Mal {once}"
        if plan.get("wdh") == "woechentlich":
            days = ", ".join(SHORT_DAYS[d] for d in plan.get("tage") or [])
            return f"jede Woche {days} {plan['zeit']}, das nächste Mal {once}"
        return once

    # ---- the tool ----
    async def run_tool(self, args: dict) -> dict:
        args = args or {}
        action = args.get("aktion")
        if action == "anlegen":
            return self.add(args)
        if action == "loeschen":
            return self.remove(args)
        return self.listing()

    def _steps(self, raw) -> tuple:
        if not isinstance(raw, list) or not raw:
            return None, "Der Plan braucht mindestens einen Schritt (schritte)."
        if len(raw) > MAX_STEPS:
            return None, f"Ein Plan hat höchstens {MAX_STEPS} Schritte."
        schemas, steps = self._schemas(), []
        for i, s in enumerate(raw, 1):
            device = s.get("geraet") if isinstance(s, dict) else None
            device = device if isinstance(device, str) else None
            if device == SAY and self._say:
                schema = SAY_SCHEMA
            elif device in schemas:
                schema = schemas[device]
            else:
                return None, (f"Schritt {i}: '{device}' kann ich nicht planen. Es geht: "
                              + ", ".join(self.devices) + ".")
            given = s.get("argumente")
            if device == SAY and isinstance(given, str) and not given.lstrip().startswith(("{", '"')):
                given = {"text": given}  # the bare sentence instead of {"text": ...}
            a, wrong = check_args(schema, given)
            if wrong:
                return None, f"Schritt {i} ({device}): {wrong}"
            if device == SAY:
                a["text"] = " ".join(a["text"].split())
                if not a["text"]:
                    return None, f"Schritt {i}: die Ansage braucht einen Text."
                if len(a["text"]) > MAX_SAY_CHARS:
                    return None, f"Schritt {i}: die Ansage ist zu lang (höchstens {MAX_SAY_CHARS} Zeichen)."
            elif a.get("action") in READ_ONLY:
                return None, (f"Schritt {i}: '{a['action']}' liest nur etwas ab, das kann man "
                              "nicht planen.")
            wrong = self._check(device, a) if self._check and device != SAY else None
            if wrong:
                return None, f"Schritt {i} ({device}): {wrong}"
            steps.append({"geraet": device, "argumente": a})
        return steps, None

    def _due_once(self, args: dict, now: float) -> tuple:
        """(due time, error) of a one time plan from datum and uhrzeit."""
        t = parse_time(args.get("uhrzeit"))
        if not t:
            return None, "Ich brauche eine Uhrzeit (uhrzeit als HH:MM) oder in_minuten."
        today = self._local(now).date()
        word = str(args.get("datum") or "").strip().lower()
        if not word:
            day = today if self._at(today, t) > now else today + timedelta(days=1)
        elif word in LONG_DAYS:  # that weekday: today when the time is still ahead
            day = today + timedelta(days=(LONG_DAYS.index(word) - today.weekday()) % 7)
            if self._at(day, t) <= now:
                day += timedelta(days=7)
        else:
            day = parse_date(word, today)
            if not day:
                return None, f"Das Datum '{args.get('datum')}' verstehe ich nicht (JJJJ-MM-TT, heute, morgen oder ein Wochentag)."
        due = self._at(day, t)
        if due <= now:
            return None, f"Das liegt in der Vergangenheit, jetzt ist es {self._local(now):%d.%m. %H:%M}."
        if due - now > MAX_AHEAD_DAYS * 86400:
            return None, "Das ist mehr als ein Jahr entfernt."
        return due, None

    def add(self, args: dict, who: str = "Metin") -> dict:
        now = self.clock()
        steps, wrong = self._steps(args.get("schritte"))
        if wrong:
            return {"error": wrong}
        repeat = args.get("wiederholung") or "einmal"
        if repeat not in REPEATS:
            return {"error": "wiederholung ist einmal, taeglich oder woechentlich."}
        plan = {"id": uuid.uuid4().hex[:8], "schritte": steps, "wdh": repeat, "status": OPEN,
                "angelegt": round(now), "von": who}
        minutes = args.get("in_minuten")
        if minutes is not None:
            if args.get("uhrzeit"):
                return {"error": "Entweder uhrzeit oder in_minuten, nicht beides."}
            if repeat != "einmal":
                return {"error": "in_minuten geht nur einmal. Für eine Wiederholung brauche ich die Uhrzeit."}
            if not _fits(minutes, "integer") or not 1 <= minutes <= MAX_MINUTES:
                return {"error": f"in_minuten muss zwischen 1 und {MAX_MINUTES} liegen."}
            plan["faellig"] = now + minutes * 60
            plan["zeit"] = f"{self._local(plan['faellig']):%H:%M}"
        elif repeat == "einmal":
            plan["faellig"], wrong = self._due_once(args, now)
            if wrong:
                return {"error": wrong}
            plan["zeit"] = f"{self._local(plan['faellig']):%H:%M}"
        else:
            t = parse_time(args.get("uhrzeit"))
            if not t:
                return {"error": "Für eine Wiederholung brauche ich die Uhrzeit (uhrzeit als HH:MM)."}
            plan["zeit"] = f"{t:%H:%M}"
            start = None
            if args.get("datum"):
                start = parse_date(args["datum"], self._local(now).date())
                if not start:
                    return {"error": f"Das Datum '{args['datum']}' verstehe ich nicht."}
            if repeat == "woechentlich":
                days = args.get("tage")
                if days is not None and (not isinstance(days, list)
                                         or any(d not in DAYS for d in days)):
                    return {"error": "tage sind mo, di, mi, do, fr, sa, so."}
                plan["tage"] = sorted({DAYS.index(d) for d in days or []}) \
                    or ([start.weekday()] if start else [])
                if not plan["tage"]:
                    return {"error": "Für woechentlich brauche ich die Wochentage (tage) oder ein Datum."}
            after = now
            if start:
                after = max(now, self._at(start, dtime(0, 0)) - 1)
            plan["faellig"] = self._next(plan, after)
            if not plan["faellig"]:
                return {"error": "Dafür finde ich keinen nächsten Zeitpunkt."}
        title = " ".join(str(args.get("titel") or "").split())[:60]
        plan["titel"] = title or describe(plan)[:60]
        for old in self.open_plans():  # the model sometimes calls twice
            if (old["schritte"] == steps and old.get("wdh") == repeat
                    and old.get("tage") == plan.get("tage")
                    and abs(old["faellig"] - plan["faellig"]) < SAME_S):
                return self._made(old, now, again=True)
        if len(self.open_plans()) >= MAX_PLANS:
            return {"error": f"Mehr als {MAX_PLANS} offene Pläne gehen nicht, lösch zuerst einen."}
        self.plans.append(plan)
        if not self._save():  # a plan that would be gone after a restart is no plan
            self.plans = [p for p in self.plans if p is not plan]
            return {"error": "Der Plan konnte nicht gespeichert werden, es ist nichts geplant."}
        logger.info("Planner: plan %s made, %s, %d step(s): %s", plan["id"], repeat, len(steps),
                    ", ".join(s["geraet"] for s in steps))
        return self._made(plan, now)

    def _made(self, plan: dict, now: float, again: bool = False) -> dict:
        out = {"ok": True, "titel": plan["titel"], "wann": self.when(plan, now),
               "was": describe(plan),
               "hinweis": "Geplant, jetzt wird nichts geschaltet. Sag Metin in einem Satz "
                          "genau wann und was, aus diesem Ergebnis."}
        if again:
            out["schon_geplant"] = True
        return out

    def listing(self) -> dict:
        now = self.clock()
        plans = self.open_plans()
        self._shown = [p["id"] for p in plans]
        out = {"ok": True, "anzahl": len(plans),
               "geplant": [{"nummer": i, "titel": p["titel"], "wann": self.when(p, now),
                            "was": describe(p), **self._last(p)}
                           for i, p in enumerate(plans, 1)]}
        done = sorted((p for p in self.plans if p.get("status") in (DONE, FAILED, MISSED)),
                      key=lambda p: (p.get("lauf") or {}).get("t", 0), reverse=True)
        if done:
            out["zuletzt"] = [{"titel": p["titel"], "was": describe(p), **self._last(p)}
                              for p in done[:8]]
        if not plans:
            out["hinweis"] = "Es ist nichts geplant."
        return out

    def _last(self, plan: dict) -> dict:
        run = plan.get("lauf")
        if not run:
            return {}
        when = f"{self._local(run['t']):%d.%m. %H:%M}"
        if run.get("verpasst"):
            return {"letztes_mal": f"{when} verpasst, ich war nicht an"}
        if run.get("ok"):
            return {"letztes_mal": f"{when} erledigt"}
        return {"letztes_mal": f"{when} nicht ganz geklappt", "probleme": run.get("probleme", [])}

    def remove(self, args: dict) -> dict:
        plans = self.open_plans()
        by_id = {p["id"]: p for p in plans}
        number, word = args.get("nummer"), _key(args.get("titel"))
        if number is not None:
            if not _fits(number, "integer") or not 1 <= number <= len(self._shown):
                return {"error": "Diese Nummer gibt es in der letzten Liste nicht. Zeig die "
                                 "Pläne zuerst an (aktion anzeigen)."}
            plan = by_id.get(self._shown[number - 1])
            if not plan:
                return {"error": "Dieser Plan ist schon weg."}
        elif word:
            hits = [p for p in plans if word in _key(p["titel"]) or word in _key(describe(p))]
            if not hits:
                return {"error": "Dazu finde ich keinen Plan.",
                        "geplant": self.listing()["geplant"]}
            if len(hits) > 1:
                self._shown = [p["id"] for p in hits]
                return {"error": "Dazu passen mehrere Pläne. Frag Metin, welche Nummer.",
                        "geplant": [{"nummer": i, "titel": p["titel"],
                                     "wann": self.when(p), "was": describe(p)}
                                    for i, p in enumerate(hits, 1)]}
            plan = hits[0]
        else:
            return {"error": "Welchen Plan? Gib die nummer aus der letzten Liste oder ein Wort "
                             "aus dem Titel."}
        self.plans.remove(plan)  # the numbers she read out stay valid for the other plans
        if not self._save():
            self.plans.append(plan)
            return {"error": "Das Löschen konnte nicht gespeichert werden, der Plan ist noch da."}
        self._waiting.discard(plan["id"])
        logger.info("Planner: plan %s deleted", plan["id"])
        return {"ok": True, "geloescht": plan["titel"], "war_geplant": self.when(plan),
                "was": describe(plan)}

    # ---- doing it ----
    def due(self, now: Optional[float] = None) -> list:
        now = self.clock() if now is None else now
        return [p for p in self.open_plans() if p["faellig"] <= now]

    def wait_s(self) -> float:
        """How long the loop may sleep until the next plan is due."""
        plans = self.open_plans()
        if not plans:
            return POLL_S
        if self._waiting:  # a plan waits for a talk to end: look again soon, but do not spin
            return 1.0
        return min(POLL_S, max(0.2, plans[0]["faellig"] - self.clock()))

    def _held(self, plan: dict, now: float) -> bool:
        """True while the plan has to wait (see `hold`), at most HOLD_S after its time."""
        held = False
        if self._hold and now - plan["faellig"] <= HOLD_S:
            try:
                held = bool(self._hold(plan))
            except Exception as e:
                logger.warning("Planner: hold check failed: %s", type(e).__name__)
        if held and plan["id"] not in self._waiting:
            logger.info("Planner: plan %s waits until the talk is over", plan["id"])
        (self._waiting.add if held else self._waiting.discard)(plan["id"])
        return held

    def _claim(self, plan: dict, now: float) -> float:
        """Mark the plan as taken before anything is switched. Returns the time it was due."""
        was_due = plan["faellig"]
        if plan.get("wdh") in ("taeglich", "woechentlich"):
            nxt = self._next(plan, max(now, was_due))
            if nxt:
                plan["faellig"] = nxt
            else:  # cannot happen with a valid time; never run it in a loop
                plan["status"] = RUNNING
        else:
            plan["status"] = RUNNING
        return was_due

    async def tick(self) -> int:
        """Run what is due. Returns how many plans were run."""
        ran = 0
        for plan in self.due():
            now = self.clock()
            if self._held(plan, now):
                continue
            was_due = self._claim(plan, now)
            at = f"{self._local(was_due):%H:%M}"
            if now - was_due > GRACE_S:
                plan["lauf"] = {"t": round(now), "ok": False, "verpasst": True}
                if plan["status"] == RUNNING:
                    plan["status"] = MISSED
                self._save()
                logger.info("Planner: plan %s missed, %d min late", plan["id"], (now - was_due) / 60)
                self._tell.append(("Leyla Planer", f"„{plan['titel']}“ war für {at} Uhr geplant, "
                                   "da war ich nicht an. Ich habe es nicht nachgeholt."))
                continue
            self._save()  # claimed on disk before the first switch
            wrong = await self._do(plan)
            plan["lauf"] = {"t": round(self.clock()), "ok": not wrong}
            if wrong:
                plan["lauf"]["probleme"] = wrong[:6]
                self._tell.append(("Leyla Planer", f"„{plan['titel']}“ ({at} Uhr) hat nicht ganz "
                                   "geklappt: " + wrong[0][:160]))
            if plan["status"] == RUNNING:
                plan["status"] = FAILED if wrong else DONE
            self._save()
            ran += 1
            logger.info("Planner: plan %s ran, %s", plan["id"],
                        "%d problem(s)" % len(wrong) if wrong else "ok")
        await self._tell_metin()
        return ran

    async def _do(self, plan: dict) -> list:
        """Run the steps in order. Returns what went wrong ([] when all is well)."""
        wrong = []
        for step in plan["schritte"]:
            label = describe_step(step) if step["geraet"] != SAY else "Ansage"
            try:
                if step["geraet"] == SAY:
                    if not self._say:
                        raise RuntimeError("no announcements here")
                    await self._say(step["argumente"]["text"])
                else:
                    result = await self._run(step["geraet"], dict(step["argumente"]))
                    wrong += [f"{label}: {p}" for p in problems(result)]
            except asyncio.TimeoutError:
                wrong.append(f"{label}: hat zu lange gedauert.")
            except Exception as e:
                logger.warning("Planner: step %s of plan %s failed: %s", step["geraet"],
                               plan["id"], type(e).__name__)
                wrong.append(f"{label}: ging nicht.")
        return wrong

    async def _tell_metin(self) -> None:
        pending, self._tell = self._tell, []
        for title, message in pending:
            if not self._notify:
                continue
            try:
                await self._notify(title, message)
            except Exception as e:
                logger.info("Planner: could not tell Metin: %s", type(e).__name__)

    async def loop(self) -> None:
        """Runs for as long as the add on runs. Nothing a plan does may end it, and a fault
        never makes it spin."""
        while True:
            try:
                delay = self.wait_s()
            except Exception:
                delay = POLL_S
            await asyncio.sleep(delay)
            try:
                await self.tick()
            except Exception as e:
                logger.warning("Planner: %s", type(e).__name__)
                await asyncio.sleep(POLL_S)

    def stats(self) -> dict:
        """Counts and times only, for a check from outside (no titles, no texts)."""
        now = self.clock()
        open_ = self.open_plans()
        count = lambda s: sum(1 for p in self.plans if p.get("status") == s)  # noqa: E731
        return {"offen": len(open_), "erledigt": count(DONE), "fehler": count(FAILED),
                "verpasst": count(MISSED),
                "wiederholt": sum(1 for p in open_ if p.get("wdh") != "einmal"),
                "naechster": f"{self._local(open_[0]['faellig']):%d.%m. %H:%M}" if open_ else None,
                "in_s": round(open_[0]["faellig"] - now) if open_ else None,
                "laeufe": [{"t": f"{self._local(p['lauf']['t']):%d.%m. %H:%M}",
                            "ok": bool(p["lauf"].get("ok")),
                            "verpasst": bool(p["lauf"].get("verpasst")),
                            "schritte": [s["geraet"] for s in p["schritte"]]}
                           for p in self.plans if p.get("lauf")][-10:]}
