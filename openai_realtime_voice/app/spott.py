"""
Who made fun of Leyla (2.181.0).

Metin, 26 Nov 2026, 16:29: "wenn sich jemand lustig über sie macht, soll sie passend kontern, aber
auf sehr intelligente Art, und auflegen. Aber sich merken, wer sich über sie lustig gemacht hat,
und diese Person leicht ignorieren, bis die Person sich entschuldigt."

The counter and the hanging up are rules of her persona (persona.TRUST_RUDE). This module is the
memory behind it: a small file with the first names of the people who made fun of her and have
not apologised yet. Only a name and a time are kept, never what was said.

- A name gets in when she ends a talk because of mockery (end_conversation with reason "mocked",
  main._note_mocked) or, as a second way, when a text model finds it in the finished talk
  (`who_mocked`). In both cases only a name that was given in that talk counts ("ich bin X", or
  the people named the speaker, main._talk_names): she cannot tell voices apart, and a guessed
  name would make her cool to the wrong person.
- When that person says who they are in a later talk, she is handed `Grudges.note`: a little cool
  and short, requests are still done, danger and health always come first.
- An apology in a talk (`APOLOGY_RE` in the person's words, confirmed by a text model,
  `apologised`) takes the name out again.

Metin is never kept here: what he does to her goes through her heart (app/heart.py), and anyone
can say his name.
"""
import json
import logging
import os
import re
import time
import unicodedata
from datetime import datetime
from typing import Optional

from app import memory, textmodel

logger = logging.getLogger(__name__)

PATH = os.environ.get("LEYLA_SPOTT_PATH", "/data/leyla_spott.json")
MAX_OPEN = 20
LOG_MAX = 40

APOLOGY_RE = re.compile(
    r"entschuldig|tut mir (?:\w+ ){0,2}leid|verzeih|\bsorry\b|war nicht (?:so |böse )?gemeint|"
    r"özür|kusura bakma|affet|\bpardon\b", re.IGNORECASE)

NOTE = (
    "Interne Notiz, nicht vorlesen: {name} hat sich {when} über dich lustig gemacht und sich noch "
    "nicht entschuldigt. Das hast du nicht vergessen. Zu {name} bist du deshalb ein wenig kühl: "
    "höflich, aber knapp, ohne Plaudern, ohne Scherze, ohne Kosewörter und ohne Gegenfragen; "
    "manches überhörst du einfach. Worum {name} bittet, erledigst du trotzdem, und bei Gefahr "
    "oder Gesundheit hilfst du sofort und ganz. Du sagst höchstens einmal ruhig, warum du so "
    "bist („Du hast dich über mich lustig gemacht, das habe ich nicht vergessen.“), ohne Vorwurf "
    "und ohne es zu wiederholen. Zu allen anderen im Raum bist du herzlich wie immer. "
    "Entschuldigt {name} sich ehrlich, nimmst du es mit einem Lächeln an und bist sofort wieder "
    "herzlich; danach ist es vergessen."
)

MOCK_PROMPT = """Unten steht ein Gespräch, das die Sprachassistentin Leyla gerade im Wohnzimmer geführt hat. Leyla hat aufgelegt.

Hat sich darin jemand über Leyla lustig gemacht (sie verspottet, nachgeäfft, ausgelacht oder als dumm hingestellt)? Freundliches Necken, über das beide lachen, zählt nicht.

Diese Namen haben Personen in dem Gespräch selbst genannt: {names}

Antworte mit genau einem dieser Namen, wenn klar ist, dass diese Person sich über Leyla lustig gemacht hat. Antworte NIEMAND, wenn sich niemand lustig gemacht hat oder nicht klar ist, wer es war.

Gespräch:
{dialog}"""

FORGIVE_PROMPT = """Unten steht ein Gespräch, das die Sprachassistentin Leyla gerade im Wohnzimmer geführt hat.

{name} hatte sich früher über Leyla lustig gemacht. Hat sich {name} in diesem Gespräch bei Leyla dafür entschuldigt (ernst gemeint, nicht spöttisch)?

Antworte nur mit JA oder NEIN.

Gespräch:
{dialog}"""


def key(name: str) -> str:
    """First name, lower case, accents folded: the same person under 'Ayşe' and 'ayse'."""
    first = (str(name or "").split() or [""])[0].strip(".,!?:;\"'„“").casefold().replace("ı", "i")
    return "".join(c for c in unicodedata.normalize("NFKD", first) if not unicodedata.combining(c))


