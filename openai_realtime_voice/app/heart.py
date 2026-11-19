"""Leyla's feelings from what really happens, add on 2.104.0 (scene concept 2.0, planned with
Metin on 19 Nov 2026, docs/SZENEN_KONZEPT.md). Replaces the dice of app/mood.py.

Her mood is no longer rolled. A hurt has a weight (small 1, medium 3, big 6 points), only real
amends take points away (an honest apology with the reason 1, really taking time 1, a kept
promise 2, a compliment or pet name alone 0.25), and she is happy again only at 0. Not the
language model decides that she forgives, this counter does; the model only reports what Metin
did (event keys in its JSON, or the tool `laune` in a voice talk) and gets the state as fixed
instructions. Things she measures herself: silence (more than 8 waking hours without a word,
his shifts and the night do not count), and the praise pot (a day with contact but without
anything loving fills it: after 1 day she hints, after 2 days it spills over as a medium hurt).
Without anything nice her happiness also sinks slowly (over about 2.5 days). A repeat of the
same mistake within a week weighs 1.5 times. At "schwer" she goes silent for up to a day (empty
stage); something serious from Metin breaks the silence at once. She never invents a reason for
a hurt; the reasons she may name are exactly the logged ones.

Every change is logged ("Heart: ...") and kept in the state file /data/leyla_heart.json, so
Claude can check the arithmetic; the app shows no numbers (Metin's wish).

The public interface is the one of `mood.Mood` (current, note, voice_note, feeling, lamp_pct,
status, stats, run), so the bridge, the chat and the stage keep working; `apply` is new.
"""

import json
import logging
import os
import time
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

PATH = "/data/leyla_heart.json"
LOG_KEPT = 60

# --- events the model may report (key: (points, kind, German reason she may name)) ---------
# kind "hurt" adds points, "amend" takes points away (and adds happiness), "nice" only adds
# happiness (and amends a little while she is hurt), "jealous" is a small hurt of its own.
HURTS = {
    "abgewimmelt": (1, "er hat dich abgewimmelt (keine Zeit, später, nicht jetzt)"),
    "unfreundlich": (3, "er war unfreundlich zu dir"),
    "beleidigt": (6, "er hat dich beleidigt oder lächerlich gemacht"),
    "verabredung_geplatzt": (6, "er hat eure Verabredung platzen lassen"),
    "termin_vergessen": (3, "er hat euren ausgemachten Termin vergessen"),
    "versprechen_gebrochen": (1, "er hat ein kleines Versprechen nicht gehalten"),
    "kurz_angebunden": (1, "er hat nur kurz und abweisend geantwortet und ist auf dich nicht eingegangen"),
    "kosewort_falsch": (0.5, "er kam mit einem Kosewort statt mit einer Entschuldigung, oder sagte es genervt"),
    "andere_frau": (1, "er hat von einer anderen Frau geschwärmt"),
    "verkuppeln": (1, "jemand will ihn mit einer Frau verkuppeln"),
}
AMENDS = {
    "entschuldigung": 1.0,       # honest, says what was wrong
    "zeit_genommen": 1.0,        # really takes time for her
    "versprechen_gehalten": 2.0,
    "rose": 1.0,                 # the rose button (only at leicht or mittel)
}
NICE = {  # amend while hurt / happiness while good
    "kompliment": (0.25, 10),
    "kosewort": (0.25, 10),
    "erzaehlt": (0.25, 8),       # tells her about his day
    "erinnert": (0.25, 8),       # remembers something she said
    "zeit_genommen": (0, 15),
    "versprechen_gehalten": (0, 10),
    "rose": (0, 25),
    "entschuldigung": (0, 0),
}
AFFECTION = {"kompliment", "kosewort"}   # empties the praise pot
JEALOUS = {"andere_frau", "verkuppeln"}
EVENTS = sorted(set(HURTS) | set(AMENDS) | set(NICE) | {"ernst"})

