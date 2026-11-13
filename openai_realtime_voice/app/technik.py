"""
A look at the house technology: Leyla can check automations (is it on, when does it run,
when did it run last, what does it do) and the state of devices, so she can answer
"schaltet die Automation um 23:30 die Lampen aus?" from the real configuration.

She can change four things in an existing automation, only for Metin (main.py lets these
actions through only when the code phrase was heard in the conversation): the clock time of a
time trigger ("zeit_aendern") and the colour, brightness or white tone of the lamps the
automation switches on ("licht_aendern"), and which lamps it switches on ("lampen_aendern":
take some out, add some, or only these) and which fan steps it runs ("ventilator_aendern":
the leyla_command events for the ceiling fan and its light, add, remove or replace). Metin gets a push message about every change.
"""
import re
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

TECHNIK_TOOL = {
    "type": "function",
    "name": "technik_pruefen",
    "description": (
        "Check the house technology, read only. 'automationen' lists the automations matching "
        "a search word with on/off, trigger times, conditions, what they do and when they last "
        "ran. 'geraete' reads the state of devices (lights, switches, fan, TV, sensors) "
        "matching a search word. 'zeit_aendern' changes the clock time of an existing automation, "
        "'licht_aendern' changes the colour, brightness or white tone the lamps get when an "
        "automation switches them on, 'lampen_aendern' changes which lamps it switches on (take "
        "out, add, or only these), 'ventilator_aendern' changes which fan steps it runs, all "
        "four only when Metin asks and said the code phrase. Use the rest to answer questions about "
        "whether something is set up or switched on."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["automationen", "geraete", "zeit_aendern", "licht_aendern",
                               "lampen_aendern", "ventilator_aendern"]},
            "suche": {"type": ["string", "null"],
                      "description": "Search word, for example 'Lampen', 'Sonnenuntergang', "
                                     "'23:30'. Null lists the first ones."},
            "alt": {"type": ["string", "null"],
                    "description": "For 'zeit_aendern': the current time HH:MM when the "
                                   "automation has several times, otherwise null."},
            "lampe": {"type": ["string", "null"],
                      "description": "For 'licht_aendern': a word for one lamp or room, for "
                                     "example 'Wohnzimmer', when the automation switches "
                                     "several lamps and only some should change, else null."},
            "modus": {"type": ["string", "null"], "enum": ["entfernen", "hinzufuegen", "nur", "ersetzen", None],
                      "description": "For 'lampen_aendern': 'entfernen' takes the lamps out "
                                     "of the automation (they stay as they are), "
                                     "'hinzufuegen' adds them, 'nur' makes exactly these "
                                     "lamps the ones it switches on. For 'ventilator_aendern': "
                                     "'hinzufuegen' adds the fan step 'ventilator', "
                                     "'entfernen' removes it, 'ersetzen' replaces it by "
                                     "'ventilator_neu'."},
            "ventilator": {"type": ["string", "null"],
                           "enum": ["aus", "an", "stufe", "licht_an", "licht_aus", "naturwind",
                                    "links", "rechts", "timer", None],
                           "description": "For 'ventilator_aendern': the fan step: aus or an "
                                          "(fan itself), licht_an or licht_aus (fan light), "
                                          "stufe (speed), timer, naturwind, links, rechts."},
            "ventilator_neu": {"type": ["string", "null"],
                               "enum": ["aus", "an", "stufe", "licht_an", "licht_aus",
                                        "naturwind", "links", "rechts", "timer", None],
                               "description": "For 'ventilator_aendern' with modus ersetzen: "
                                              "the new step."},
            "stufe": {"type": ["integer", "null"],
                      "description": "For 'ventilator_aendern': speed 1 to 6 of the step "
                                     "stufe (the new one when replacing), else null."},
            "stunden": {"type": ["integer", "null"],
                        "description": "For 'ventilator_aendern': timer 1, 2 or 4 hours, "
                                       "else null."},
            "lampen": {"type": ["array", "null"], "items": {"type": "string"},
                       "description": "For 'lampen_aendern': the lamps by name as Metin says "
                                      "them, for example ['Wohnzimmer Lamba 1', 'Flur']."},
            "farbe": {"type": ["string", "null"],
                      "description": "For 'licht_aendern': colour in German, for example "
                                     "'rot', 'orange', 'blau', 'warmweiß', 'kaltweiß', or "
                                     "'255,120,0' (red,green,blue). Null keeps it."},
            "helligkeit": {"type": ["integer", "null"],
                           "description": "For 'licht_aendern': brightness 1 to 100 percent. "
                                          "Null keeps it."},
            "neu": {"type": ["string", "null"],
                    "description": "For 'zeit_aendern': the new time HH:MM (24 hours)."},
        },
        "required": ["action", "suche", "alt", "neu", "lampe", "farbe", "helligkeit", "modus",
                     "lampen", "ventilator", "ventilator_neu", "stufe", "stunden"],
        "additionalProperties": False,
    },
}

