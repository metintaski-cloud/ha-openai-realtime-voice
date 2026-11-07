"""
Living room TV control for the voice assistant.

The TV is an Android TV paired with Home Assistant (Android TV Remote integration):
power and volume go over WLAN through its remote entity. The channels come from a
satellite receiver without network, so channel numbers are sent as infrared codes
through the Broadlink RM4 Pro (app/rf.py). The receiver digits were learned as
rx_null .. rx_neun and its power button as rx_power.

Channel names are configured as "name=number" pairs, e.g. "atv Avrupa=1; A Haber=2".
"""
import asyncio
import logging
import os
import re
import unicodedata
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_CHANNELS = "atv Avrupa=1; A Haber=2; Euro D=6"
DEFAULT_TV_REMOTE = "remote.android_tv"
DEFAULT_TV_PLAYER = "media_player.android_tv_2"
DIGITS = ["null", "eins", "zwei", "drei", "vier", "fuenf", "sechs", "sieben", "acht", "neun"]


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", text.lower())


def parse_channels(raw: Optional[str]) -> dict[str, int]:
    raw = DEFAULT_CHANNELS if raw is None or raw.strip().lower() in ("", "null") else raw
    out: dict[str, int] = {}
    for part in re.split(r"[;\n]", raw):
        if "=" not in part:
            continue
        name, num = part.rsplit("=", 1)
        try:
            out[name.strip()] = int(num.strip())
        except ValueError:
            continue
    return out


def find_channel(channels: dict[str, int], wanted) -> Optional[tuple[str, int]]:
    if wanted is None:
        return None
    if isinstance(wanted, int) or str(wanted).strip().isdigit():
        n = int(wanted)
        for name, num in channels.items():
            if num == n:
                return name, n
        return f"Programm {n}", n
    key = _norm(str(wanted))
    for name, num in channels.items():
        if _norm(name) == key:
            return name, num
    for name, num in channels.items():
        if key and (key in _norm(name) or _norm(name) in key):
            return name, num
    return None


def build_tool(channels: dict[str, int]) -> dict:
    names = ", ".join(f"{n} ({c})" for n, c in channels.items())
    return {
        "type": "function",
        "name": "fernseher_steuern",
        "description": (
            "Control the living room TV (Turkish: televizyon) and its satellite receiver. "
            "an or aus: TV power. kanal: switch the receiver to a channel by name or number; "
            f"known channels: {names}. lauter, leiser: TV volume by some steps. stumm: mute or "
            "unmute the TV sound. lautstaerke: set the volume to an exact value 0 to 100. "
            "status: read whether the TV is on and the current volume. receiver: press the "
            "power button of the receiver."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["an", "aus", "kanal", "lauter", "leiser", "lautstaerke", "stumm",
                             "status", "receiver"],
                },
                "channel": {
                    "type": ["string", "null"],
                    "description": "Channel name or number for action kanal, otherwise null.",
                },
                "steps": {
                    "type": ["integer", "null"],
                    "description": "Volume steps 1 to 15 for lauter or leiser (default 3), "
                                   "otherwise null.",
                },
            },
                "volume_percent": {
                    "type": ["integer", "null"],
                    "description": "For action lautstaerke: exact TV volume 0 to 100 "
                                   "(0 means mute), otherwise null.",
                },
            "required": ["action", "channel", "steps", "volume_percent"],
            "additionalProperties": False,
        },
    }


TV_BACKEND_HINT = (
    " You can control the living room TV with fernseher_steuern (German: Fernseher, Turkish: "
    "televizyon). Channels known by name: {names}. When the user names one of them, also with "
    "a different spelling or in Turkish ('A Haber'yi aç', 'atv koy'), use that channel. For an "
    "unknown channel name say which channels you know. 'Lauter' or 'leiser' without a number "
    "means 3 steps; 'viel lauter' about 6. When the user names a number ('Lautstärke 20', "
    "'sesi 30 yap'), use lautstaerke with volume_percent; 0 means mute. To tell the current "
    "volume, use status. 'Stumm' or 'Ton aus' mutes, 'Ton wieder an' presses "
    "stumm again. The receiver power button is a toggle; press it only when the user asks for "
    "the receiver. Always call the tool and confirm very briefly what was done; if it returns an "
    "error, say so honestly."
)

