"""
Robot vacuum (Dreame X60 through the Dreame Vacuum integration from HACS).

Leyla can start a full clean or single rooms, choose sweeping or mopping and the
suction, pause, stop, send the robot back to its station and tell the status:
battery, what it is doing, water tanks, dust bag and how much life the brushes and the
filter have left. Rooms come from the vacuum's own map (attribute "rooms"), so names
like Küche or Flur work, and the common Turkish names are mapped to them.
"""
import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_ENTITY = "vacuum.x60_pro_ultra_complete"

MODES = {
    "saugen": "sweeping",
    "wischen": "mopping",
    "saugen_und_wischen": "sweeping and mopping",
    "erst_saugen_dann_wischen": "mopping after sweeping",
}
SUCTION = {
    "leise": ("quiet", "silent"),
    "standard": ("standard",),
    "stark": ("strong",),
    "turbo": ("turbo",),
}
# Turkish (and a few German) room words -> the German names used on the map
ROOM_ALIASES = {
    "mutfak": "küche", "mutfağ": "küche", "kueche": "küche", "koridor": "flur", "antre": "flur", "hol": "flur",
    "salon": "wohnzimmer", "oturma odası": "wohnzimmer", "oturma odasi": "wohnzimmer",
    "banyo": "bad", "badezimmer": "bad", "yatak odası": "schlafzimmer",
    "yatak odasi": "schlafzimmer",
}

VACUUM_TOOL = {
    "type": "function",
    "name": "saugroboter",
    "description": (
        "Control the robot vacuum (Turkish: robot süpürge). Start a full clean or single rooms, "
        "choose sweeping or mopping and the suction, pause, stop, send it back to the station, "
        "or read the status (battery, what it does, water tanks, dust bag, brushes and filter)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["status", "starten", "raeume", "pause", "stopp", "zurueck", "wartung"],
                "description": "starten = whole home, raeume = only the given rooms, "
                               "zurueck = back to the station, wartung = brushes, filter, "
                               "tanks and dust bag.",
            },
            "rooms": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Room names for 'raeume', as on the map (for example Küche, "
                               "Flur). Empty otherwise.",
            },
            "modus": {
                "type": ["string", "null"],
                "enum": list(MODES) + [None],
                "description": "Cleaning mode, or null to keep the current one.",
            },
            "staerke": {
                "type": ["string", "null"],
                "enum": list(SUCTION) + [None],
                "description": "Suction, or null to keep the current one.",
            },
        },
        "required": ["action", "rooms", "modus", "staerke"],
        "additionalProperties": False,
    },
}

VACUUM_BACKEND_HINT = (
    " You can control the robot vacuum with saugroboter. 'Saug die Küche' or 'mutfağı süpür' "
    "means action raeume with that room; 'wisch' means modus wischen; without a room it is the "
    "whole home (starten). Translate Turkish room names to the German names on the map; if you "
    "do not know the rooms, read the status first, it lists them. The suction is always turbo, "
    "set automatically; if asked for quieter, say that Metin wants it always at full power. For 'wo ist er', 'ist er fertig', 'Wassertank' or 'wann muss die Bürste gewechselt "
    "werden' read the status or wartung. 'Kanten und Ecken' or 'kenarları temizle' needs no "
    "special mode: the normal clean with modus saugen_und_wischen already cleans the edges "
    "with the extended mop, so start that (rooms if named) and say he cleans the edges too. "
    "Report only what the result says, briefly."
)


def _norm(text: str) -> str:
    return " ".join((text or "").lower().replace("_", " ").split())


def pick_option(options: list, wanted) -> Optional[str]:
    """The select option that matches one of the wanted words (case and _ ignored)."""
    wanted = [wanted] if isinstance(wanted, str) else list(wanted)
    for w in wanted:
        for o in options or []:
            if _norm(o) == _norm(w):
                return o
    return None


def map_rooms(rooms_attr) -> dict:
    """{"küche": 1, "flur": 2} from the vacuum's rooms attribute (first map)."""
    out: dict = {}
    if isinstance(rooms_attr, dict):
        maps = list(rooms_attr.values())
        rooms = maps[0] if maps else []
    else:
        rooms = rooms_attr or []
    for r in rooms if isinstance(rooms, list) else []:
        if isinstance(r, dict) and r.get("name") and r.get("id") is not None:
            out[_norm(r["name"])] = r["id"]
    return out


def match_rooms(names: list, rooms: dict) -> tuple[list, list]:
    """(segment ids, unknown names) for the asked rooms."""
    ids, unknown = [], []
    for name in names or []:
        key = _norm(name)
        key = ROOM_ALIASES.get(key, key)
        rid = rooms.get(key)
        if rid is None:  # "die Küche" or "mutfağı": look for a room name inside
            rid = next((v for k, v in rooms.items() if k in key), None)
        if rid is None:
            alias = next((v for k, v in ROOM_ALIASES.items() if k in key), None)
            rid = rooms.get(alias) if alias else None
        if rid is None:
            unknown.append(name)
        elif rid not in ids:
            ids.append(rid)
    return ids, unknown


