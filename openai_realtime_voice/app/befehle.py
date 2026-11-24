"""
Fixed commands: a sentence of the family that always does exactly the same (2.155.0).

Metin, 24 Nov 2026: he had to teach her for four days (19 to 22 Nov, 27 light commands on the
19th alone) that "Lambaları kapat" from his mother also means the fan light. A rule lived
only as a free sentence in her memory, was stored after the talk, and every time someone said
it the model worked out anew which lamps to switch. Now such a sentence is a command: Metin
sets it once by saying it ("ab jetzt heißt Lichter aus auch das Ventilatorlicht"), it applies
from that moment, and the code switches exactly what was set. The model only has to recognise
the sentence and call the command by name.

A command: a name, the sentences that mean it, lamps to switch on, lamps to switch off, the
fan light (an, aus or untouched) and the fan (aus or untouched). Anyone may use one; only
Metin may set, change or delete one. Stored in /data, not in the repo.
"""
import asyncio
import json
import logging
import os
import re
import time
import unicodedata
from typing import Optional

logger = logging.getLogger(__name__)

PATH = os.environ.get("LEYLA_COMMANDS_PATH", "/data/leyla_befehle.json")
MAX_COMMANDS = 30
MAX_SENTENCES = 8

RUN_TOOL = {
    "type": "function",
    "name": "fester_befehl",
    "description": (
        "Run one of the family's fixed commands by its name (or by one of its sentences). The "
        "code switches exactly what Metin set for it; use this instead of working out lamps "
        "yourself whenever someone says one of the listed sentences or clearly means it."
    ),
    "parameters": {
        "type": "object",
        "properties": {"name": {"type": "string", "description": "Name of the fixed command."}},
        "required": ["name"],
        "additionalProperties": False,
    },
}

SET_TOOL = {
    "type": "function",
    "name": "befehl_festlegen",
    "description": (
        "Set, change or delete a fixed command, only when Metin asks. A command says what "
        "always happens when someone says one of its sentences. To change an existing one give "
        "its name and only what changes (null leaves a part as it is); new sentences are added "
        "to the ones it has. It applies at once."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string",
                     "description": "Short name, for example 'lichter aus'. An existing name "
                                    "changes that command."},
            "saetze": {"type": ["array", "null"], "items": {"type": "string"},
                       "description": "Sentences that mean this command, as people say them "
                                      "(German or Turkish), or null."},
            "lampen_an": {"type": ["array", "null"], "items": {"type": "integer"},
                          "description": "Floor lamp numbers to switch on, [] for none, null "
                                         "to leave as set."},
            "lampen_aus": {"type": ["array", "null"], "items": {"type": "integer"},
                           "description": "Floor lamp numbers to switch off, [] for none, "
                                          "null to leave as set."},
            "ventilatorlicht": {"type": ["string", "null"], "enum": ["an", "aus", "nichts", None],
                                "description": "The fan light: an, aus, nichts (do not touch "
                                               "it), or null to leave as set."},
            "ventilator": {"type": ["string", "null"], "enum": ["aus", "nichts", None],
                           "description": "The fan itself: aus, nichts, or null to leave as set."},
            "loeschen": {"type": "boolean", "description": "true deletes the command."},
        },
        "required": ["name", "saetze", "lampen_an", "lampen_aus", "ventilatorlicht",
                     "ventilator", "loeschen"],
        "additionalProperties": False,
    },
}

HINT_HEAD = (
    " FIXED COMMANDS: for the sentences below the family has fixed what happens. When someone "
    "says one of them, or clearly means the same, call ONLY fester_befehl with that name and no "
    "other tool, and never work out the lamps or the fan yourself; then say briefly what the "
    "result says was done. A request for single lamps, a brightness or a colour is not a fixed "
    "command. The fixed commands:\n")
HINT_SET = (
    " When Metin wants a sentence to always do the same, or wants to change what one does "
    "('ab jetzt heißt Lichter aus auch das Ventilatorlicht'), call befehl_festlegen: it applies "
    "at once, also in this talk. Then tell him in one sentence what applies now, from the "
    "result. If it is not clear which lamps he means, ask before you set it.")