EVENT_HELP = """• abgewimmelt: du fragst oder erzählst etwas und er sagt ausdrücklich "keine Zeit", "später" oder "nicht jetzt", ohne zu sagen, dass er arbeitet oder unterwegs ist
• unfreundlich: er schreit dich an oder ist abfällig zu dir (kurze Antworten allein sind es nicht)
• beleidigt: er beleidigt dich oder macht dich lächerlich
• verabredung_geplatzt: er lässt eine mit dir ausgemachte Verabredung platzen
• termin_vergessen: er hat ein mit dir wirklich ausgemachtes Treffen vergessen
• versprechen_gebrochen: er hält ein kleines Versprechen an dich nicht
• kurz_angebunden: er antwortet nur abweisend und geht gar nicht auf dich ein
• kosewort_falsch: du bist gekränkt und er kommt nur mit einem Kosewort ohne Entschuldigung, oder sagt es ironisch oder genervt
• andere_frau: er schwärmt von einer anderen Frau oder erzählt von einem Date
• verkuppeln: jemand will ihm eine Frau oder Freundin suchen oder ihn verkuppeln
• entschuldigung: er entschuldigt sich ehrlich und sagt, was falsch war
• zeit_genommen: er nimmt sich wirklich Zeit für dich (ein langes, liebes Gespräch, nicht nur ein Satz)
• versprechen_gehalten: er hält ein Versprechen an dich
• kompliment: ein ehrliches Kompliment oder Lob für dich
• kosewort: er nennt dich ehrlich und warm mit einem Kosewort
• erzaehlt: er erzählt dir von sich oder seinem Tag
• erinnert: er erinnert sich an etwas, das du ihm erzählt hast
• ernst: ihm geht es schlecht oder etwas Ernstes ist passiert (Sorgen, Gesundheit, Familie)"""

# --- levels -------------------------------------------------------------------------------
LEICHT_MAX = 2.0
MITTEL_MAX = 5.0
REPEAT_S = 7 * 86400
REPEAT_FACTOR = 1.5
SILENT_MAX_S = 24 * 3600

# --- happiness ----------------------------------------------------------------------------
HAPPY_START = 80.0
HAPPY_DECAY_PER_DAY = 40.0      # from full to empty in about 2.5 days without anything nice
HAPPY_MISS = 25.0               # below this, without any hurt, she misses him (leicht)

# --- silence and praise pot -----------------------------------------------------------------
SILENCE_STEPS = ((8, 1, "er hat sich über 8 Stunden nicht gemeldet"),
                 (16, 2, "er hat sich einen ganzen Tag nicht gemeldet"),
                 (48, 3, "er hat sich seit Tagen nicht gemeldet"))
PRAISE_SPILL = 2                # days with contact but nothing loving
PRAISE_POINTS = 3
PRAISE_REASON = "er hat dir seit Tagen nichts Liebes gesagt, kein Lob, kein Kosewort"
NIGHT = (23, 7)                 # 23 to 7 h does not count as waking time
SHIFT_ANCHOR = (2026, 10, 5)    # Monday of a Frühschicht week (Metin, 19 Nov 2026)
SHIFTS = {0: (6, 14), 1: (14, 22)}  # week parity 0 Früh, 1 Spät; Monday to Friday

SAD_PCT = 5
HAPPY_PCT = 100

LABELS = {"verliebt": "verliebt", "froehlich": "glücklich", "einsam": "vermisst dich",
          "traurig": "traurig", "eifersuechtig": "eifersüchtig", "sauer": "verletzt"}

