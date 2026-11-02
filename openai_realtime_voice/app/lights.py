"""
Living room light control for the voice assistant.

Leyla switches the SwitchBot floor lamps through the Home Assistant REST API
(Supervisor proxy, needs homeassistant_api: true in config.yaml). The lamps are
listed in the add-on option light_entities, in order: the first one is "Lampe 1".
One tool call can switch one lamp, several lamps or all of them, and can set
brightness, warm or cold white, or a color at the same time.
"""
import asyncio
import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_LIGHT_ENTITIES = ("light.wohnzimmer_lamba_1, light.wohnzimmer_lamba_2, "
                          "light.wohnzimmer_lamba_3, light.wohnzimmer_lamba_4")

WHITE_KELVIN = {"warm": 2700, "neutral": 4000, "kalt": 6500}

COLORS = {
    "rot": (255, 0, 0),
    "orange": (255, 110, 0),
    "gelb": (255, 200, 0),
    "gruen": (0, 255, 0),
    "tuerkis": (0, 220, 200),
    "blau": (0, 0, 255),
    "lila": (150, 0, 255),
    "pink": (255, 0, 140),
}

LIGHTS_TOOL = {
    "type": "function",
    "name": "licht_steuern",
    "description": (
        "Control the living room floor lamps (Lampe 1 to 4, Turkish: lamba). Switch on, off, "
        "set brightness in percent, white tone (warm, neutral, kalt) or a color, for one lamp, "
        "several lamps or all lamps. Use action 'status' to read how the lamps are set now."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "lamps": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Lamp numbers, for example [2] or [1, 3]. Empty list means all lamps.",
            },
            "action": {
                "type": "string",
                "enum": ["on", "off", "toggle", "status"],
                "description": "'on' also applies brightness, white or color if given.",
            },
            "brightness_percent": {
                "type": ["integer", "null"],
                "description": "Brightness 1 to 100 percent, or null to keep it.",
            },
            "white": {
                "type": ["string", "null"],
                "enum": ["warm", "neutral", "kalt", None],
                "description": "White tone: warm (2700 K, cozy yellowish), neutral (4000 K), "
                               "kalt (6500 K, bright bluish daylight). Null to keep it.",
            },
            "color": {
                "type": ["string", "null"],
                "enum": list(COLORS) + [None],
                "description": "A color instead of white, or null.",
            },
        },
        "required": ["lamps", "action", "brightness_percent", "white", "color"],
        "additionalProperties": False,
    },
}

LIGHTS_BACKEND_HINT = (
    " You can control the living room floor lamps with licht_steuern: there are {count} lamps, "
    "Lampe 1 to Lampe {count} (Turkish: lamba 1 to {count}). The user may want all lamps or "
    "single ones. They can be switched on or off, dimmed from 1 to 100 percent, set to warm, "
    "neutral or kalt white, or to a color (rot, orange, gelb, gruen, tuerkis, blau, lila, pink). "
    "If the user does not say which lamp, use all lamps. 'Heller' or 'dunkler' means about 25 "
    "percent more or less than now; read the status first if you need the current value. "
    "Confirm very briefly what you did. If the user asks what is possible or seems unsure, "
    "explain these options simply and suggest something fitting, for example warm white at 40 "
    "percent for a cozy evening or kalt white at 100 percent for reading or cleaning."
)


def _env(name: str) -> str:
    value = (os.environ.get(name) or "").strip()
    return "" if value.lower() == "null" else value


def parse_entities(raw: Optional[str]) -> list[str]:
    raw = DEFAULT_LIGHT_ENTITIES if raw is None or raw.strip().lower() == "null" else raw
    return [e.strip() for e in raw.replace(";", ",").split(",") if e.strip()]


def entities_from_env() -> list[str]:
    raw = os.environ.get("LIGHT_ENTITIES")
    return parse_entities(raw)


