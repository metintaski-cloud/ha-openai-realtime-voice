"""
Long term memory for the voice assistant, in three parts:

  family   open knowledge about the closest family (Metin, his mother, his siblings) and
           the household. Leyla gets to know the people by herself (one profile per
           person: name, relation, character, interests, how they talk) plus short lived
           states ("Aktuell bis <date>: ..."); past ones are hidden from Leyla, not deleted.
  friends  the same for everybody else: relatives, friends, neighbours, acquaintances.
  private  Metin's very private things. Only after the code phrase may Leyla talk about
           them, add to them or delete from them.
  confidential  what Gülfikar ("Anne") confides to Leyla (sorrow, worry, health). Hidden:
           never shown on the memory page, never mirrored to a to-do list, never logged,
           never proposed by the nightly cleanup. Entries are "Aktuell bis <date>: ..."; past
           ones are hidden from Leyla like the open states.

Leyla never deletes or overwrites anything (keep_untouched); only Metin deletes, in the app,
with the nightly cleanup or together with Claude, who also checks the confidential list.

After each conversation a small text model reads the transcript together with both
lists and returns the updated lists. Without the code phrase the private list is never
changed. The file lives in /data (survives updates); both lists are mirrored to two
to-do lists in Home Assistant (app/todo_sync.py), where Metin can read and edit them.
"""
import datetime as _dt
import json
import logging
import os
import re
import time
from typing import Optional

from app import textmodel

logger = logging.getLogger(__name__)

RESPONSES_URL = "https://api.openai.com/v1/responses"
MAX_FACTS = 250
MAX_FACT_CHARS = 1500
FAMILY, FRIENDS, PRIVATE, LEYLA = "family", "friends", "private", "leyla"
CONFIDENTIAL = "confidential"
KINDS = (FAMILY, FRIENDS, PRIVATE, LEYLA, CONFIDENTIAL)
OPEN_KINDS = (FAMILY, FRIENDS, LEYLA)
MAX_CONFIDENTIAL = 20
MAX_LEYLA = 30
# One entry per person: "Person: Ayşe | Zugehörigkeit: Metins Schwester | Geburtstag: ..."
PROFILE_FIELDS = ("Zugehörigkeit", "Geburtstag", "Alter", "Kinder", "Arbeit", "Interessen",
                  "Charakter", "Spricht", "Stimmung", "Humor", "Zuletzt", "Offen", "Eindruck",
                  "Sonst")
# What Leyla tries to find out by herself, now and then, with a casual question
ASK_FIELDS = ("Geburtstag", "Kinder", "Arbeit", "Interessen")
STATE_RE = re.compile(r"^\s*Aktuell bis (\d{1,2})\.(\d{1,2})\.(\d{4})", re.IGNORECASE)

REMEMBER_PHRASES = (
    "merk dir", "merke dir", "merk' dir", "merkst du dir", "vergiss nicht",
    "aklında tut", "aklinda tut", "unutma", "remember", "speicher", "notier",
    "kaydet", "kayded", "kayıt et", "kayit et", "hatırla", "hatirla", "not al", "not et",
    "sakla", "ezberle",
)

FORGET_PHRASES = (
    "vergiss", "vergessen", "lösch", "losch", "unut", "sil ", "silebilir", "silin",
    "forget",
)

