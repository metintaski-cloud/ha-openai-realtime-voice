"""
Ceiling fan control for the voice assistant, through the RF remote (app/rf.py).

The fan ignores a radio frame that is identical to the last one it received, so
every button was learned three times (name_1 .. name_3). Each send uses the next
capture of that button, so the same capture is never sent twice in a row.

The fan itself does not report anything back. A Shelly PM Mini Gen3 in the canopy
measures the power of light and motor together (FAN_POWER_SENSOR). Measured on
7 Nov 2026 (watts, steady):

    everything off 0, light 13.5 to 18.5 (it varies), fan alone by speed
    1: 5.2  2: 6.6  3: 10.7  4: 14.8  5: 19.1  6: 28.5, light plus fan adds up.

The total alone is ambiguous (light 14 W = fan speed 4), so the controller also
follows what happened: its own button presses, and the shape of every power change.
The light jumps within a second (on: +13 to +19 W), while the fan ramps by a few
watts per second when it changes speed; 0 W means everything is off.
The light button is a toggle, so "licht_an" and "licht_aus" press it, check how the
power changed and press again if the light went the wrong way.
"""
import asyncio
import json
import logging
import os
import time
from collections import deque
from typing import Optional

import httpx
import websockets
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# tool action -> learned button name (without the _1.._3 suffix)
BUTTONS = {
    "aus": "stop",
    "an": "power",
    "licht": "licht",
    "naturwind": "wind",
    "links": "vorwaerts",
    "rechts": "rueckwaerts",
}
TIMERS = {1: "timer1", 2: "timer2", 4: "timer4"}

DEFAULT_POWER_SENSOR = "sensor.ventilator_leistung"
DEFAULT_ENERGY_SENSOR = "sensor.ventilator_energie"
# Average German household price (Destatis, first half of 2026: 37.97 ct/kWh); the
# add-on option strompreis_ct sets the family's own tariff.
DEFAULT_PRICE_CT = 38.0
LIGHT_W = 16.0                    # typical fan light
LIGHT_MIN_W, LIGHT_MAX_W = 13.0, 19.5
FAN_W = {0: 0.0, 1: 5.2, 2: 6.6, 3: 10.7, 4: 14.8, 5: 19.1, 6: 28.5}
OFF_W = 2.0         # below this everything is off
STEP_W = 6.0        # a change this big after pressing licht is the light
JUMP_W = 12.5       # a change this big within JUMP_WINDOW_S is the light switching
SPIKE_S = 1.5        # the fan kicks up to 12 W for a second when it starts
JUMP_WINDOW_S = 3.5  # the light needs 2 to 3 s; the fan ramps 1 to 2 W per second
SETTLE_S = 3.0      # the light needs about 2 s to reach its power


def candidates(watts: float, light_w: Optional[float] = None) -> list[tuple[bool, int]]:
    """All (light on, speed) states whose power fits the measured watts."""
    lo_l, hi_l = (light_w - 1.5, light_w + 1.5) if light_w else (LIGHT_MIN_W, LIGHT_MAX_W)
    out = []
    for light in (False, True):
        for speed, fan_w in FAN_W.items():
            lo = fan_w + (lo_l if light else 0.0)
            hi = fan_w + (hi_l if light else 0.0)
            tol = 1.0 + 0.06 * hi
            if lo - tol <= watts <= hi + tol:
                out.append((light, speed))
    return out


def nearest_speed(fan_w: float) -> int:
    if fan_w < 2.5:
        return 0
    return min((s for s in FAN_W if s), key=lambda s: abs(FAN_W[s] - fan_w))

FAN_TOOL = {
    "type": "function",
    "name": "ventilator_steuern",
    "description": (
        "Press a button of the living room ceiling fan remote (Turkish: vantilatör). "
        "aus: fan off. stufe: set speed 1 to 6 directly (also switches the fan on). "
        "an: power button, fan on at its last speed. licht_an or licht_aus: switch the fan light "
        "on or off; the power meter checks the result and corrects it. licht: only toggle the "
        "light without checking. status: what is on (light, fan and about which speed), from "
        "the power meter. stromkosten: what fan and light cost in electricity (now per hour, "
        "today, since measuring started, estimate per month). naturwind: natural wind mode. "
        "links or rechts: turning direction. timer: switch off after 1, 2 or 4 hours."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["aus", "an", "stufe", "licht_an", "licht_aus", "licht", "status",
                         "stromkosten", "naturwind", "links", "rechts", "timer"],
            },
            "speed": {
                "type": ["integer", "null"],
                "description": "Speed 1 (slow) to 6 (fast) for action stufe, otherwise null.",
            },
            "hours": {
                "type": ["integer", "null"],
                "enum": [1, 2, 4, None],
                "description": "Timer hours for action timer, otherwise null.",
            },
        },
        "required": ["action", "speed", "hours"],
        "additionalProperties": False,
    },
}

