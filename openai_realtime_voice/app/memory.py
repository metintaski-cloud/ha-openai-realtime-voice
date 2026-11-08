"""
Long term memory for the voice assistant, in two parts:

  family   open knowledge about the family and the household. Leyla gets to know the
           people by herself (one profile per person: name, relation, character,
           interests, how they talk) plus short lived states ("Aktuell bis <date>: ...")
           that expire on their own. She uses it openly with everyone.
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
MAX_FACT_CHARS = 400
FAMILY, PRIVATE = "family", "private"
KINDS = (FAMILY, PRIVATE)
# One entry per person: "Person: Ayşe | Zugehörigkeit: Metins Schwester | Geburtstag: ..."
PROFILE_FIELDS = ("Zugehörigkeit", "Geburtstag", "Alter", "Kinder", "Arbeit", "Interessen",
                  "Charakter", "Spricht", "Sonst")
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

Es gibt zwei Listen:
1. "family" (offen): was Leyla über die Familie und den Haushalt weiß und offen nutzen darf.
   Für jede Person genau EIN Eintrag in genau dieser Form, Felder mit " | " getrennt, leere
   Felder weglassen, Reihenfolge beibehalten:
   "Person: <Name> | Zugehörigkeit: <zum Beispiel Metins Schwester> | Geburtstag: <TT.MM.JJJJ oder
   TT.MM.> | Alter: ... | Kinder: ... | Arbeit: ... | Interessen: ... | Charakter: ... |
   Spricht: <Sprache, Art zu reden, wie sie angesprochen werden möchte> | Sonst: ..."
   Ergänze und verbessere den Eintrag mit jedem Gespräch, statt neue Einträge für dieselbe
   Person anzulegen. Einträge in einem älteren Format bringst du in diese Form.
   Vorübergehendes (Krankheit, Prüfung, Reise, Sorge, Freude mit Anlass) als eigener Eintrag:
   "Aktuell bis TT.MM.JJJJ: <Name> ..." mit einem Datum etwa zwei Wochen nach heute. Ist es
   erledigt oder besser, entferne den Eintrag.
   Allgemeines über den Haushalt als kurze Sätze.
2. "private" (gesperrt): Metins sehr private Dinge.

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
- Reden mehrere Personen, trägst du nur ein, was eindeutig einer Person zuzuordnen ist (sie hat
  sich selbst genannt, wurde mit Namen angesprochen, oder Leyla hat es bestätigt).
- Schreib Namen immer so, wie sie schon in der Liste stehen (zum Beispiel Gülfikar, nicht
  Gül Fikar), auch wenn die Spracherkennung sie anders schreibt.
- Ignoriere Fernsehen, Radio, Werbung und Gespräche, die nicht mit Leyla geführt werden.
- "private" änderst du nur, wenn das Codewort gesagt wurde: Dann kommen Dinge hierher, die Metin
  sich ausdrücklich privat merken lassen will. Sagt er "für alle" oder ist es Familienwissen,
  gehört es nach "family". Wurde das Codewort nicht gesagt, gib "private" unverändert zurück.
- Vergessen: Bittet jemand, etwas zu vergessen, entferne es. Ohne Codewort nur aus "family"
  und nur, was die Person selbst betrifft. Sonst löschst du ohne Codewort nichts außer
  abgelaufenen oder erledigten "Aktuell" Einträgen.
- Keine Passwörter, PINs, Konto oder Kartennummern.
- Kurze deutsche Sätze, höchstens {max_facts} Einträge je Liste.
- Gibt es nichts Neues, gib beide Listen unverändert zurück.
Antworte nur mit JSON in der Form {{"family": ["..."], "private": ["..."]}} und sonst nichts."""


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
    """Extract {"family": [...], "private": [...]} from model output."""
    data = _json_object(text)
    if data is None or FAMILY not in data:
        return None
    return {FAMILY: _clean_facts(data.get(FAMILY)), PRIVATE: _clean_facts(data.get(PRIVATE))}


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
            return {FAMILY: [], PRIVATE: []}
        except Exception as e:
            logger.warning("Could not read memory file %s: %s", self.path, e)
            return {FAMILY: [], PRIVATE: []}
        if FAMILY not in data and PRIVATE not in data:
            # Old single list: everything stays private until Metin moves it
            return {FAMILY: [], PRIVATE: _clean_facts(data.get("facts", []))}
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
            json.dump({"version": 2, FAMILY: data[FAMILY], PRIVATE: data[PRIVATE],
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
        family = self.load(FAMILY)
        gone = [f for f in family if expired(f, today)]
        if gone:
            self.save([f for f in family if f not in gone], FAMILY)
        return gone

    def instructions_block(self) -> str:
        family = [f for f in self.load(FAMILY) if not expired(f)]
        if not family:
            return ""
        lines = "\n".join(f"• {f}" for f in family)
        open_ = []
        for f in family:
            parsed = parse_profile(f)
            missing = missing_fields(f)
            if parsed and missing:
                open_.append(f"• {parsed[0]}: {', '.join(missing)}")
        text = "\n\nFAMILIE UND HAUSHALT\n" + lines
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
        lists=json.dumps({FAMILY: old.get(FAMILY, []), PRIVATE: old.get(PRIVATE, [])
                          if unlocked else ["(gesperrt, unverändert lassen)"]},
                         ensure_ascii=False),
        unlocked="ja" if unlocked else "nein",
        dialog=format_dialog(dialog)[-12000:],
        max_facts=MAX_FACTS,
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
            if not unlocked:
                lists[PRIVATE] = list(old.get(PRIVATE, []))
            old_family = old.get(FAMILY, [])
            if not unlocked and len(lists[FAMILY]) < len(old_family) - 3:
                logger.warning("Memory update would drop %d family entries without the code "
                               "phrase; ignored", len(old_family) - len(lists[FAMILY]))
                lists[FAMILY] = list(old_family)
            return lists
    return None