TECHNIK_BACKEND_HINT = (
    " You can check the technology with technik_pruefen (read only): 'automationen' for "
    "questions like 'schaltet die Automation um 23:30 die Lampen aus' or 'wann lief sie zuletzt', "
    "'geraete' for the state of devices. Answer only from the result, in simple words, and say "
    "plainly if no automation matches. You can make four changes in an automation, only when "
    "Metin himself asks and has said the code phrase: the time with 'zeit_aendern', the "
    "colour, brightness or white tone of its lamps with 'licht_aendern' and which lamps it "
    "switches on with 'lampen_aendern' (modus entfernen, hinzufuegen or nur, lampen by name; "
    "if a name is not clear the result lists the candidates, ask which one) and which steps "
    "it runs for the ceiling fan and its light with 'ventilator_aendern' (modus hinzufuegen, "
    "entfernen or ersetzen; ventilator aus, an, licht_an, licht_aus, stufe, timer and so on). "
    "The fan light is licht_an or licht_aus, the fan itself an or aus. The 23:30 night "
    "check is fixed and cannot be changed this way. First say which "
    "automation and what you understood (times alt to neu, colour and brightness, or which "
    "lamps), and call "
    "it only after he confirms. 'automationen' shows the current colour and brightness of the "
    "lamps, so read it first. If the result says it is not allowed, say that only Metin can "
    "change this. Never change anything else."
)

DEVICE_DOMAINS = ("light", "switch", "fan", "media_player", "vacuum", "climate", "cover",
                  "sensor", "binary_sensor", "input_boolean", "automation", "number", "select")
MAX_RESULTS = 12


def _words(text: Optional[str]) -> list:
    return [w for w in (text or "").lower().replace(":", " ").split() if w]


def _matches(haystack: str, words: list) -> bool:
    h = haystack.lower()
    return all(w in h for w in words)


def _trigger_text(t: dict) -> str:
    kind = t.get("trigger") or t.get("platform") or "?"
    if kind == "time":
        return f"täglich um {t.get('at')}"
    if kind == "sun":
        off = t.get("offset")
        return f"{t.get('event')}" + (f" ({off})" if off else "")
    if kind == "state":
        to = t.get("to")
        ent = t.get("entity_id")
        return f"wenn {ent} " + (f"auf {to} wechselt" if to else "wechselt")
    if kind == "time_pattern":
        return "zeitgesteuert (Muster)"
    return str(kind)


def _target_text(a: dict) -> str:
    target = a.get("target") or {}
    data = a.get("data") or {}
    ents = target.get("entity_id") or data.get("entity_id") or a.get("entity_id")
    if isinstance(ents, list):
        ents = ", ".join(str(e) for e in ents)
    return str(ents) if ents else ""


def _action_texts(actions) -> list:
    out = []
    for a in actions if isinstance(actions, list) else []:
        if not isinstance(a, dict):
            continue
        if "choose" in a:
            for opt in a.get("choose") or []:
                out.extend(_action_texts(opt.get("sequence")))
        elif "if" in a:
            out.extend(_action_texts(a.get("then")))
            out.extend(_action_texts(a.get("else")))
        elif "delay" in a:
            out.append("wartet kurz")
        elif "event" in a:
            data = a.get("event_data") or {}
            if a["event"] == "leyla_command" and data.get("device"):
                step = " ".join(str(data[k]) for k in ("device", "action", "speed", "hours")
                                if data.get(k) is not None)
                out.append(f"Leyla Befehl: {step}")
            else:
                out.append(f"Ereignis {a['event']}")
        else:
            name = a.get("action") or a.get("service")
            if name:
                tgt = _target_text(a)
                text = name + (f" auf {tgt}" if tgt else "")
                look = _light_look(a)
                out.append(text + (f" ({look})" if look else ""))
    return out