TV_LIVE_HINT = (
    "\n\nFernseher: Du kannst den Fernseher im Wohnzimmer über deinen Hintergrund (Delegation) "
    "bedienen: an, aus, Sender wechseln ({names}), lauter, leiser und stumm. Gib jede "
    "Fernsehbitte sofort dorthin weiter und bestätige erst, wenn das Ergebnis zurück ist."
)


class TvController:
    def __init__(self, remote, channels: dict[str, int], tv_remote: str = DEFAULT_TV_REMOTE,
                 api_url: Optional[str] = None, token: Optional[str] = None,
                 tv_player: str = DEFAULT_TV_PLAYER) -> None:
        self.rf = remote
        self.tv_player = tv_player
        self.channels = channels
        self.tv_remote = tv_remote
        self.api_url = api_url or os.environ.get("HA_API_URL") or "http://supervisor/core/api"
        self.token = token if token is not None else os.environ.get("SUPERVISOR_TOKEN", "")

    @property
    def available(self) -> bool:
        return bool(self.token and self.tv_remote)

    @property
    def names(self) -> str:
        return ", ".join(f"{n} auf {c}" for n, c in self.channels.items())

    async def _service(self, domain: str, service: str, data: dict) -> None:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"{self.api_url}/services/{domain}/{service}", json=data,
                                     headers={"Authorization": f"Bearer {self.token}"})
        if resp.status_code >= 300:
            raise RuntimeError(f"HA HTTP {resp.status_code}: {resp.text[:200]}")

    async def _state(self) -> str:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.api_url}/states/{self.tv_remote}",
                                        headers={"Authorization": f"Bearer {self.token}"})
            return resp.json().get("state", "unknown") if resp.status_code == 200 else "unknown"
        except Exception:
            return "unknown"

    def _has_ir_power(self) -> bool:
        return bool(self.rf.available and "tv_power" in self.rf.load())

    async def _power(self, on: bool) -> dict:
        """Switch the TV on or off. In deep standby the TV turns its WLAN off, then only
        the infrared power button (tv_power, a toggle) can wake it."""
        state = await self._state()
        if on and state == "on":
            return {"done": "Fernseher ist schon an"}
        if not on and state in ("off", "unavailable", "standby"):
            return {"done": "Fernseher ist schon aus"}
        used_ir = False
        if state == "unavailable" or (on and state != "on" and self._has_ir_power()):
            if not self._has_ir_power():
                return {"error": "Der Fernseher ist über WLAN nicht erreichbar."}
            await self.rf.send("tv_power")
            used_ir = True
        else:
            await self._service("remote", "turn_on" if on else "turn_off",
                                {"entity_id": self.tv_remote})
        for _ in range(10):
            await asyncio.sleep(1.5)
            state = await self._state()
            if (state == "on") == on:
                return {"done": "Fernseher eingeschaltet" if on else "Fernseher ausgeschaltet"}
        if used_ir and on:
            # The TV does not always report back quickly after waking up.
            return {"done": "Ein/Aus Taste per Infrarot gedrückt",
                    "note": "Der Fernseher hat sich noch nicht zurückgemeldet."}
        return {"error": "Der Fernseher hat nicht reagiert."}

    async def _player(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.api_url}/states/{self.tv_player}",
                                        headers={"Authorization": f"Bearer {self.token}"})
            return resp.json() if resp.status_code == 200 else {}
        except Exception:
            return {}

    async def _volume(self) -> tuple[Optional[int], bool]:
        attrs = (await self._player()).get("attributes") or {}
        level = attrs.get("volume_level")
        return (None if level is None else round(float(level) * 100),
                bool(attrs.get("is_volume_muted")))

    async def _set_volume(self, target: int) -> dict:
        target = max(0, min(100, int(target)))
        current, muted = await self._volume()
        if target == 0:
            if not muted:
                await self._tv_key("VOLUME_MUTE")
            return {"done": "Ton stumm", "volume_percent": 0}
        if current is None:
            return {"error": "Ich kann die aktuelle Lautstärke gerade nicht lesen."}
        if muted:
            await self._tv_key("VOLUME_MUTE")
            await asyncio.sleep(0.8)
        for _ in range(3):
            diff = target - current
            if diff == 0:
                break
            await self._tv_key("VOLUME_UP" if diff > 0 else "VOLUME_DOWN", min(abs(diff), 60))
            await asyncio.sleep(1.5)
            new, _ = await self._volume()
            if new is None or new == current:
                break
            current = new
        return {"done": f"Lautstärke {current}", "volume_percent": current}

    async def _tv_key(self, command: str, repeats: int = 1) -> None:
        data = {"entity_id": self.tv_remote, "command": command}
        if repeats > 1:
            data.update(num_repeats=repeats, delay_secs=0.25)
        await self._service("remote", "send_command", data)

    async def _channel(self, number: int) -> None:
        if not self.rf.available:
            raise RuntimeError("Der Infrarot Sender ist nicht eingerichtet.")
        codes = [f"rx_{DIGITS[int(d)]}" for d in str(number)]
        missing = [c for c in codes if c not in self.rf.load()]
        if missing:
            raise KeyError(f"Für Programm {number} fehlt noch die Receiver Taste "
                           f"{', '.join(m[3:] for m in missing)}.")
        for i, code in enumerate(codes):
            if i:
                await asyncio.sleep(0.4)
            await self.rf.send(code)

    async def run(self, args: dict) -> dict:
        action = (args.get("action") or "").strip().lower()
        try:
            if action == "an":
                return await self._power(True)
            if action == "aus":
                return await self._power(False)
            if action in ("lauter", "leiser"):
                try:
                    steps = int(args.get("steps") or 3)
                except (TypeError, ValueError):
                    steps = 3
                steps = max(1, min(15, steps))
                await self._tv_key("VOLUME_UP" if action == "lauter" else "VOLUME_DOWN", steps)
                return {"done": f"{steps} Stufen {action}"}
            if action == "lautstaerke":
                if args.get("volume_percent") is None:
                    return {"error": "Welche Lautstärke? 0 bis 100."}
                return await self._set_volume(args["volume_percent"])
            if action == "status":
                state = await self._state()
                volume, muted = await self._volume()
                out = {"tv": "an" if state == "on" else "aus"}
                if state == "on" and volume is not None:
                    out["volume_percent"] = 0 if muted else volume
                    out["muted"] = muted
                return out
            if action == "stumm":
                await self._tv_key("VOLUME_MUTE")
                return {"done": "Stummtaste gedrückt"}
            if action == "receiver":
                await self.rf.send("rx_power")
                return {"done": "Receiver Ein/Aus Taste gedrückt"}
            if action == "kanal":
                found = find_channel(self.channels, args.get("channel"))
                if not found:
                    return {"error": f"Diesen Sender kenne ich nicht. Bekannt: {self.names}."}
                name, number = found
                await self._channel(number)
                return {"done": f"{name} (Programm {number})"}
            return {"error": f"Unbekannte Aktion: {action}"}
        except KeyError as e:
            return {"error": str(e).strip("'\"")}
        except Exception as e:
            logger.warning("TV %s failed: %s", action, e)
            return {"error": "Der Fernseher konnte gerade nicht gesteuert werden."}


def from_env(remote) -> TvController:
    tv_remote = (os.environ.get("TV_REMOTE") or "").strip()
    if not tv_remote or tv_remote.lower() == "null":
        tv_remote = DEFAULT_TV_REMOTE
    return TvController(remote, parse_channels(os.environ.get("TV_CHANNELS")), tv_remote)
