"""
Lamp show: the rear lamps follow the conversation in the colours of the KI icon, also when they are off.
Listening is cyan, thinking violet, and while Leyla speaks the lamps breathe between blue and magenta with
her loudness. Afterwards every lamp goes back to what it was before (off stays off, white stays white).
Matter lamps take about three changes per second, so this is a soft breathing, not an exact copy.

Restoring is made safe against lamps that do not answer (Matter timeouts, 14 Nov 2026: Lamba 1 stayed
blue after a talk and was then taken for the family's own setting): the state from before the show is
kept in /data/lamp_show.json as "pending" until the lamp really reports it again; a failed restore is
tried again in the background and at the next start; the next conversation starts from the pending
state, not from the stuck show colour; and a show colour is never learned as a lamp's normal setting.
"""
import asyncio
import colorsys
import json
import math
import re
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
ORANGE = (249, 115, 22)
# Two sets of looks (Metin, 24 Nov 2026): the normal one, and one for a talk with him while
# she is low (keys with "sad_"). By day the old sign of a low, every look at 5 percent, could
# not be told from lamps that are off, so a low now has its own listening colour, and every
# look has its own colour and its own strength, all chosen in the app.
SAD = "sad_"
DEFAULT_COLORS = {"listen": CYAN, "think": VIOLET, "speak_low": BLUE, "speak_high": MAGENTA,
                  "sad_listen": ORANGE, "sad_think": VIOLET, "sad_speak_low": BLUE,
                  "sad_speak_high": MAGENTA}
COLOR_LABELS = {"listen": "Zuhören", "think": "Denken", "speak_low": "Reden leise",
                "speak_high": "Reden laut", "sad_listen": "Zuhören, traurig",
                "sad_think": "Denken, traurig", "sad_speak_low": "Reden leise, traurig",
                "sad_speak_high": "Reden laut, traurig"}
MODES = ("listen", "think", "speak")
DEFAULT_LEVELS = {"listen": 100, "think": 100, "speak": 100,   # brightness percent of each look
                  "sad_listen": 50, "sad_think": 50, "sad_speak": 50}
LEVEL_TOLERANCE = 8       # of 255: a lamp reports the strength it was given this exactly
PREVIEW_S = 4.0           # how long a colour test in the app shows
HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
LEVEL_FULL_RMS = 5000.0   # rms that counts as full loudness
MIN_INTERVAL_S = 0.5      # at most two commands a second: Matter over Thread chokes on more (14 Nov 2026)
LEVEL_STEPS = 4           # loudness in 5 steps, so small changes send nothing
LEVEL_TAU_S = 0.25        # the loudness is smoothed over about a syllable
TRANSITION_S = 0.35
RESTORE_WAIT_S = 1.2      # a lamp that was off fades to its old strength before it is switched off
SPEECH_HOLD_S = 0.7       # no audio for this long: Leyla stopped speaking, back to listening
AUDIO_LEAD_S = 0.2        # the audio is sent this far ahead of playback, so the light waits as long
SHOW_TIMEOUT_S = 5.0      # one show step may be dropped, the next one follows
RESTORE_TIMEOUT_S = 15.0  # Home Assistant waits up to about 15 s for a Matter lamp
VERIFY_WAIT_S = 1.5       # then the lamp must report the old state
RESTORE_TRIES = 3
RETRY_DELAYS_S = (10.0, 30.0, 90.0, 300.0)  # background retries after a failed restore


def mix(a: tuple, b: tuple, t: float) -> tuple:
    t = max(0.0, min(1.0, t))
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def speak_look(level: float, colors: Optional[dict] = None, sad: bool = False,
               levels: Optional[dict] = None) -> tuple[tuple, int]:
    """Colour and brightness percent for a loudness between 0 (quiet) and 1 (loud). The
    breathing is in the colour, the strength stays the one chosen for speaking."""
    c, pre = colors or DEFAULT_COLORS, SAD if sad else ""
    level = max(0.0, min(1.0, level))
    return (mix(c[pre + "speak_low"], c[pre + "speak_high"], level),
            (levels or DEFAULT_LEVELS)[pre + "speak"])


