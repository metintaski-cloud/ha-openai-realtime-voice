"""
Long term memory for the voice assistant, in three parts:

  family   open knowledge about the closest family (Metin, his mother, his siblings) and
           the household. Leyla gets to know the people by herself (one profile per
           person: name, relation, character, interests, how they talk) plus short lived
           states ("Aktuell bis <date>: ...") that expire on their own.
  friends  the same for everybody else: relatives, friends, neighbours, acquaintances.
  private  Metin's very private things. Only after the code phrase may Leyla talk about
           them, add to them or delete from them.

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

import httpx

logger = logging.getLogger(__name__)

RESPONSES_URL = "https://api.openai.com/v1/responses"
MAX_FACTS = 250
MAX_FACT_CHARS = 700
FAMILY, FRIENDS, PRIVATE, LEYLA = "family", "friends", "private", "leyla"
KINDS = (FAMILY, FRIENDS, PRIVATE, LEYLA)
OPEN_KINDS = (FAMILY, FRIENDS, LEYLA)
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

Es gibt vier Listen:
1. "family" (offen): nur die engste Familie, also Metin, seine Mutter Gülfikar und Metins
   Geschwister, dazu Allgemeines über den Haushalt.
   Für jede Person genau EIN Eintrag in genau dieser Form, Felder mit " | " getrennt, leere
   Felder weglassen, Reihenfolge beibehalten:
   "Person: <Name> | Zugehörigkeit: <zum Beispiel Metins Schwester> | Geburtstag: <TT.MM.JJJJ oder
   TT.MM.> | Alter: ... | Kinder: ... | Arbeit: ... | Interessen: ... | Charakter: ... |
   Spricht: <Sprache, Art zu reden, wie sie angesprochen werden möchte> | Stimmung: <wie die
   Person beim letzten Mal drauf war> | Humor: <worüber sie lacht, eure Insider und Sprüche> |
   Zuletzt: <TT.MM.: worüber ihr zuletzt wirklich geredet habt, ein Satz> | Offen: <was Leyla
   nachfragen wollte oder zugesagt hat> | Eindruck: <Leylas eigener Eindruck von der Person, ein
   Satz> | Sonst: ..."
   Ergänze und verbessere den Eintrag mit jedem Gespräch, statt neue Einträge für dieselbe
   Person anzulegen. Einträge in einem älteren Format bringst du in diese Form.
   Das Gedächtnis soll sich wie das einer guten Freundin anfühlen: "Zuletzt" und "Stimmung" ersetzt
   du bei jedem echten Gespräch mit dieser Person (nicht anhäufen), aber nur wenn es um etwas
   Persönliches oder Bleibendes ging, nicht bei Befehlen, Smalltalk oder einmaligen Wissensfragen.
   "Offen" sind echte Fäden: ein Termin, eine Prüfung, eine Sorge, ein Vorhaben oder etwas, das
   Leyla zugesagt hat; ist es erledigt, entferne es. "Humor" nur, wenn wirklich ein Spruch oder
   Witz entstanden ist, der euch verbindet. Jedes Feld höchstens ein kurzer Satz.
   Vorübergehendes (Krankheit, Prüfung, Reise, Sorge, Freude mit Anlass) als eigener Eintrag:
   "Aktuell bis TT.MM.JJJJ: <Name> ..." mit einem Datum etwa zwei Wochen nach heute. Ist es
   erledigt oder besser, entferne den Eintrag.
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
- Reden mehrere Personen, trägst du nur ein, was eindeutig einer Person zuzuordnen ist (sie hat
  sich selbst genannt, wurde mit Namen angesprochen, oder Leyla hat es bestätigt).
- Schreib Namen immer so, wie sie schon in der Liste stehen (zum Beispiel Gülfikar, nicht
  Gül Fikar), auch wenn die Spracherkennung sie anders schreibt.
- Ignoriere Fernsehen, Radio, Werbung und Gespräche, die nicht mit Leyla geführt werden.
- "private" änderst du nur, wenn das Codewort gesagt wurde: Dann kommen Dinge hierher, die Metin
  sich ausdrücklich privat merken lassen will. Sagt er "für alle" oder ist es Familienwissen,
  gehört es nach "family". Wurde das Codewort nicht gesagt, gib "private" unverändert zurück.
- Vergessen: Bittet jemand, etwas zu vergessen, entferne es. Ohne Codewort nur aus "family"
  oder "friends" und nur, was die Person selbst betrifft. Sonst löschst du ohne Codewort nichts außer
  abgelaufenen oder erledigten "Aktuell" Einträgen.
- Keine Passwörter, PINs, Konto oder Kartennummern.
- Kurze deutsche Sätze, höchstens {max_facts} Einträge je Liste.
- Gibt es nichts Neues, gib alle Listen unverändert zurück.
Antworte nur mit JSON in der Form {{"family": ["..."], "friends": ["..."], "private": ["..."],
"leyla": ["..."]}} und sonst nichts."""


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