def _key(text: str) -> str:
    text = unicodedata.normalize("NFKD", (text or "").replace("ı", "i")).encode(
        "ascii", "ignore").decode().lower()
    return " ".join(re.findall(r"[a-z0-9]+", text))


def _lamps(value, count: int) -> list:
    out = []
    for n in value if isinstance(value, list) else []:
        try:
            n = int(n)
        except (TypeError, ValueError):
            continue
        if 1 <= n <= count and n not in out:
            out.append(n)
    return sorted(out)


def describe(c: dict) -> str:
    """What a command does, in one German sentence (for her and for the result)."""
    parts = []
    if c.get("lampen_an"):
        parts.append("Stehlampe " + " und ".join(map(str, c["lampen_an"])) + " an")
    if c.get("lampen_aus"):
        parts.append("Stehlampe " + " und ".join(map(str, c["lampen_aus"])) + " aus")
    if c.get("ventilatorlicht") in ("an", "aus"):
        parts.append("Ventilatorlicht " + c["ventilatorlicht"])
    if c.get("ventilator") == "aus":
        parts.append("Ventilator aus")
    return ", ".join(parts) or "nichts"


class Commands:
    def __init__(self, lights=None, fan=None, path: Optional[str] = None) -> None:
        self.lights, self.fan = lights, fan
        self.path = path or PATH

    # ---- the store ----
    def load(self) -> list:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return []
        return [c for c in data if isinstance(c, dict) and c.get("name")] if isinstance(data, list) else []

    def _save(self, commands: list) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(commands, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    def find(self, name: str, commands: Optional[list] = None) -> Optional[dict]:
        """By name, else by one of its sentences (the model may pass what was said)."""
        key = _key(name)
        commands = self.load() if commands is None else commands
        for c in commands:
            if _key(c["name"]) == key:
                return c
        for c in commands:
            if key and key in (_key(s) for s in c.get("saetze", [])):
                return c
        return None

    @property
    def lamp_count(self) -> int:
        return len(getattr(self.lights, "entities", []) or [])

    # ---- what she is told ----
    def hint(self) -> str:
        """For the backend: the commands there are and how to set one."""
        commands = self.load()
        lines = "".join(
            f"- '{c['name']}': " + ", ".join(f"«{s}»" for s in c.get("saetze", [])[:MAX_SENTENCES])
            + f" -> {describe(c)}\n" for c in commands)
        return (HINT_HEAD + lines if commands else "") + HINT_SET

    # ---- using one ----
    async def run(self, args: dict) -> dict:
        c = self.find(str((args or {}).get("name") or ""))
        if not c:
            names = [x["name"] for x in self.load()]
            return {"error": "Diesen festen Befehl gibt es nicht.", "es_gibt": names}
        blank = {"brightness_percent": None, "white": None, "color": None}
        jobs, labels = [], []
        lamps_ok = bool(self.lights and getattr(self.lights, "available", False))
        fan_ok = bool(self.fan and getattr(self.fan, "available", False))
        if c.get("lampen_an") and lamps_ok:
            jobs.append(self.lights.run({"lamps": c["lampen_an"], "action": "on", **blank}))
            labels.append("lampen_an")
        if c.get("lampen_aus") and lamps_ok:
            jobs.append(self.lights.run({"lamps": c["lampen_aus"], "action": "off", **blank}))
            labels.append("lampen_aus")
        fan_steps = []
        if c.get("ventilatorlicht") in ("an", "aus"):
            fan_steps.append("licht_" + c["ventilatorlicht"])
        if c.get("ventilator") == "aus":
            fan_steps.append("aus")
        if fan_steps and fan_ok:
            jobs.append(self._fan(fan_steps))  # one after the other: one remote, one meter
            labels.append("ventilator")
        results = await asyncio.gather(*jobs, return_exceptions=True)
        out = {"ok": True, "befehl": c["name"], "getan": describe(c), "ergebnis": {}}
        problems = []
        if (c.get("lampen_an") or c.get("lampen_aus")) and not lamps_ok:
            problems.append("Die Stehlampen sind gerade nicht erreichbar.")
        if fan_steps and not fan_ok:
            problems.append("Der Ventilator ist gerade nicht erreichbar.")
        for label, r in zip(labels, results):
            if isinstance(r, Exception):
                problems.append(f"{label}: ging nicht")
                logger.warning("Fixed command %s, %s failed: %s", c["name"], label, r)
            else:
                out["ergebnis"][label] = r
                for err in ([r.get("error")] if isinstance(r, dict) else
                            [x.get("error") for x in r if isinstance(x, dict)]):
                    if err:
                        problems.append(str(err))
                if isinstance(r, dict) and r.get("unavailable"):
                    problems.append("Nicht erreichbar: Stehlampe "
                                    + ", ".join(map(str, r["unavailable"])))
        if problems:
            out["ok"] = False
            out["probleme"] = problems
        logger.info("Fixed command '%s': %s%s", c["name"], describe(c),
                    " (problems: %s)" % problems if problems else "")
        return out

    async def _fan(self, steps: list) -> list:
        return [await self.fan.run({"action": s, "speed": None, "hours": None}) for s in steps]

    # ---- setting one ----
    def define(self, args: dict, who: str = "Metin") -> dict:
        args = args or {}
        name = " ".join(str(args.get("name") or "").split())[:40]
        if not _key(name):
            return {"error": "Der Befehl braucht einen Namen."}
        commands = self.load()
        old = self.find(name, commands)
        if args.get("loeschen"):
            if not old:
                return {"error": "Diesen festen Befehl gibt es nicht."}
            commands.remove(old)
            self._save(commands)
            logger.info("Fixed command '%s' deleted", old["name"])
            return {"ok": True, "geloescht": old["name"]}
        c = dict(old) if old else {"name": name, "saetze": [], "lampen_an": [], "lampen_aus": [],
                                   "ventilatorlicht": "nichts", "ventilator": "nichts"}
        seen = {_key(s) for s in c["saetze"]}
        for s in args.get("saetze") or []:
            s = " ".join(str(s).split())[:80]
            if _key(s) and _key(s) not in seen:
                seen.add(_key(s))
                c["saetze"].append(s)
        c["saetze"] = c["saetze"][-MAX_SENTENCES:]
        for field in ("lampen_an", "lampen_aus"):
            if args.get(field) is not None:
                wanted = args[field] if isinstance(args[field], list) else []
                c[field] = _lamps(wanted, self.lamp_count)
                if len(c[field]) != len({int(n) for n in wanted if str(n).lstrip("-").isdigit()}):
                    return {"error": f"Es gibt nur Stehlampe 1 bis {self.lamp_count}."}
        both = set(c["lampen_an"]) & set(c["lampen_aus"])
        if both:
            return {"error": "Stehlampe " + ", ".join(map(str, sorted(both)))
                             + " kann nicht zugleich an und aus gehen."}
        for field, allowed in (("ventilatorlicht", ("an", "aus", "nichts")),
                               ("ventilator", ("aus", "nichts"))):
            if args.get(field) in allowed:
                c[field] = args[field]
        if describe(c) == "nichts":
            return {"error": "Der Befehl muss etwas schalten: Lampen, Ventilatorlicht oder Ventilator."}
        if not c["saetze"]:
            return {"error": "Der Befehl braucht mindestens einen Satz, bei dem er gilt."}
        for other in commands:  # one sentence, one command
            if other is not old and seen & {_key(s) for s in other.get("saetze", [])}:
                return {"error": f"Diesen Satz gibt es schon beim Befehl '{other['name']}'."}
        if not old and len(commands) >= MAX_COMMANDS:
            return {"error": "Mehr feste Befehle gehen nicht, lösch zuerst einen."}
        c["t"], c["von"] = round(time.time()), who
        if old:
            commands[commands.index(old)] = c
        else:
            commands.append(c)
        self._save(commands)
        logger.info("Fixed command '%s' %s: %s", c["name"], "changed" if old else "set", describe(c))
        return {"ok": True, "befehl": c["name"], "saetze": c["saetze"], "gilt_jetzt": describe(c),
                "hinweis": "Gilt ab sofort. Sag Metin in einem Satz, was jetzt gilt."}

    def listing(self) -> list:
        return [dict(c, tut=describe(c)) for c in self.load()]
