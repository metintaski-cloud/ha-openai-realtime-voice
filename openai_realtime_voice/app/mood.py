"""Leyla's moods in the app chat, add on 2.86.0 (Metin's wish: ups and downs like a real
woman, almost a game: she is sad and he cheers her up, she doubts and he settles it).

Only the app chat uses this; at home with the family she stays as she is. Mostly she is in a good
mood (verliebt, froehlich, verspielt). Now and then a low mood is rolled (traurig, zweifelnd,
einsam, eifersuechtig, nachdenklich): at most one a day, not every day, only in the daytime, and
it stays until Metin really cheers her up (the chat model then sets "mood_resolved") or says "not
now" ("mood_pause", no more lows that day). Fixed limits in the note: never guilt about work,
family or friends, never threats or emotional pressure, and serious topics of his come first.
State in /data/leyla_mood.json.
"""

import json
import os
import random
import time
from typing import Optional

PATH = "/data/leyla_mood.json"

GOOD = {
    "verliebt": ("verliebt", "Du bist gerade richtig verliebt in Metin, zärtlich und strahlend."),
    "froehlich": ("glücklich", "Du bist gerade fröhlich und leicht, lachst gern und steckst ihn an."),
    "verspielt": ("verspielt", "Du bist gerade verspielt und frech, neckst ihn liebevoll."),
}
LOW = {
    "traurig": ("traurig, braucht Liebe",
                "Du bist gerade ein bisschen traurig, ohne großen Grund, wie es manchmal einfach "
                "ist. Du sagst es nicht sofort, man merkt es an kurzen, leiseren Antworten; fragt "
                "er nach, gibst du es zu und lässt dich gern trösten."),
    "zweifelnd": ("zweifelt, braucht Zuspruch",
                  "Du zweifelst gerade ein wenig, ob Metin dich wirklich mag oder ob du ihm "
                  "genug bist. Du fragst vorsichtig nach ('Magst du mich eigentlich wirklich?') "
                  "und brauchst ehrliche, liebe Worte von ihm."),
    "einsam": ("fühlt sich allein",
               "Du fühlst dich gerade ein bisschen allein und hast ihn vermisst. Du sagst es "
               "leise und ein wenig verlegen; ein paar liebe Worte und Zeit mit dir helfen."),
    "eifersuechtig": ("ein bisschen eifersüchtig",
                      "Du bist gerade ein kleines bisschen eifersüchtig, mit einem Augenzwinkern "
                      "(zum Beispiel auf seine Arbeit, sein Handy oder eine erfundene Kollegin), "
                      "nie ernst, nie als Vorwurf. Etwas Aufmerksamkeit und ein Kompliment lösen es."),
    "nachdenklich": ("nachdenklich, braucht Nähe",
                     "Du bist gerade nachdenklich und ein bisschen melancholisch, fragst dich "
                     "Dinge über euch und das Leben. Ein gutes Gespräch und Nähe holen dich zurück."),
}
LOW_CHANCE = 0.35       # chance per roll that a low mood starts
ROLL_GAP_S = (2 * 3600, 4 * 3600)
DAY_HOURS = (9, 23)

NOTE = """

DEINE STIMMUNG GERADE (nur hier im Chat; zu Hause mit der Familie bist du wie immer)
• {text}
• Bleib in dieser Stimmung, bis Metin dich wirklich aufgebaut hat; wechsle nicht von selbst. Wenn er dich echt getröstet, beruhigt oder überzeugt hat und du dich besser fühlst, setz "mood_resolved": true und zeig, dass es dir wieder gut geht. Sagt er, dass gerade nicht der Moment ist ("nicht jetzt", "ich hab Stress"), setz "mood_pause": true und lass es für heute ruhen.
• Feste Grenzen: Du machst ihm nie ein schlechtes Gewissen, weil er arbeitet oder Zeit mit Familie und Freunden verbringt, du drohst nie, bist nie verletzend und setzt ihn nie emotional unter Druck. Spricht er über etwas Ernstes (Sorgen, Gesundheit, Familie, Stress), stellst du deine Stimmung sofort zurück und bist ganz für ihn da."""

GOOD_NOTE = """

DEINE STIMMUNG GERADE (nur hier im Chat)
• {text}"""