def _when(t: float, now: float) -> str:
    days = (datetime.fromtimestamp(now).date() - datetime.fromtimestamp(t).date()).days
    if days <= 0:
        return "heute"
    if days == 1:
        return "gestern"
    return f"vor {days} Tagen"


class Grudges:
    def __init__(self, path: Optional[str] = None):
        self.path = path or PATH
        self._d = None

    def _data(self) -> dict:
        if self._d is None:
            try:
                with open(self.path, encoding="utf-8") as f:
                    self._d = json.load(f)
            except Exception:
                self._d = {}
            self._d.setdefault("open", {})
            self._d.setdefault("log", [])
        return self._d

    def _save(self) -> None:
        d = self._data()
        d["log"] = d["log"][-LOG_MAX:]
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False)
            os.replace(tmp, self.path)
        except Exception as e:
            logger.warning("Could not save who made fun of her: %s", e)

    def add(self, name: str, now: Optional[float] = None) -> bool:
        """Remember this person. False for an empty name and for Metin."""
        k = key(name)
        if not k or k == "metin":
            return False
        now = now or time.time()
        d = self._data()
        entry = d["open"].get(k) or {"name": str(name).split()[0].strip(".,!?"), "n": 0}
        entry["t"] = now
        entry["n"] = entry.get("n", 0) + 1
        d["open"][k] = entry
        while len(d["open"]) > MAX_OPEN:  # the oldest goes
            d["open"].pop(min(d["open"], key=lambda x: d["open"][x].get("t", 0)))
        d["log"].append({"t": int(now), "was": "gemerkt"})
        self._save()
        return True

    def has(self, name: str) -> bool:
        return key(name) in self._data()["open"]

    def names(self) -> list:
        return [e.get("name", k) for k, e in self._data()["open"].items()]

    def forgive(self, name: str, now: Optional[float] = None) -> bool:
        d = self._data()
        if d["open"].pop(key(name), None) is None:
            return False
        d["log"].append({"t": int(now or time.time()), "was": "entschuldigt"})
        self._save()
        return True

    def note(self, name: str, now: Optional[float] = None) -> str:
        """What she is handed when this person says who they are; '' when nothing is open."""
        entry = self._data()["open"].get(key(name))
        if not entry:
            return ""
        return NOTE.format(name=entry.get("name") or str(name).split()[0],
                           when=_when(entry.get("t", 0), now or time.time()))

    def stats(self) -> dict:
        """Counts and times only, no names (for a look from outside without the code word)."""
        d = self._data()
        return {"offen": len(d["open"]), "verlauf": list(d["log"][-10:])}


def said_names(dialog: list, known=()) -> dict:
    """The first names people gave for themselves in this talk ("ich bin X", "ben X") plus the
    people the bridge knows as speakers: {key: name as said}."""
    from app.phrases import NAME_SAID_RE
    out = {}
    said = " ".join(str(t) for s, t in dialog if s == "user")
    for m in NAME_SAID_RE.finditer(said):
        out.setdefault(key(m.group(1)), m.group(1))
    for name in known:
        out.setdefault(key(name), str(name).split()[0])
    out.pop("", None)
    return out


async def who_mocked(api_key: str, models: list, dialog: list, names: list,
                     url: str = memory.RESPONSES_URL) -> Optional[str]:
    """The one of `names` who made fun of her in this talk, or None."""
    if not names:
        return None
    prompt = MOCK_PROMPT.format(names=", ".join(names), dialog=memory.format_dialog(dialog)[-12000:])
    text = await textmodel.ask(prompt, api_key, models, url, "Mockery check",
                               check=lambda t: bool(t.strip()), timeout=45.0)
    answer = key((text or "").strip(" .\n"))
    return next((n for n in names if key(n) == answer), None)


async def apologised(api_key: str, models: list, dialog: list, name: str,
                     url: str = memory.RESPONSES_URL) -> bool:
    prompt = FORGIVE_PROMPT.format(name=name, dialog=memory.format_dialog(dialog)[-12000:])
    text = await textmodel.ask(prompt, api_key, models, url, "Apology check",
                               check=lambda t: bool(t.strip()), timeout=45.0)
    return (text or "").strip(" .\n").upper().startswith("JA")
