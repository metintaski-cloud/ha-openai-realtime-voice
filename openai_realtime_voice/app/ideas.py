"""Leyla's sudden ideas in the chat (add on 2.95.2, Metin's wishes of 16 Nov 2026).

Now and then her question jumps to another topic, like a person who suddenly remembers
something. The kind of idea is rolled from KINDS, never the same kind twice a day, so it stays
varied and realistic; what she already asked today is listed so she does not repeat it. A
question from such an idea stays open until he answers it: the next answers get a note to
come back to it (at most MAX_REMINDS times, within a day), the model says with
"frage_beantwortet" when his message answered it. Texts are never logged.
"""

import json
import logging
import os
import random
import re
import time
from typing import Optional

logger = logging.getLogger(__name__)

PATH = "/data/leyla_ideas.json"
MAX_REMINDS = 2
OPEN_FOR_S = 24 * 3600

KINDS = {
    "termin": "nach einem seiner Termine von heute (siehe seine Termine heute)",
    "frueher": "nach etwas, das er dir früher erzählt hat (aus deinem Tagebuch oder seinem Profil)",
    "offen": "nach einem offenen Punkt aus seinem Profil (Offen oder NOCH OFFEN)",
    "familie": "wie es jemandem aus seiner Familie oder seinem Freundeskreis geht, den du kennst",
    "ich": "von dir selbst: ein kleiner Gedanke oder eine kleine Alltagssache von dir, die zu deinem Tag passt, und was er dazu meint",
    "wunsch": "nach einem Wunsch, Traum oder Plan von ihm",
    "stimmung": "von dir selbst: deine Stimmung gerade, einfach in den Raum geworfen (zum Beispiel: Weißt du was, heute geht es mir nicht so gut. Magst du mich ein bisschen aufbauen?)",
}

NOTE = """

PLÖTZLICHER EINFALL (nur diesmal)
• Mitten im Gespräch fällt dir plötzlich etwas ein, das nichts mit seiner Nachricht zu tun hat, so wie bei einem echten Menschen. Geh erst kurz auf seine Nachricht ein, dann der Einfall, natürlich und nicht erzwungen. Dein Einfall diesmal: {kind}.
• Nur Echtes und Realistisches: nichts erfinden, was es in seinem Leben nicht gibt. Passt gerade nichts davon, lass den Einfall weg.
• Nie bei etwas Ernstem oder Traurigem von ihm.{asked}"""

OPEN_NOTE = """

DEINE OFFENE FRAGE
• Vorhin hast du ihn gefragt: «{q}». Beantwortet seine neue Nachricht das, setz "frage_beantwortet": true. Wenn nicht, bestehst du liebevoll darauf, dass die Frage noch offen ist (zum Beispiel: "Du hast mir übrigens noch gar nicht verraten, ..."), einmal, nicht drängelnd, und setz "frage_beantwortet": false."""

_QUESTION_RE = re.compile(r"[^.!?]*\?")


def last_question(text: str) -> str:
    found = _QUESTION_RE.findall(text or "")
    return found[-1].strip()[:200] if found else ""


class Ideas:
    def __init__(self, path: Optional[str] = None, rng: Optional[random.Random] = None) -> None:
        self.path = path or os.environ.get("LEYLA_IDEAS_PATH", PATH)
        self.rng = rng or random.Random()

    def _load(self, now: float) -> dict:
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f) or {}
        except Exception:
            d = {}
        today = time.strftime("%Y-%m-%d", time.localtime(now))
        if d.get("day") != today:  # a new day: every kind may come again
            d.update(day=today, used=[], asked=[])
        d.setdefault("open", None)
        return d

    def _save(self, d: dict) -> None:
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False)
            os.replace(tmp, self.path)
        except Exception as e:
            logger.warning("Ideas not saved: %s", e)

    def pick(self, low: bool = False, agenda: bool = False,
             now: Optional[float] = None) -> tuple:
        """(kind, note) for a sudden idea, or ("", "") when every fitting kind was used today."""
        now = now or time.time()
        d = self._load(now)
        kinds = [k for k in KINDS if k not in d["used"]
                 and (k != "stimmung" or low) and (k != "termin" or agenda)]
        if not kinds:
            return "", ""
        kind = self.rng.choice(kinds)
        asked = ("\n• Heute hast du schon gefragt, wiederhol nichts davon: "
                 + " / ".join(d["asked"])) if d["asked"] else ""
        return kind, NOTE.format(kind=KINDS[kind], asked=asked)

    def open_note(self, now: Optional[float] = None) -> str:
        now = now or time.time()
        o = self._load(now).get("open")
        if not o or now - o.get("t", 0) > OPEN_FOR_S or o.get("reminded", 0) >= MAX_REMINDS:
            return ""
        return OPEN_NOTE.format(q=o["q"])

    def voice_note(self, now: Optional[float] = None) -> str:
        """Her open chat question for a talk at home with Metin; counts as one reminder,
        because the live voice cannot report whether he answered."""
        now = now or time.time()
        d = self._load(now)
        o = d.get("open")
        if not o or now - o.get("t", 0) > OPEN_FOR_S or o.get("reminded", 0) >= MAX_REMINDS:
            return ""
        o["reminded"] = o.get("reminded", 0) + 1
        self._save(d)
        return ("\n\nOFFENE FRAGE AUS DEM CHAT: Du hattest Metin im Chat gefragt: «" + o["q"]
                + "». Er hat noch nicht geantwortet. Frag ihn im Gespräch noch einmal danach, "
                "und lass an deiner Stimme hören, dass du schon zum zweiten Mal fragst, mit "
                "einem Lächeln, nicht vorwurfsvoll.")

    def after_answer(self, reply: str, kind: str = "", open_noted: bool = False,
                     answered: bool = False, now: Optional[float] = None) -> None:
        now = now or time.time()
        d = self._load(now)
        if open_noted and d.get("open"):
            if answered:
                d["open"] = None
            else:
                d["open"]["reminded"] = d["open"].get("reminded", 0) + 1
        if kind:
            d["used"].append(kind)
            q = last_question(reply)
            if q:
                d["asked"].append(q)
                d["open"] = {"q": q, "t": now, "reminded": 0}
        self._save(d)
