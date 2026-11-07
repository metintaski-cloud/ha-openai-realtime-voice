"""
Ceiling fan control for the voice assistant, through the RF remote (app/rf.py).

The fan ignores a radio frame that is identical to the last one it received, so
every button was learned three times (name_1 .. name_3). Each send uses the next
capture of that button, so the same capture is never sent twice in a row.

The fan itself does not report anything back. A Shelly PM Mini Gen3 in the canopy
measures its power (FAN_POWER_SENSOR). Measured on 7 Nov 2026: everything off 0 W,
light about 14 W, fan alone about 5 W (speed 1), 10 W (speed 3), 20 W (speed 6).
The light button is a toggle, so "licht_an" and "licht_aus" press it, check how the
power changed and press again if the light went the wrong way.
"""
import asyncio
import logging
import os
from typing import Optional

import httpx

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
LIGHT_W = 14.0      # the fan light
OFF_W = 2.0         # below this everything is off
STEP_W = 6.0        # a change this big after pressing licht is the light
SETTLE_S = 3.0      # the light needs about 2 s to reach its power

FAN_TOOL = {
    "type": "function",
    "name": "ventilator_steuern",
    "description": (
        "Press a button of the living room ceiling fan remote (Turkish: vantilatör). "
        "aus: fan off. stufe: set speed 1 to 6 directly (also switches the fan on). "
        "an: power button, fan on at its last speed. licht_an or licht_aus: switch the fan light "
        "on or off; the power meter checks the result and corrects it. licht: only toggle the "
        "light without checking. status: measured power, whether the light is on and whether "
        "the fan turns. naturwind: natural wind mode. "
        "links or rechts: turning direction. timer: switch off after 1, 2 or 4 hours."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["aus", "an", "stufe", "licht_an", "licht_aus", "licht", "status",
                         "naturwind", "links", "rechts", "timer"],
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
    "whether the light is on and whether the fan turns: use status when asked, and only "
    "report what the result says. Speeds are "
    "1 (slow) to 6 (fast); 'schneller' or 'langsamer' means one step up or down from the speed "
    "the user last asked for in this conversation, otherwise ask. For the fan light use licht_an "
    "or licht_aus; if the result says it was already on or off, say so kindly. Words like 'Deckenlicht', 'Ventilatorlicht' or 'Licht am Ventilator' mean the "
    "fan light; plain 'Licht' or 'Lampe' without the fan means the floor lamps (licht_steuern). "
    "Direction: links means turning left (counterclockwise), rechts means turning right "
    "(clockwise). Timers switch the fan off after 1, 2 or 4 hours. Always call the tool, also "
    "when the same request was made before, and confirm very briefly what was sent. If the tool "
    "returns an error, say so honestly."
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
                 api_url: Optional[str] = None, token: Optional[str] = None) -> None:
        self.remote = remote
        if power_sensor is None:
            power_sensor = (os.environ.get("FAN_POWER_SENSOR") or "").strip()
            if not power_sensor or power_sensor.lower() == "null":
                power_sensor = DEFAULT_POWER_SENSOR
        self.power_sensor = power_sensor
        self.api_url = api_url or os.environ.get("HA_API_URL") or "http://supervisor/core/api"
        self.token = token if token is not None else os.environ.get("SUPERVISOR_TOKEN", "")
        self.light_on: Optional[bool] = None  # last state the meter confirmed
        self._confirmed_w: Optional[float] = None  # power at that moment

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

    def _describe(self, watts: float) -> dict:
        out: dict = {"watt": round(watts, 1)}
        if watts < OFF_W:
            self._confirm(False, watts)
            out.update(light="aus", fan="steht")
        elif self.light_on is None:
            out.update(light="unbekannt", fan="unbekannt",
                       note="Licht oder Ventilator ist an; welches, weiß ich erst nach dem "
                            "nächsten Schalten des Lichts.")
        else:
            if self.light_on and watts < LIGHT_W - 4.0:
                self.light_on = False  # switched off with the remote meanwhile
            fan_w = watts - (LIGHT_W if self.light_on else 0.0)
            out.update(light="an" if self.light_on else "aus",
                       fan="dreht sich" if fan_w > 3.0 else "steht")
        return out

    def _confirm(self, light_on: Optional[bool], watts: Optional[float]) -> None:
        self.light_on = light_on
        self._confirmed_w = watts

    async def _press_light(self) -> tuple[Optional[float], Optional[float]]:
        """Press the light button; return (power change, power after), None without meter."""
        before = await self.power()
        await self.remote.send_rotating("licht")
        if before is None:
            return None, None
        await asyncio.sleep(SETTLE_S)
        after = await self.power()
        return (None, None) if after is None else (after - before, after)

    async def set_light(self, on: bool) -> dict:
        watts = await self.power()
        if watts is None:
            await self.remote.send_rotating("licht")
            return {"pressed": "licht", "note": "Lichttaste gedrückt, kein Strommesser."}
        if watts < OFF_W:
            self._confirm(False, watts)
            if not on:
                return {"done": "Das Licht ist schon aus.", "watt": round(watts, 1)}
        elif self.light_on == on and (
                (on and watts >= LIGHT_W - 4.0) or
                (self._confirmed_w is not None and abs(watts - self._confirmed_w) < 3.0)):
            # Confirmed earlier and the power still fits (the fan only adds power)
            return {"done": f"Das Licht ist schon {'an' if on else 'aus'}.",
                    "watt": round(watts, 1)}
        for attempt in range(2):
            delta, after = await self._press_light()
            if delta is None or abs(delta) < STEP_W:
                self._confirm(None, None)
                return {"pressed": "licht", "note": "Lichttaste gedrückt, der Strommesser hat "
                        "keine klare Änderung gesehen."}
            self._confirm(delta > 0, after)
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
            if action == "status":
                watts = await self.power()
                if watts is None:
                    return {"error": "Der Ventilator hat keinen Strommesser."}
                return self._describe(watts)
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
        if action == "licht" and self.light_on is not None:
            self.light_on = not self.light_on
            self._confirmed_w = None
        out["note"] = "Taste gesendet."
        return out
