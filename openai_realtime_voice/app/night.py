"""
The 23:30 night check is configured in the Home Assistant automation, in the data of its
leyla_command event, so Leyla can change it through technik_pruefen (nacht_aendern):

    {"device": "nacht", "lampen": [1, 2], "ventilator": false, "ventilatorlicht": true,
     "fragen": false, "warten": 120}

Every key is optional; without keys everything behaves as before: all lamps, fan and fan
light, ask first, wait 70 seconds. "lampen" without a key means all lamps, an empty list
means no lamp.
"""
import asyncio
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import httpx

from app import fan, lights

logger = logging.getLogger(__name__)


@dataclass
class NightOptions:
    lamps: Optional[list] = None  # None = all lamps, else the lamp numbers
    fan: bool = True
    fan_light: bool = True
    ask: bool = True
    wait_s: Optional[float] = None  # None = the default wait of the bridge

    @property
    def nothing(self) -> bool:
        return self.lamps == [] and not self.fan and not self.fan_light


def _flag(value, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def parse(data: Optional[dict]) -> NightOptions:
    data = data or {}
    lamps = data.get("lampen")
    if isinstance(lamps, list):
        lamps = sorted({int(n) for n in lamps if isinstance(n, int) and not isinstance(n, bool)
                        and n > 0})
    else:
        lamps = None
    wait = data.get("warten")
    wait = float(wait) if isinstance(wait, (int, float)) and not isinstance(wait, bool) \
        and 0 <= wait <= 600 else None
    return NightOptions(lamps=lamps, fan=_flag(data.get("ventilator"), True),
                        fan_light=_flag(data.get("ventilatorlicht"), True),
                        ask=_flag(data.get("fragen"), True), wait_s=wait)


def _join(parts: list, word: str) -> str:
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + f" {word} " + parts[-1]


def _numbers(nums: list, word: str) -> str:
    return _join([str(n) for n in nums], word)


def things(o: NightOptions) -> tuple:
    """(German, Turkish) names of what is switched off, in the form used after 'ob du'."""
    de, tr = [], []
    if o.lamps is None:
        de.append("die Lampen")
        tr.append("Lambaları")
    elif o.lamps:
        de.append(("Lampe " if len(o.lamps) == 1 else "Lampe ") + _numbers(o.lamps, "und"))
        tr.append(_numbers(o.lamps, "ve") + " numaralı lambaları")
    if o.fan:
        de.append("den Ventilator")
        tr.append("vantilatörü")
    if o.fan_light:
        de.append("das Ventilatorlicht")
        tr.append("vantilatör ışığını")
    return _join(de, "und"), _join(tr, "ve")


def wait_phrase(wait_s: float) -> tuple:
    minutes = max(1, round(wait_s / 60))
    if minutes == 1:
        return "in einer Minute", "bir dakika sonra"
    return f"in {minutes} Minuten", f"{minutes} dakika sonra"


NIGHT_WAIT_S = 70.0
NIGHT_KEEP_RE = re.compile(
    r"\b(hay[ıi]r|kals[ıi]n|kapatma|istemiyorum|bekle|nein|nicht|lass|bleib)\b", re.IGNORECASE)
NIGHT_PROMPT = (
    "Du meldest dich gerade von selbst, weil es spät ist (es ist {time} Uhr). Frag auf Türkisch "
    "kurz und lieb, ob du {was_de} ausschalten sollst, und sag dazu, dass "
    "du es {wait_de} machst, wenn niemand antwortet, zum Beispiel „Saat on bir buçuk "
    "oldu. {was_tr} kapatayım mı? Cevap gelmezse {wait_tr} "
    "kapatacağım.“ Nenn dabei die richtige Uhrzeit. Sagt jemand ja, "
    "schalte über deinen Hintergrund genau das aus ({was_de}; Ventilatorlicht mit licht_aus), "
    "und wünsch kurz eine gute Nacht. Sagt jemand nein oder will etwas anlassen, "
    "lass es so und sag kurz tamam. Antwortet niemand, sag nichts mehr."
)


class NightMixin:
    """The 23:30 night check of the bridge. Needs self.lights, self.fan, self._converse,
    self._night and self._night_opts from the bridge."""

    def _night_lamps(self) -> list:
        """Entity ids of the lamps the night check looks after."""
        o = self._night_opts
        ids, _ = lights.select_entities(self.lights.entities, o.lamps)
        return [] if o.lamps == [] else ids

    async def _anything_on(self) -> bool:
        o = self._night_opts
        ids = self._night_lamps()
        if ids and self.lights.available:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    states = await self.lights._states(client, ids)
                if any(st.get("state") == "on" for st in states):
                    return True
            except Exception as e:
                logger.info("Lamp status for the night check: %s", e)
        if not (o.fan or o.fan_light):
            return False
        watts = await self.fan.power()
        if not (watts and watts >= fan.OFF_W):
            return False
        if o.fan and o.fan_light:
            return True
        state = self.fan.describe(watts)
        return (o.fan and state.get("ventilator") != "aus") or \
            (o.fan_light and state.get("licht") != "aus")

    async def _all_off(self) -> None:
        o = self._night_opts
        ids = self._night_lamps()
        if ids and self.lights.available:
            numbers = [self.lights.entities.index(e) + 1 for e in ids]
            await self.lights.run({"lamps": numbers, "action": "off", "brightness_percent": None,
                                   "white": None, "color": None})
        if not (o.fan or o.fan_light):
            return
        watts = await self.fan.power()
        if watts is not None and watts >= fan.OFF_W:
            state = self.fan.describe(watts)
            if o.fan and state.get("ventilator") != "aus":
                await self.fan.run({"action": "aus", "speed": None, "hours": None})
                await asyncio.sleep(2.5)
            if o.fan_light and state.get("licht") != "aus":
                await self.fan.run({"action": "licht_aus", "speed": None, "hours": None})

    async def _night_check(self) -> None:
        """23:00: ask whether to switch everything off; without an answer, switch off."""
        if self._night is not None:
            return
        try:
            if self._night_opts.nothing or not await self._anything_on():
                logger.info("Night check: nothing to switch off")
                return
            self._night = {"text": ""}
            try:
                from zoneinfo import ZoneInfo
                now = datetime.now(ZoneInfo(os.environ.get("TZ") or "Europe/Berlin"))
            except Exception:
                now = datetime.now()
            o = self._night_opts
            wait_s = o.wait_s if o.wait_s is not None else NIGHT_WAIT_S
            if not o.ask:
                await self._all_off()
                logger.info("Night check: switched off without asking")
                return
            was_de, was_tr = things(o)
            wait_de, wait_tr = wait_phrase(wait_s)
            asked = await self._converse(NIGHT_PROMPT.format(
                time=now.strftime("%H:%M"), was_de=was_de, was_tr=was_tr[0].upper() + was_tr[1:],
                wait_de=wait_de, wait_tr=wait_tr))
            logger.info("Night check: asked %s", "in a conversation" if asked else "not possible")
            await asyncio.sleep(wait_s if asked else 0)
            answer = self._night["text"]
            if NIGHT_KEEP_RE.search(answer):
                logger.info("Night check: keep on (%r)", answer[-120:])
                return
            if not await self._anything_on():
                logger.info("Night check: switched off in the conversation")
                return
            await self._all_off()
            logger.info("Night check: no answer, lamps and fan switched off")
        except Exception as e:
            logger.warning("Night check failed: %s", e)
        finally:
            self._night = None
