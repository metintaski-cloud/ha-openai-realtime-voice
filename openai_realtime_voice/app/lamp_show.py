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
SHOWN_MAX = 60            # looks the show really sent are remembered, newest first,
SHOWN_KEEP_S = 48 * 3600  # this long: a leftover is known even after the colours were changed
PREVIEW_S = 4.0           # how long a colour test in the app shows
HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
LEVEL_FULL_RMS = 5000.0   # rms that counts as full loudness
MIN_INTERVAL_S = 0.5      # at most two commands a second: Matter over Thread chokes on more (14 Nov 2026)
LEVEL_STEPS = 4           # loudness in 5 steps, so small changes send nothing
LEVEL_TAU_S = 0.25        # the loudness is smoothed over about a syllable
TRANSITION_S = 0.35
RESTORE_WAIT_S = 1.5      # a lamp that was off is set to its old strength, this long, then switched off
SETTLE_S = 0.6            # after the last look of the show, before the lamps are put back
# What a lamp is set to before it is switched off when no normal state of it is known yet
# (Metin's rear lamps as they were seen on most often). Without it the lamp would keep the last
# look of the show for its next normal switch on, and the on before the off is also what makes
# a lamp obey whose own on/off state got out of step with its light (see _restore_one).
NEUTRAL = {"state": "on", "brightness": 153, "color_mode": "color_temp", "color_temp_kelvin": 6000}
OFF_AGAIN_S = 3.0         # a lamp that was switched off is told so a second time after this
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


def look_key(rgb: tuple, pct: int) -> str:
    """A look the show sent, the way a lamp reports it: "hue,saturation,brightness of 255"."""
    hue, sat = _hue(rgb)
    return f"{round(hue)},{round(sat)},{round(pct * 2.55)}"


def same_look(state: dict, key: str) -> bool:
    """Does the lamp report this look (`look_key`)? A lamp in white mode never does."""
    hs, bright = state.get("hs_color"), state.get("brightness") or 0
    if not bright or not hs or state.get("color_mode") == "color_temp":
        return False
    try:
        hue, sat = float(hs[0]), float(hs[1])
        h, s, b = (float(x) for x in key.split(","))
    except (TypeError, ValueError, IndexError):
        return False
    if abs(bright - b) > LEVEL_TOLERANCE or abs(sat - s) > 25:
        return False
    return s < 15 or _hue_gap(hue, h) <= 20


def restore_data(entity: str, before: dict) -> tuple[str, dict]:
    """Service and data that bring one lamp back to its state before the show. Off is a plain
    off without a fade: an off that has to overtake a fade still running in the lamp can lose
    (24 Nov 2026: Home Assistant said off, the lamps stood on in white)."""
    if before.get("state") != "on":
        return "turn_off", {"entity_id": entity}
    return "turn_on", _on_data(entity, before)


def _on_data(entity: str, before: dict, transition: float = 1) -> dict:
    data: dict = {"entity_id": entity, "transition": transition}
    if before.get("brightness"):
        data["brightness"] = before["brightness"]
    if before.get("color_mode") == "color_temp" and before.get("color_temp_kelvin"):
        data["color_temp_kelvin"] = before["color_temp_kelvin"]
    elif before.get("hs_color"):
        data["hs_color"] = before["hs_color"]
    return data