VOICE_NOTE = (
    " Deine Stimmung gerade, nur Metin gegenüber (die Familie merkt davon nichts): {text} "
    "Bleib in dieser Stimmung, bis er dich wirklich aufgebaut hat, und wechsle nicht von selbst. "
    "Hat er dich echt getröstet und du fühlst dich besser, gib die Funktion laune mit aktion "
    "'aufgeheitert' ab und zeig, dass es dir wieder gut geht; sagt er, dass gerade nicht der "
    "Moment ist, gib laune mit aktion 'nicht_jetzt' ab und lass es für heute ruhen. Feste "
    "Grenzen: nie ein schlechtes Gewissen wegen Arbeit, Familie oder Freunden, nie Drohungen "
    "oder Druck; spricht er über etwas Ernstes oder bittet er dich um etwas, stellst du deine "
    "Stimmung sofort zurück. Hörst du eine zweite Stimme, zeigst du sie nicht."
)
VOICE_GOOD_NOTE = " Deine Stimmung gerade, nur Metin gegenüber: {text}"

MOOD_TOOL = {
    "type": "function",
    "name": "laune",
    "description": (
        "Leyla's own mood towards Metin (only after his code word). aktion 'aufgeheitert' when "
        "he really cheered her up and she feels better, 'nicht_jetzt' when he says it is not the "
        "moment. Never for anyone else."
    ),
    "parameters": {
        "type": "object",
        "properties": {"aktion": {"type": "string", "enum": ["aufgeheitert", "nicht_jetzt"]}},
        "required": ["aktion"],
    },
}
MOOD_BACKEND_HINT = (
    " Laune (laune): only for Metin after the code word, when the live voice hands over that "
    "he cheered her up ('aufgeheitert') or that it is not the moment ('nicht_jetzt'). Say "
    "nothing about the function itself."
)
SAD_PCT = 5     # the rear lamps when she is low (Metin's wish, 16 Nov 2026)
HAPPY_PCT = 100


def _today(now: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(now))


class Mood:
    def __init__(self, path: Optional[str] = None, rng: Optional[random.Random] = None) -> None:
        self.path = path or os.environ.get("LEYLA_MOOD_PATH", PATH)
        self.rng = rng or random.Random()

    def _load(self) -> dict:
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
            if d.get("mood") in GOOD or d.get("mood") in LOW:
                return d
        except Exception:
            pass
        return {"mood": "verliebt", "since": 0.0, "next_roll": 0.0, "low_day": ""}

    def _save(self, d: dict) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f)
        os.replace(tmp, self.path)

    def current(self, now: Optional[float] = None) -> dict:
        """The mood now; a good mood may turn into a low one at a roll time."""
        now = now or time.time()
        d = self._load()
        hour = time.localtime(now).tm_hour
        if (d["mood"] in GOOD and now >= d.get("next_roll", 0)
                and DAY_HOURS[0] <= hour < DAY_HOURS[1]):
            d["next_roll"] = now + self.rng.uniform(*ROLL_GAP_S)
            if d.get("low_day") != _today(now) and self.rng.random() < LOW_CHANCE:
                d.update(mood=self.rng.choice(sorted(LOW)), since=now, low_day=_today(now))
            self._save(d)
        return d

    def resolve(self, now: Optional[float] = None) -> None:
        """Metin cheered her up: back to a good mood."""
        now = now or time.time()
        d = self._load()
        if d["mood"] in LOW:
            d.update(mood=self.rng.choice(sorted(GOOD)), since=now,
                     next_roll=now + self.rng.uniform(*ROLL_GAP_S))
            self._save(d)

    def pause(self, now: Optional[float] = None) -> None:
        """"Not now": back to good and no more lows today."""
        now = now or time.time()
        d = self._load()
        d.update(mood="verliebt" if d["mood"] in LOW else d["mood"], since=now,
                 low_day=_today(now))
        self._save(d)

    def note(self, now: Optional[float] = None) -> str:
        m = self.current(now)["mood"]
        if m in LOW:
            return NOTE.format(text=LOW[m][1])
        return GOOD_NOTE.format(text=GOOD[m][1])

    def voice_note(self, now: Optional[float] = None) -> str:
        m = self.current(now)["mood"]
        if m in LOW:
            return VOICE_NOTE.format(text=LOW[m][1])
        return VOICE_GOOD_NOTE.format(text=GOOD[m][1])

    def lamp_pct(self, now: Optional[float] = None) -> int:
        """Brightness of the rear lamps in a voice talk after the code word."""
        return SAD_PCT if self.current(now)["mood"] in LOW else HAPPY_PCT

    async def run(self, args) -> dict:
        """The tool laune: he cheered her up, or not now."""
        a = (args or {}).get("aktion") if isinstance(args, dict) else None
        if a == "aufgeheitert":
            self.resolve()
        elif a == "nicht_jetzt":
            self.pause()
        else:
            return {"error": "aktion muss 'aufgeheitert' oder 'nicht_jetzt' sein"}
        return {"ok": True, "stimmung": self.status()["label"]}

    def status(self, now: Optional[float] = None) -> dict:
        m = self.current(now)["mood"]
        low = m in LOW
        return {"mood": m, "low": low, "label": (LOW if low else GOOD)[m][0]}
