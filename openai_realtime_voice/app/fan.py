"""
Ceiling fan control for the voice assistant, through the RF remote (app/rf.py).

The fan ignores a radio frame that is identical to the last one it received, so
every button was learned three times (name_1 .. name_3). Each send uses the next
capture of that button, so the same capture is never sent twice in a row.

The fan does not report anything back. Leyla only presses buttons; she does not
track whether the fan light is on. The user says "Licht an" or "Licht aus" and
sees the result himself.
"""
import logging
from typing import Optional

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

FAN_TOOL = {
    "type": "function",
    "name": "ventilator_steuern",
    "description": (
        "Press a button of the living room ceiling fan remote (Turkish: vantilatör). "
        "aus: fan off. stufe: set speed 1 to 6 directly (also switches the fan on). "
        "an: power button, fan on at its last speed. licht: press the fan light button, it "
        "switches the light on if it is off and off if it is on. naturwind: natural wind mode. "
        "links or rechts: turning direction. timer: switch off after 1, 2 or 4 hours."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["aus", "an", "stufe", "licht", "naturwind", "links", "rechts", "timer"],
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
    "Turkish: vantilatör). It works like pressing a button on its remote; the fan does not "
    "report its state, so never claim to know whether the fan or its light is on. Speeds are "
    "1 (slow) to 6 (fast); 'schneller' or 'langsamer' means one step up or down from the speed "
    "the user last asked for in this conversation, otherwise ask. For the fan light the user "
    "says 'Licht an' or 'Licht aus' at the fan; press licht exactly once and do not argue about "
    "its state. Words like 'Deckenlicht', 'Ventilatorlicht' or 'Licht am Ventilator' mean the "
    "fan light; plain 'Licht' or 'Lampe' without the fan means the floor lamps (licht_steuern). "
    "Direction: links means turning left (counterclockwise), rechts means turning right "
    "(clockwise). Timers switch the fan off after 1, 2 or 4 hours. Always call the tool, also "
    "when the same request was made before, and confirm very briefly what was sent. If the tool "
    "returns an error, say so honestly."
)

FAN_LIVE_HINT = (
    "\n\nVentilator: Du kannst den Deckenventilator im Wohnzimmer über deinen Hintergrund "
    "(Delegation) bedienen: aus, Stufe 1 bis 6, Licht am Ventilator, Naturwind, Drehrichtung "
    "links oder rechts und Timer 1, 2 oder 4 Stunden. Gib jede Ventilatorbitte sofort dorthin "
    "weiter und bestätige erst, wenn das Ergebnis zurück ist. Der Ventilator meldet nichts "
    "zurück, also sag nur, welche Taste gesendet wurde."
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
    def __init__(self, remote) -> None:
        self.remote = remote

    @property
    def available(self) -> bool:
        if not self.remote.available:
            return False
        return any(name.startswith("stop") for name in self.remote.load())

    async def run(self, args: dict) -> dict:
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
        out["note"] = "Taste gesendet. Der Ventilator meldet keinen Zustand zurück."
        return out