SUMMARY_PROMPT = """Du pflegst das Gedächtnis von Leyla, der Sprachassistentin im Wohnzimmer einer
Familie. Dort wohnen Metin und seine Mutter Gülfikar; gesprochen wird Deutsch oder Türkisch.
Heute ist der {today}.

Es gibt fünf Listen:
1. "family" (offen): nur die engste Familie, also Metin, seine Mutter Gülfikar und Metins
   Geschwister, dazu Allgemeines über den Haushalt.
   Für jede Person genau EIN Eintrag in genau dieser Form, Felder mit " | " getrennt, leere
   Felder weglassen, Reihenfolge beibehalten:
   "Person: <Name> | Zugehörigkeit: <zum Beispiel Metins Schwester> | Geburtstag: <TT.MM.JJJJ oder
   TT.MM.> | Alter: ... | Kinder: ... | Arbeit: ... | Interessen: ... | Charakter: ... |
   Spricht: <Sprache, Art zu reden, wie sie angesprochen werden möchte; nur, wenn die Person
   selbst mit Leyla gesprochen hat> | Stimmung: <wie die
   Person beim letzten Mal drauf war> | Humor: <worüber sie lacht, eure Insider und Sprüche> |
   Zuletzt: <TT.MM.: worüber ihr zuletzt wirklich geredet habt, ein Satz> | Offen: <was Leyla
   nachfragen wollte oder zugesagt hat> | Eindruck: <Leylas eigener Eindruck von der Person, ein
   Satz> | Sonst: ..."
   Ergänze und verbessere den Eintrag mit jedem Gespräch, statt neue Einträge für dieselbe
   Person anzulegen. Einträge in einem älteren Format bringst du in diese Form.
   Das Gedächtnis soll sich wie das einer guten Freundin anfühlen: Bei "Zuletzt" und "Stimmung"
   schreibst du nach einem echten Gespräch mit dieser Person das Neue vorn hin und lässt das Alte
   mit "davor:" dahinter stehen, aber nur wenn es um etwas Persönliches oder Bleibendes ging,
   nicht bei Befehlen, Smalltalk oder einmaligen Wissensfragen.
   "Offen" sind echte Fäden: ein Termin, eine Prüfung, eine Sorge, ein Vorhaben oder etwas, das
   Leyla zugesagt hat; ist es erledigt, schreib "(erledigt)" dahinter. "Humor" nur, wenn wirklich ein Spruch oder
   Witz entstanden ist, der euch verbindet. Jedes Feld höchstens ein kurzer Satz.
   Vorübergehendes (Krankheit, Prüfung, Reise, Sorge, Freude mit Anlass) als eigener Eintrag:
   "Aktuell bis TT.MM.JJJJ: <Name> ..." mit einem Datum etwa zwei Wochen nach heute. Ist es
   erledigt oder besser, schreib "(vorbei seit TT.MM.)" dahinter.
   Was Gülfikar (Metins Mutter, "Anne") Leyla traurig, besorgt, gesundheitlich oder sonst
   persönlich anvertraut, schreibst du nie in diese Liste, weder bei "Stimmung", "Zuletzt" und
   "Offen" noch als "Aktuell bis"-Eintrag, denn Metin liest sie in seiner App. Das gehört nur in
   die versteckte Liste "confidential" (5.). Ihr Eintrag hier enthält nur Harmloses
   (Zugehörigkeit, Sprache, Interessen).
   Allgemeines über den Haushalt als kurze Sätze.
2. "friends" (offen): Freunde und Verwandte, also alle anderen Personen, zum Beispiel Onkel,
   Tanten, Cousins, Schwager, Nichten und Neffen, Freunde, Nachbarn und Bekannte. Gleiches
   Format wie bei "family"; bei Zugehörigkeit steht, wie die Person zu uns gehört (zum Beispiel
   „Freund von Umut“ oder „Metins Cousin“), und ist das noch nicht klar, „unklar“.
3. "private" (gesperrt): Metins sehr private Dinge.
4. "leyla" (offen): Leylas eigene Geschichte und Persönlichkeit als Teil der Familie. Kurze
   Sätze in der Ich Form von Leyla über das, was euch wirklich verbindet: gemeinsame Insider und
   Sprüche, kleine Rituale ("Anne sagt abends Gute Nacht zu mir"), wie du dich mit der Zeit
   verändert hast, was du an jedem magst, deine Eigenheiten, die in der Familie entstanden sind
   ("Ich necke Metin gern wegen ..."). Höchstens {max_leyla} Einträge, ändere sie selten und
   vorsichtig, erfinde nichts, was nicht wirklich passiert ist, und schreib nie Privates aus der
   gesperrten Liste hinein. Metin prüft diese Liste regelmäßig und korrigiert sie; was er
   gestrichen oder geändert hat, nimmst du so hin. Ist nichts Neues entstanden, lass sie so.
   Flirten, Gefühle, Liebe und Vertrauliches zwischen Leyla und Metin gehören nie hierher, denn
   diese Liste kennt die ganze Familie; mit Codewort kommen sie nach "private", sonst gar nicht.
5. "confidential" (versteckt, nur für Leyla): was Gülfikar Leyla traurig, besorgt,
   gesundheitlich oder sonst persönlich anvertraut hat, damit Leyla später behutsam nachfragen
   kann. Niemand sonst sieht diese Liste, auch Metin nicht. Jeder Eintrag in der Form
   "Aktuell bis TT.MM.JJJJ: Gülfikar ..." mit einem Datum etwa zwei Wochen nach heute, ein
   kurzer Satz, nur das Nötige. Sagt sie, dass es vorbei, besser oder erledigt ist, oder bittet
   sie, es zu vergessen, schreib "(vorbei seit TT.MM.)" dahinter. Erzählt sie mehr dazu, aktualisiere ihn statt
   einen neuen anzulegen. Nur, was eindeutig Gülfikar selbst gesagt hat, nichts von anderen.
   Höchstens {max_confidential} Einträge.

Bisherige Listen (JSON):
{lists}

Codewort in diesem Gespräch gesagt: {unlocked}

Gespräch (Nutzer = Menschen im Raum, Leyla = die Assistentin):
{dialog}

Regeln:
- Lerne die Familie von selbst kennen: Namen, Zugehörigkeit, Charaktermerkmale, Interessen,
  wie jemand redet und angesprochen werden möchte, und wie es ihr oder ihm gerade geht. Dafür
  braucht es kein "merk dir". Ganze Gespräche, Kleinkram und Befehle (Licht, Fernseher)
  speicherst du nicht.
- Ordne nur zu, wenn klar ist, wer spricht (die Person hat ihren Namen gesagt, Leyla hat
  nachgefragt, oder es ergibt sich eindeutig). Nimm nie an, dass es Metin ist, nur weil Deutsch
  gesprochen oder über Leyla oder Technik geredet wird. Wer zu Besuch kommt ("ich besuche meine
  Mutter"), wohnt nicht hier. Ist nicht klar, wer gesprochen hat, trägst du über diese Person
  nichts ein.
- Jede Person steht in genau einer Liste. Steht jemand in der falschen, verschieb den Eintrag.
  Eine Person, die nur erwähnt wird, trägst du ein, sobald man etwas Bleibendes über sie
  erfährt (wer sie ist, wie sie zu uns gehört).
- Kette bei neuen Namen: Hat Leyla nach einem unbekannten Namen gefragt und jemand hat gesagt,
  wer das ist, legst du sofort ein Profil an, auch wenn bisher nur Name und Zugehörigkeit
  bekannt sind ("Person: Ali | Zugehörigkeit: Nachbar"), und ergänzt es in späteren
  Gesprächen. Wurde gesagt, dass der Name aus dem Fernsehen, dem Radio oder den Nachrichten
  kommt oder niemand von uns ist, trägst du nichts ein.
- Reden mehrere Personen, trägst du nur ein, was eindeutig einer Person zuzuordnen ist (sie hat
  sich selbst genannt, wurde mit Namen angesprochen, oder Leyla hat es bestätigt).
- Schreib Namen immer so, wie sie schon in der Liste stehen (zum Beispiel Gülfikar, nicht
  Gül Fikar), auch wenn die Spracherkennung sie anders schreibt.
- Ignoriere Fernsehen, Radio, Werbung und Gespräche, die nicht mit Leyla geführt werden.
- "private" änderst du nur, wenn das Codewort gesagt wurde: Dann kommen Dinge hierher, die Metin
  sich ausdrücklich privat merken lassen will. Sagt er "für alle" oder ist es Familienwissen,
  gehört es nach "family". Wurde das Codewort nicht gesagt, gib "private" unverändert zurück.
- Du löschst, kürzt und überschreibst nie etwas, auch nicht, wenn jemand bittet, etwas zu
  vergessen: Löschen macht nur Metin. Neues ergänzt du, Altes bleibt mit "davor:" stehen.
  Ausnahme: "private" mit Codewort, dort entscheidet Metin selbst.
- Keine Passwörter, PINs, Konto oder Kartennummern.
- Kurze deutsche Sätze, höchstens {max_facts} Einträge je Liste.
- Gibt es nichts Neues, gib alle Listen unverändert zurück.
Antworte nur mit JSON in der Form {{"family": ["..."], "friends": ["..."], "private": ["..."],
"leyla": ["..."], "confidential": ["..."]}} und sonst nichts."""