LIGHT_KEYS = ("rgb_color", "color_name", "color_temp_kelvin", "color_temp", "kelvin",
              "hs_color", "xy_color", "rgbw_color", "rgbww_color", "brightness_pct",
              "brightness", "effect")
COLOR_KEYS = ("rgb_color", "color_name", "color_temp_kelvin", "color_temp", "kelvin",
              "hs_color", "xy_color", "rgbw_color", "rgbww_color", "effect")
COLORS = {
    "rot": (255, 0, 0), "grün": (0, 200, 0), "gruen": (0, 200, 0), "blau": (0, 0, 255),
    "gelb": (255, 220, 0), "orange": (255, 120, 0), "lila": (150, 0, 255),
    "violett": (150, 0, 255), "pink": (255, 40, 150), "rosa": (255, 120, 170),
    "türkis": (0, 220, 200), "tuerkis": (0, 220, 200), "cyan": (0, 220, 255),
}
WHITES = {"warmweiß": 2700, "warmweiss": 2700, "warm": 2700, "neutralweiß": 4000,
          "neutralweiss": 4000, "weiß": 4000, "weiss": 4000, "kaltweiß": 6000,
          "kaltweiss": 6000, "kalt": 6000, "tageslicht": 5500}


def _light_look(a: dict) -> str:
    """Colour and brightness an action sets, in short words (empty when it sets none)."""
    data = a.get("data") or {}
    parts = [f"{k} {data[k]}" for k in LIGHT_KEYS if k in data]
    return ", ".join(parts)


def parse_color(text: Optional[str]) -> Optional[dict]:
    """'rot', 'warmweiß' or '255,120,0' -> light.turn_on data, None when not understood."""
    t = (text or "").strip().lower()
    if not t:
        return None
    if t in COLORS:
        return {"rgb_color": list(COLORS[t])}
    if t in WHITES:
        return {"color_temp_kelvin": WHITES[t]}
    m = re.match(r"^(\d{1,3})\s*[, ]\s*(\d{1,3})\s*[, ]\s*(\d{1,3})$", t)
    if m and all(int(x) <= 255 for x in m.groups()):
        return {"rgb_color": [int(x) for x in m.groups()]}
    return None


def _light_on_actions(actions) -> list:
    """All light.turn_on actions in a list of actions, also inside choose and if."""
    found = []
    for a in actions if isinstance(actions, list) else []:
        if not isinstance(a, dict):
            continue
        if "choose" in a:
            for opt in a.get("choose") or []:
                found.extend(_light_on_actions(opt.get("sequence")))
            found.extend(_light_on_actions(a.get("default")))
        elif "if" in a:
            found.extend(_light_on_actions(a.get("then")))
            found.extend(_light_on_actions(a.get("else")))
        elif "sequence" in a:
            found.extend(_light_on_actions(a.get("sequence")))
        elif (a.get("action") or a.get("service")) == "light.turn_on":
            found.append(a)
    return found


def _lamp_ids(a: dict):
    """Entity ids a light action targets, None when it targets by area or device."""
    target = a.get("target") or {}
    if target.get("area_id") or target.get("device_id") or target.get("label_id"):
        return None
    data = a.get("data") or {}
    ents = target.get("entity_id") or data.get("entity_id") or a.get("entity_id") or []
    if isinstance(ents, str):
        ents = [e.strip() for e in ents.split(",") if e.strip()]
    return [str(e) for e in ents]


def _set_lamp_ids(a: dict, ids: list) -> None:
    a.setdefault("target", {})["entity_id"] = list(ids)
    (a.get("data") or {}).pop("entity_id", None)
    a.pop("entity_id", None)


def _filter_light_actions(actions, keep) -> list:
    """Same list of actions, where light.turn_on actions for which keep(action) is False are
    dropped, also inside choose, if and sequence."""
    return _filter_actions(actions, lambda a: (a.get("action") or a.get("service"))
                           == "light.turn_on" and not keep(a))


