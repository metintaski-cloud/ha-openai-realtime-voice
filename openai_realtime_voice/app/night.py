"""
The 23:30 night check is configured in the Home Assistant automation, in the data of its
leyla_command event, so Leyla can change it through technik_pruefen (nacht_aendern):

    {"device": "nacht", "lampen": [1, 2], "ventilator": false, "ventilatorlicht": true,
     "fragen": false, "warten": 120}

Every key is optional; without keys everything behaves as before: all lamps, fan and fan
light, ask first, wait 70 seconds. "lampen" without a key means all lamps, an empty list
means no lamp.
"""
from dataclasses import dataclass
from typing import Optional


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
