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
# While Leyla listens, the TV is turned down to DUCK_FACTOR of its volume, at most
# DUCK_MAX_PERCENT, so that she hears the family instead of the TV. A TV that keeps
# talking makes GPT Live wait for the end of a turn that never comes.
DUCK_FACTOR = 0.3
DUCK_MAX_PERCENT = 8
DUCK_MIN_PERCENT = 8
# After a volume request during a conversation, let the family hear the new volume
# for a moment before turning the TV down again.
REDUCK_AFTER_S = 4.0
# Delay between volume key presses. 0.25 s made "Lautstärke 50" take 8 s, and while a
# tool runs Leyla does not take the next request.
STEP_DELAY_S = 0.1
DUCK_STEP_DELAY_S = STEP_DELAY_S
# How long to wait for the TV to report on or off before answering.
POWER_WAIT_S = 4.5
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
    "volume, use status. While a conversation runs, the TV is turned down automatically and "
    "goes back to its volume afterwards; volume requests work from the normal volume. "
    "'Stumm' or 'Ton aus' mutes, 'Ton wieder an' presses "
    "stumm again. The receiver power button is a toggle; press it only when the user asks for "
    "the receiver. Always call the tool and confirm very briefly what was done; if it returns an "
    "error, say so honestly."
)

TV_LIVE_HINT = (
    "\n\nFernseher: Du kannst den Fernseher im Wohnzimmer über deinen Hintergrund (Delegation) "
    "bedienen: an, aus, Sender wechseln ({names}), lauter, leiser und stumm. Gib jede "
    "Fernsehbitte sofort dorthin weiter und bestätige erst, wenn das Ergebnis zurück ist. "
    "Solange ihr redet, ist der Fernseher automatisch leiser, damit du alle gut verstehst; "
    "danach geht er von selbst wieder auf die alte Lautstärke."
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
        self.duck_enabled = (os.environ.get("TV_DUCK") or "true").strip().lower() != "false"
        self._ducked_from: Optional[int] = None
        self._lock = asyncio.Lock()
        self.listening = False  # a conversation is running
        self._tasks: set = set()

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
        if on:
            self._later(self._duck_when_on())
        for _ in range(int(POWER_WAIT_S / 1.5)):
            await asyncio.sleep(1.5)
            state = await self._state()
            if (state == "on") == on:
                return {"done": "Fernseher eingeschaltet" if on else "Fernseher ausgeschaltet"}
        # Do not keep Leyla waiting: while a tool runs she takes no new request.
        if on:
            return {"done": "Einschalten gesendet",
                    "note": "Der Fernseher startet noch, das dauert ein paar Sekunden."}
        if used_ir:
            return {"done": "Ein/Aus Taste per Infrarot gedrückt"}
        return {"done": "Ausschalten gesendet",
                "note": "Der Fernseher hat sich noch nicht als aus gemeldet."}

    def _later(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _duck_when_on(self) -> None:
        """The TV was switched on during a conversation: turn it down once it is up."""
        for _ in range(20):
            await asyncio.sleep(1.5)
            if not self.listening:
                return
            if await self._state() == "on" and (await self._volume())[0] is not None:
                await self.duck()
                return

    async def _reduck_later(self) -> None:
        await asyncio.sleep(REDUCK_AFTER_S)
        if self.listening:
            await self.duck()

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

    async def duck(self) -> None:
        """Turn the TV down while Leyla listens and remember the volume (see DUCK_FACTOR)."""
        if not (self.available and self.duck_enabled):
            return
        self.listening = True
        async with self._lock:
            if not self.listening:
                return  # the conversation ended meanwhile
            if self._ducked_from is not None or await self._state() != "on":
                return
            current, muted = await self._volume()
            if current is None or muted or current <= DUCK_MIN_PERCENT:
                return
            target = max(2, min(round(current * DUCK_FACTOR), DUCK_MAX_PERCENT))
            self._ducked_from = current
            try:
                await self._set_volume(target, DUCK_STEP_DELAY_S)
                logger.info("TV turned down from %d to %d while Leyla listens", current, target)
            except Exception as e:
                logger.warning("Could not turn the TV down: %s", e)

    async def unduck(self) -> None:
        """Bring the TV back to the volume it had before the conversation."""
        self.listening = False
        async with self._lock:
            await self._unduck_locked()

    async def _unduck_locked(self) -> None:
        original, self._ducked_from = self._ducked_from, None
        if original is None or await self._state() != "on":
            return
        current, muted = await self._volume()
        if current is None or muted:
            return
        try:
            await self._set_volume(original, DUCK_STEP_DELAY_S)
            logger.info("TV volume back to %d", original)
        except Exception as e:
            logger.warning("Could not restore the TV volume: %s", e)

    async def _set_volume(self, target: int, step_delay: float = STEP_DELAY_S) -> dict:
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
            await self._tv_key("VOLUME_UP" if diff > 0 else "VOLUME_DOWN", min(abs(diff), 60),
                               step_delay)
            await asyncio.sleep(1.0)
            new, _ = await self._volume()
            if new is None or new == current:
                break
            current = new
        return {"done": f"Lautstärke {current}", "volume_percent": current}

    async def _tv_key(self, command: str, repeats: int = 1,
                      step_delay: float = STEP_DELAY_S) -> None:
        data = {"entity_id": self.tv_remote, "command": command}
        if repeats > 1:
            data.update(num_repeats=repeats, delay_secs=step_delay)
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
        if action not in ("status", "lauter", "leiser", "lautstaerke", "stumm", "aus"):
            return await self._run(action, args)
        async with self._lock:  # wait until turning down or back up is finished
            if action == "status" and self._ducked_from is not None:
                return {"tv": "an", "volume_percent": self._ducked_from, "muted": False,
                        "note": "Während des Gesprächs ist der Fernseher automatisch leiser."}
            if action == "aus":
                self._ducked_from = None
                return await self._run(action, args)
            if action == "status":
                return await self._run(action, args)
            await self._unduck_locked()  # volume requests start from the normal volume
            result = await self._run(action, args)
        if self.listening and "error" not in result:
            # The new volume is the one to come back to after the conversation.
            self._later(self._reduck_later())
        return result

    async def _run(self, action: str, args: dict) -> dict:
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
                target = args.get("volume_percent")
                if target is None:
                    target = args.get("steps")  # the model sometimes puts the number there
                if target is None:
                    return {"error": "Welche Lautstärke? 0 bis 100."}
                return await self._set_volume(target)
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