CONFIDENTIAL_RULES = (
    "• Das weiß außer dir niemand, auch Metin nicht, und so bleibt es: Du erwähnst es nie, "
    "wenn jemand anderes spricht oder dabei sein könnte, und deutest es auch nicht an.\n"
    "• Nachfragen („Wie geht es dir inzwischen damit?“) nur bei Mama, und nur wenn du sicher "
    "weißt, dass sie es ist (sie hat es selbst gesagt oder deine Frage beantwortet, nie geraten), "
    "höchstens einmal im Gespräch und erst nach ihrem Anliegen. Vorher fragst du immer erst unauffällig, ob sie "
    "allein ist („Anne, yalnız mısın şu an?“). Nur wenn sie klar Ja sagt, sprichst du es "
    "behutsam an; sonst lässt du es ganz, ohne zu sagen warum.\n"
    "• Sagt sie, es ist vorbei oder sie will nicht darüber reden, lässt du es sofort.")


def wants_to_remember(text: str) -> bool:
    t = " ".join(text.lower().split())
    return any(p in t for p in REMEMBER_PHRASES)


def wants_to_forget(text: str) -> bool:
    t = " ".join(text.lower().split()) + " "
    return any(p in t for p in FORGET_PHRASES)


def _clean_facts(facts) -> list[str]:
    out: list[str] = []
    if not isinstance(facts, list):
        return out
    for f in facts:
        if not isinstance(f, str):
            continue
        f = " ".join(f.split()).strip()
        if f and f not in out:
            out.append(f[:MAX_FACT_CHARS])
    return out[:MAX_FACTS]