FAN_STEPS = ("aus", "an", "stufe", "licht_an", "licht_aus", "naturwind", "links", "rechts",
             "timer")


def _find_steps(actions, match) -> list:
    """All actions for which match(action) is true, also inside choose, if and sequence."""
    found = []
    for a in actions if isinstance(actions, list) else []:
        if not isinstance(a, dict):
            continue
        if "choose" in a:
            for opt in a.get("choose") or []:
                found.extend(_find_steps(opt.get("sequence"), match))
            found.extend(_find_steps(a.get("default"), match))
        elif "if" in a:
            found.extend(_find_steps(a.get("then"), match))
            found.extend(_find_steps(a.get("else"), match))
        elif "sequence" in a:
            found.extend(_find_steps(a.get("sequence"), match))
        elif match(a):
            found.append(a)
    return found


def _is_fan_step(a: dict) -> bool:
    data = a.get("event_data") or {}
    return a.get("event") == "leyla_command" and str(data.get("device", "")).lower() in (
        "ventilator", "fan")


def _fan_event(step: str, speed, hours) -> dict:
    data = {"device": "ventilator", "action": step}
    if step == "stufe":
        data["speed"] = speed
    if step == "timer":
        data["hours"] = hours
    return {"event": "leyla_command", "event_data": data}


def _check_fan_step(step, speed, hours):
    """Error text when the fan step is not valid, else None."""
    if step not in FAN_STEPS:
        return "Welcher Ventilator Schritt? Zum Beispiel an, aus, licht_an oder licht_aus."
    if step == "stufe" and not (isinstance(speed, int) and 1 <= speed <= 6):
        return "Die Stufe muss zwischen 1 und 6 liegen."
    if step == "timer" and hours not in (1, 2, 4):
        return "Der Timer kann nur 1, 2 oder 4 Stunden."
    return None


def _filter_actions(actions, drop) -> list:
    """Same list of actions without the ones for which drop(action) is true, also inside
    choose, if and sequence."""
    out = []
    for a in actions if isinstance(actions, list) else []:
        if isinstance(a, dict):
            if "choose" in a:
                for opt in a.get("choose") or []:
                    opt["sequence"] = _filter_actions(opt.get("sequence"), drop)
                if "default" in a:
                    a["default"] = _filter_actions(a.get("default"), drop)
            elif "if" in a:
                a["then"] = _filter_actions(a.get("then"), drop)
                if "else" in a:
                    a["else"] = _filter_actions(a.get("else"), drop)
            elif "sequence" in a:
                a["sequence"] = _filter_actions(a.get("sequence"), drop)
            elif drop(a):
                continue
        out.append(a)
    return out


def _condition_texts(conds) -> list:
    out = []
    for c in conds if isinstance(conds, list) else []:
        if not isinstance(c, dict):
            continue
        kind = c.get("condition", "?")
        if kind == "time":
            out.append(f"Uhrzeit {c.get('after', '')} bis {c.get('before', '')}".strip())
            if c.get("weekday"):
                out.append("Wochentage " + ",".join(c["weekday"]))
        elif kind == "state":
            out.append(f"{c.get('entity_id')} ist {c.get('state')}")
        else:
            out.append(kind)
    return out


TIME_RE = re.compile(r"^\s*(\d{1,2})[:.](\d{2})\s*$")


def parse_time(text: Optional[str]) -> Optional[str]:
    """'23:45' -> '23:45:00', None when it is not a valid clock time."""
    m = TIME_RE.match(text or "")
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    return f"{h:02d}:{mi:02d}:00" if h < 24 and mi < 60 else None