class VacuumController:
    def __init__(self, entity: Optional[str] = None, api_url: Optional[str] = None,
                 token: Optional[str] = None) -> None:
        raw = entity if entity is not None else os.environ.get("VACUUM_ENTITY", DEFAULT_ENTITY)
        self.entity = "" if (raw or "").strip().lower() in ("", "null") else raw.strip()
        self.prefix = self.entity.split(".", 1)[1] if "." in self.entity else ""
        self.api_url = api_url or os.environ.get("HA_API_URL") or "http://supervisor/core/api"
        self.token = token if token is not None else os.environ.get("SUPERVISOR_TOKEN", "")

    @property
    def available(self) -> bool:
        return bool(self.entity and self.token)

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    async def _state(self, client: httpx.AsyncClient, eid: str) -> dict:
        resp = await client.get(f"{self.api_url}/states/{eid}", headers=self._headers())
        return resp.json() if resp.status_code == 200 else {"state": "unknown", "attributes": {}}

    async def _service(self, client: httpx.AsyncClient, domain: str, service: str,
                       data: dict) -> None:
        resp = await client.post(f"{self.api_url}/services/{domain}/{service}", json=data,
                                 headers=self._headers())
        if resp.status_code >= 300:
            raise RuntimeError(f"HA HTTP {resp.status_code}: {resp.text[:200]}")

    async def _select(self, client, name: str, wanted) -> Optional[str]:
        eid = f"select.{self.prefix}_{name}"
        options = (await self._state(client, eid)).get("attributes", {}).get("options") or []
        option = pick_option(options, wanted)
        if option:
            await self._service(client, "select", "select_option",
                                {"entity_id": eid, "option": option})
        return option

    async def _sensor(self, client, name: str) -> str:
        return (await self._state(client, f"sensor.{self.prefix}_{name}")).get("state", "unknown")

    async def status(self, client, maintenance: bool = False) -> dict:
        st = await self._state(client, self.entity)
        a = st.get("attributes", {})
        info = {
            "state": st.get("state"),
            "status": a.get("status"),
            "battery_percent": a.get("battery_level"),
            "current_room": await self._sensor(client, "current_room"),
            "cleaning_progress": await self._sensor(client, "cleaning_progress"),
            "error": a.get("error"),
            "low_water_warning": a.get("low_water_warning"),
            "cleaning_mode": a.get("cleaning_mode"),
            "suction_level": a.get("suction_level"),
            "rooms": [r for r in map_rooms(a.get("rooms"))],
        }
        if maintenance:
            info.update({
                "main_brush_left_percent": a.get("main_brush_left"),
                "side_brush_left_percent": a.get("side_brush_left"),
                "filter_left_percent": a.get("filter_left"),
                "clean_water_tank": await self._sensor(client, "clean_water_tank_status"),
                "dirty_water_tank": await self._sensor(client, "dirty_water_tank_status"),
                "dust_bag": await self._sensor(client, "dust_bag_status"),
                "detergent": await self._sensor(client, "detergent_status"),
            })
        return info

    async def run(self, args: dict) -> dict:
        action = args.get("action") or "status"
        async with httpx.AsyncClient(timeout=10.0) as client:
            if action in ("status", "wartung"):
                return await self.status(client, maintenance=action == "wartung")
            done: dict = {}
            if action in ("starten", "raeume"):
                if args.get("modus") in MODES:
                    done["modus"] = await self._select(client, "cleaning_mode",
                                                       MODES[args["modus"]])
                # Metin's rule: always the highest suction, no exception, whatever is asked
                done["staerke"] = await self._select(client, "suction_level",
                                                     SUCTION["turbo"])
            if action == "starten":
                await self._service(client, "vacuum", "start", {"entity_id": self.entity})
            elif action == "raeume":
                st = await self._state(client, self.entity)
                rooms = map_rooms(st.get("attributes", {}).get("rooms"))
                ids, unknown = match_rooms(args.get("rooms") or [], rooms)
                if not ids:
                    return {"error": "Diese Räume kenne ich nicht.", "unknown": unknown,
                            "rooms": list(rooms)}
                await self._service(client, "dreame_vacuum", "vacuum_clean_segment",
                                    {"entity_id": self.entity, "segments": ids})
                done["rooms"] = [k for k, v in rooms.items() if v in ids]
                if unknown:
                    done["unknown_rooms"] = unknown
            elif action == "pause":
                await self._service(client, "vacuum", "pause", {"entity_id": self.entity})
            elif action == "stopp":
                await self._service(client, "vacuum", "stop", {"entity_id": self.entity})
            elif action == "zurueck":
                await self._service(client, "vacuum", "return_to_base",
                                    {"entity_id": self.entity})
            else:
                return {"error": f"Unbekannte Aktion: {action}"}
            done["sent"] = action
            return done