def build_service_data(args: dict) -> tuple[str, dict]:
    """Translate tool arguments into a Home Assistant light service and its data."""
    action = args.get("action") or "on"
    data: dict = {}
    if action == "off":
        return "turn_off", data
    if action == "toggle":
        return "toggle", data
    brightness = args.get("brightness_percent")
    if brightness is not None:
        data["brightness_pct"] = max(1, min(100, int(brightness)))
    color = args.get("color")
    white = args.get("white")
    if color in COLORS:
        data["rgb_color"] = list(COLORS[color])
    elif white in WHITE_KELVIN:
        data["color_temp_kelvin"] = WHITE_KELVIN[white]
    return "turn_on", data


def select_entities(entities: list[str], lamps) -> tuple[list[str], list[int]]:
    """Return (entity ids, unknown lamp numbers). No lamps means all lamps."""
    if not lamps:
        return list(entities), []
    chosen, unknown = [], []
    for n in lamps:
        try:
            idx = int(n)
        except (TypeError, ValueError):
            continue
        if 1 <= idx <= len(entities):
            if entities[idx - 1] not in chosen:
                chosen.append(entities[idx - 1])
        else:
            unknown.append(idx)
    return chosen, unknown


def describe_state(number: int, state: dict) -> dict:
    attrs = state.get("attributes") or {}
    info: dict = {"lamp": number, "state": state.get("state", "unknown")}
    if info["state"] == "on":
        if attrs.get("brightness") is not None:
            info["brightness_percent"] = round(int(attrs["brightness"]) * 100 / 255)
        if attrs.get("color_mode") in ("color_temp",) and attrs.get("color_temp_kelvin"):
            k = int(attrs["color_temp_kelvin"])
            info["white"] = "warm" if k < 3400 else ("neutral" if k < 5000 else "kalt")
            info["kelvin"] = k
        elif attrs.get("rgb_color"):
            info["rgb_color"] = attrs["rgb_color"]
    return info


class LightController:
    def __init__(self, entities: list[str], api_url: Optional[str] = None,
                 token: Optional[str] = None) -> None:
        self.entities = entities
        self.api_url = (api_url or os.environ.get("HA_API_URL") or "http://supervisor/core/api")
        self.token = token if token is not None else os.environ.get("SUPERVISOR_TOKEN", "")

    @property
    def available(self) -> bool:
        return bool(self.entities and self.token)

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    async def _states(self, client: httpx.AsyncClient, ids: list[str]) -> list[dict]:
        out = []
        for eid in ids:
            resp = await client.get(f"{self.api_url}/states/{eid}", headers=self._headers())
            if resp.status_code != 200:
                out.append({"entity_id": eid, "state": "unknown"})
            else:
                out.append(resp.json())
        return out

    async def run(self, args: dict) -> dict:
        ids, unknown = select_entities(self.entities, args.get("lamps"))
        if not ids:
            return {"error": f"Es gibt nur Lampe 1 bis {len(self.entities)}.",
                    "unknown_lamps": unknown}
        numbers = [self.entities.index(e) + 1 for e in ids]
        async with httpx.AsyncClient(timeout=8.0) as client:
            if args.get("action") != "status":
                service, data = build_service_data(args)
                body = dict(data, entity_id=ids)
                resp = await client.post(f"{self.api_url}/services/light/{service}",
                                         json=body, headers=self._headers())
                if resp.status_code >= 300:
                    raise RuntimeError(f"HA HTTP {resp.status_code}: {resp.text[:200]}")
                logger.info("Lights %s %s %s", service, numbers, data)
                await asyncio.sleep(0.6)  # give the lamps a moment to report back
            states = await self._states(client, ids)
        result = {"lamps": [describe_state(n, s) for n, s in zip(numbers, states)]}
        if unknown:
            result["unknown_lamps"] = unknown
            result["note"] = f"Es gibt nur Lampe 1 bis {len(self.entities)}."
        unavailable = [d["lamp"] for d in result["lamps"] if d["state"] == "unavailable"]
        if unavailable:
            result["unavailable"] = unavailable
            result["hint"] = "Diese Lampen sind nicht erreichbar, vielleicht ausgesteckt."
        return result