class TechnikChecker:
    def __init__(self, api_url: Optional[str] = None, token: Optional[str] = None,
                 notify=None) -> None:
        self.notify = notify  # async (title, message), set by main when push is available
        self.api_url = api_url or os.environ.get("HA_API_URL") or "http://supervisor/core/api"
        self.token = token if token is not None else os.environ.get("SUPERVISOR_TOKEN", "")

    @property
    def available(self) -> bool:
        return bool(self.token)

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    async def _get(self, client, path: str):
        resp = await client.get(f"{self.api_url}/{path}", headers=self._headers())
        return resp.json() if resp.status_code == 200 else None

    async def _timezone(self, client):
        cfg = await self._get(client, "config") or {}
        name = cfg.get("time_zone")
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(name) if name else timezone.utc
        except Exception:
            return timezone.utc

    @staticmethod
    def _local(ts: Optional[str], tz) -> Optional[str]:
        if not ts:
            return None
        try:
            return datetime.fromisoformat(ts).astimezone(tz).strftime("%d.%m.%Y %H:%M")
        except ValueError:
            return ts

    async def automations(self, client, search: Optional[str]) -> dict:
        states = await self._get(client, "states") or []
        tz = await self._timezone(client)
        words = _words(search)
        found = []
        for st in states:
            if not st.get("entity_id", "").startswith("automation."):
                continue
            attrs = st.get("attributes", {})
            alias = attrs.get("friendly_name") or st["entity_id"]
            cfg = await self._get(client, f"config/automation/config/{attrs.get('id')}") \
                if attrs.get("id") else None
            cfg = cfg or {}
            triggers = [_trigger_text(t) for t in (cfg.get("triggers") or cfg.get("trigger") or [])
                        if isinstance(t, dict)]
            actions = _action_texts(cfg.get("actions") or cfg.get("action"))
            conditions = _condition_texts(cfg.get("conditions") or cfg.get("condition"))
            text = " ".join([alias, cfg.get("description") or "", *triggers, *actions])
            if words and not _matches(text, words):
                continue
            found.append({
                "name": alias,
                "eingeschaltet": st.get("state") == "on",
                "ausloeser": triggers,
                "bedingungen": conditions,
                "macht": actions[:8],
                "beschreibung": cfg.get("description"),
                "zuletzt_gelaufen": self._local(attrs.get("last_triggered"), tz),
            })
            if len(found) >= MAX_RESULTS:
                break
        jetzt = datetime.now(tz).strftime("%d.%m.%Y %H:%M")
        if not found:
            return {"jetzt": jetzt, "treffer": 0, "hinweis": "Keine passende Automation."}
        return {"jetzt": jetzt, "treffer": len(found), "automationen": found}

    async def devices(self, client, search: Optional[str]) -> dict:
        states = await self._get(client, "states") or []
        words = _words(search)
        found = []
        for st in states:
            eid = st.get("entity_id", "")
            if eid.split(".", 1)[0] not in DEVICE_DOMAINS:
                continue
            name = st.get("attributes", {}).get("friendly_name") or eid
            if words and not _matches(f"{eid} {name}", words):
                continue
            found.append({"name": name, "zustand": st.get("state")})
            if len(found) >= MAX_RESULTS:
                break
        if not found:
            return {"treffer": 0, "hinweis": "Kein passendes Gerät."}
        return {"treffer": len(found), "geraete": found}

    async def change_time(self, client, search: Optional[str], old: Optional[str],
                          new: Optional[str]) -> dict:
        """Change the clock time of one time trigger of the one automation that matches."""
        new_t = parse_time(new)
        if not new_t:
            return {"error": "Die neue Uhrzeit habe ich nicht verstanden (Format HH:MM)."}
        words = _words(search)
        if not words:
            return {"error": "Welche Automation? Es fehlt ein Suchwort."}
        states = await self._get(client, "states") or []
        matches = []
        for st in states:
            attrs = st.get("attributes", {})
            if not st.get("entity_id", "").startswith("automation.") or not attrs.get("id"):
                continue
            cfg = await self._get(client, f"config/automation/config/{attrs['id']}") or {}
            trigs = cfg.get("triggers") or cfg.get("trigger") or []
            times = [t for t in trigs if isinstance(t, dict)
                     and (t.get("trigger") or t.get("platform")) == "time"
                     and isinstance(t.get("at"), str) and parse_time(t["at"][:5])]
            text = " ".join([attrs.get("friendly_name") or "", cfg.get("description") or "",
                             *[_trigger_text(t) for t in trigs if isinstance(t, dict)],
                             *_action_texts(cfg.get("actions") or cfg.get("action"))])
            if _matches(text, words):
                matches.append((attrs["id"], attrs.get("friendly_name") or attrs["id"],
                                cfg, times))
        if not matches:
            return {"error": "Keine passende Automation gefunden."}
        if len(matches) > 1:
            return {"error": "Mehrere Automationen passen, welche meinst du?",
                    "automationen": [m[1] for m in matches][:6]}
        aid, name, cfg, times = matches[0]
        if not times:
            return {"error": f"{name} hat keine feste Uhrzeit, die ich ändern könnte."}
        if len(times) > 1:
            want = parse_time(old)
            picked = [t for t in times if want and parse_time(t["at"][:5]) == want]
            if len(picked) != 1:
                return {"error": "Die Automation hat mehrere Uhrzeiten, welche ändern?",
                        "uhrzeiten": [t["at"][:5] for t in times]}
            times = picked
        trig = times[0]
        before = trig["at"][:5]
        trig["at"] = new_t
        resp = await client.post(f"{self.api_url}/config/automation/config/{aid}", json=cfg,
                                 headers=self._headers())
        if resp.status_code >= 300:
            raise RuntimeError(f"HA HTTP {resp.status_code}: {resp.text[:200]}")
        logger.info("Automation %s: time %s -> %s", aid, before, new_t[:5])
        if self.notify:
            try:
                await self.notify("Leyla hat eine Zeit geändert",
                                  f"{name}: von {before} auf {new_t[:5]} Uhr.")
            except Exception as e:
                logger.warning("Could not push the time change: %s", e)
        return {"geaendert": name, "von": before, "auf": new_t[:5]}

    async def _find_one(self, client, search: Optional[str]):
        """(id, name, config) of the one automation matching the search, else an error dict."""
        words = _words(search)
        if not words:
            return {"error": "Welche Automation? Es fehlt ein Suchwort."}
        states = await self._get(client, "states") or []
        matches = []
        for st in states:
            attrs = st.get("attributes", {})
            if not st.get("entity_id", "").startswith("automation.") or not attrs.get("id"):
                continue
            cfg = await self._get(client, f"config/automation/config/{attrs['id']}") or {}
            trigs = cfg.get("triggers") or cfg.get("trigger") or []
            text = " ".join([attrs.get("friendly_name") or "", cfg.get("description") or "",
                             *[_trigger_text(t) for t in trigs if isinstance(t, dict)],
                             *_action_texts(cfg.get("actions") or cfg.get("action"))])
            if _matches(text, words):
                matches.append((attrs["id"], attrs.get("friendly_name") or attrs["id"], cfg))
        if not matches:
            return {"error": "Keine passende Automation gefunden."}
        if len(matches) > 1:
            return {"error": "Mehrere Automationen passen, welche meinst du?",
                    "automationen": [m[1] for m in matches][:6]}
        return matches[0]

    async def _resolve_lamps(self, client, names):
        """Names as Metin says them -> light entity ids, or an error dict with candidates."""
        if not isinstance(names, list) or not [n for n in names if str(n).strip()]:
            return {"error": "Welche Lampen? Es fehlen die Namen."}
        lights = [(st["entity_id"], (st.get("attributes") or {}).get("friendly_name") or "")
                  for st in (await self._get(client, "states") or [])
                  if st.get("entity_id", "").startswith("light.")]
        ids = []
        for name in names:
            words = _words(str(name))
            exact = [e for e, f in lights if f.lower() == str(name).strip().lower()]
            hits = exact or [e for e, f in lights if _matches(f"{e} {f}", words)]
            if len(hits) != 1:
                return {"error": f"Die Lampe '{name}' ist nicht eindeutig." if hits
                        else f"Die Lampe '{name}' habe ich nicht gefunden.",
                        "lampen": [f or e for e, f in lights
                                   if not hits or e in hits][:12]}
            if hits[0] not in ids:
                ids.append(hits[0])
        return ids

    async def change_lamps(self, client, search: Optional[str], mode: Optional[str],
                           names) -> dict:
        """Take lamps out of, add them to, or restrict the lamps the light.turn_on actions of
        the one matching automation switch on. Colours and brightness stay as they are."""
        if mode not in ("entfernen", "hinzufuegen", "nur"):
            return {"error": "Es fehlt, ob Lampen entfernt, hinzugefügt oder nur diese "
                             "geschaltet werden sollen."}
        found = await self._find_one(client, search)
        if isinstance(found, dict):
            return found
        aid, name, cfg = found
        ids = await self._resolve_lamps(client, names)
        if isinstance(ids, dict):
            return ids
        key = "actions" if "actions" in cfg or "action" not in cfg else "action"
        lamp_actions = _light_on_actions(cfg.get(key))
        if not lamp_actions:
            return {"error": f"{name} schaltet keine Lampen direkt ein (zum Beispiel über eine "
                             "Szene), deshalb kann ich die Lampen dort nicht ändern."}
        if any(_lamp_ids(a) is None for a in lamp_actions):
            return {"error": f"{name} wählt die Lampen über einen Bereich oder ein Gerät, "
                             "das kann ich nicht ändern."}
        if mode in ("entfernen", "nur"):
            for a in lamp_actions:
                _set_lamp_ids(a, [e for e in _lamp_ids(a) if (e in ids) == (mode == "nur")])
            cfg[key] = _filter_light_actions(cfg.get(key), lambda a: bool(_lamp_ids(a)))
        remaining = _light_on_actions(cfg[key])
        if mode in ("hinzufuegen", "nur"):
            have = {e for a in remaining for e in _lamp_ids(a)}
            missing = [e for e in ids if e not in have]
            if missing:
                if not remaining:  # "nur" with lamps that none of the actions had
                    return {"error": "Diese Lampen sind in der Automation nicht dabei, ich "
                                     "ändere nichts."}
                _set_lamp_ids(remaining[0], _lamp_ids(remaining[0]) + missing)
        if not _light_on_actions(cfg[key]):
            return {"error": "Dann würde die Automation gar keine Lampe mehr einschalten, "
                             "deshalb ändere ich nichts."}
        resp = await client.post(f"{self.api_url}/config/automation/config/{aid}", json=cfg,
                                 headers=self._headers())
        if resp.status_code >= 300:
            raise RuntimeError(f"HA HTTP {resp.status_code}: {resp.text[:200]}")
        now = sorted({e for a in _light_on_actions(cfg[key]) for e in _lamp_ids(a)})
        logger.info("Automation %s: lamps %s %s", aid, mode, ids)
        if self.notify:
            try:
                await self.notify("Leyla hat Lampen geändert",
                                  f"{name}: Lampen {mode}: {', '.join(ids)}.")
            except Exception as e:
                logger.warning("Could not push the lamp change: %s", e)
        return {"geaendert": name, "modus": mode, "lampen": ids, "schaltet_jetzt": now}

    async def change_fan(self, client, search: Optional[str], mode: Optional[str], step,
                         new_step, speed, hours) -> dict:
        """Add, remove or replace the fan steps (leyla_command events for the ceiling fan) of
        the one matching automation. Everything else in it stays."""
        if mode not in ("hinzufuegen", "entfernen", "ersetzen"):
            return {"error": "Es fehlt, ob der Schritt hinzugefügt, entfernt oder ersetzt "
                             "werden soll."}
        if mode == "ersetzen":
            err = _check_fan_step(new_step, speed, hours)
        elif mode == "hinzufuegen":
            err = _check_fan_step(step, speed, hours)
        else:
            err = None if step in FAN_STEPS else \
                "Welcher Ventilator Schritt soll weg? Zum Beispiel licht_an."
        if err:
            return {"error": err}
        if mode == "ersetzen" and step not in FAN_STEPS:
            return {"error": "Welcher Ventilator Schritt soll ersetzt werden?"}
        found = await self._find_one(client, search)
        if isinstance(found, dict):
            return found
        aid, name, cfg = found
        key = "actions" if "actions" in cfg or "action" not in cfg else "action"
        actions = cfg.get(key) if isinstance(cfg.get(key), list) else []

        def is_old(a):
            return _is_fan_step(a) and (a.get("event_data") or {}).get("action") == step

        if mode in ("entfernen", "ersetzen"):
            if not any(_find_steps(actions, is_old)):
                return {"error": f"{name} hat keinen Ventilator Schritt '{step}'."}
        if mode == "entfernen":
            cfg[key] = _filter_actions(actions, is_old)
        elif mode == "ersetzen":
            for a in _find_steps(actions, is_old):
                a["event_data"] = _fan_event(new_step, speed, hours)["event_data"]
        else:
            actions.append(_fan_event(step, speed, hours))
            cfg[key] = actions
        resp = await client.post(f"{self.api_url}/config/automation/config/{aid}", json=cfg,
                                 headers=self._headers())
        if resp.status_code >= 300:
            raise RuntimeError(f"HA HTTP {resp.status_code}: {resp.text[:200]}")
        shown = {"hinzufuegen": f"Ventilator {step} dazu", "entfernen": f"Ventilator {step} weg",
                 "ersetzen": f"Ventilator {step} durch {new_step}"}[mode]
        logger.info("Automation %s: %s", aid, shown)
        if self.notify:
            try:
                await self.notify("Leyla hat den Ventilator geändert", f"{name}: {shown}.")
            except Exception as e:
                logger.warning("Could not push the fan change: %s", e)
        return {"geaendert": name, "jetzt": [a for a in _action_texts(cfg[key])
                                             if a.startswith("Leyla Befehl")]}

    async def change_light(self, client, search: Optional[str], lamp: Optional[str],
                           color: Optional[str], brightness) -> dict:
        """Change colour, brightness or white tone in the light.turn_on actions of the one
        automation that matches. Nothing else in the automation is touched."""
        new = {}
        if color:
            parsed = parse_color(color)
            if not parsed:
                return {"error": "Die Farbe habe ich nicht verstanden."}
            new.update(parsed)
        if brightness is not None:
            if not isinstance(brightness, int) or isinstance(brightness, bool) \
                    or not 1 <= brightness <= 100:
                return {"error": "Die Helligkeit muss zwischen 1 und 100 Prozent liegen."}
            new["brightness_pct"] = brightness
        if not new:
            return {"error": "Es fehlt eine Farbe oder eine Helligkeit."}
        found = await self._find_one(client, search)
        if isinstance(found, dict):
            return found
        aid, name, cfg = found
        lamp_words = _words(lamp)
        actions = [a for a in _light_on_actions(cfg.get("actions") or cfg.get("action"))
                   if not lamp_words or _matches(_target_text(a), lamp_words)]
        if not actions:
            return {"error": f"{name} schaltet keine Lampen direkt ein (zum Beispiel über eine "
                             "Szene), deshalb kann ich ihre Farbe dort nicht ändern."}
        for a in actions:
            data = a.setdefault("data", {})
            if any(k in new for k in COLOR_KEYS):
                for k in COLOR_KEYS:
                    data.pop(k, None)
            data.update(new)
        resp = await client.post(f"{self.api_url}/config/automation/config/{aid}", json=cfg,
                                 headers=self._headers())
        if resp.status_code >= 300:
            raise RuntimeError(f"HA HTTP {resp.status_code}: {resp.text[:200]}")
        what = ", ".join(x for x in [color, f"{brightness} Prozent" if brightness else None] if x)
        logger.info("Automation %s: light changed to %s", aid, new)
        if self.notify:
            try:
                await self.notify("Leyla hat Lampen geändert", f"{name}: jetzt {what}.")
            except Exception as e:
                logger.warning("Could not push the light change: %s", e)
        return {"geaendert": name, "lampen": len(actions), "jetzt": what}

    async def run(self, args: dict) -> dict:
        action = args.get("action")
        async with httpx.AsyncClient(timeout=10.0) as client:
            if action == "automationen":
                return await self.automations(client, args.get("suche"))
            if action == "geraete":
                return await self.devices(client, args.get("suche"))
            if action == "zeit_aendern":
                return await self.change_time(client, args.get("suche"), args.get("alt"),
                                              args.get("neu"))
            if action == "ventilator_aendern":
                return await self.change_fan(client, args.get("suche"), args.get("modus"),
                                             args.get("ventilator"), args.get("ventilator_neu"),
                                             args.get("stufe"), args.get("stunden"))
            if action == "lampen_aendern":
                return await self.change_lamps(client, args.get("suche"), args.get("modus"),
                                               args.get("lampen"))
            if action == "licht_aendern":
                return await self.change_light(client, args.get("suche"), args.get("lampe"),
                                               args.get("farbe"), args.get("helligkeit"))
        return {"error": f"Unbekannte Aktion: {action}"}