FAN_BACKEND_HINT = (
    " You can control the living room ceiling fan with ventilator_steuern (German: Ventilator, "
    "Turkish: vantilatör). It works like pressing a button on its remote. A power meter tells "
    "whether the light is on and whether the fan turns: use status when asked, and report "
    "exactly what the result says; never guess, and if it says unklar, name the "
    "possibilities it lists. Speeds are "
    "1 (slow) to 6 (fast); 'schneller' or 'langsamer' means one step up or down from the speed "
    "the user last asked for in this conversation, otherwise ask. For the fan light use licht_an "
    "or licht_aus; if the result says it was already on or off, say so kindly. Words like 'Deckenlicht', 'Ventilatorlicht' or 'Licht am Ventilator' mean the "
    "fan light; plain 'Licht' or 'Lampe' without the fan means the floor lamps (licht_steuern). "
    "Direction: links means turning left (counterclockwise), rechts means turning right "
    "(clockwise). Timers switch the fan off after 1, 2 or 4 hours. Always call the tool, also "
    "when the same request was made before, and confirm very briefly what was sent. If the tool "
    "returns an error, say so honestly. For electricity costs of fan and light use "
    "stromkosten and say the amounts in euros and cents, rounded, in one or two sentences."
)

FAN_LIVE_HINT = (
    "\n\nVentilator: Du kannst den Deckenventilator im Wohnzimmer über deinen Hintergrund "
    "(Delegation) bedienen: aus, Stufe 1 bis 6, Licht am Ventilator an oder aus, Naturwind, "
    "Drehrichtung links oder rechts und Timer 1, 2 oder 4 Stunden. Ein Strommesser sagt dir, "
    "ob das Licht an ist und ob er sich dreht. Gib jede Ventilatorbitte sofort dorthin weiter "
    "und bestätige erst, wenn das Ergebnis zurück ist."
)


def button_for(args: dict) -> tuple[Optional[str], Optional[str]]:
    """Return (button name, error) for the tool arguments."""
    action = (args.get("action") or "").strip().lower()
    if action == "stufe":
        try:
            speed = int(args.get("speed"))
        except (TypeError, ValueError):
            return None, "Welche Stufe? Es gibt Stufe 1 bis 6."
        if not 1 <= speed <= 6:
            return None, "Es gibt nur Stufe 1 bis 6."
        return f"stufe{speed}", None
    if action == "timer":
        try:
            hours = int(args.get("hours"))
        except (TypeError, ValueError):
            return None, "Der Timer kann 1, 2 oder 4 Stunden."
        if hours not in TIMERS:
            return None, "Der Timer kann nur 1, 2 oder 4 Stunden."
        return TIMERS[hours], None
    if action in BUTTONS:
        return BUTTONS[action], None
    return None, f"Unbekannte Aktion: {action}"