OWN_CALL_S = 8.0  # so long a reported service call can be one of the show's own (its report comes within ms)


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
        self._shown: dict[str, float] = {}   # looks the show sent (look_key) and when
        self._pending: dict[str, dict] = {}  # state before a show that is not restored yet
        self._load_memory()
        self.api_url = api_url or os.environ.get("HA_API_URL") or "http://supervisor/core/api"
        self.token = token if token is not None else os.environ.get("SUPERVISOR_TOKEN", "")
        self._before: dict[str, dict] = {}
        self._own: list = []  # (time, key) of the show's own calls, to tell them from what others switch (2.200.0)
        self._own_rgb: dict = {}  # colours the show sent and when: a call with one of them is never taken as a wish
        self._active = 0
        self._mode = "off"          # listen, think, speak
        self._level = 0.0
        self._level_at = 0.0
        self._last_audio = 0.0
        self._sent = None           # what the lamps last got
        self._worker: Optional[asyncio.Task] = None
        self._retry: Optional[asyncio.Task] = None
        self._again: Optional[asyncio.Task] = None   # the second off after a show
        self._ending = False                         # between the last look and the lamps being back
        self._quit = asyncio.Event()                 # ends the worker of the running show
        self._lock: Optional[asyncio.Lock] = None

    @property
    def available(self) -> bool:
        return bool(self.entities and self.token)

    @property
    def busy(self) -> bool:
        """True while a show runs or its lamps are not back yet. Whoever switches these lamps
        for good at a set time (app/planer.py) waits for it: the end of a show puts them back
        to what they were before the talk, and a second off follows OFF_AGAIN_S later."""
        return bool(self._active or self._ending
                    or (self._pending and self._retry is not None)  # a restore is tried again
                    or (self._lock is not None and self._lock.locked())
                    or (self._again is not None and not self._again.done()))

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
        last_on, pending, shown = data.get("last_on"), data.get("pending"), data.get("shown")
        if not isinstance(shown, dict):
            # A file from before 2.159.1. Until then a look below full strength was not known
            # as a leftover of the show, so a learned coloured state may be one (24 Nov 2026:
            # orange at 15 percent was learned as normal). Only white states are kept, the
            # coloured ones are learned afresh.
            last_on = {e: v for e, v in (last_on if isinstance(last_on, dict) else {}).items()
                       if isinstance(v, dict) and v.get("color_mode") == "color_temp"}
            shown = {}
        self._shown = {k: t for k, t in shown.items() if isinstance(t, (int, float))}
        self._last_on = {e: v for e, v in (last_on if isinstance(last_on, dict) else {}).items()
                         if isinstance(v, dict) and not self._leftover(v)}
        self._pending = {e: v for e, v in (pending if isinstance(pending, dict) else {}).items()
                         if isinstance(v, dict)}

    def _save_memory(self) -> None:
        try:
            tmp = self.memory_path + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"last_on": self._last_on, "pending": self._pending, "shown": self._shown}, f)
            os.replace(tmp, self.memory_path)
        except Exception as e:
            logger.warning("Lamp show: could not save the lamp memory: %s", e)

    def _note_shown(self, rgb: tuple, pct: int) -> None:
        now = time.time()
        self._shown.pop(look_key(rgb, pct), None)
        self._shown[look_key(rgb, pct)] = now  # newest last
        for key in [k for k, t in self._shown.items() if now - t > SHOWN_KEEP_S]:
            del self._shown[key]
        while len(self._shown) > SHOWN_MAX:
            del self._shown[next(iter(self._shown))]

    def _leftover(self, state: dict) -> bool:
        """The lamp shows a look of the show: one of today's looks, or one the show really sent
        (the colours and strengths can be changed in the app while a look is on the lamps)."""
        return (is_show_look(state, self.colors, self.levels)
                or any(same_look(state, key) for key in self._shown))

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
                if st.get("state") == "on" and self._leftover(st):
                    if await self._restore_one(entity, {"state": "off"}):
                        fixed.append(entity)
            # A lamp can stand on while Home Assistant says off (seen 24 Nov 2026): the button
            # also puts every lamp that is reported off through on and off once (they flash
            # for a moment). Lamps reported on in a normal state are his and stay.
            dark = [e for e, st in states.items() if st.get("state") == "off"]
            done = await asyncio.gather(*(self._restore_one(e, {"state": "off"}) for e in dark))
            fixed += [e + " (reported off)" for e, ok in zip(dark, done) if ok]
        logger.info("Lamp show: reset from the app (%s)", ", ".join(fixed) or "nothing stuck")
        return "ok" if not self._pending else "failed"

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    # ---- Home Assistant ----
    @staticmethod
    def _call_key(service: str, data: dict) -> str:
        d = dict(data or {})
        e = d.get("entity_id")
        d["entity_id"] = sorted([e] if isinstance(e, str) else list(e or []))
        return service + json.dumps(d, sort_keys=True, default=list)

    def outside(self, service: str, data: dict) -> None:
        """Home Assistant reports every light service call (`messages.listen`). A call that is not one of the
        show's own and switches a lamp of the show while a show runs (or its end is still to come) is somebody's
        wish: an automation, the Home Assistant app, a switch, or Leyla's own lamp tool. The lamp is then put
        back to THAT at the end, not to what it was before the talk (2.200.0, Metin 28 Nov 2026)."""
        try:
            if service not in ("turn_on", "turn_off", "toggle") or not (self._active or self._pending):
                return
            e = (data or {}).get("entity_id")
            mine = [x for x in ([e] if isinstance(e, str) else list(e or [])) if x in self.entities]
            if not mine:
                return
            now, key = time.monotonic(), self._call_key(service, data)
            self._own = [(t, k) for t, k in self._own if now - t < OWN_CALL_S]
            for i, (_, k) in enumerate(self._own):
                if k == key:
                    del self._own[i]
                    return  # the show itself
            rgb = data.get("rgb_color")
            if service == "turn_on" and rgb is not None and now - self._own_rgb.get(tuple(int(v) for v in rgb), -1e9) < 900:
                return  # a look of the show, whatever else differs in the report
            for entity in mine:
                base = self._pending.get(entity) or self._before.get(entity) or {"state": "off"}
                if service == "turn_off" or (service == "toggle" and base.get("state") == "on"):
                    new = {"state": "off"}
                else:
                    new = dict(self._last_on.get(entity) or (base if base.get("state") == "on" else {}))
                    new["state"] = "on"
                    if data.get("brightness") is not None:
                        new["brightness"] = int(data["brightness"])
                    elif data.get("brightness_pct") is not None:
                        new["brightness"] = max(1, round(float(data["brightness_pct"]) * 255 / 100))
                    kelvin = data.get("color_temp_kelvin") or data.get("kelvin")
                    if not kelvin and data.get("color_temp"):
                        kelvin = round(1_000_000 / float(data["color_temp"]))
                    if kelvin:
                        new.update(color_mode="color_temp", color_temp_kelvin=int(kelvin), hs_color=None)
                    elif data.get("hs_color") is not None:
                        new.update(color_mode="hs", hs_color=[float(v) for v in data["hs_color"]])
                    elif data.get("rgb_color") is not None:
                        r, g, b = (float(v) / 255 for v in data["rgb_color"])
                        h, sat, _ = colorsys.rgb_to_hsv(r, g, b)
                        new.update(color_mode="hs", hs_color=[round(h * 360, 3), round(sat * 100, 3)])
                    if not new.get("brightness"):
                        new["brightness"] = 255
                    self._last_on[entity] = dict(new)
                self._pending[entity] = new
                if entity in self._before:
                    self._before[entity] = dict(new)
            self._save_memory()
            logger.info("Lamp show: %s switched from outside during the show (%s), kept for afterwards",
                        ", ".join(mine), service)
        except Exception as e:  # a report must never disturb the show
            logger.warning("Lamp show: outside call not understood: %s", e)

    def _mine(self, service: str, data: dict) -> None:
        """Remember a call of the show itself, so its report from Home Assistant is not taken for a wish."""
        self._own.append((time.monotonic(), self._call_key(service, data)))
        del self._own[:-60]
        if data.get("rgb_color") is not None:
            self._own_rgb[tuple(int(v) for v in data["rgb_color"])] = time.monotonic()

    async def _service(self, service: str, data: dict, timeout: float = SHOW_TIMEOUT_S) -> None:
        self._mine(service, data)
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

    async def _now(self, entity: str) -> dict:
        async with httpx.AsyncClient(timeout=5.0) as client:
            return await self._read_state(client, entity)

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
                if now.get("state") == "on" and self._leftover(now):
                    # nothing pending and still a look of the show (a restart, a late report):
                    # that is never the state to go back to; like the reset in the app, off
                    logger.warning("Lamp show: %s still shows a look of the show, it counts as off", entity)
                    now = {"state": "off"}
                elif now.get("state") == "on" and now.get("brightness"):
                    self._last_on[entity] = dict(now)
                self._before[entity] = now
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
        self._quit = asyncio.Event()
        self._worker = asyncio.create_task(self._run(self._quit))

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
        self._ending = True  # still busy for a plan until the lamps are back
        try:
            if worker:
                # Never cut a look that is on its way: Home Assistant would still send it, and
                # it could reach the lamp after the commands that put the lamp back. The worker
                # ends after the call it is in, then the lamp gets a moment for its last fade.
                self._quit.set()
                try:
                    await asyncio.wait_for(asyncio.shield(worker), SHOW_TIMEOUT_S + 1.0)
                except Exception:
                    worker.cancel()
                    await asyncio.gather(worker, return_exceptions=True)
                await asyncio.sleep(SETTLE_S)
            await self._restore_all()
        finally:
            self._ending = False

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
            dark = []
            for (entity, before), ok in zip(todo, done):
                if ok:
                    self._pending.pop(entity, None)
                    if before.get("state") != "on":
                        dark.append(entity)
            self._save_memory()
        if dark:
            self._again = asyncio.create_task(self._off_again(dark))
        if schedule and self._pending and not self._active and self._retry is None:
            self._retry = asyncio.create_task(self._retry_later())

    async def _off_again(self, entities: list) -> None:
        """A second, plain off a few seconds after the lamps were switched off. The first one
        can lose against what is still running in the lamp, and Home Assistant then reports
        off for a lamp that stands on, so checking the state cannot find it. Not when a new
        show has begun."""
        await asyncio.sleep(OFF_AGAIN_S)
        async with self._get_lock():
            if self._active:
                return
            # only lamps that are still reported off: one reported on was switched on by
            # somebody in the meantime and is his
            entities = [e for e in entities if (await self._now(e))["state"] == "off"]
            if not entities:
                return
            try:
                await self._service("turn_off", {"entity_id": entities}, RESTORE_TIMEOUT_S)
            except Exception as e:
                logger.warning("Lamp show: second off for %s failed: %s", ", ".join(entities),
                               str(e) or type(e).__name__)

    async def _restore_one(self, entity: str, before: dict) -> bool:
        """Bring one lamp back and check that it reports the old state. True when it does."""
        want = "on" if before.get("state") == "on" else "off"
        for attempt in range(RESTORE_TRIES):
            try:
                if want == "off":
                    # A lamp that was off keeps its strength for the next normal switch on: set it
                    # back first, at once and without a fade, so nothing is still running in the
                    # lamp when the off comes. Never a bare off: on 24 Nov 2026 the lamps stood on
                    # in the last look while Home Assistant reported off, and a plain off did
                    # nothing; on and then off did.
                    await self._service("turn_on", _on_data(entity, self._last_on.get(entity) or NEUTRAL, 0),
                                        RESTORE_TIMEOUT_S)
                    await asyncio.sleep(RESTORE_WAIT_S)
                service, data = restore_data(entity, before)
                await self._service(service, data, RESTORE_TIMEOUT_S)
                for _ in range(3):  # Matter reports the new state a moment later
                    await asyncio.sleep(VERIFY_WAIT_S)
                    full = await self._now(entity)
                    now = full["state"]
                    # a lamp that was on is back only when it no longer reports a look of the
                    # show; "on" alone was true all the time (24 Nov 2026: lamps that were on
                    # before a test stayed in the test colour, and the next test took it as normal)
                    if now == want and (want == "off" or not self._leftover(full)):
                        if attempt:
                            logger.info("Lamp show: %s restored on try %d", entity, attempt + 1)
                        return True
                logger.warning("Lamp show: %s is %s%s after the restore, should be %s", entity, now,
                               " in a look of the show" if now == want else "", want)
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

    async def _run(self, quit: asyncio.Event) -> None:
        while not quit.is_set():
            rgb, pct = self._look()
            look = (rgb, pct)
            if look != self._sent:
                self._sent = look
                try:
                    await self._service("turn_on", {"entity_id": self.entities, "rgb_color": list(rgb),
                                                     "brightness_pct": pct, "transition": TRANSITION_S})
                    self._note_shown(rgb, pct)
                except Exception as e:
                    logger.warning("Lamp show: %s", str(e) or type(e).__name__)
            try:
                await asyncio.wait_for(quit.wait(), MIN_INTERVAL_S)
            except asyncio.TimeoutError:
                pass


def from_env() -> LampShow:
    def env(name: str, default: str) -> str:
        v = (os.environ.get(name) or "").strip()
        return default if v in ("", "null") else v  # bashio gives "null" for an option that is not set

    on = env("LAMP_SHOW", "true").lower() != "false"
    raw = env("LAMP_SHOW_LIGHTS", "light.wohnzimmer_lamba_1, light.wohnzimmer_lamba_2")
    entities = [e.strip() for e in raw.split(",") if e.strip()] if on else []
    return LampShow(entities)