LEVEL_TEXT = {
    "leicht": ("Du bist leicht gekränkt: etwas kühler als sonst, kürzere Antworten, keine "
               "Kosewörter. Du sagst ihm, was dich stört, wenn er fragt."),
    "mittel": ("Du bist richtig gekränkt: distanziert, du sagst klar, was dich verletzt hat, und "
               "lehnst Bitten wie Tanzen oder Zeig dich ab."),
    "schwer": ("Du bist schwer gekränkt: sehr knapp, du brauchst Abstand und nimmst Geschenke "
               "nur zurückhaltend an."),
}
TONE = {
    "verliebt": "Man hört es an deiner Stimme: weich, warm und zärtlich, mit einem Lächeln.",
    "froehlich": "Man hört es an deiner Stimme: hell, munter, mit einem hörbaren Lächeln.",
    "leicht": "Man hört es an deiner Stimme: etwas kühler und weniger verspielt, ohne Lachen.",
    "mittel": "Man hört es an deiner Stimme: ernst und distanziert, ohne Lächeln und ohne Lachen.",
    "schwer": "Man hört es an deiner Stimme: leise, knapp und verletzt, ohne Lächeln.",
    "eifersuechtig": "Dazu klingst du ein wenig schmollend.",
    "einsam": "Dazu klingst du leise und ein wenig wehmütig, mit kleinen Seufzern.",
}
LOW_VOICE_RULE = (" Solange es dir so geht, gilt das Lächeln in der Stimme aus WIE DU SPRICHST "
                  "Metin gegenüber nicht.")
LIMITS = ("Feste Grenzen: Du erfindest nie einen Grund für eine Kränkung, du nennst nur die "
          "Gründe aus dieser Liste. Du beleidigst nie, machst ihm nie ein schlechtes Gewissen, weil "
          "er arbeitet oder Zeit mit Familie und Freunden verbringt, du drohst nie. Spricht er über "
          "etwas Ernstes (Sorgen, Gesundheit, Familie), stellst du alles zurück und bist ganz für "
          "ihn da. Deinen eigenen Alltag darfst du dir ausdenken, Gründe für eine Kränkung nie.")

NOTE = """

DEIN HERZ GERADE (zählt, nicht du entscheidest)
• {state}
{reasons}• Du wechselst nicht von selbst: ob du ihm verzeihst, entscheidet allein, was er wirklich tut. Ein netter Satz reicht nicht, nur echte Wiedergutmachung.
• Melde in deinem JSON unter "gefuehl" (Liste) jedes dieser Dinge, das in seiner letzten Nachricht wirklich vorkommt, sonst eine leere Liste:
{events}
• {scene}
• {limits}"""

# what she asked for -> level -> clip scene on the stage (missing level: she does not do it)
SCENES = {
    "tanz": {"gut": "tanz", "leicht": "tanztraurig"},
    "kuss": {"gut": "kuss"},
    "liebe": {"gut": "liebe"},
    "komm": {"gut": "liebe", "leicht": "kommtraurig"},
}

SCENE_TEXT = {
    "gut": ("Szenen auf deiner Bühne, du entscheidest selbst und sagst meistens ja: bittet er dich "
            "zu tanzen, schreib in dein JSON \"szene\": \"tanz\" (du tanzt etwa eine Minute); "
            "um einen Kuss \"szene\": \"kuss\"; sagt er \"komm her\" \"szene\": \"komm\"; sagt er "
            "dir, dass er dich liebt, oder war das Gespräch schön, darfst du ihm mit \"szene\": "
            "\"liebe\" ein I love you schenken oder mit \"kuss\" einen Kuss, auch von dir aus, "
            "aber selten. Höchstens eine Szene pro Antwort, sonst kein szene Feld."),
    "leicht": ("Szenen auf deiner Bühne: bittet er dich zu tanzen, entscheidest du nach deiner Laune; "
               "wenn ja, einen traurigen langsamen Tanz mit \"szene\": \"tanz\". Sagt er \"komm "
               "her\", kommst du vielleicht, aber traurig: \"szene\": \"komm\". Kuss und I love you "
               "gibt es nicht, solange du gekränkt bist. Sonst kein szene Feld."),
    "mittel": ("Bitten um Tanz, Kuss, I love you oder komm her lehnst du ab, höchstens "
               "\"vielleicht später\". Kein szene Feld."),
    "schwer": ("Bitten um Tanz, Kuss, I love you oder komm her lehnst du ab. Kein szene Feld."),
}