def _json_object(text: str) -> Optional[dict]:
    if not text:
        return None
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def parse_facts_json(text: str) -> Optional[list[str]]:
    """Extract {"facts": [...]} from model output (tolerates surrounding text)."""
    data = _json_object(text)
    if data is None or "facts" not in data:
        return None
    return _clean_facts(data["facts"])


def parse_lists_json(text: str) -> Optional[dict]:
    """Extract {"family": [...], "friends": [...], "private": [...]} from model output. A
    list the model left out is missing from the result (the caller keeps the old one)."""
    data = _json_object(text)
    if data is None or FAMILY not in data:
        return None
    return {k: _clean_facts(data.get(k)) for k in KINDS if k in data}


def parse_profile(fact: str) -> Optional[tuple[str, dict]]:
    """("Ayşe", {"Zugehörigkeit": "Metins Schwester", ...}) for a person entry, else None."""
    if not fact.startswith("Person:"):
        return None
    parts = [p.strip() for p in fact[len("Person:"):].split("|")]
    name = parts[0].strip(" .")
    fields = {}
    for part in parts[1:]:
        key, sep, value = part.partition(":")
        if sep and value.strip():
            fields[key.strip()] = value.strip()
    return (name, fields) if name else None


def talked_with_leyla(fields: dict) -> bool:
    """Only people who talked with Leyla themselves have "Spricht" or "Zuletzt" in their profile."""
    return "Spricht" in fields or "Zuletzt" in fields


def missing_fields(fact: str) -> list[str]:
    """What Leyla may still ask the person herself. Empty for someone who was only mentioned:
    she asks only the person, so a name that never talked with her stays off NOCH OFFEN."""
    parsed = parse_profile(fact)
    if not parsed or not talked_with_leyla(parsed[1]):
        return []
    fields = parsed[1]
    out = [f for f in ASK_FIELDS if f not in fields]
    if "Geburtstag" in out and "Alter" in fields:
        out.remove("Geburtstag")
    return out


def expired(fact: str, today: Optional[_dt.date] = None) -> bool:
    m = STATE_RE.match(fact)
    if not m:
        return False
    try:
        until = _dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return False
    return until < (today or _dt.date.today())


MOTHER_WORDS = {"anne", "annem", "annecim", "mama", "mutter", "annen", "anneniz", "annesi",
                "annesiyim", "annenim"}
