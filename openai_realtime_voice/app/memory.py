"""
Long term memory for the voice assistant.

After each conversation a small text model reads the transcript together with the
facts already stored and returns an updated list of facts worth keeping (names,
who lives in the household, preferences, things the user asked to remember).
The facts are stored in a JSON file on the Home Assistant host (/data survives
add-on restarts and updates) and added to the instructions of the next session.
"""
import json
import logging
import os
import re
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

RESPONSES_URL = "https://api.openai.com/v1/responses"
MAX_FACTS = 60
MAX_FACT_CHARS = 200

REMEMBER_PHRASES = (
    "merk dir", "merke dir", "merk' dir", "merkst du dir", "vergiss nicht",
    "aklında tut", "aklinda tut", "unutma", "remember",
)

SUMMARY_PROMPT = """Du pflegst das Langzeitgedächtnis einer Sprachassistentin in einem Wohnzimmer.
Im Haushalt sprechen vor allem Metin (meist Deutsch) und seine Mutter (meist Türkisch).

Bisher gespeicherte Fakten (JSON Liste):
{facts}

Neues Gespräch (Nutzer = wer gesprochen hat, Assistentin = die Sprachassistentin):
{dialog}

Aufgabe: Gib die aktualisierte Faktenliste zurück.
Regeln:
- Behalte alle bisherigen Fakten, außer sie sind durch das Gespräch überholt oder der Nutzer wollte sie vergessen.
- Füge nur dauerhaft nützliche Dinge hinzu: Namen, wer zum Haushalt gehört, Vorlieben, Gewohnheiten,
  wichtige Termine, und alles, worum der Nutzer ausdrücklich gebeten hat ("merk dir", "aklında tut").
- Wenn erkennbar ist, wer etwas gesagt hat (zum Beispiel an der Sprache oder am Namen), schreibe es dazu.
- Keine Passwörter, PINs, Konto oder Kartennummern.
- Kurze deutsche Sätze, höchstens {max_facts} Fakten.
- Wenn es nichts Neues gibt, gib die bisherige Liste unverändert zurück.
Antworte nur mit JSON in der Form {{"facts": ["...", "..."]}} und sonst nichts."""


def wants_to_remember(text: str) -> bool:
    t = " ".join(text.lower().split())
    return any(p in t for p in REMEMBER_PHRASES)


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


def parse_facts_json(text: str) -> Optional[list[str]]:
    """Extract {"facts": [...]} from model output (tolerates surrounding text)."""
    if not text:
        return None
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or "facts" not in data:
        return None
    return _clean_facts(data["facts"])


class MemoryStore:
    def __init__(self, path: str) -> None:
        self.path = path

    def load(self) -> list[str]:
        try:
            with open(self.path, encoding="utf-8") as f:
                return _clean_facts(json.load(f).get("facts", []))
        except FileNotFoundError:
            return []
        except Exception as e:
            logger.warning("Could not read memory file %s: %s", self.path, e)
            return []

    def save(self, facts: list[str]) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"facts": _clean_facts(facts), "updated": int(time.time())}, f,
                      ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def instructions_block(self) -> str:
        facts = self.load()
        if not facts:
            return ""
        lines = "\n".join(f"- {f}" for f in facts)
        return (
            "\n\nDein Gedächtnis aus früheren Gesprächen (nutze es natürlich, zähle es nicht auf):\n"
            + lines
        )


def format_dialog(dialog: list[list[str]]) -> str:
    names = {"user": "Nutzer", "bot": "Assistentin"}
    return "\n".join(f"{names.get(s, s)}: {t.strip()}" for s, t in dialog if t.strip())


async def summarize(
    api_key: str,
    models: list[str],
    old_facts: list[str],
    dialog: list[list[str]],
    url: str = RESPONSES_URL,
) -> Optional[list[str]]:
    """Ask a text model for the updated fact list. Tries the given models in order."""
    prompt = SUMMARY_PROMPT.format(
        facts=json.dumps(old_facts, ensure_ascii=False),
        dialog=format_dialog(dialog)[-12000:],
        max_facts=MAX_FACTS,
    )
    async with httpx.AsyncClient(timeout=60.0) as client:
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
            facts = parse_facts_json(text)
            if facts is None:
                logger.warning("Memory update: could not parse model output: %r", text[:300])
                continue
            return facts
    return None