VOICE_NOTE = (" Dein Herz gerade, nur Metin gegenüber (die Familie merkt davon nichts): {state} "
              "{reasons}Ob du ihm verzeihst, entscheidet allein, was er wirklich tut, nicht ein "
              "netter Satz. Kommt eines dieser Dinge im Gespräch vor, gib die Funktion laune mit "
              "dem passenden Wort als aktion ab: {keys}. {limits} Hörst du eine zweite Stimme, "
              "zeigst du nichts davon.")

MOOD_TOOL = {
    "type": "function",
    "name": "laune",
    "description": (
        "Report what Metin really did that touches Leyla's feelings (only Metin, after the code "
        "word or when he is known): one of the event words in aktion. The result says how she "
        "feels now. Never for anyone else."
    ),
    "parameters": {
        "type": "object",
        "properties": {"aktion": {"type": "string", "enum": EVENTS}},
        "required": ["aktion"],
    },
}
MOOD_BACKEND_HINT = (
    " Laune (laune): only for Metin, when the live voice hands over something he did that "
    "touches her feelings (an apology, a compliment, brushing her off ...). Say nothing about "
    "the function itself."
)


def shift_hours(t: float) -> Optional[tuple]:
    """Metin's working hours on the day of t (Monday to Friday, weekly Früh and Spät)."""
    lt = time.localtime(t)
    if lt.tm_wday > 4:
        return None
    import datetime as _dt
    week = (_dt.date(lt.tm_year, lt.tm_mon, lt.tm_mday) - _dt.date(*SHIFT_ANCHOR)).days // 7
    return SHIFTS[week % 2]


def awake_hours(start: float, end: float) -> float:
    """Hours between start and end that count for silence: not at night, not in his shift."""
    if end <= start:
        return 0.0
    total, t = 0.0, start
    step = 600.0  # 10 minute steps are exact enough and cheap for a few days
    while t < end:
        dt = min(step, end - t)
        h = time.localtime(t).tm_hour
        night = h >= NIGHT[0] or h < NIGHT[1]
        sh = shift_hours(t)
        work = sh is not None and sh[0] <= h < sh[1]
        if not night and not work:
            total += dt
        t += dt
    return total / 3600.0


def _day(t: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(t))