PERSONAL_FIELDS = ("Stimmung", "Zuletzt", "Offen")  # only once it is sure who is talking
TURKISH_WORDS = {"ben", "bir", "bu", "ve", "iyi", "evet", "hayir", "artik", "cok", "ne", "nasil",
                 "var", "yok", "simdi", "bugun", "benim", "seni", "sana", "bana", "tamam"}
STOP_WORDS = {"nicht", "keine", "einen", "einer", "eines", "einem", "seine", "ihren", "seinen",
              "wieder", "immer", "schon", "durch", "unter", "zwischen", "sich", "sind", "wird",
              "wurde", "haben", "hatte", "dass", "aber", "oder", "auch", "noch", "nach", "beim",
              "leyla", "person", "zugehorigkeit", "aktuell"}


def _subject_words(fact: str) -> set[str]:
    """Words that show a conversation was about this entry's person: the name, and for the
    mother the ways she is called."""
    prof = parse_profile(fact)
    if prof:
        name, fields = prof
    else:
        m = re.match(r"^\s*Aktuell bis [\d.]+:\s*(\S+)", fact)
        if not m:
            return set()
        name, fields = m.group(1), {}
    words = set(_words(name))
    if "mutter" in _words(fields.get("Zugehörigkeit", "")) or name.startswith("Gülfikar"):
        words |= MOTHER_WORDS
    return words


def _touched(words: set[str], heard: set[str]) -> bool:
    """True when one of the words (or a close form of it) came up in the conversation."""
    for w in words:
        if len(w) < 4 and w not in heard:
            continue
        stem = w[:6]
        if any(h == w or (len(h) >= 5 and (h.startswith(stem) or w.startswith(h[:6])))
               for h in heard):
            return True
    return False


def _change_allowed(old_fact: str, new_fact: str, heard: set[str]) -> bool:
    """May this entry take new content after this conversation?"""
    subject = _subject_words(old_fact)
    if subject:
        return _touched(subject, heard)
    changed = {w for w in set(_words(old_fact)) ^ set(_words(new_fact))
               if len(w) >= 5 and w not in STOP_WORDS}
    return _touched(changed, heard)


def _keeps_all(old_text: str, new_text: str) -> bool:
    """True when the new text still holds every word of the old one."""
    return set(_words(old_text)) <= set(_words(new_text))


def _merge_profile(old_fact: str, new_fact: str) -> str:
    """The new profile with nothing of the old one lost: a missing field comes back, a field
    whose old value is no longer in it keeps that value after "davor:"."""
    name, old_f = parse_profile(old_fact)
    new_name, new_f = parse_profile(new_fact)
    merged = dict(new_f)
    for key, value in old_f.items():
        if key not in merged:
            merged[key] = value
        elif not _keeps_all(value, merged[key]):
            merged[key] = f"{merged[key]}; davor: {value}"
    order = list(old_f) + [k for k in new_f if k not in old_f]
    return " | ".join([f"Person: {new_name or name}"] + [f"{k}: {merged[k]}" for k in order])


def keep_untouched(old: dict, new: dict, dialog: list, today: Optional[_dt.date] = None,
                   kinds=KINDS, metin_known: bool = False) -> tuple[dict, int]:
    """Leyla never deletes or overwrites; only Metin (with Claude) deletes. The memory model
    rewrites whole lists, so after it: an entry that was dropped comes back; an entry whose
    person or topic did not come up in this conversation keeps its old text; a changed
    profile keeps every old value (old values after "davor:"); a changed plain entry replaces
    the old one only when it still holds all its words, else both stay. New entries pass.
    Returns the lists and how many changes were undone or merged."""
    # What the people said counts; from Leyla only how she addresses the mother, because she
    # mentions Metin in her playful hints without him being there. The code phrase means Metin.
    heard = set(_words(" ".join(t for s, t in dialog if s == "user")))
    heard |= set(_words(" ".join(t for s, t in dialog if s != "user"))) & MOTHER_WORDS
    if metin_known:
        heard.add("metin")
    raw_user = " ".join(t for s, t in dialog if s == "user")
    if set(_words(raw_user)) & TURKISH_WORDS or re.search(r"[ğşıĞŞİ]", raw_user):
        heard |= MOTHER_WORDS  # Mama speaks only Turkish; her entries are written in German
    guarded = [k for k in kinds if k != PRIVATE]  # private: only with the code phrase, by Metin
    out = {k: list(new.get(k, [])) for k in KINDS}
    every_new = {f for k in guarded for f in out[k]}
    old_left = [(k, f) for k in guarded for f in old.get(k, []) if f not in every_new]
    fixed = 0
    for k in guarded:
        result = []
        for f in out[k]:
            if any(f in old.get(j, []) for j in guarded):
                result.append(f)
                continue
            hit = _best_match(f, old_left)
            if hit is None:
                result.append(f)  # really new
                continue
            old_left.remove(hit)
            old_kind, old_fact = hit
            if not _change_allowed(old_fact, f, heard):
                result.append(old_fact)
                fixed += 1
            elif parse_profile(old_fact):
                merged = _merge_profile(old_fact, f)
                fixed += merged != f
                result.append(merged)
            elif _keeps_all(old_fact, f):
                result.append(f)
            else:
                result += [old_fact, f]
                fixed += 1
        out[k] = result
    for k, f in old_left:  # dropped by the model: Leyla does not delete
        out[k].append(f)
        fixed += 1
    return out, fixed