class FanController:
    def __init__(self, remote, power_sensor: Optional[str] = None,
                 api_url: Optional[str] = None, token: Optional[str] = None,
                 state_path: Optional[str] = None) -> None:
        self.remote = remote
        if power_sensor is None:
            power_sensor = (os.environ.get("FAN_POWER_SENSOR") or "").strip()
            if not power_sensor or power_sensor.lower() == "null":
                power_sensor = DEFAULT_POWER_SENSOR
        self.power_sensor = power_sensor
        self.api_url = api_url or os.environ.get("HA_API_URL") or "http://supervisor/core/api"
        self.token = token if token is not None else os.environ.get("SUPERVISOR_TOKEN", "")
        self.energy_sensor = (os.environ.get("FAN_ENERGY_SENSOR") or "").strip() or \
            DEFAULT_ENERGY_SENSOR
        try:
            self.price_ct = float(os.environ.get("STROMPREIS_CT") or DEFAULT_PRICE_CT)
        except ValueError:
            self.price_ct = DEFAULT_PRICE_CT
        if self.price_ct <= 0:
            self.price_ct = DEFAULT_PRICE_CT
        self.light_on: Optional[bool] = None  # what we know about the light
        self.speed: Optional[int] = None      # what we know about the fan, 0 = stopped
        self.light_w: Optional[float] = None  # measured power of the light
        self._recent: deque = deque()         # (time, watts) of the last few seconds
        self._last_w: Optional[float] = None
        self._pending: Optional[tuple[float, float, float]] = None  # rise: time, level, low
        # Remembered across restarts, used only while the power still fits
        self.state_path = state_path
        self._saved: Optional[tuple] = None
        self._restored: Optional[dict] = None
        if state_path:
            try:
                with open(state_path) as f:
                    self._restored = json.load(f)
            except (OSError, ValueError):
                pass

    def _save(self) -> None:
        if not self.state_path or self._last_w is None:
            return
        snap = (self.light_on, self.speed, self.light_w)
        if self._saved and snap == self._saved[0] and abs(self._last_w - self._saved[1]) < 1.0:
            return  # nothing new (the power drifts slowly as the light warms up)
        self._saved = (snap, self._last_w)
        try:
            with open(self.state_path, "w") as f:
                json.dump({"light_on": self.light_on, "speed": self.speed,
                           "light_w": self.light_w, "watts": self._last_w}, f)
        except OSError as e:
            logger.warning("Could not save the fan state: %s", e)

    def _restore(self, watts: float) -> None:
        """After a restart: take the saved state if the power is still the same."""
        saved, self._restored = self._restored, None
        if saved and abs(float(saved.get("watts") or -99) - watts) < 2.5:
            self.light_on = saved.get("light_on")
            self.speed = saved.get("speed")
            self.light_w = saved.get("light_w")
            logger.info("Fan state restored: light %s, speed %s", self.light_on, self.speed)

    async def _api(self, method: str, path: str, **kw):
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.request(method, f"{self.api_url}/{path}",
                                        headers={"Authorization": f"Bearer {self.token}"}, **kw)
        resp.raise_for_status()
        return resp

    async def _stat_change(self, start_iso: str, period: str) -> Optional[float]:
        """Energy used since start_iso, from Home Assistant's statistics. They also count
        right when the Shelly restarts and its own counter begins at 0 again."""
        u = urlparse(self.api_url)
        ws_url = f"{'wss' if u.scheme == 'https' else 'ws'}://{u.netloc}" + \
            u.path.rsplit("/api", 1)[0] + "/websocket"
        async with websockets.connect(ws_url, max_size=None, open_timeout=5) as ws:
            await ws.recv()
            await ws.send(json.dumps({"type": "auth", "access_token": self.token}))
            if json.loads(await ws.recv()).get("type") != "auth_ok":
                return None
            await ws.send(json.dumps({
                "id": 1, "type": "recorder/statistics_during_period",
                "start_time": start_iso, "statistic_ids": [self.energy_sensor],
                "period": period, "types": ["change"]}))
            msg = json.loads(await asyncio.wait_for(ws.recv(), 10))
        rows = (msg.get("result") or {}).get(self.energy_sensor) or []
        return sum(float(r.get("change") or 0.0) for r in rows)

    async def energy_report(self) -> dict:
        """Electricity cost of fan and light: now, today, since measuring started."""
        price = self.price_ct
        out: dict = {"strompreis_ct_pro_kwh": price}
        watts = await self.power()
        if watts is not None:
            out["jetzt_watt"] = round(watts, 1)
            out["jetzt_cent_pro_stunde"] = round(watts / 1000 * price, 2)
        midnight = (await self._api("POST", "template", json={
            "template": "{{ today_at().isoformat() }}"})).text.strip()
        since = await self._measuring_since()
        try:
            today = await self._stat_change(midnight, "5minute")
            total = None
            if since is not None:
                since_iso = (await self._api("POST", "template", json={
                    "template": "{{ as_datetime(%d).isoformat() }}" % int(since)})).text.strip()
                total = await self._stat_change(since_iso, "hour")
                total = max(total or 0.0, today or 0.0)
        except Exception as e:
            logger.warning("Energy statistics failed: %s", e)
            today = total = None
        if today is None:  # fall back to the meter's own counter
            state = (await self._api("GET", f"states/{self.energy_sensor}")).json()
            today = total = float(state["state"])
        out["heute_kwh"] = round(today, 3)
        out["heute_cent"] = round(today * price, 1)
        if total is not None and since is not None:
            days = (time.time() - since) / 86400
            out["gesamt_kwh"] = round(total, 3)
            out["gesamt_cent"] = round(total * price, 1)
            out["gemessen_seit_tagen"] = round(days, 1)
            if days >= 2:
                out["schaetzung_monat_euro"] = round(total / days * 30 * price / 100, 2)
            else:
                out["note"] = ("Erst seit Kurzem gemessen; eine Monatsschätzung gibt es nach ein "
                               "paar Tagen. Grob: eine Stunde Licht kostet etwa 0,6 Cent, eine "
                               "Stunde Ventilator auf Stufe 6 etwa 1,1 Cent.")
        return out

    async def _measuring_since(self) -> Optional[float]:
        """When the energy meter started, from the saved state file or now."""
        if not self.state_path:
            return None
        path = self.state_path + ".since"
        try:
            with open(path) as f:
                return float(f.read().strip())
        except (OSError, ValueError):
            now = time.time()
            try:
                with open(path, "w") as f:
                    f.write(str(now))
            except OSError:
                return None
            return now

    async def power(self) -> Optional[float]:
        """Watts from the power meter, None when there is none."""
        if not (self.token and self.power_sensor):
            return None
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.api_url}/states/{self.power_sensor}",
                                        headers={"Authorization": f"Bearer {self.token}"})
            if resp.status_code != 200:
                return None
            return float(resp.json().get("state"))
        except Exception:
            return None

    # Following the power ---------------------------------------------------------
    def on_power(self, watts: float, now: Optional[float] = None) -> None:
        """Every new reading of the power meter (Home Assistant state_changed)."""
        now = time.monotonic() if now is None else now
        if self._restored is not None:
            self._restore(watts)
        prev = self._last_w
        self._last_w = watts
        if self._pending and now - self._pending[0] < SPIKE_S \
                and watts < self._pending[1] - 5.0:
            self._pending = None  # only the start kick of the fan
        self._settle(now)
        if watts < OFF_W:
            self._pending = None
            self.light_on, self.speed = False, 0
            self._recent.clear()
            self._recent.append((now, watts))
            self._save()
            return
        while self._recent and now - self._recent[0][0] > JUMP_WINDOW_S:
            self._recent.popleft()
        if prev is not None and not self._recent:
            self._recent.append((now - 0.1, prev))
        if self._recent:
            low = min(w for _, w in self._recent)
            high = max(w for _, w in self._recent)
            if watts - low >= JUMP_W:
                # Jumped up within a second or two: the light went on (the fan ramps).
                # Confirmed once it stays up (see _settle).
                self._pending = (now, watts, low)
                self._recent.clear()
            elif high - watts >= JUMP_W:
                self._dropped(high, watts)
                self._recent.clear()
        self._recent.append((now, watts))
        self._save()

    def _settle(self, now: float) -> None:
        if not self._pending or now - self._pending[0] < SPIKE_S:
            return
        _, level, low = self._pending
        self._pending = None
        self.light_on = True
        self.light_w = min(max(level - low, LIGHT_MIN_W), LIGHT_MAX_W)
        if self.speed is None and low < OFF_W:
            self.speed = 0
        logger.info("Fan light switched on (%.1f W -> %.1f W)", low, level)

    def on_power_state(self, state: str) -> None:
        """Callback for Home Assistant state_changed of the power sensor."""
        try:
            self.on_power(float(state))
        except (TypeError, ValueError):
            pass  # unavailable or unknown

    def _dropped(self, before: float, after: float) -> None:
        """A quick drop: the light went off, or the fan stopped from speed 4 or more."""
        light_w = self.light_w or LIGHT_W
        fan_before = before - light_w if self.light_on else None
        if self.light_on is False:
            self.speed = 0
        elif self.light_on is None and self.speed is not None and FAN_W[self.speed] < 12.0:
            self.light_on = False  # the fan was too slow to drop that much
        elif fan_before is not None and fan_before < 12.0:
            self.light_on = False  # the fan alone could not drop that much
        elif self.light_on and abs(after - light_w) + 3.0 < abs(after - (before - light_w)):
            self.speed = 0         # what is left looks like the light alone
        elif self.light_on and fan_before is not None:
            self.light_on = False
            self.speed = nearest_speed(after)
        else:
            self.light_on = self.speed = None
        logger.info("Fan power dropped %.1f W -> %.1f W: light %s, speed %s",
                    before, after, self.light_on, self.speed)

    def describe(self, watts: float) -> dict:
        """What is on, from the watts and what the controller has followed."""
        out: dict = {"watt": round(watts, 1)}
        if self._restored is not None:
            self._restore(watts)
        if self._last_w is None:
            self._last_w = watts
        self._settle(time.monotonic())
        if watts < OFF_W:
            self.light_on, self.speed = False, 0
            out.update(licht="aus", ventilator="aus")
            return out
        light = self.light_on
        if light and watts < LIGHT_MIN_W - 2.0:
            light = self.light_on = False  # too little power for the light
        if light is None:
            cands = candidates(watts, self.light_w)
            if self.speed is not None:
                cands = [c for c in cands if c[1] == self.speed] or cands
            lights = {c[0] for c in cands}
            if len(lights) == 1:
                light = self.light_on = lights.pop()
            else:
                options = []
                for on, speed in sorted(set(cands), key=lambda c: (c[1], c[0])):
                    if on and speed == 0:
                        options.append("nur das Licht")
                    elif on:
                        options.append(f"Licht und Ventilator auf Stufe {speed}")
                    elif speed:
                        options.append(f"nur der Ventilator auf Stufe {speed}")
                out.update(licht="unklar", ventilator="unklar",
                           moeglich=options[:3] or ["Licht oder Ventilator"],
                           note="Das kann ich an den Watt allein nicht unterscheiden, bis "
                                "einmal geschaltet wurde.")
                return out
        fan_w = watts - ((self.light_w or LIGHT_W) if light else 0.0)
        speed = nearest_speed(fan_w)
        out["licht"] = "an" if light else "aus"
        out["ventilator"] = "aus" if speed == 0 else f"an, ungefähr Stufe {speed}"
        self._save()
        return out

    async def _press_light(self) -> Optional[float]:
        """Press the light button; return the power change it caused, None without meter."""
        before = await self.power()
        await self.remote.send_rotating("licht")
        if before is None:
            return None
        await asyncio.sleep(SETTLE_S)
        after = await self.power()
        if after is None:
            return None
        delta = after - before
        if abs(delta) >= STEP_W:
            self.light_on = delta > 0
            if delta > 0:
                self.light_w = min(max(delta, LIGHT_MIN_W), LIGHT_MAX_W)
            if after < OFF_W:
                self.speed = 0
        self._recent.clear()
        self._last_w = after
        self._save()
        return delta

    async def set_light(self, on: bool) -> dict:
        watts = await self.power()
        if watts is None:
            await self.remote.send_rotating("licht")
            return {"pressed": "licht", "note": "Lichttaste gedrückt, kein Strommesser."}
        state = self.describe(watts).get("licht")
        if state == ("an" if on else "aus"):
            return {"done": f"Das Licht ist schon {'an' if on else 'aus'}.",
                    "watt": round(watts, 1)}
        for attempt in range(2):
            delta = await self._press_light()
            if delta is None or abs(delta) < STEP_W:
                self.light_on = None
                return {"pressed": "licht", "note": "Lichttaste gedrückt, der Strommesser hat "
                        "keine klare Änderung gesehen."}
            if self.light_on == on:
                return {"done": f"Licht {'an' if on else 'aus'}",
                        "note": "Vom Strommesser bestätigt." if attempt == 0 else
                        "Es war schon " + ("an" if on else "aus") + ", jetzt stimmt es wieder."}
        return {"error": "Das Licht hat nicht wie erwartet reagiert."}

    @property
    def available(self) -> bool:
        if not self.remote.available:
            return False
        return any(name.startswith("stop") for name in self.remote.load())

    async def run(self, args: dict) -> dict:
        action = (args.get("action") or "").strip().lower()
        try:
            if action in ("licht_an", "licht_aus"):
                return await self.set_light(action == "licht_an")
            if action == "stromkosten":
                if not self.token:
                    return {"error": "Der Ventilator hat keinen Strommesser."}
                return await self.energy_report()
            if action == "status":
                watts = await self.power()
                if watts is None:
                    return {"error": "Der Ventilator hat keinen Strommesser."}
                return self.describe(watts)
        except KeyError as e:
            return {"error": str(e).strip("'\"")}
        except Exception as e:
            logger.warning("Fan light/status failed: %s", e)
            return {"error": "Der Ventilator Sender ist gerade nicht erreichbar."}
        button, error = button_for(args)
        if error:
            return {"error": error}
        try:
            result = await self.remote.send_rotating(button)
        except KeyError as e:
            return {"error": str(e).strip("'\"")}
        except Exception as e:
            logger.warning("Fan button %s failed: %s", button, e)
            return {"error": "Der Ventilator Sender ist gerade nicht erreichbar."}
        logger.info("Fan: %s sent (%s)", button, result.get("sent"))
        out = {"pressed": args.get("action"), "button": button}
        if args.get("action") == "stufe":
            out["speed"] = int(args["speed"])
        if args.get("action") == "timer":
            out["hours"] = int(args["hours"])
        if action == "stufe":
            self.speed = int(args["speed"])
        elif action == "aus":
            self.speed = 0
        elif action in ("an", "naturwind"):
            self.speed = None
        out["note"] = "Taste gesendet."
        return out