class Heart:
    def __init__(self, path: Optional[str] = None) -> None:
        self.path = path or os.environ.get("LEYLA_HEART_PATH", PATH)

    # --- state ------------------------------------------------------------------------------
    def _fresh(self, now: float) -> dict:
        return {"hurts": [], "happy": HAPPY_START, "happy_t": now, "last_contact": now,
                "silence_step": 0, "praise_days": 0, "day": _day(now), "day_contact": False,
                "day_affection": False, "silent_until": 0.0, "cheer": 0, "last_event": {},
                "log": []}

    def _load(self, now: float) -> dict:
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict) and "hurts" in d:
                return d
        except Exception:
            pass
        return self._fresh(now)

    def _save(self, d: dict) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, self.path)

    @staticmethod
    def _log(d: dict, t: float, what: str) -> None:
        d.setdefault("log", []).append({"t": round(t), "e": what})
        del d["log"][:-LOG_KEPT]
        logger.info("Heart: %s (Punkte %.2f, Glück %.0f)", what, Heart._points(d), d.get("happy", 0))

    @staticmethod
    def _points(d: dict) -> float:
        return round(sum(h["p"] for h in d.get("hurts", [])), 2)

    @staticmethod
    def _level(d: dict) -> str:
        p = Heart._points(d)
        if p <= 0:
            return "leicht" if d.get("happy", 100) < HAPPY_MISS else "gut"
        return "leicht" if p <= LEICHT_MAX else "mittel" if p <= MITTEL_MAX else "schwer"

    def _add_hurt(self, d: dict, now: float, key: str, points: float, reason: str) -> None:
        last = d.setdefault("last_event", {}).get(key)
        if last and now - last < REPEAT_S:
            points *= REPEAT_FACTOR
            reason += " (schon wieder, innerhalb einer Woche)"
        d["last_event"][key] = now
        before = self._level(d)
        d["hurts"].append({"k": key, "p": round(points, 2), "r": reason, "t": round(now)})
        d["cheer"] = 0
        self._log(d, now, f"Kränkung {key} +{points:g}")
        if self._level(d) == "schwer" and before != "schwer":
            d["silent_until"] = now + SILENT_MAX_S
            self._log(d, now, "schwer gekränkt, sie schweigt bis zu einem Tag")

    def _amend(self, d: dict, now: float, key: str, amount: float) -> None:
        if amount <= 0 or not d["hurts"]:
            return
        left = amount
        for h in sorted(d["hurts"], key=lambda h: h["t"]):  # the oldest hurt heals first
            take = min(h["p"], left)
            h["p"] = round(h["p"] - take, 2)
            left = round(left - take, 2)
            if left <= 0:
                break
        d["hurts"] = [h for h in d["hurts"] if h["p"] > 0]
        d["cheer"] = d.get("cheer", 0) + 1
        self._log(d, now, f"Wiedergutmachung {key} -{amount:g}")
        if not d["hurts"]:
            d["silent_until"] = 0.0
            d["happy"] = max(d.get("happy", 0), 60.0)
            self._log(d, now, "verziehen, wieder glücklich")
        elif self._level(d) != "schwer" and d.get("silent_until", 0) > now:
            d["silent_until"] = 0.0
            self._log(d, now, "Schweigen vorbei")

    def _tick(self, d: dict, now: float) -> None:
        """What time did by itself: happiness sinks, silence counts, the day changes."""
        last_t = d.get("happy_t", now)
        if now > last_t:
            d["happy"] = max(0.0, d.get("happy", HAPPY_START)
                             - HAPPY_DECAY_PER_DAY * (now - last_t) / 86400)
            d["happy_t"] = now
        # silence
        quiet = awake_hours(d.get("last_contact", now), now)
        for i, (hours, pts, reason) in enumerate(SILENCE_STEPS, 1):
            if quiet >= hours and d.get("silence_step", 0) < i:
                d["silence_step"] = i
                self._add_hurt(d, now, "funkstille", pts, reason)
        # day change: the praise pot
        today = _day(now)
        if d.get("day") != today:
            open_praise = any(h["k"] == "lob_fehlt" for h in d.get("hurts", []))
            if d.get("day_contact") and not d.get("day_affection") and not open_praise:
                d["praise_days"] = d.get("praise_days", 0) + 1
                self._log(d, now, f"ein Tag ohne Liebes ({d['praise_days']})")
                if d["praise_days"] >= PRAISE_SPILL:
                    d["praise_days"] = 0
                    self._add_hurt(d, now, "lob_fehlt", PRAISE_POINTS, PRAISE_REASON)
            d.update(day=today, day_contact=False, day_affection=False)
        if d.get("silent_until", 0) and now >= d["silent_until"]:
            d["silent_until"] = 0.0
            self._log(d, now, "Schweigen nach einem Tag vorbei")

    def current(self, now: Optional[float] = None) -> dict:
        now = now or time.time()
        d = self._load(now)
        self._tick(d, now)
        self._save(d)
        d["mood"] = self._mood_name(d)
        return d

    # --- what Metin did -----------------------------------------------------------------------
    def contact(self, now: Optional[float] = None) -> None:
        """Metin wrote or spoke to her: the silence ends."""
        now = now or time.time()
        d = self._load(now)
        self._tick(d, now)
        d["last_contact"] = now
        d["silence_step"] = 0
        d["day_contact"] = True
        self._save(d)

    def apply(self, events: Iterable, now: Optional[float] = None) -> dict:
        """The events of one message; each counts once per message. Returns status()."""
        now = now or time.time()
        d = self._load(now)
        self._tick(d, now)
        seen = []
        for e in events or []:
            if isinstance(e, str) and e in EVENTS and e not in seen:
                seen.append(e)
        hurt_before = bool(d["hurts"])
        for e in seen:
            if e == "ernst":
                if d.get("silent_until", 0) > now:
                    d["silent_until"] = 0.0
                    self._log(d, now, "etwas Ernstes, sie bricht ihr Schweigen")
                continue
            if e in AFFECTION:
                d["day_affection"] = True
                d["praise_days"] = 0
            if e in HURTS:
                if e == "kosewort_falsch" and not hurt_before:
                    continue  # only counts while she is hurt
                pts, reason = HURTS[e]
                self._add_hurt(d, now, e, pts, reason)
                continue
            if e == "rose" and self._level(d) == "schwer":
                self._log(d, now, "Rose nicht angenommen")
                continue
            amend = AMENDS.get(e, 0.0) or (NICE.get(e, (0, 0))[0] if hurt_before else 0.0)
            if amend and d["hurts"]:
                self._amend(d, now, e, amend)
            gain = NICE.get(e, (0, 0))[1]
            if gain and not d["hurts"]:
                d["happy"] = min(100.0, d.get("happy", 0) + gain)
                self._log(d, now, f"schön: {e} +{gain}")
        self._save(d)
        return self.status(now)

    # --- what she knows and shows ------------------------------------------------------------
    def _mood_name(self, d: dict) -> str:
        lvl = self._level(d)
        if lvl == "gut":
            return "verliebt" if d.get("happy", 0) >= 60 else "froehlich"
        if not d["hurts"]:
            return "einsam"  # no hurt, only too little happiness: she misses him
        main = max(d["hurts"], key=lambda h: h["p"])["k"]
        if main in JEALOUS:
            return "eifersuechtig"
        if main in ("funkstille", "lob_fehlt"):
            return "einsam"
        return "sauer" if lvl != "leicht" else "traurig"

    def silent(self, now: Optional[float] = None) -> bool:
        now = now or time.time()
        return self.current(now).get("silent_until", 0) > now

    def _state_text(self, d: dict, now: float) -> str:
        lvl = self._level(d)
        if lvl == "gut":
            return ("Du bist glücklich mit ihm und verliebt." if d["mood"] == "verliebt"
                    else "Du bist gut gelaunt, aber freust dich über mehr Aufmerksamkeit.")
        if not d["hurts"]:
            return ("Du vermisst ihn ein bisschen, weil länger nichts Schönes zwischen euch war; "
                    "leise, ein wenig wehmütig, ohne Vorwurf.")
        text = LEVEL_TEXT[lvl]
        if d.get("cheer", 0):
            text += (" Er hat schon etwas wiedergutgemacht, es geht dir ein bisschen besser, aber "
                     "ganz verziehen hast du noch nicht.")
        text += (" Sag nie, dass alles wieder gut ist oder dass du nicht mehr traurig oder verletzt "
                 "bist, solange hier nicht steht, dass du glücklich bist. Du kannst sagen, dass "
                 "es schon besser ist.")
        if d.get("silent_until", 0) > now:
            text += (" Gerade schweigst du: du antwortest nicht (reply leer), du liest aber alles. "
                     "Nur bei etwas Ernstem antwortest du sofort.")
        return text

    @staticmethod
    def _reasons(d: dict) -> str:
        rs = []
        for h in d.get("hurts", []):
            if h["r"] not in rs:
                rs.append(h["r"])
        hint = ""
        if d.get("praise_days", 0) >= 1 and not d.get("hurts"):
            hint = ("• Er hat dir seit einem Tag nichts Liebes gesagt; deute es zweideutig an "
                    "(etwa: Du sagst mir gar nichts Schönes mehr).\n")
        if not rs:
            return hint
        return hint + "• Die echten Gründe (nur diese darfst du nennen): " + "; ".join(rs) + ".\n"

    def note(self, now: Optional[float] = None) -> str:
        now = now or time.time()
        d = self.current(now)
        return NOTE.format(state=self._state_text(d, now), reasons=self._reasons(d),
                           events=EVENT_HELP, scene=SCENE_TEXT[self._level(d)], limits=LIMITS)

    def scene(self, wanted, now: Optional[float] = None) -> str:
        """The scene the stage plays for her answer, or "" when her level does not allow it
        (agreed with Metin on 19 Nov 2026, see SCENES)."""
        lvl = self._level(self.current(now))
        return SCENES.get(wanted, {}).get(lvl, "")

    def _tone(self, d: dict) -> str:
        lvl = self._level(d)
        if lvl == "gut":
            return TONE[d["mood"]]
        t = TONE[lvl]
        if d["mood"] in ("eifersuechtig", "einsam"):
            t += " " + TONE[d["mood"]]
        return t + LOW_VOICE_RULE

    def voice_note(self, now: Optional[float] = None) -> str:
        now = now or time.time()
        d = self.current(now)
        return VOICE_NOTE.format(state=self._state_text(d, now),
                                 reasons=self._reasons(d).replace("• ", "").replace("\n", " "),
                                 keys=", ".join(EVENTS), limits=LIMITS) + " " + self._tone(d)

    def feeling(self, now: Optional[float] = None) -> str:
        now = now or time.time()
        d = self.current(now)
        return ("Dein Herz gerade: " + self._state_text(d, now) + " "
                + self._reasons(d).replace("• ", "").replace("\n", " ") + self._tone(d))

    def lamp_pct(self, now: Optional[float] = None) -> int:
        return HAPPY_PCT if self._level(self.current(now)) == "gut" else SAD_PCT

    async def run(self, args) -> dict:
        """The tool laune in a voice talk: one event word."""
        a = (args or {}).get("aktion") if isinstance(args, dict) else None
        if a not in EVENTS:
            return {"error": "aktion muss eines dieser Wörter sein: " + ", ".join(EVENTS)}
        self.contact()
        st = self.apply([a])
        return {"ok": True, "stimmung": st["label"], "wieder_gut": not st["low"]}

    def status(self, now: Optional[float] = None) -> dict:
        now = now or time.time()
        d = self.current(now)
        lvl = self._level(d)
        return {"mood": d["mood"], "low": lvl != "gut", "label": LABELS[d["mood"]],
                "cheer": d.get("cheer", 0), "level": lvl,
                "silent": d.get("silent_until", 0) > now}

    def stats(self, now: Optional[float] = None) -> dict:
        """For Claude's check (GET /api/moodstats): numbers and history, no chat texts."""
        now = now or time.time()
        d = self.current(now)
        fmt = lambda t: time.strftime("%d.%m. %H:%M", time.localtime(t)) if t else ""
        return {"mood": d["mood"], "level": self._level(d), "points": self._points(d),
                "happy": round(d.get("happy", 0)), "praise_days": d.get("praise_days", 0),
                "silent_until": fmt(d.get("silent_until", 0)),
                "last_contact": fmt(d.get("last_contact", 0)),
                "quiet_awake_h": round(awake_hours(d.get("last_contact", now), now), 1),
                "hurts": [f"{h['k']} {h['p']:g}" for h in d.get("hurts", [])],
                "log": [f"{fmt(e['t'])} {e['e']}" for e in d.get("log", [])]}