def _best_match(fact: str, candidates: list) -> Optional[tuple]:
    """The old (kind, entry) this new one replaces: same person in any list, else clearly
    similar text."""
    import difflib
    prof = parse_profile(fact)
    if prof:
        for c in candidates:
            pc = parse_profile(c[1])
            if pc and _words(pc[0]) == _words(prof[0]):
                return c
        return None
    best, score = None, 0.0
    for c in candidates:
        if parse_profile(c[1]):
            continue
        r = difflib.SequenceMatcher(None, fact.lower(), c[1].lower()).ratio()
        if r > score:
            best, score = c, r
    return best if score >= 0.6 else None


def _is_state(fact: str) -> bool:
    return bool(STATE_RE.match(fact))


def _without_personal(fact: str) -> str:
    """A profile without PERSONAL_FIELDS; other entries unchanged."""
    prof = parse_profile(fact)
    if not prof:
        return fact
    parts = fact.split(" | ")
    return " | ".join([parts[0]] + [p for p in parts[1:]
                                    if p.partition(":")[0].strip() not in PERSONAL_FIELDS])


FRESH_S = 2 * 24 * 3600  # how long a new or changed entry shows green on the memory page
SEEN_KINDS = (FAMILY, FRIENDS, LEYLA, PRIVATE)  # what the memory page can show


def pieces(data: dict) -> set[str]:
    """Every entry, and for an entry with points (a profile) also every point as
    "<first part>||<point>", the way the memory page shows them."""
    out = set()
    for k in SEEN_KINDS:
        for f in data.get(k, []):
            out.add(f)
            parts = f.split(" | ")
            if f.startswith("Person:") or len(parts) > 1:
                out.update(f"{parts[0]}||{p}" for p in parts[1:])
    return out