def missing_fields(fact: str) -> list[str]:
    parsed = parse_profile(fact)
    if not parsed:
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
            return {FAMILY: [], FRIENDS: [], LEYLA: [],
                    PRIVATE: _clean_facts(data.get("facts", []))}
        return {k: _clean_facts(data.get(k, [])) for k in KINDS}

    def load(self, kind: str = FAMILY) -> list[str]:
        return self._read()[kind]

    def load_all(self) -> dict:
        return self._read()

    def save_all(self, lists: dict) -> None:
        data = self._read()
        for k in KINDS:
            if k in lists:
                data[k] = _clean_facts(lists[k])
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"version": 3, **{k: data[k] for k in KINDS},
                       "updated": int(time.time())}, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def save(self, facts: list[str], kind: str = FAMILY) -> None:
        self.save_all({kind: facts})

    def forget(self, raw_patterns: str) -> list[str]:
        """Remove every fact (both lists) that contains one of the ;-separated pieces."""
        patterns = [p.strip().lower() for p in (raw_patterns or "").split(";")
                    if p.strip() and p.strip().lower() != "null"]
        if not patterns:
            return []
        data = self._read()
        removed = []
        for k in KINDS:
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

    def expire(self, today: Optional[_dt.date] = None) -> list[str]:
        """Drop "Aktuell bis <date>" entries whose date has passed."""
        gone = []
        for kind in OPEN_KINDS:
            facts = self.load(kind)
            old = [f for f in facts if expired(f, today)]
            if old:
                self.save([f for f in facts if f not in old], kind)
                gone += old
        return gone

    def instructions_block(self) -> str:
        data = self._read()
        family = [f for f in data[FAMILY] if not expired(f)]
        friends = [f for f in data[FRIENDS] if not expired(f)]
        own = [f for f in data.get(LEYLA, []) if not expired(f)]
        if not family and not friends and not own:
            return ""
        open_ = []
        for f in family + friends:
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
) -> Optional[dict]:
    """Ask a text model for the updated lists. Tries the given models in order. Without the
    code phrase the private list always comes back unchanged."""
    today = today or _dt.date.today()
    prompt = SUMMARY_PROMPT.format(
        today=today.strftime("%d.%m.%Y"),
        lists=json.dumps({FAMILY: old.get(FAMILY, []), FRIENDS: old.get(FRIENDS, []),
                          PRIVATE: old.get(PRIVATE, [])
                          if unlocked else ["(gesperrt, unverändert lassen)"],
                          LEYLA: old.get(LEYLA, [])},
                         ensure_ascii=False),
        unlocked="ja" if unlocked else "nein",
        dialog=format_dialog(dialog)[-12000:],
        max_facts=MAX_FACTS,
        max_leyla=MAX_LEYLA,
    )
    async with httpx.AsyncClient(timeout=90.0) as client:
        for model in [m for m in models if m]:
            try:
                resp = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {api_key}",
                             "Content-Type": "application/json"},
                    json={"model": model, "input": prompt},
                )
            except Exception as e:
                logger.warning("Memory update request failed (%s): %s", model, e)
                continue
            if resp.status_code != 200:
                logger.warning("Memory update with model %s failed: HTTP %s %s",
                               model, resp.status_code, resp.text[:300])
                continue
            data = resp.json()
            text = data.get("output_text") or ""
            if not text:
                for item in data.get("output", []):
                    if item.get("type") == "message":
                        for part in item.get("content", []):
                            if part.get("type") == "output_text":
                                text += part.get("text", "")
            lists = parse_lists_json(text)
            if lists is None:
                logger.warning("Memory update: could not parse model output: %r", text[:300])
                continue
            for k in KINDS:
                if k not in lists or (k == PRIVATE and not unlocked):
                    lists[k] = list(old.get(k, []))
            lists[LEYLA] = lists[LEYLA][:MAX_LEYLA]
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
            return lists
    return None
