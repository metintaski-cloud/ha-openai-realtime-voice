"""
Lamp show: the rear lamps follow the conversation in the colours of the KI icon, also when they are off.
Listening is cyan, thinking violet, and while Leyla speaks the lamps breathe between blue and magenta with
her loudness. Afterwards every lamp goes back to what it was before (off stays off, white stays white).
Matter lamps take about three changes per second, so this is a soft breathing, not an exact copy.
"""
import asyncio
import logging
import os
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

CYAN = (34, 211, 238)
BLUE = (59, 130, 246)
VIOLET = (168, 85, 247)
MAGENTA = (217, 70, 239)
LISTEN_PCT = 40
THINK_PCT = 55
SPEAK_MIN_PCT = 30
SPEAK_MAX_PCT = 95
LEVEL_FULL_RMS = 5000.0   # rms that counts as full loudness
MIN_INTERVAL_S = 0.33     # the lamps cannot follow faster
TRANSITION_S = 0.35
SPEECH_HOLD_S = 0.7       # no audio for this long: Leyla stopped speaking, back to listening
AUDIO_LEAD_S = 0.2        # the audio is sent this far ahead of playback, so the light waits as long


def mix(a: tuple, b: tuple, t: float) -> tuple:
    t = max(0.0, min(1.0, t))
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def speak_look(level: float) -> tuple[tuple, int]:
    """Colour and brightness percent for a loudness between 0 (quiet) and 1 (loud)."""
    level = max(0.0, min(1.0, level))
    return mix(BLUE, MAGENTA, level), round(SPEAK_MIN_PCT + (SPEAK_MAX_PCT - SPEAK_MIN_PCT) * level)


def level_from_rms(rms: float) -> float:
    return max(0.0, min(1.0, rms / LEVEL_FULL_RMS))


def restore_data(entity: str, before: dict) -> tuple[str, dict]:
    """Service and data that bring one lamp back to its state before the show."""
    if before.get("state") != "on":
        return "turn_off", {"entity_id": entity, "transition": 1}
    data: dict = {"entity_id": entity, "transition": 1}
    if before.get("brightness"):
        data["brightness"] = before["brightness"]
    if before.get("color_mode") == "color_temp" and before.get("color_temp_kelvin"):
        data["color_temp_kelvin"] = before["color_temp_kelvin"]
    elif before.get("hs_color"):
        data["hs_color"] = before["hs_color"]
    return "turn_on", data


class LampShow:
    def __init__(self, entities: list[str], api_url: Optional[str] = None, token: Optional[str] = None) -> None:
        self.entities = entities
        self.api_url = api_url or os.environ.get("HA_API_URL") or "http://supervisor/core/api"
        self.token = token if token is not None else os.environ.get("SUPERVISOR_TOKEN", "")
        self._before: dict[str, dict] = {}
        self._active = 0
        self._mode = "off"          # listen, think, speak
        self._level = 0.0
        self._last_audio = 0.0
        self._sent = None           # what the lamps last got
        self._worker: Optional[asyncio.Task] = None

    @property
    def available(self) -> bool:
        return bool(self.entities and self.token)

    # ---- Home Assistant ----
    async def _service(self, service: str, data: dict) -> None:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(f"{self.api_url}/services/light/{service}", json=data,
                                     headers={"Authorization": f"Bearer {self.token}"})
        if resp.status_code >= 300:
            raise RuntimeError(f"HA HTTP {resp.status_code}: {resp.text[:120]}")

    async def _snapshot(self) -> None:
        self._before = {}
        async with httpx.AsyncClient(timeout=5.0) as client:
            for entity in self.entities:
                try:
                    resp = await client.get(f"{self.api_url}/states/{entity}",
                                            headers={"Authorization": f"Bearer {self.token}"})
                    j = resp.json() if resp.status_code == 200 else {}
                except Exception:
                    j = {}
                a = j.get("attributes") or {}
                self._before[entity] = {
                    "state": j.get("state", "unknown"), "brightness": a.get("brightness"),
                    "color_mode": a.get("color_mode"), "color_temp_kelvin": a.get("color_temp_kelvin"),
                    "hs_color": a.get("hs_color"),
                }

    # ---- Conversation hooks (never raise, never block) ----
    async def begin(self) -> None:
        if not self.available:
            return
        self._active += 1
        if self._active > 1:
            return
        try:
            await self._snapshot()
        except Exception as e:
            logger.warning("Lamp show: could not read the lamps: %s", e)
            self._active -= 1
            return
        if self._active == 0:  # the conversation was over before the lamps were read
            return
        self._mode, self._level, self._sent = "listen", 0.0, None
        self._worker = asyncio.create_task(self._run())

    def phase(self, name: str) -> None:
        if self._worker is None:
            return
        if name in ("thinking", "searching"):
            self._mode = "think"
        elif name == "replying":
            self._mode = "speak"
            self._last_audio = time.monotonic()

    def audio(self, rms: float) -> None:
        """Loudness of a piece of reply audio; the light follows after the lead."""
        if self._worker is None:
            return
        level = level_from_rms(rms)
        asyncio.get_event_loop().call_later(AUDIO_LEAD_S, self._set_level, level)

    def _set_level(self, level: float) -> None:
        if self._worker is None:
            return
        self._mode = "speak"
        self._level = level
        self._last_audio = time.monotonic()

    async def end(self) -> None:
        if self._active == 0:
            return
        self._active -= 1
        if self._active > 0:
            return
        worker, self._worker = self._worker, None
        if worker:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
        for entity, before in self._before.items():
            service, data = restore_data(entity, before)
            try:
                await self._service(service, data)
            except Exception as e:
                logger.warning("Lamp show: could not restore %s: %s", entity, e)

    # ---- The breathing ----
    def _look(self) -> tuple[tuple, int]:
        if self._mode == "speak" and time.monotonic() - self._last_audio > SPEECH_HOLD_S:
            self._mode = "listen"
        if self._mode == "speak":
            return speak_look(self._level)
        if self._mode == "think":
            return VIOLET, THINK_PCT
        return CYAN, LISTEN_PCT

    async def _run(self) -> None:
        try:
            while True:
                rgb, pct = self._look()
                look = (rgb, pct)
                if look != self._sent:
                    self._sent = look
                    try:
                        await self._service("turn_on", {"entity_id": self.entities, "rgb_color": list(rgb),
                                                         "brightness_pct": pct, "transition": TRANSITION_S})
                    except Exception as e:
                        logger.warning("Lamp show: %s", e)
                await asyncio.sleep(MIN_INTERVAL_S)
        except asyncio.CancelledError:
            raise


def from_env() -> LampShow:
    def env(name: str, default: str) -> str:
        v = (os.environ.get(name) or "").strip()
        return default if v in ("", "null") else v  # bashio gives "null" for an option that is not set

    on = env("LAMP_SHOW", "true").lower() != "false"
    raw = env("LAMP_SHOW_LIGHTS", "light.wohnzimmer_lamba_1, light.wohnzimmer_lamba_2")
    entities = [e.strip() for e in raw.split(",") if e.strip()] if on else []
    return LampShow(entities)