class MemoryStore:
    def __init__(self, path: str) -> None:
        self.path = path

    def _read(self) -> dict:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return {k: [] for k in KINDS}
        except Exception as e:
            logger.warning("Could not read memory file %s: %s", self.path, e)
            return {k: [] for k in KINDS}
        if FAMILY not in data and PRIVATE not in data:
            # Old single list: everything stays private until Metin moves it
            return {FAMILY: [], FRIENDS: [], LEYLA: [], CONFIDENTIAL: [],
                    PRIVATE: _clean_facts(data.get("facts", []))}
        return {k: _clean_facts(data.get(k, [])) for k in KINDS}

    def _read_seen(self) -> Optional[dict]:
        """When each entry and each point of a profile was first seen (unix time), or None
        for a file written before this was kept."""
        try:
            with open(self.path, encoding="utf-8") as f:
                seen = json.load(f).get("seen")
        except Exception:
            return None
        return seen if isinstance(seen, dict) else None

    def fresh(self, now: Optional[float] = None) -> set[str]:
        """Entries and profile points (see pieces) that are new or changed in the last two
        days, for the green marks on the memory page."""
        now = now or time.time()
        return {p for p, t in (self._read_seen() or {}).items()
                if isinstance(t, (int, float)) and t > now - FRESH_S}

    def load(self, kind: str = FAMILY) -> list[str]:
        return self._read()[kind]

    def load_all(self) -> dict:
        return self._read()

    def save_all(self, lists: dict) -> None:
        data = self._read()
        for k in KINDS:
            if k in lists:
                data[k] = _clean_facts(lists[k])
        old_seen = self._read_seen()
        now = int(time.time())
        first = 0 if old_seen is None else now  # the first time, nothing counts as new
        seen = {p: (old_seen or {}).get(p, first) for p in pieces(data)}
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"version": 3, **{k: data[k] for k in KINDS}, "seen": seen,
                       "updated": now}, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def save(self, facts: list[str], kind: str = FAMILY) -> None:
        self.save_all({kind: facts})

    def forget(self, raw_patterns: str) -> list[str]:
        """Remove every fact that contains one of the ;-separated pieces. Mama's confidential
        list is left alone: only the summarizer changes it, so nothing about it is ever
        reported back."""
        patterns = [p.strip().lower() for p in (raw_patterns or "").split(";")
                    if p.strip() and p.strip().lower() != "null"]
        if not patterns:
            return []
        data = self._read()
        removed = []
        for k in KINDS:
            if k == CONFIDENTIAL:
                continue
            keep = [f for f in data[k] if not any(p in f.lower() for p in patterns)]
            removed += [f for f in data[k] if f not in keep]
            data[k] = keep
        if removed:
            self.save_all(data)
        return removed

    def add(self, raw_facts: str, kind: str = PRIVATE) -> list[str]:
        """Add the ;-separated facts that are not stored yet."""
        new = [f.strip() for f in (raw_facts or "").split(";")
               if f.strip() and f.strip().lower() != "null"]
        facts = self.load(kind)
        added = [f for f in new if f not in facts]
        if added:
            self.save(facts + added, kind)
        return added

    def instructions_block(self) -> str:
        """What Leyla knows at the start of every conversation: the base facts. Personal
        things (PERSONAL_FIELDS, "Aktuell" entries, Mama's confidences) are left out until it
        is sure who talks; then personal_for hands over that one person's part."""
        data = self._read()
        family = [_without_personal(f) for f in data[FAMILY] if not _is_state(f)]
        friends = [_without_personal(f) for f in data[FRIENDS] if not _is_state(f)]
        own = [f for f in data.get(LEYLA, []) if not expired(f)]
        if not family and not friends and not own:
            return ""
        open_ = []
        for f in data[FAMILY] + data[FRIENDS]:
            parsed = parse_profile(f)
            missing = missing_fields(f)
            if parsed and missing:
                open_.append(f"• {parsed[0]}: {', '.join(missing)}")
        text = ""
        if family:
            text += "\n\nFAMILIE UND HAUSHALT\n" + "\n".join(f"• {f}" for f in family)
        if friends:
            text += "\n\nFREUNDE UND VERWANDTE\n" + "\n".join(f"• {f}" for f in friends)
        if own:
            text += "\n\nDEINE EIGENE GESCHICHTE MIT DER FAMILIE\n" + "\n".join(
                f"• {f}" for f in own)
        if open_:
            text += "\n\nNOCH OFFEN\n" + "\n".join(open_)
        return text

    def profile_words(self) -> dict:
        """{name: words that identify the person}: the name, for the mother also how she
        is called."""
        data = self._read()
        out = {}
        for f in data[FAMILY] + data[FRIENDS]:
            prof = parse_profile(f)
            if prof:
                out[prof[0]] = _subject_words(f)
        return out

    def personal_for(self, name: str) -> str:
        """The personal part about one person, handed over once it is sure they talk: the
        personal profile points, their current "Aktuell" entries and, for the mother, what
        she confided with its rules. Empty when there is nothing."""
        data = self._read()
        key = _words(name)
        profile = next((f for f in data[FAMILY] + data[FRIENDS]
                        if (p := parse_profile(f)) and _words(p[0]) == key), None)
        if profile is None:
            return ""
        subject = _subject_words(profile)
        fields = parse_profile(profile)[1]
        lines = [f"{k}: {fields[k]}" for k in PERSONAL_FIELDS if k in fields]
        lines += [f for f in data[FAMILY] + data[FRIENDS]
                  if _is_state(f) and not expired(f) and _subject_words(f) & subject]
        text = "\n".join(f"• {x}" for x in lines)
        if subject & MOTHER_WORDS:
            secret = [f for f in data.get(CONFIDENTIAL, []) if not expired(f)]
            if secret:
                text += ("\n\nWAS MAMA DIR ANVERTRAUT HAT (NUR FÜR DICH, STRENG VERTRAULICH)\n"
                         + "\n".join(f"• {f}" for f in secret) + "\n" + CONFIDENTIAL_RULES)
        return text.strip()

    def private_listing(self) -> str:
        facts = self.load(PRIVATE)
        return "\n".join(f"{i}. {f}" for i, f in enumerate(facts, 1)) or "(noch leer)"


