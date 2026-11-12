"""
Read only look at the house technology: Leyla can check automations (is it on, when does it
run, when did it run last, what does it do) and the state of devices, so she can answer
"schaltet die Automation um 23:30 die Lampen aus?" from the real configuration.

She can not change anything with this tool.
"""
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
        "matching a search word. Use it to answer questions about whether something is set up "
        "or switched on."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["automationen", "geraete"]},
            "suche": {"type": ["string", "null"],
                      "description": "Search word, for example 'Lampen', 'Sonnenuntergang', "
                                     "'23:30'. Null lists the first ones."},
        },
        "required": ["action", "suche"],
        "additionalProperties": False,
    },
}

TECHNIK_BACKEND_HINT = (
    " You can check the technology with technik_pruefen (read only): 'automationen' for "
    "questions like 'schaltet die Automation um 23:30 die Lampen aus' or 'wann lief sie zuletzt', "
    "'geraete' for the state of devices. Answer only from the result, in simple words, and say "
    "plainly if no automation matches. You can not change anything with it."
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
            out.append(f"Ereignis {a['event']}")
        else:
            name = a.get("action") or a.get("service")
            if name:
                tgt = _target_text(a)
                out.append(name + (f" auf {tgt}" if tgt else ""))
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


class TechnikChecker:
    def __init__(self, api_url: Optional[str] = None, token: Optional[str] = None) -> None:
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

    async def run(self, args: dict) -> dict:
        action = args.get("action")
        async with httpx.AsyncClient(timeout=10.0) as client:
            if action == "automationen":
                return await self.automations(client, args.get("suche"))
            if action == "geraete":
                return await self.devices(client, args.get("suche"))
        return {"error": f"Unbekannte Aktion: {action}"}
