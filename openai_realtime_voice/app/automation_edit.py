"""
Pure helpers to read and change Home Assistant automation configs for technik.py: search
words, trigger and action texts, colours, lamp and fan step handling, clock times. No network
access here, only dicts in and out.
"""
import re
from typing import Optional

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