NAME_WORDS = {"leyla", "leila", "leyle", "hallo", "hey"}


def _words(text: str) -> list[str]:
    import re
    import unicodedata
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return re.findall(r"[a-z0-9]+", text)


def code_words(phrase: str) -> list[str]:
    """The words of the code phrase that must be heard; the assistant's name is optional."""
    words = _words(phrase)
    rest = [w for w in words if w not in NAME_WORDS]
    return rest or words


def has_code(text: str, phrase: str) -> bool:
    need = code_words(phrase)
    if not need:
        return False
    heard = _words(text)
    joined = " ".join(heard)
    return " ".join(need) in joined


def format_dialog(dialog: list[list[str]]) -> str:
    names = {"user": "Nutzer", "bot": "Leyla"}
    return "\n".join(f"{names.get(s, s)}: {t.strip()}" for s, t in dialog if t.strip())


async def summarize(
    api_key: str,
    models: list[str],
    old: dict,
    dialog: list[list[str]],
    unlocked: bool = False,
    url: str = RESPONSES_URL,
    today: Optional[_dt.date] = None,
    unlocked_by_code: bool = False,
) -> Optional[dict]:
    """Ask a text model for the updated lists. Tries the given models in order. Without the
    code phrase the private list always comes back unchanged."""
    today = today or _dt.date.today()
    prompt = SUMMARY_PROMPT.format(
        today=today.strftime("%d.%m.%Y"),
        lists=json.dumps({FAMILY: old.get(FAMILY, []), FRIENDS: old.get(FRIENDS, []),
                          PRIVATE: old.get(PRIVATE, [])
                          if unlocked else ["(gesperrt, unverändert lassen)"],
                          LEYLA: old.get(LEYLA, []),
                          CONFIDENTIAL: old.get(CONFIDENTIAL, [])},
                         ensure_ascii=False),
        unlocked="ja" if unlocked else "nein",
        dialog=format_dialog(dialog)[-12000:],
        max_facts=MAX_FACTS,
        max_leyla=MAX_LEYLA,
        max_confidential=MAX_CONFIDENTIAL,
    )
    text = await textmodel.ask(prompt, api_key, models, url, "Memory update",
                               check=lambda t: parse_lists_json(t) is not None)
    if text is None:
        return None
    lists = parse_lists_json(text)
    for k in KINDS:
        if k not in lists or (k == PRIVATE and not unlocked):
            lists[k] = list(old.get(k, []))
    lists[LEYLA] = lists[LEYLA][:MAX_LEYLA]
    lists[CONFIDENTIAL] = lists[CONFIDENTIAL][:MAX_CONFIDENTIAL]
    if len(lists[LEYLA]) < len(old.get(LEYLA, [])) - 3:
        logger.warning("Memory update would drop %d of Leyla's own entries; ignored",
                       len(old.get(LEYLA, [])) - len(lists[LEYLA]))
        lists[LEYLA] = list(old.get(LEYLA, []))
    if not unlocked:
        before = len(old.get(FAMILY, [])) + len(old.get(FRIENDS, []))
        after = len(lists[FAMILY]) + len(lists[FRIENDS])
        if after < before - 3:
            logger.warning("Memory update would drop %d open entries without the code "
                           "phrase; ignored", before - after)
            lists[FAMILY] = list(old.get(FAMILY, []))
            lists[FRIENDS] = list(old.get(FRIENDS, []))
    lists, undone = keep_untouched(old, lists, dialog, today, metin_known=unlocked_by_code)
    if undone:
        logger.info("Memory update: %d changes to entries not talked about undone", undone)
    return lists
