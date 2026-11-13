"""
Air purifier (Dreo 530S through the HACS integration hass-dreo).

Leyla switches it on or off, sets auto, sleep or turbo mode or a level from 1 to 4,
sets an off timer and tells the air quality from its PM2.5 sensor.
"""
import asyncio
import logging
import os
from typing import Optional

import httpx

from app.freshness import STALE_AFTER_MIN, age_minutes

logger = logging.getLogger(__name__)

DEFAULT_ENTITY = "fan.luftreiniger"
MODES = {"auto": "auto", "schlaf": "sleep", "turbo": "turbo", "manuell": "manual"}

PURIFIER_TOOL = {
    "type": "function",
    "name": "luftreiniger",
    "description": (
        "Control the air purifier (Turkish: hava temizleyici). Switch on or off, set mode "
        "(auto, schlaf, turbo), set the level 1 to 4, set an off timer in minutes, or read "
        "the status with the air quality (fine dust PM2.5)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["status", "an", "aus", "modus", "stufe", "timer"]},
            "modus": {"type": ["string", "null"], "enum": list(MODES) + [None]},
            "stufe": {"type": ["integer", "null"], "description": "Level 1 to 4 for 'stufe'."},
            "minuten": {"type": ["integer", "null"],
                        "description": "Minutes until it switches off for 'timer'; 0 clears it."},
        },
        "required": ["action", "modus", "stufe", "minuten"],
        "additionalProperties": False,
    },
}

PURIFIER_BACKEND_HINT = (
    " You can control the air purifier with luftreiniger: on, off, mode auto, schlaf (quiet "
    "for the night) or turbo, level 1 to 4, an off timer, and the status with the air quality. "
    "For 'wie ist die Luft' or 'hava nasıl' read the status and say the quality in simple "
    "words. Report only what the result says, briefly. If the result has a warning or says the "
    "purifier is not reachable, say exactly that and never give old values as current."
)


def air_quality(pm25) -> str:
    try:
        v = float(pm25)
    except (TypeError, ValueError):
        return "unbekannt"
    if v <= 12:
        return "gut"
    if v <= 35:
        return "mäßig"
    if v <= 55:
        return "schlecht"
    return "sehr schlecht"


class PurifierController:
    def __init__(self, entity: Optional[str] = None, api_url: Optional[str] = None,
                 token: Optional[str] = None) -> None:
        raw = entity if entity is not None else os.environ.get("PURIFIER_ENTITY", DEFAULT_ENTITY)
        self.entity = "" if (raw or "").strip().lower() in ("", "null") else raw.strip()
        self.name = self.entity.split(".", 1)[1] if "." in self.entity else ""
        self.api_url = api_url or os.environ.get("HA_API_URL") or "http://supervisor/core/api"
        self.token = token if token is not None else os.environ.get("SUPERVISOR_TOKEN", "")

    @property
    def available(self) -> bool:
        return bool(self.entity and self.token)

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    async def _state(self, client, eid: str) -> dict:
        resp = await client.get(f"{self.api_url}/states/{eid}", headers=self._headers())
        return resp.json() if resp.status_code == 200 else {"state": "unknown", "attributes": {}}

    async def _service(self, client, domain: str, service: str, data: dict) -> None:
        resp = await client.post(f"{self.api_url}/services/{domain}/{service}", json=data,
                                 headers=self._headers())
        if resp.status_code >= 300:
            raise RuntimeError(f"HA HTTP {resp.status_code}: {resp.text[:200]}")

    async def status(self, client) -> dict:
        try:  # fresh data first, a cloud device can lag; never fails the status
            await asyncio.wait_for(self._service(client, "homeassistant", "update_entity", {
                "entity_id": [self.entity, f"sensor.{self.name}_feinstaub"]}), timeout=6.0)
        except Exception as e:
            logger.info("Purifier refresh did not work: %s", e)
        st = await self._state(client, self.entity)
        if st.get("state") in ("unavailable", "unknown"):
            return {"reachable": False,
                    "error": "Der Luftreiniger ist gerade nicht erreichbar. Seinen Stand kenne "
                             "ich deshalb nicht."}
        a = st.get("attributes", {})
        pm = (await self._state(client, f"sensor.{self.name}_feinstaub")).get("state")
        pct = a.get("percentage")
        age = age_minutes(st)
        info = {"state": st.get("state"), "mode": a.get("preset_mode"),
                "level": round(pct / 25) if isinstance(pct, (int, float)) else None,
                "pm25": pm, "air_quality": air_quality(pm), "data_age_minutes": age}
        if age is not None and age >= STALE_AFTER_MIN:
            info["warning"] = f"Die Daten sind {age} Minuten alt."
        return info

    async def run(self, args: dict) -> dict:
        action = args.get("action") or "status"
        e = {"entity_id": self.entity}
        async with httpx.AsyncClient(timeout=10.0) as client:
            if action == "an":
                await self._service(client, "fan", "turn_on", e)
            elif action == "aus":
                await self._service(client, "fan", "turn_off", e)
            elif action == "modus":
                mode = MODES.get(args.get("modus") or "")
                if not mode:
                    return {"error": "Modus fehlt (auto, schlaf, turbo)."}
                await self._service(client, "fan", "set_preset_mode", dict(e, preset_mode=mode))
            elif action == "stufe":
                level = max(1, min(4, int(args.get("stufe") or 1)))
                await self._service(client, "fan", "set_percentage", dict(e, percentage=level * 25))
            elif action == "timer":
                minutes = max(0, min(719, int(args.get("minuten") or 0)))
                await self._service(client, "number", "set_value",
                                    {"entity_id": f"number.{self.name}_timer_aus",
                                     "value": minutes})
            elif action != "status":
                return {"error": f"Unbekannte Aktion: {action}"}
            return await self.status(client)