def to_hex(rgb: tuple) -> str:
    return "#%02x%02x%02x" % tuple(rgb)


def from_hex(text) -> Optional[tuple]:
    if not isinstance(text, str) or not HEX_RE.match(text):
        return None
    return tuple(int(text[i:i + 2], 16) for i in (1, 3, 5))


def _pct(value) -> Optional[int]:
    """A brightness percent from the app: a whole number from 1 to 100, else None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 1 <= value <= 100:
        return None
    return round(value)


def _hue(rgb: tuple) -> tuple[float, float]:
    h, s, _ = colorsys.rgb_to_hsv(*(x / 255 for x in rgb))
    return h * 360, s * 100


def _hue_gap(a: float, b: float) -> float:
    d = abs(a - b) % 360
    return min(d, 360 - d)


def level_from_rms(rms: float) -> float:
    return max(0.0, min(1.0, rms / LEVEL_FULL_RMS))


def show_looks(colors: Optional[dict] = None, levels: Optional[dict] = None) -> list:
    """Every look the show can leave on a lamp, as (hue, saturation, brightness percent)."""
    c, lv = colors or DEFAULT_COLORS, levels or DEFAULT_LEVELS
    out = []
    for pre in ("", SAD):
        out.append(_hue(c[pre + "listen"]) + (lv[pre + "listen"],))
        out.append(_hue(c[pre + "think"]) + (lv[pre + "think"],))
        out += [_hue(mix(c[pre + "speak_low"], c[pre + "speak_high"], i / 8)) + (lv[pre + "speak"],)
                for i in range(9)]
    return out


def is_show_look(state: dict, colors: Optional[dict] = None, levels: Optional[dict] = None) -> bool:
    """True for a lamp that shows one of the show looks (the listen or think colour, or anything
    between the two speaking colours, each at its own strength, normal or low): such a state
    comes from a show that was not undone and is never taken as the normal setting."""
    hs, bright = state.get("hs_color"), state.get("brightness") or 0
    if not bright or not hs or state.get("color_mode") == "color_temp":
        return False
    try:
        hue, sat = float(hs[0]), float(hs[1])
    except (TypeError, ValueError, IndexError):
        return False
    return any(s >= 30 and sat >= 30 and _hue_gap(hue, h) <= 20
               and abs(bright - round(pct * 2.55)) <= LEVEL_TOLERANCE
               for h, s, pct in show_looks(colors, levels))


def restore_data(entity: str, before: dict) -> tuple[str, dict]:
    """Service and data that bring one lamp back to its state before the show."""
    if before.get("state") != "on":
        return "turn_off", {"entity_id": entity, "transition": 1}
    return "turn_on", _on_data(entity, before)


def _on_data(entity: str, before: dict) -> dict:
    data: dict = {"entity_id": entity, "transition": 1}
    if before.get("brightness"):
        data["brightness"] = before["brightness"]
    if before.get("color_mode") == "color_temp" and before.get("color_temp_kelvin"):
        data["color_temp_kelvin"] = before["color_temp_kelvin"]
    elif before.get("hs_color"):
        data["hs_color"] = before["hs_color"]
    return data


class LampShow:
    def __init__(self, entities: list[str], api_url: Optional[str] = None, token: Optional[str] = None,
                 memory_path: str = "/data/lamp_show.json") -> None:
        self.entities = entities
        self.mood_low: Optional[bool] = None  # her mood in a talk with Metin (None: not shown)
        self.memory_path = memory_path
        self.colors_path = os.path.join(os.path.dirname(memory_path) or ".", "lamp_colors.json")
        self.levels: dict = dict(DEFAULT_LEVELS)
        self.colors: dict = self._load_colors()
        self._last_on: dict[str, dict] = {}  # strength and colour each lamp had when last on
        self._pending: dict[str, dict] = {}  # state before a show that is not restored yet
        self._load_memory()
        self.api_url = api_url or os.environ.get("HA_API_URL") or "http://supervisor/core/api"
        self.token = token if token is not None else os.environ.get("SUPERVISOR_TOKEN", "")
        self._before: dict[str, dict] = {}
        self._active = 0
        self._mode = "off"          # listen, think, speak
        self._level = 0.0
        self._level_at = 0.0
        self._last_audio = 0.0
        self._sent = None           # what the lamps last got
        self._worker: Optional[asyncio.Task] = None
        self._retry: Optional[asyncio.Task] = None
        self._lock: Optional[asyncio.Lock] = None

    @property
    def available(self) -> bool:
        return bool(self.entities and self.token)

    def _load_memory(self) -> None:
        try:
            with open(self.memory_path) as f:
                data = json.load(f)
        except Exception:
            return
        if not isinstance(data, dict):
            return
        if "last_on" not in data and "pending" not in data:
            data = {"last_on": data}  # older file: only the last on states
        last_on, pending = data.get("last_on"), data.get("pending")
        self._last_on = {e: v for e, v in (last_on if isinstance(last_on, dict) else {}).items()
                         if isinstance(v, dict) and not is_show_look(v, self.colors, self.levels)}
        self._pending = {e: v for e, v in (pending if isinstance(pending, dict) else {}).items()
                         if isinstance(v, dict)}

    def _save_memory(self) -> None:
        try:
            tmp = self.memory_path + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"last_on": self._last_on, "pending": self._pending}, f)
            os.replace(tmp, self.memory_path)
        except Exception as e:
            logger.warning("Lamp show: could not save the lamp memory: %s", e)

    # ---- Colours chosen in the app ----
    def _load_colors(self) -> dict:
        """The colours, and with them the strengths (`levels`, key "pct" of the same file)."""
        colors = dict(DEFAULT_COLORS)
        try:
            with open(self.colors_path) as f:
                data = json.load(f)
            for k in DEFAULT_COLORS:
                rgb = from_hex(data.get(k)) if isinstance(data, dict) else None
                if rgb:
                    colors[k] = rgb
            for k, v in (data.get("pct") or {}).items():
                if k in DEFAULT_LEVELS and _pct(v) is not None:
                    self.levels[k] = _pct(v)
        except Exception:
            pass
        return colors

    def colors_hex(self) -> dict:
        return {k: to_hex(v) for k, v in self.colors.items()}

    def set_colors(self, data, levels=None) -> bool:
        """Take new colours ({"listen": "#22d3ee", ...}) and strengths ({"sad_listen": 40, ...},
        percent 1 to 100); missing keys stay, None = default. False when a value is not a
        colour or not a strength; then nothing changes."""
        if not isinstance(data or {}, dict) or not isinstance(levels or {}, dict):
            return False
        new, new_levels = dict(self.colors), dict(self.levels)
        for k, v in (data or {}).items():
            if k not in DEFAULT_COLORS:
                return False
            rgb = DEFAULT_COLORS[k] if v is None else from_hex(v)
            if rgb is None:
                return False
            new[k] = rgb
        for k, v in (levels or {}).items():
            if k not in DEFAULT_LEVELS:
                return False
            pct = DEFAULT_LEVELS[k] if v is None else _pct(v)
            if pct is None:
                return False
            new_levels[k] = pct
        self.colors, self.levels = new, new_levels
        self._sent = None  # a running show takes the new looks at once
        try:
            tmp = self.colors_path + ".tmp"
            with open(tmp, "w") as f:
                json.dump({**self.colors_hex(), "pct": self.levels}, f)
            os.replace(tmp, self.colors_path)
        except Exception as e:
            logger.warning("Lamp show: could not save the colours: %s", e)
        return True

    async def preview(self, mode: str) -> str:
        """Show one colour on the lamps for a few seconds, then put them back. Not while Leyla
        is in a conversation or another test runs."""
        if not self.available:
            return "off"
        sad, mode = mode.startswith(SAD), mode.removeprefix(SAD)
        if mode not in MODES:
            return "bad"
        if self._active:
            return "busy"
        await self.begin()
        try:
            if self._worker is None:
                return "error"
            self.mood_low = sad or None  # `end` takes it back
            if mode == "think":
                self._mode = "think"
            steps = int(PREVIEW_S / 0.6)
            for i in range(steps):
                if self._active > 1:
                    break  # a real conversation started: it takes over
                if mode == "speak":
                    self._set_level(1.0 if i % 2 else 0.0)  # breathe between quiet and loud
                await asyncio.sleep(0.6)
        finally:
            await self.end()
        return "ok"

    async def reset(self) -> str:
        """The button in the app: lamps left in a show colour go back to normal (pending
        restores first, then any lamp still showing a show colour is switched off)."""
        if not self.available:
            return "off"
        if self._active:
            return "busy"
        if self._retry is not None:
            self._retry.cancel()
            self._retry = None
        await self._restore_all(schedule=False)
        fixed = []
        async with self._get_lock():
            async with httpx.AsyncClient(timeout=5.0) as client:
                states = {e: await self._read_state(client, e) for e in self.entities}
            for entity, st in states.items():
                if st.get("state") == "on" and is_show_look(st, self.colors, self.levels):
                    if await self._restore_one(entity, {"state": "off"}):
                        fixed.append(entity)
        logger.info("Lamp show: reset from the app (%s)", ", ".join(fixed) or "nothing stuck")
        return "ok" if not self._pending else "failed"

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    # ---- Home Assistant ----
    async def _service(self, service: str, data: dict, timeout: float = SHOW_TIMEOUT_S) -> None:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{self.api_url}/services/light/{service}", json=data,
                                     headers={"Authorization": f"Bearer {self.token}"})
        if resp.status_code >= 300:
            raise RuntimeError(f"HA HTTP {resp.status_code}: {resp.text[:120]}")

    async def _read_state(self, client: httpx.AsyncClient, entity: str) -> dict:
        try:
            resp = await client.get(f"{self.api_url}/states/{entity}",
                                    headers={"Authorization": f"Bearer {self.token}"})
            j = resp.json() if resp.status_code == 200 else {}
        except Exception:
            j = {}
        a = j.get("attributes") or {}
        return {"state": j.get("state", "unknown"), "brightness": a.get("brightness"),
                "color_mode": a.get("color_mode"), "color_temp_kelvin": a.get("color_temp_kelvin"),
                "hs_color": a.get("hs_color")}

    async def _state_of(self, entity: str) -> str:
        async with httpx.AsyncClient(timeout=5.0) as client:
            return (await self._read_state(client, entity))["state"]

    async def _snapshot(self) -> None:
        """Read the lamps. A lamp whose last restore failed starts from its pending state, because
        what it shows now is the leftover of the show."""
        self._before = {}
        async with httpx.AsyncClient(timeout=5.0) as client:
            for entity in self.entities:
                if entity in self._pending:
                    self._before[entity] = dict(self._pending[entity])
                    continue
                now = await self._read_state(client, entity)
                self._before[entity] = now
                if now.get("state") == "on" and now.get("brightness") and not is_show_look(now, self.colors, self.levels):
                    self._last_on[entity] = dict(now)
        self._pending = {e: dict(b) for e, b in self._before.items()}
        self._save_memory()

    # ---- Conversation hooks (never raise, never block) ----
    async def begin(self) -> None:
        if not self.available:
            return
        self._active += 1
        if self._active > 1:
            return
        if self._retry is not None:  # this conversation restores the lamps when it ends
            self._retry.cancel()
            self._retry = None
        async with self._get_lock():  # never read the lamps while a restore is still running
            try:
                await self._snapshot()
            except Exception as e:
                logger.warning("Lamp show: could not read the lamps: %s", e)
                self._active -= 1
                return
        if self._active == 0:  # the conversation was over before the lamps were read
            await self._restore_all()
            return
        self._mode, self._level, self._sent = "listen", 0.0, None
        self._worker = asyncio.create_task(self._run())

    def set_mood(self, low: Optional[bool]) -> None:
        """Leyla's mood in a talk with Metin: while she is low the show uses its second set of
        looks (None or False = the normal ones). `end` forgets it."""
        self.mood_low = low

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
        now = time.monotonic()
        if self._mode != "speak":
            self._level = level  # a new reply starts from its own loudness
        else:
            k = 1.0 - math.exp(-max(0.0, now - self._level_at) / LEVEL_TAU_S)
            self._level += (level - self._level) * k
        self._mode = "speak"
        self._level_at = self._last_audio = now

    async def end(self) -> None:
        if self._active == 0:
            return
        self._active -= 1
        if self._active > 0:
            return
        self.mood_low = None
        worker, self._worker = self._worker, None
        if worker:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
        await self._restore_all()

    async def recover(self) -> None:
        """At start: a restore that failed before the add on stopped is done now."""
        if self.available and self._pending and self._active == 0:
            logger.info("Lamp show: restoring %d lamp(s) left over from before the start",
                        len(self._pending))
            await self._restore_all()

    async def _restore_all(self, schedule: bool = True) -> None:
        async with self._get_lock():
            if self._active or not self._pending:
                return  # a new conversation took over; it restores when it ends
            todo = list(self._pending.items())
            done = await asyncio.gather(*(self._restore_one(e, b) for e, b in todo))  # all lamps at once
            for (entity, _), ok in zip(todo, done):
                if ok:
                    self._pending.pop(entity, None)
            self._save_memory()
        if schedule and self._pending and not self._active and self._retry is None:
            self._retry = asyncio.create_task(self._retry_later())

    async def _restore_one(self, entity: str, before: dict) -> bool:
        """Bring one lamp back and check that it reports the old state. True when it does."""
        want = "on" if before.get("state") == "on" else "off"
        for attempt in range(RESTORE_TRIES):
            try:
                if want == "off" and self._last_on.get(entity):
                    # A lamp that was off keeps its strength for the next normal switch on: set it back first
                    await self._service("turn_on", _on_data(entity, self._last_on[entity]), RESTORE_TIMEOUT_S)
                    await asyncio.sleep(RESTORE_WAIT_S)
                service, data = restore_data(entity, before)
                await self._service(service, data, RESTORE_TIMEOUT_S)
                for _ in range(3):  # Matter reports the new state a moment later
                    await asyncio.sleep(VERIFY_WAIT_S)
                    now = await self._state_of(entity)
                    if now == want:
                        if attempt:
                            logger.info("Lamp show: %s restored on try %d", entity, attempt + 1)
                        return True
                logger.warning("Lamp show: %s is %s after the restore, should be %s", entity, now, want)
            except Exception as e:
                logger.warning("Lamp show: could not restore %s (try %d): %s", entity, attempt + 1,
                               str(e) or type(e).__name__)
            if attempt + 1 < RESTORE_TRIES:
                await asyncio.sleep(RESTORE_WAIT_S * (attempt + 1))
        return False

    async def _retry_later(self) -> None:
        try:
            for delay in RETRY_DELAYS_S:
                await asyncio.sleep(delay)
                if self._active or not self._pending:
                    return
                await self._restore_all(schedule=False)
                if not self._pending:
                    logger.info("Lamp show: lamps restored on a later try")
                    return
            logger.warning("Lamp show: %s still not restored; tried again at the next conversation",
                           ", ".join(self._pending))
        finally:
            if self._retry is asyncio.current_task():
                self._retry = None

    # ---- The breathing ----
    def _look(self) -> tuple[tuple, int]:
        sad = bool(self.mood_low)
        pre = SAD if sad else ""
        if self._mode == "speak" and time.monotonic() - self._last_audio > SPEECH_HOLD_S:
            self._mode = "listen"
        if self._mode == "speak":
            return speak_look(round(self._level * LEVEL_STEPS) / LEVEL_STEPS, self.colors, sad, self.levels)
        key = pre + ("think" if self._mode == "think" else "listen")
        return self.colors[key], self.levels[key]

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
                        logger.warning("Lamp show: %s", str(e) or type(e).__name__)
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
